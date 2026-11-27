"""Camera shown on each station output, chosen from the Core (ADR 0009)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import Camera, Right, Selection, Station
from osmiracore.schemas import Matrix, MatrixDestination, MatrixSource, OutputSelection
from osmiracore.services import cameras, stations
from osmiracore.services.errors import ConflictError, NotFoundError


def set_selection(session: Session, station_id: str, output: int, camera_id: str) -> None:
    station = stations.get_station(session, station_id)
    cameras.get_camera(session, camera_id)
    if not 1 <= output <= station.outputs:
        raise NotFoundError(f"station '{station_id}' has no output {output}")
    right = session.get(Right, (station_id, camera_id))
    if right is None or not right.view:
        raise ConflictError(f"station '{station_id}' has no 'view' right on camera '{camera_id}'")

    selection = session.get(Selection, (station_id, output))
    if selection is None:
        session.add(Selection(station_id=station_id, output=output, camera_id=camera_id))
    else:
        selection.camera_id = camera_id
    session.commit()


def output_selections(session: Session, station: Station) -> list[OutputSelection]:
    """One entry per output of the station, camera_id None when nothing is chosen."""
    chosen = {
        s.output: s.camera_id
        for s in session.scalars(select(Selection).where(Selection.station_id == station.id))
    }
    return [
        OutputSelection(output=n, camera_id=chosen.get(n)) for n in range(1, station.outputs + 1)
    ]


def build_matrix(session: Session) -> Matrix:
    sources = [
        MatrixSource(camera_id=c.id, label=c.label)
        for c in session.scalars(select(Camera).order_by(Camera.id))
    ]
    destinations: list[MatrixDestination] = []
    # Rows in the order people read them: by station name, then id.
    for station in sorted(stations.list_stations(session), key=lambda s: (s.label, s.id)):
        allowed = list(
            session.scalars(
                select(Right.camera_id)
                .where(Right.station_id == station.id, Right.view)
                .order_by(Right.position)
            )
        )
        for selection in output_selections(session, station):
            destinations.append(
                MatrixDestination(
                    station_id=station.id,
                    station_label=station.label,
                    output=selection.output,
                    selected=selection.camera_id,
                    allowed=allowed,
                )
            )
    return Matrix(sources=sources, destinations=destinations)
