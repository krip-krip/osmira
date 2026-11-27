"""Pages to manage cameras, stations and station rights."""

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from osmiracore.api.deps import BusDep, CollectorDep, SessionDep, SettingsDep
from osmiracore.models import Right
from osmiracore.services import cameras, media_servers, stations
from osmiracore.services import status as heartbeat
from osmiracore.services.errors import ConflictError, NotFoundError
from osmiracore.web.forms import CameraForm, FormError, RightForm, StationForm, preview_camera
from osmiracore.web.templating import TEMPLATES

router = APIRouter(include_in_schema=False)

FormErrors = (FormError, ConflictError, NotFoundError)


def _messages(exc: Exception) -> list[str]:
    return exc.messages if isinstance(exc, FormError) else [str(exc)]


def _done(url: str) -> RedirectResponse:
    # 303: the browser follows with a GET (no "resend the form?" on reload).
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


# --- cameras ------------------------------------------------------------------


@router.get("/cameras")
def camera_list(
    request: Request, session: SessionDep, settings: SettingsDep, collector: CollectorDep
) -> HTMLResponse:
    received = heartbeat.received_media(session, settings.online_timeout_s)
    views = [
        cameras.to_out(c, received.get(c.id), collector.source_of(c))
        for c in cameras.list_cameras(session)
    ]
    return TEMPLATES.TemplateResponse(
        request, "cameras.html", {"active": "cameras", "cameras": views}
    )


@router.get("/cameras/new")
def camera_new(
    request: Request,
    session: SessionDep,
    source: str | None = None,
    media_server_id: str = "",
    path: str = "",
    id: str = "",  # noqa: A002  (form field name)
    label: str = "",
) -> HTMLResponse:
    """Empty form, or prefilled from a media exposed by a media server."""
    form = CameraForm(id=id, label=label, media_server_id=media_server_id, path=path)
    if source in ("media_server", "direct"):
        form.source = source
    elif not media_servers.list_servers(session):
        form.source = "direct"  # no media server declared yet
    return _camera_form(request, session, form, is_new=True)


@router.post("/cameras/source")
def camera_source(
    request: Request, session: SessionDep, form: Annotated[CameraForm, Form()]
) -> HTMLResponse:
    """The Source block alone, redrawn while the user changes it (htmx)."""
    return TEMPLATES.TemplateResponse(
        request, "_camera_source.html", {"form": form, **_source_context(session, form)}
    )


@router.post("/cameras/new")
def camera_create(
    request: Request, session: SessionDep, bus: BusDep, form: Annotated[CameraForm, Form()]
) -> Response:
    try:
        cameras.create_camera(session, form.to_create())
    except FormErrors as exc:
        session.rollback()
        return _camera_form(request, session, form, is_new=True, errors=_messages(exc))
    bus.sync(session)
    return _done("/cameras")


@router.get("/cameras/{camera_id}")
def camera_edit(request: Request, session: SessionDep, camera_id: str) -> HTMLResponse:
    camera = cameras.get_camera(session, camera_id)
    form = CameraForm.from_camera(camera)
    return _camera_form(
        request, session, form, is_new=False, password_set=bool(camera.control_password)
    )


@router.post("/cameras/{camera_id}")
def camera_update(
    request: Request,
    session: SessionDep,
    bus: BusDep,
    camera_id: str,
    form: Annotated[CameraForm, Form()],
) -> Response:
    form.id = camera_id  # the identifier cannot change
    try:
        cameras.update_camera(session, camera_id, form.to_update())
    except FormErrors as exc:
        session.rollback()
        camera = cameras.get_camera(session, camera_id)
        return _camera_form(
            request,
            session,
            form,
            is_new=False,
            password_set=bool(camera.control_password),
            errors=_messages(exc),
        )
    bus.sync(session)
    return _done("/cameras")


@router.post("/cameras/{camera_id}/delete")
def camera_delete(session: SessionDep, bus: BusDep, camera_id: str) -> RedirectResponse:
    cameras.delete_camera(session, camera_id)
    bus.sync(session)
    return _done("/cameras")


def _source_context(session: Session, form: CameraForm) -> dict[str, object]:
    servers = media_servers.list_servers(session)
    server = next((s for s in servers if s.id == form.media_server_id), None)
    if form.source == "media_server" and server is None and servers:
        server = servers[0]
        form.media_server_id = server.id
    computed = cameras.computed_url(preview_camera(form, server), server)
    return {"servers": servers, "server": server, "computed": computed}


def _camera_form(
    request: Request,
    session: Session,
    form: CameraForm,
    *,
    is_new: bool,
    password_set: bool = False,
    errors: list[str] | None = None,
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "camera_form.html",
        {
            "active": "cameras",
            "form": form,
            "is_new": is_new,
            "password_set": password_set,
            "errors": errors or [],
            **_source_context(session, form),
        },
        status_code=422 if errors else 200,
    )


# --- stations -----------------------------------------------------------------


@router.get("/stations")
def station_list(request: Request, session: SessionDep, settings: SettingsDep) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "stations.html", {"active": "stations", "rows": _station_rows(session, settings)}
    )


