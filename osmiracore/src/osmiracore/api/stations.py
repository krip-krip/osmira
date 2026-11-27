"""/api/stations routes: stations, rights, configuration, selection, events."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.orm import Session, sessionmaker

from osmiracore.api.deps import BusDep, SessionDep
from osmiracore.schemas import (
    OutputSelection,
    RightIn,
    RightOut,
    SelectionIn,
    StationConfig,
    StationCreate,
    StationOut,
    StationUpdate,
)
from osmiracore.services import config, events, selection, stations

router = APIRouter(prefix="/api/stations", tags=["stations"])


@router.get("")
def list_stations(session: SessionDep) -> list[StationOut]:
    return [stations.to_out(s) for s in stations.list_stations(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_station(data: StationCreate, session: SessionDep, bus: BusDep) -> StationOut:
    station = stations.create_station(session, data)
    bus.sync(session)
    return stations.to_out(station)


@router.get("/{station_id}")
def get_station(station_id: str, session: SessionDep) -> StationOut:
    return stations.to_out(stations.get_station(session, station_id))


@router.put("/{station_id}")
def update_station(
    station_id: str, data: StationUpdate, session: SessionDep, bus: BusDep
) -> StationOut:
    station = stations.update_station(session, station_id, data)
    bus.sync(session)
    return stations.to_out(station)


@router.delete("/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_station(station_id: str, session: SessionDep, bus: BusDep) -> None:
    stations.delete_station(session, station_id)
    bus.sync(session)


# --- rights -------------------------------------------------------------------


@router.get("/{station_id}/rights")
def list_rights(station_id: str, session: SessionDep) -> list[RightOut]:
    return [stations.right_to_out(r) for r in stations.list_rights(session, station_id)]


@router.put("/{station_id}/rights/{camera_id}")
def set_right(
    station_id: str, camera_id: str, data: RightIn, session: SessionDep, bus: BusDep
) -> RightOut:
    right = stations.set_right(session, station_id, camera_id, data)
    bus.sync(session)
    return stations.right_to_out(right)


@router.delete("/{station_id}/rights/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_right(station_id: str, camera_id: str, session: SessionDep, bus: BusDep) -> None:
    stations.delete_right(session, station_id, camera_id)
    bus.sync(session)


# --- configuration ------------------------------------------------------------


@router.get(
    "/{station_id}/config",
    response_model=None,
    responses={200: {"model": StationConfig}, 304: {"description": "Not modified"}},
)
def get_station_config(
    station_id: str,
    session: SessionDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Station configuration. Send If-None-Match with the last ETag to get 304 if unchanged."""
    station_config = config.build_station_config(session, station_id)
    etag = f'"{station_config.version}"'
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return JSONResponse(station_config.model_dump(), headers={"ETag": etag})


# --- selection (matrix) -------------------------------------------------------


@router.get("/{station_id}/outputs")
def list_outputs(station_id: str, session: SessionDep) -> list[OutputSelection]:
    station = stations.get_station(session, station_id)
    return selection.output_selections(session, station)


@router.put("/{station_id}/outputs/{output}/selection")
def set_selection(
    station_id: str, output: int, data: SelectionIn, session: SessionDep, bus: BusDep
) -> OutputSelection:
    """Show a camera on a station output. The station needs the 'view' right on it."""
    selection.set_selection(session, station_id, output, data.camera_id)
    bus.sync(session)
    return OutputSelection(output=output, camera_id=data.camera_id)


# --- events (SSE) -------------------------------------------------------------


def existing_station(station_id: str, session: SessionDep) -> str:
    """Check the station before the stream starts, so an unknown id gives 404."""
    return stations.get_station(session, station_id).id


@router.get("/{station_id}/events", response_class=EventSourceResponse)
async def station_events(
    station_id: Annotated[str, Depends(existing_station)], request: Request, bus: BusDep
) -> AsyncIterator[ServerSentEvent]:
    """Permanent event stream for a station: first 'state', then 'select' and
    'config_changed' as they happen. Keep-alive comments are sent when idle."""
    queue = bus.subscribe(station_id)
    try:
        # Subscribed first, then read the state: no change can fall in between.
        session_factory: sessionmaker[Session] = request.app.state.session_factory

        def read_state() -> events.Event:
            with session_factory() as session:
                return events.station_state(session, station_id).as_event()

        first = await run_in_threadpool(read_state)
        yield ServerSentEvent(event=first.name, data=first.data)
        while True:
            event = await queue.get()
            yield ServerSentEvent(event=event.name, data=event.data)
    finally:
        bus.unsubscribe(station_id, queue)
