"""/api/media-servers: MediaMTX servers read for SRT statistics (ADR 0010)."""

from fastapi import APIRouter, status

from osmiracore.api.deps import CollectorDep, SessionDep
from osmiracore.models import MediaServer
from osmiracore.schemas import MediaServerCreate, MediaServerOut, MediaServerUpdate
from osmiracore.services import media_servers

router = APIRouter(prefix="/api/media-servers", tags=["media servers"])


def _out(server: MediaServer, collector: CollectorDep) -> MediaServerOut:
    state = collector.states.get(server.id)
    return media_servers.to_out(server, state.public() if state else None)


@router.get("")
def list_servers(session: SessionDep, collector: CollectorDep) -> list[MediaServerOut]:
    """`state`: what the collector last saw (reachable, MediaMTX version, paths)."""
    return [_out(s, collector) for s in media_servers.list_servers(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_server(
    data: MediaServerCreate, session: SessionDep, collector: CollectorDep
) -> MediaServerOut:
    return _out(media_servers.create_server(session, data), collector)


@router.get("/{server_id}")
def get_server(server_id: str, session: SessionDep, collector: CollectorDep) -> MediaServerOut:
    return _out(media_servers.get_server(session, server_id), collector)


@router.put("/{server_id}")
def update_server(
    server_id: str, data: MediaServerUpdate, session: SessionDep, collector: CollectorDep
) -> MediaServerOut:
    return _out(media_servers.update_server(session, server_id, data), collector)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: str, session: SessionDep) -> None:
    """The samples already recorded are kept."""
    media_servers.delete_server(session, server_id)
