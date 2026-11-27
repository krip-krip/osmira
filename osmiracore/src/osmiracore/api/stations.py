"""/api/stations routes, including station rights on cameras."""

from fastapi import APIRouter, status

from osmiracore.api.deps import SessionDep
from osmiracore.schemas import RightIn, RightOut, StationCreate, StationOut, StationUpdate
from osmiracore.services import stations

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
