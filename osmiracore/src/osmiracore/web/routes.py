"""Matrix page. Thin layer over services, like the REST API."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from osmiracore.api.deps import BusDep, SessionDep, SettingsDep
from osmiracore.services import selection
from osmiracore.services import status as heartbeat
from osmiracore.services.errors import ConflictError, NotFoundError
from osmiracore.web.templating import STATIC_DIR, TEMPLATES

__all__ = ["STATIC_DIR", "router"]

router = APIRouter(include_in_schema=False)


@router.get("/")
def home() -> RedirectResponse:
    return RedirectResponse("/matrix")


@router.get("/matrix")
def matrix_page(request: Request, session: SessionDep, settings: SettingsDep) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "matrix.html",
        {"active": "matrix", "matrix": _matrix(session, settings), "error": None},
    )


@router.get("/matrix/grid")
def matrix_grid(request: Request, session: SessionDep, settings: SettingsDep) -> HTMLResponse:
    """The grid alone: htmx reloads it every few seconds."""
    return _grid(request, session, settings)


@router.post("/matrix/select")
def matrix_select(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    bus: BusDep,
    station_id: Annotated[str, Form()],
    output: Annotated[int, Form()],
    camera_id: Annotated[str, Form()],
) -> HTMLResponse:
    """Click on a cell: show this camera on this station output."""
    try:
        selection.set_selection(session, station_id, output, camera_id)
    except (NotFoundError, ConflictError) as exc:
        session.rollback()
        return _grid(request, session, settings, error=str(exc))
    bus.sync(session)
    return _grid(request, session, settings)


def _matrix(session: SessionDep, settings: SettingsDep) -> object:
    online = heartbeat.online_station_ids(session, settings.online_timeout_s)
    return selection.build_matrix(session, online)


def _grid(
    request: Request, session: SessionDep, settings: SettingsDep, error: str | None = None
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "_matrix_grid.html", {"matrix": _matrix(session, settings), "error": error}
    )
