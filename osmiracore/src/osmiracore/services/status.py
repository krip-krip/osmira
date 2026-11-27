"""Station status and heartbeat (ADR 0005: POST /api/stations/{id}/status)."""

import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import Station, StationStatus
from osmiracore.schemas import StationStatusIn, StationStatusOut
from osmiracore.services import config, stations


def record_status(
    session: Session, station_id: str, data: StationStatusIn, now: float | None = None
) -> None:
    stations.get_station(session, station_id)  # 404 for an unknown station
    row = session.get(StationStatus, station_id)
    if row is None:
        row = StationStatus(station_id=station_id)
        session.add(row)
    row.received_at = time.time() if now is None else now
    row.payload = data.model_dump()
    session.commit()


def station_status(
    session: Session, station: Station, timeout_s: float, now: float | None = None
) -> StationStatusOut:
    now = time.time() if now is None else now
    row = session.get(StationStatus, station.id)
    if row is None:
        return StationStatusOut(
            station_id=station.id,
            online=False,
            last_seen=None,
            seconds_since=None,
            config_up_to_date=None,
            status=None,
        )
    data = StationStatusIn.model_validate(row.payload)
    current = config.build_station_config(session, station.id).version
    since = max(0.0, now - row.received_at)
    return StationStatusOut(
        station_id=station.id,
        online=since <= timeout_s,
        last_seen=datetime.fromtimestamp(row.received_at, UTC).isoformat(timespec="seconds"),
        seconds_since=round(since, 1),
        config_up_to_date=None if data.config_version is None else data.config_version == current,
        status=data,
    )


def online_station_ids(session: Session, timeout_s: float, now: float | None = None) -> set[str]:
    now = time.time() if now is None else now
    rows = session.execute(select(StationStatus.station_id, StationStatus.received_at)).all()
    return {station_id for station_id, at in rows if now - at <= timeout_s}
