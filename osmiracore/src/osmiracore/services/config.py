"""Configuration sent to a station, with its version fingerprint (ADR 0008)."""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import Camera, Right
from osmiracore.schemas import ConfigCamera, ConfigMedia, RightLevels, StationConfig
from osmiracore.services import stations


def build_station_config(session: Session, station_id: str) -> StationConfig:
    """Cameras the station decodes, in position order, with a content version."""
    station = stations.get_station(session, station_id)
    rows = session.execute(
        select(Right, Camera)
        .join(Camera, Camera.id == Right.camera_id)
        .where(Right.station_id == station_id, Right.decode)
        .order_by(Right.position)
    ).all()

    config_cameras = [
        ConfigCamera(
            id=camera.id,
            label=camera.label,
            position=right.position,
            rights=RightLevels(decode=right.decode, view=right.view, control=right.control),
            media=ConfigMedia(
                srt_url=camera.media_srt_url,
                latency_ms=camera.media_latency_ms,
                codec=camera.media_codec,
                width=camera.media_width,
                height=camera.media_height,
                fps=camera.media_fps,
            ),
        )
        for right, camera in rows
    ]
    station_out = stations.to_out(station)
    content = {
        "station": station_out.model_dump(),
        "cameras": [c.model_dump() for c in config_cameras],
    }
    return StationConfig(station=station_out, version=fingerprint(content), cameras=config_cameras)


def fingerprint(content: dict) -> str:
    """SHA-256 of canonical JSON: same content, same version, on any machine."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
