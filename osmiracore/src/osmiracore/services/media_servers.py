"""Media servers (MediaMTX) the Core reads SRT statistics from (ADR 0010)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import MediaServer
from osmiracore.schemas import (
    MediaServerCreate,
    MediaServerOut,
    MediaServerState,
    MediaServerUpdate,
)
from osmiracore.services.errors import ConflictError, NotFoundError

NOT_POLLED = MediaServerState(reachable=None, last_ok=None, last_error=None, version=None, paths=0)


def to_out(server: MediaServer, state: MediaServerState | None = None) -> MediaServerOut:
    """Public view: the API password is never returned."""
    return MediaServerOut(
        id=server.id,
        label=server.label,
        api_url=server.api_url,
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
    server = get_server(session, server_id)
    _apply(server, data)
    session.commit()
    return server


def delete_server(session: Session, server_id: str) -> None:
    """Delete a server; its recorded samples stay (they belong to the history)."""
    session.delete(get_server(session, server_id))
    session.commit()


def _apply(server: MediaServer, data: MediaServerUpdate) -> None:
    server.label = data.label
    server.api_url = data.api_url.rstrip("/")
    server.api_username = data.api_username or None
    server.enabled = data.enabled
    if data.api_password is not None:
        server.api_password = data.api_password or None
