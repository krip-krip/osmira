"""Pages to manage media servers (MediaMTX) read for SRT statistics."""

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from osmiracore.api.deps import CollectorDep, SessionDep
from osmiracore.services import media_servers
from osmiracore.services.errors import ConflictError, NotFoundError
from osmiracore.web.forms import FormError, MediaServerForm
from osmiracore.web.templating import TEMPLATES

router = APIRouter(include_in_schema=False)


def _done() -> RedirectResponse:
    return RedirectResponse("/media-servers", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/media-servers")
def server_list(request: Request, session: SessionDep, collector: CollectorDep) -> HTMLResponse:
    rows = []
    for server in media_servers.list_servers(session):
        state = collector.states.get(server.id)
        rows.append(media_servers.to_out(server, state.public() if state else None))
    return TEMPLATES.TemplateResponse(
        request, "media_servers.html", {"active": "media", "servers": rows}
    )


@router.get("/media-servers/new")
def server_new(request: Request) -> HTMLResponse:
    return _form(request, MediaServerForm(enabled=True), is_new=True)


@router.post("/media-servers/new")
def server_create(
    request: Request, session: SessionDep, form: Annotated[MediaServerForm, Form()]
) -> Response:
    try:
        media_servers.create_server(session, form.to_create())
    except (FormError, ConflictError) as exc:
        session.rollback()
        return _form(request, form, is_new=True, errors=_messages(exc))
    return _done()


@router.get("/media-servers/{server_id}")
def server_edit(request: Request, session: SessionDep, server_id: str) -> HTMLResponse:
    server = media_servers.get_server(session, server_id)
    return _form(
        request,
        MediaServerForm.from_server(server),
        is_new=False,
        password_set=bool(server.api_password),
    )


@router.post("/media-servers/{server_id}")
def server_update(
    request: Request,
    session: SessionDep,
    server_id: str,
    form: Annotated[MediaServerForm, Form()],
) -> Response:
    form.id = server_id
    try:
        media_servers.update_server(session, server_id, form.to_update())
    except (FormError, NotFoundError) as exc:
        session.rollback()
        return _form(request, form, is_new=False, errors=_messages(exc))
    return _done()


@router.post("/media-servers/{server_id}/delete")
def server_delete(session: SessionDep, server_id: str) -> RedirectResponse:
    media_servers.delete_server(session, server_id)
    return _done()


def _messages(exc: Exception) -> list[str]:
    return exc.messages if isinstance(exc, FormError) else [str(exc)]


def _form(
    request: Request,
    form: MediaServerForm,
    *,
    is_new: bool,
    password_set: bool = False,
    errors: list[str] | None = None,
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "media_server_form.html",
        {
            "active": "media",
            "form": form,
            "is_new": is_new,
            "password_set": password_set,
            "errors": errors or [],
        },
        status_code=422 if errors else 200,
    )
