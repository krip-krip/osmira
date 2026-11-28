"""Station status and heartbeat (ADR 0005: POST /api/stations/{id}/status)."""

import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import Camera, Station, StationMetric, StationSample, StationStatus
from osmiracore.schemas import PlayerSrt, ReceivedMedia, StationStatusIn, StationStatusOut
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
    if data.metrics:
        _store_metrics(session, station_id, data.metrics, row.received_at)
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
        srt = cam.srt or PlayerSrt()
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
                srt_rtt_ms=srt.rtt_ms,
                srt_mbps=srt.recv_mbps,
                srt_bandwidth_mbps=srt.bandwidth_mbps,
                srt_latency_ms=srt.latency_ms,
                srt_buffer_ms=srt.buffer_ms,
                srt_packets=srt.packets,
                srt_lost=srt.lost,
                srt_retrans=srt.retrans,
                srt_dropped=srt.dropped,
                srt_belated=srt.belated,
            )
        )


def _store_metrics(session: Session, station_id: str, m: dict[str, Any], ts: float) -> None:
    processes = m.get("processes") or {}
    ptz = processes.get("ptzview") or {}
    agent = processes.get("agent") or {}
    session.add(
        StationMetric(
            ts=ts,
            station_id=station_id,
            cpu_pct=_float(m.get("cpu_pct")),
            load1=_float(m.get("load1")),
            cpu_mhz=_int(m.get("cpu_mhz")),
            temp_c=_float(m.get("temp_c")),
            throttled=_int(m.get("throttled")),
            mem_total_mb=_int(m.get("mem_total_mb")),
            mem_available_mb=_int(m.get("mem_available_mb")),
            swap_used_mb=_int(m.get("swap_used_mb")),
            cma_total_mb=_int(m.get("cma_total_mb")),
            cma_free_mb=_int(m.get("cma_free_mb")),
            disk_used_pct=_float(m.get("disk_used_pct")),
            uptime_s=_int(m.get("uptime_s")),
            ptzview_cpu_pct=_float(ptz.get("cpu_pct")),
            ptzview_rss_mb=_float(ptz.get("rss_mb")),
            agent_cpu_pct=_float(agent.get("cpu_pct")),
            agent_rss_mb=_float(agent.get("rss_mb")),
            net=m.get("net") if isinstance(m.get("net"), dict) else {},
        )
    )


def _int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


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
