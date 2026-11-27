"""/api/links: every link of a period (active or ended), and its curves."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request

from osmiracore.api.deps import SessionDep, SettingsDep
from osmiracore.schemas import LinkSeries, LinkSummary
from osmiracore.services import links

router = APIRouter(prefix="/api/links", tags=["links"])


def _since(request: Request, since: datetime | None) -> float:
    # Default: since this Core started.
    return since.timestamp() if since else request.app.state.started_at


@router.get("")
def list_links(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[LinkSummary]:
    """Links seen in the period (default: since the Core started), one per pair
    of ends: camera_server, server_station, camera_station (direct). Times: ISO
    8601, e.g. since=2026-11-27T18:00:00Z."""
    return links.list_links(
        session,
        _since(request, since),
        until.timestamp() if until else None,
        active_s=settings.srt_interval_s * 3,
    )


@router.get("/series")
def link_series(
    request: Request,
    session: SessionDep,
    id: str,  # noqa: A002  (link id from /api/links)
    since: datetime | None = None,
    until: datetime | None = None,
    points: Annotated[int, Query(ge=10, le=5000)] = links.DEFAULT_POINTS,
) -> LinkSeries:
    """Curves of one link (id from /api/links), in at most `points` buckets."""
    return links.series(
        session, id, _since(request, since), until.timestamp() if until else None, points
    )
