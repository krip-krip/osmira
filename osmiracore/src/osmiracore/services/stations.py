"""Station management and station rights on cameras."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from osmiracore.models import Right, Selection, Station
from osmiracore.schemas import RightIn, RightOut, StationCreate, StationOut, StationUpdate
from osmiracore.services.cameras import get_camera
from osmiracore.services.errors import ConflictError, NotFoundError


def to_out(station: Station) -> StationOut:
    return StationOut(
        id=station.id,
        label=station.label,
        max_decoders=station.max_decoders,
        outputs=station.outputs,
    )


def right_to_out(right: Right) -> RightOut:
    return RightOut(
        camera_id=right.camera_id,
        position=right.position,
        decode=right.decode,
        view=right.view,
        control=right.control,
    )


def list_stations(session: Session) -> list[Station]:
    return list(session.scalars(select(Station).order_by(Station.id)))


def get_station(session: Session, station_id: str) -> Station:
    station = session.get(Station, station_id)
    if station is None:
        raise NotFoundError(f"station '{station_id}' not found")
    return station


def create_station(session: Session, data: StationCreate) -> Station:
    if session.get(Station, data.id) is not None:
        raise ConflictError(f"station '{data.id}' already exists")
    station = Station(
        id=data.id, label=data.label, max_decoders=data.max_decoders, outputs=data.outputs
    )
    session.add(station)
    session.commit()
    return station


def update_station(session: Session, station_id: str, data: StationUpdate) -> Station:
    station = get_station(session, station_id)
    decoding = _count_decode(session, station_id)
    if data.max_decoders < decoding:
        raise ConflictError(
            f"station '{station_id}' decodes {decoding} cameras: "
            f"remove decode rights before lowering max_decoders to {data.max_decoders}"
        )
    station.label = data.label
    station.max_decoders = data.max_decoders
    station.outputs = data.outputs
    # Outputs that no longer exist lose their selection.
    session.execute(
        delete(Selection).where(Selection.station_id == station_id, Selection.output > data.outputs)
    )
    session.commit()
    return station


def delete_station(session: Session, station_id: str) -> None:
    """Delete a station; its rights go with it (ON DELETE CASCADE)."""
    session.delete(get_station(session, station_id))
    session.commit()


def list_rights(session: Session, station_id: str) -> list[Right]:
    get_station(session, station_id)
    query = select(Right).where(Right.station_id == station_id).order_by(Right.position)
    return list(session.scalars(query))


def set_right(session: Session, station_id: str, camera_id: str, data: RightIn) -> Right:
    """Create or replace the right of a station on a camera."""
    station = get_station(session, station_id)
    get_camera(session, camera_id)

    taken = session.scalar(
        select(Right.camera_id).where(
            Right.station_id == station_id,
            Right.position == data.position,
            Right.camera_id != camera_id,
        )
    )
    if taken is not None:
        raise ConflictError(
            f"position {data.position} on station '{station_id}' is already used by '{taken}'"
        )

    if data.decode:
        decoding = _count_decode(session, station_id, excluding_camera=camera_id)
        if decoding + 1 > station.max_decoders:
            raise ConflictError(
                f"station '{station_id}' can decode at most {station.max_decoders} cameras"
            )

    right = session.get(Right, (station_id, camera_id))
    if right is None:
        right = Right(station_id=station_id, camera_id=camera_id)
        session.add(right)
    right.position = data.position
    right.decode = data.decode
    right.view = data.view
    right.control = data.control
    if not data.view:
        _clear_selections(session, station_id, camera_id)
    session.commit()
    return right


def delete_right(session: Session, station_id: str, camera_id: str) -> None:
    right = session.get(Right, (station_id, camera_id))
    if right is None:
        raise NotFoundError(f"station '{station_id}' has no right on camera '{camera_id}'")
    session.delete(right)
    _clear_selections(session, station_id, camera_id)
    session.commit()


def _clear_selections(session: Session, station_id: str, camera_id: str) -> None:
    """A camera the station may no longer view leaves the station's outputs."""
    session.execute(
        delete(Selection).where(
            Selection.station_id == station_id, Selection.camera_id == camera_id
        )
    )


def _count_decode(session: Session, station_id: str, excluding_camera: str | None = None) -> int:
    query = select(func.count()).where(Right.station_id == station_id, Right.decode)
    if excluding_camera is not None:
        query = query.where(Right.camera_id != excluding_camera)
    return session.scalar(query) or 0