@router.get("/stations/table")
def station_table(request: Request, session: SessionDep, settings: SettingsDep) -> HTMLResponse:
    """The table alone: htmx reloads it every few seconds (online status)."""
    return TEMPLATES.TemplateResponse(
        request, "_stations_table.html", {"rows": _station_rows(session, settings)}
    )


def _station_rows(session: Session, settings: SettingsDep) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for station in stations.list_stations(session):
        rights = stations.list_rights(session, station.id)
        rows.append(
            {
                "station": station,
                "decoding": sum(r.decode for r in rights),
                "viewable": sum(r.view for r in rights),
                "status": heartbeat.station_status(session, station, settings.online_timeout_s),
            }
        )
    return rows


@router.get("/stations/new")
def station_new(request: Request) -> HTMLResponse:
    return _station_form(request, StationForm(), is_new=True)


@router.post("/stations/new")
def station_create(
    request: Request, session: SessionDep, bus: BusDep, form: Annotated[StationForm, Form()]
) -> Response:
    try:
        station = stations.create_station(session, form.to_create())
    except FormErrors as exc:
        session.rollback()
        return _station_form(request, form, is_new=True, errors=_messages(exc))
    bus.sync(session)
    return _done(f"/stations/{station.id}/rights")


@router.get("/stations/{station_id}")
def station_edit(request: Request, session: SessionDep, station_id: str) -> HTMLResponse:
    station = stations.get_station(session, station_id)
    return _station_form(request, StationForm.from_station(station), is_new=False)


@router.post("/stations/{station_id}")
def station_update(
    request: Request,
    session: SessionDep,
    bus: BusDep,
    station_id: str,
    form: Annotated[StationForm, Form()],
) -> Response:
    form.id = station_id
    try:
        stations.update_station(session, station_id, form.to_update())
    except FormErrors as exc:
        session.rollback()
        return _station_form(request, form, is_new=False, errors=_messages(exc))
    bus.sync(session)
    return _done("/stations")


@router.post("/stations/{station_id}/delete")
def station_delete(session: SessionDep, bus: BusDep, station_id: str) -> RedirectResponse:
    stations.delete_station(session, station_id)
    bus.sync(session)
    return _done("/stations")


def _station_form(
    request: Request, form: StationForm, *, is_new: bool, errors: list[str] | None = None
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "station_form.html",
        {"active": "stations", "form": form, "is_new": is_new, "errors": errors or []},
        status_code=422 if errors else 200,
    )


# --- rights -------------------------------------------------------------------


@router.get("/stations/{station_id}/rights")
def rights_page(request: Request, session: SessionDep, station_id: str) -> HTMLResponse:
    return _rights(request, session, station_id, "rights.html")


@router.post("/stations/{station_id}/rights/{camera_id}")
def rights_save(
    request: Request,
    session: SessionDep,
    bus: BusDep,
    station_id: str,
    camera_id: str,
    form: Annotated[RightForm, Form()],
) -> HTMLResponse:
    """Save one row (htmx): returns the whole table, with a message."""
    try:
        stations.set_right(session, station_id, camera_id, form.to_right())
    except FormErrors as exc:
        session.rollback()
        return _rights(
            request,
            session,
            station_id,
            "_rights_table.html",
            errors=[f"{camera_id}: {m}" for m in _messages(exc)],
            edited={camera_id: form},
        )
    bus.sync(session)
    return _rights(request, session, station_id, "_rights_table.html", saved=camera_id)


@router.post("/stations/{station_id}/rights/{camera_id}/delete")
def rights_delete(
    request: Request, session: SessionDep, bus: BusDep, station_id: str, camera_id: str
) -> HTMLResponse:
    stations.delete_right(session, station_id, camera_id)
    bus.sync(session)
    return _rights(request, session, station_id, "_rights_table.html", saved=camera_id)


def _rights(
    request: Request,
    session: Session,
    station_id: str,
    template: str,
    *,
    errors: list[str] | None = None,
    saved: str | None = None,
    edited: dict[str, RightForm] | None = None,
) -> HTMLResponse:
    station = stations.get_station(session, station_id)
    existing: dict[str, Right] = {r.camera_id: r for r in stations.list_rights(session, station_id)}
    rows = []
    for camera in cameras.list_cameras(session):
        right = existing.get(camera.id)
        if edited and camera.id in edited:
            form = edited[camera.id]  # keep what the user typed after a refusal
        elif right is not None:
            form = RightForm.from_right(right)
        else:
            form = RightForm()
        rows.append({"camera": camera, "form": form, "exists": right is not None})
    rows.sort(key=lambda r: (not r["exists"], _position(r["form"]), r["camera"].id))
    return TEMPLATES.TemplateResponse(
        request,
        template,
        {
            "active": "stations",
            "station": station,
            "rows": rows,
            "decoding": sum(r.decode for r in existing.values()),
            "errors": errors or [],
            "saved": saved,
        },
        # htmx ignores 4xx answers: a refusal comes back as 200 with its message.
        status_code=200,
    )


def _position(form: RightForm) -> int:
    return int(form.position) if form.position.strip().isdigit() else 10**9
