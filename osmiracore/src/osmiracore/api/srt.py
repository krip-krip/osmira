"""/api/srt: SRT link statistics collected from the media servers (ADR 0010)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from osmiracore.api.deps import SessionDep, SettingsDep
from osmiracore.models import SrtSample
from osmiracore.schemas import SrtLink
from osmiracore.services import srt

router = APIRouter(prefix="/api/srt", tags=["srt statistics"])

MAX_SAMPLES = 100_000


@router.get("/links")
def links(session: SessionDep, settings: SettingsDep) -> list[SrtLink]:
    """SRT links seen recently, with loss and retransmission rates over their
    last interval. link "camera": camera -> media server (receiver side);
    link "station": media server -> station (sender side)."""
    return srt.latest_links(session, active_s=settings.srt_interval_s * 3)


@router.get("/samples")
def samples(
    session: SessionDep,
    since: datetime,
    until: datetime | None = None,
    camera_id: str | None = None,
    station_id: str | None = None,
    link: Literal["camera", "station"] | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_SAMPLES)] = 10_000,
) -> list[dict[str, Any]]:
    """Raw samples (cumulative counters), oldest first. Times: ISO 8601,
    e.g. since=2026-11-27T18:00:00Z."""
    query = select(SrtSample).where(SrtSample.ts >= since.timestamp())
    if until is not None:
        query = query.where(SrtSample.ts <= until.timestamp())
    if camera_id is not None:
        query = query.where(SrtSample.camera_id == camera_id)
    if station_id is not None:
        query = query.where(SrtSample.station_id == station_id)
    if link is not None:
        query = query.where(SrtSample.link == link)
    rows = session.scalars(query.order_by(SrtSample.ts, SrtSample.id).limit(limit))
    columns = [c.name for c in SrtSample.__table__.columns]
    return [{name: getattr(row, name) for name in columns} for row in rows]
