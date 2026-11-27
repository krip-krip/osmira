"""HTML pages. Thin layer over services, like the REST API."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from osmiracore.api.deps import BusDep, SessionDep
from osmiracore.services import selection
from osmiracore.services.errors import ConflictError, NotFoundError

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
STATIC_DIR = Path(__file__).parent / "static"

router = APIRouter(include_in_schema=False)


@router.get("/")
def home() -> RedirectResponse:
    return RedirectResponse("/matrix")


@router.get("/matrix")
def matrix_page(request: Request, session: SessionDep) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "matrix.html", {"matrix": selection.build_matrix(session), "error": None}
    )


@router.get("/matrix/grid")
def matrix_grid(request: Request, session: SessionDep) -> HTMLResponse:
    """The grid alone: htmx reloads it every few seconds."""
    return _grid(request, session)


@router.post("/matrix/select")
def matrix_select(
    request: Request,
    session: SessionDep,
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
        return _grid(request, session, error=str(exc))
    bus.sync(session)
    return _grid(request, session)


def _grid(request: Request, session: SessionDep, error: str | None = None) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "_matrix_grid.html", {"matrix": selection.build_matrix(session), "error": error}
    )
