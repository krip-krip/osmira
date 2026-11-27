"""Links page: every link of a period, and the curves of one link."""

import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from osmiracore.api.deps import SessionDep, SettingsDep
from osmiracore.schemas import LinkSummary
from osmiracore.services import cameras, links, media_servers, stations
from osmiracore.web.templating import TEMPLATES

router = APIRouter(include_in_schema=False)

PERIODS = {
    "core": "Since the Core started",
    "1h": "Last hour",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "custom": "Custom",
}
SECONDS = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}


@dataclass
class Period:
    key: str
    since: float
    until: float | None  # None: up to now (refreshed)
    since_text: str  # for the custom inputs (local time)
    until_text: str

    @property
    def query(self) -> str:
        params = {"period": self.key}
        if self.key == "custom":
            params |= {"since": self.since_text, "until": self.until_text}
        return urlencode(params)


def resolve_period(request: Request, period: str, since: str | None, until: str | None) -> Period:
    """Period from the query string. Custom dates are local time (datetime-local)."""
    now = time.time()
    key = period if period in PERIODS else "core"
    if key == "custom":
        try:
            start = datetime.fromisoformat(since or "").timestamp()
            end = datetime.fromisoformat(until).timestamp() if until else None
        except ValueError:
            key = "core"
        else:
            return Period(key, start, end, since or "", until or "")
    start = request.app.state.started_at if key == "core" else now - SECONDS[key]
    local = datetime.fromtimestamp(start).strftime("%Y-%m-%dT%H:%M")
    return Period(key, start, None, local, datetime.fromtimestamp(now).strftime("%Y-%m-%dT%H:%M"))


def _names(session: Session) -> dict[str, dict[str, str]]:
    return {
        "camera": {c.id: c.label for c in cameras.list_cameras(session)},
        "station": {s.id: s.label for s in stations.list_stations(session)},
        "server": {s.id: s.label for s in media_servers.list_servers(session)},
    }


def _groups(items: list[LinkSummary]) -> list[tuple[str | None, list[LinkSummary]]]:
    """Links grouped by camera (camera -> server, server -> stations, direct)."""
    groups: dict[str | None, list[LinkSummary]] = {}
    for item in items:
        groups.setdefault(item.camera_id, []).append(item)
    return sorted(groups.items(), key=lambda g: (g[0] is None, g[0] or ""))


def _context(
    request: Request, session: Session, settings: SettingsDep, period: Period
) -> dict[str, object]:
    found = links.list_links(
        session, period.since, period.until, active_s=settings.srt_interval_s * 3
    )
    return {
        "active": "links",
        "period": period,
        "periods": PERIODS,
        "groups": _groups(found),
        "names": _names(session),
        "count": len(found),
        "live": period.until is None,
    }


@router.get("/links")
def links_page(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    period: str = "core",
    since: str | None = None,
    until: str | None = None,
) -> HTMLResponse:
    p = resolve_period(request, period, since, until)
    return TEMPLATES.TemplateResponse(
        request, "links.html", _context(request, session, settings, p)
    )


@router.get("/links/table")
def links_table(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    period: str = "core",
    since: str | None = None,
    until: str | None = None,
) -> HTMLResponse:
    """The table alone: htmx reloads it every 10 s for a period up to now."""
    p = resolve_period(request, period, since, until)
    return TEMPLATES.TemplateResponse(
        request, "_links_table.html", _context(request, session, settings, p)
    )


@router.get("/links/detail")
def link_detail(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    id: str,  # noqa: A002  (link id)
    period: str = "core",
    since: str | None = None,
    until: str | None = None,
) -> HTMLResponse:
    p = resolve_period(request, period, since, until)
    found = links.list_links(session, p.since, p.until, active_s=settings.srt_interval_s * 3)
    link = next((x for x in found if x.id == id), None)
    params = {"id": id, "since": _iso(p.since)}
    if p.until is not None:
        params["until"] = _iso(p.until)
    return TEMPLATES.TemplateResponse(
        request,
        "link_detail.html",
        {
            "active": "links",
            "link": link,
            "link_id": id,
            "period": p,
            "periods": PERIODS,
            "names": _names(session),
            "series_url": "/api/links/series?" + urlencode(params),
        },
        status_code=200 if link else 404,
    )


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")
