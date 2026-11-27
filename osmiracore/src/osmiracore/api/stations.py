"""/api/stations routes, including station rights on cameras."""

from typing import Annotated

from fastapi import APIRouter, Header, Response, status
from fastapi.responses import JSONResponse

from osmiracore.api.deps import SessionDep
from osmiracore.schemas import (
    RightIn,
    RightOut,
    StationConfig,
    StationCreate,
    StationOut,
    StationUpdate,
)
from osmiracore.services import config, stations

router = APIRouter(prefix="/api/stations", tags=["stations"])


@router.get("")
def list_stations(session: SessionDep) -> list[StationOut]:
    return [stations.to_out(s) for s in stations.list_stations(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_station(data: StationCreate, session: SessionDep) -> StationOut:
    return stations.to_out(stations.create_station(session, data))


@router.get("/{station_id}")
def get_station(station_id: str, session: SessionDep) -> StationOut:
    return stations.to_out(stations.get_station(session, station_id))


@router.put("/{station_id}")
def update_station(station_id: str, data: StationUpdate, session: SessionDep) -> StationOut:
    return stations.to_out(stations.update_station(session, station_id, data))


@router.delete("/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_station(station_id: str, session: SessionDep) -> None:
    stations.delete_station(session, station_id)


@router.get("/{station_id}/rights")
def list_rights(station_id: str, session: SessionDep) -> list[RightOut]:
    return [stations.right_to_out(r) for r in stations.list_rights(session, station_id)]


@router.put("/{station_id}/rights/{camera_id}")
def set_right(station_id: str, camera_id: str, data: RightIn, session: SessionDep) -> RightOut:
    return stations.right_to_out(stations.set_right(session, station_id, camera_id, data))


@router.delete("/{station_id}/rights/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_right(station_id: str, camera_id: str, session: SessionDep) -> None:
    stations.delete_right(session, station_id, camera_id)


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
