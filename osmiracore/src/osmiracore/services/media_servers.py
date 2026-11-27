"""Media servers (MediaMTX) the Core reads SRT statistics from (ADR 0010)."""

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import MediaServer
from osmiracore.schemas import (
    MediaServerCreate,
    MediaServerOut,
    MediaServerState,
    MediaServerUpdate,
)
from osmiracore.services import cameras
from osmiracore.services.errors import ConflictError, NotFoundError

NOT_POLLED = MediaServerState(reachable=None, last_ok=None, last_error=None, version=None, paths=0)


def to_out(server: MediaServer, state: MediaServerState | None = None) -> MediaServerOut:
    """Public view: the API password is never returned."""
    return MediaServerOut(
        id=server.id,
        label=server.label,
        api_url=server.api_url,
        srt_address=server.srt_address,
        api_username=server.api_username,
        password_set=bool(server.api_password),
        enabled=server.enabled,
        state=state or NOT_POLLED,
    )


def list_servers(session: Session) -> list[MediaServer]:
    return list(session.scalars(select(MediaServer).order_by(MediaServer.id)))


def get_server(session: Session, server_id: str) -> MediaServer:
    server = session.get(MediaServer, server_id)
    if server is None:
        raise NotFoundError(f"media server '{server_id}' not found")
    return server


def create_server(session: Session, data: MediaServerCreate) -> MediaServer:
    if session.get(MediaServer, data.id) is not None:
        raise ConflictError(f"media server '{data.id}' already exists")
    server = MediaServer(id=data.id, api_password=None)
    _apply(server, data)
    session.add(server)
    session.commit()
    return server


def update_server(session: Session, server_id: str, data: MediaServerUpdate) -> MediaServer:
    """Cameras reading from this server follow a change of its SRT address."""
    server = get_server(session, server_id)
    _apply(server, data)
    for camera in cameras.cameras_of_server(session, server_id):
        cameras.refresh_url(camera)
    session.commit()
    return server


def delete_server(session: Session, server_id: str) -> None:
    """Delete an unused server; its recorded samples stay (they belong to the history)."""
    server = get_server(session, server_id)
    users = [c.id for c in cameras.cameras_of_server(session, server_id)]
    if users:
        raise ConflictError(
            f"media server '{server_id}' is used by cameras {', '.join(users)}: "
            "change their source first"
        )
    session.delete(server)
    session.commit()


def _apply(server: MediaServer, data: MediaServerUpdate) -> None:
    server.label = data.label
    server.api_url = data.api_url.rstrip("/")
    # Default: the API host with MediaMTX's default SRT port.
    server.srt_address = data.srt_address or f"{urlsplit(server.api_url).hostname}:8890"
    server.api_username = data.api_username or None
    server.enabled = data.enabled
    if data.api_password is not None:
        server.api_password = data.api_password or None
