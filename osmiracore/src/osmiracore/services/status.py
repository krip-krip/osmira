"""Station status and heartbeat (ADR 0005: POST /api/stations/{id}/status)."""

import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import Camera, Station, StationSample, StationStatus
from osmiracore.schemas import ReceivedMedia, StationStatusIn, StationStatusOut
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
    _store_samples(session, station_id, data, row.received_at)
    session.commit()


def _store_samples(session: Session, station_id: str, data: StationStatusIn, ts: float) -> None:
    """One sample per received camera, plus one for the station itself."""
    system = data.system
    session.add(
        StationSample(
            ts=ts,
            station_id=station_id,
            camera_id=None,
            temp_c=_float(system.get("temp_c")),
            cma_free_mb=_float(system.get("cma_free_mb")),
        )
    )
    for cam in data.player.cameras:
        camera = session.get(Camera, cam.camera_id)
        session.add(
            StationSample(
                ts=ts,
                station_id=station_id,
                camera_id=cam.camera_id,
                via_server_id=camera.media_server_id if camera else None,
                via_path=camera.media_path if camera else None,
                state=cam.state,
                fps=cam.fps,
                mbps=cam.mbps,
                width=cam.width,
                height=cam.height,
                connects=cam.connects,
                decode_errors=cam.decode_errors,
            )
        )


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


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


def received_media(
    session: Session, timeout_s: float, now: float | None = None
) -> dict[str, ReceivedMedia]:
    """Per camera, the format an online station currently receives (freshest report)."""
    now = time.time() if now is None else now
    found: dict[str, ReceivedMedia] = {}
    for row in session.scalars(select(StationStatus)):
        since = now - row.received_at
        if since > timeout_s:
            continue
        data = StationStatusIn.model_validate(row.payload)
        for cam in data.player.cameras:
            if not cam.fps:  # no picture right now
                continue
            previous = found.get(cam.camera_id)
            if previous is None or since < previous.seconds_since:
                found[cam.camera_id] = ReceivedMedia(
                    station_id=row.station_id,
                    width=cam.width or None,
                    height=cam.height or None,
                    fps=cam.fps,
                    seconds_since=round(max(0.0, since), 1),
                )
    return found
