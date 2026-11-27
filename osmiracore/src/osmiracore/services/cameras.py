"""Camera management."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import Camera, MediaServer
from osmiracore.schemas import (
    CameraCreate,
    CameraOut,
    CameraUpdate,
    ControlOut,
    Media,
    MediaOut,
    ReceivedMedia,
    SourceMedia,
)
from osmiracore.services.errors import ConflictError, NotFoundError

# A stream announced at 50 i/s is measured between ~49 and ~51.
FPS_TOLERANCE = 2.0


def to_out(
    camera: Camera, received: ReceivedMedia | None = None, source: SourceMedia | None = None
) -> CameraOut:
    """Public view of a camera: the password is never returned.

    `received`: what an online station currently receives (see services.status).
    `source`: the stream as a media server sees it (see services.srt).
    """
    media = MediaOut(
        source=camera.media_source,  # validated on write
        media_server_id=camera.media_server_id,
        path=camera.media_path,
        mode=camera.direct_mode or "caller",
        host=camera.direct_host,
        port=camera.direct_port,
        srt_url=camera.media_srt_url,
        srt_url_computed=computed_url(camera, camera.media_server),
        srt_url_overridden=camera.srt_url_override is not None,
        latency_ms=camera.media_latency_ms,
        codec=camera.media_codec,
        width=camera.media_width,
        height=camera.media_height,
        fps=camera.media_fps,
    )
    return CameraOut(
        id=camera.id,
        label=camera.label,
        media=media,
        received=received,
        source=source,
        warnings=media_warnings(media, received, source),
        control=ControlOut(
            driver=camera.control_driver,
            host=camera.control_host,
            port=camera.control_port,
            username=camera.control_username,
            options=camera.control_options,
            password_set=bool(camera.control_password),
        ),
    )


def media_warnings(
    media: Media, received: ReceivedMedia | None, source: SourceMedia | None = None
) -> list[str]:
    """Declared values (not auto) that differ from the stream actually received."""
    warnings = []
    if media.codec and source and source.codec and media.codec != source.codec:
        warnings.append(f"declared {media.codec}, media server has {source.codec}")
    if received is None:
        return warnings
    if media.width and media.height and received.width and received.height:
        if (media.width, media.height) != (received.width, received.height):
            warnings.append(
                f"declared {media.width}x{media.height}, "
                f"received {received.width}x{received.height}"
            )
    if media.fps and received.fps and abs(media.fps - received.fps) > FPS_TOLERANCE:
        warnings.append(f"declared {media.fps} fps, received {received.fps:.1f} fps")
    return warnings


def list_cameras(session: Session) -> list[Camera]:
    return list(session.scalars(select(Camera).order_by(Camera.id)))


def get_camera(session: Session, camera_id: str) -> Camera:
    camera = session.get(Camera, camera_id)
    if camera is None:
        raise NotFoundError(f"camera '{camera_id}' not found")
    return camera


def create_camera(session: Session, data: CameraCreate) -> Camera:
    if session.get(Camera, data.id) is not None:
        raise ConflictError(f"camera '{data.id}' already exists")
    camera = Camera(id=data.id, control_password=None)
    _apply(session, camera, data)  # fill it before adding: no half-filled row
    session.add(camera)
    session.commit()
    return camera


def update_camera(session: Session, camera_id: str, data: CameraUpdate) -> Camera:
    camera = get_camera(session, camera_id)
    _apply(session, camera, data)
    session.commit()
    return camera


def delete_camera(session: Session, camera_id: str) -> None:
    session.delete(get_camera(session, camera_id))
    session.commit()


def computed_url(camera: Camera, server: MediaServer | None) -> str | None:
    """SRT URL built from the camera's source (None if something is missing)."""
    if camera.media_source == "media_server":
        if server is None or not camera.media_path:
            return None
        return f"srt://{server.srt_address}?mode=caller&streamid=read:{camera.media_path}"
    if not camera.direct_port:
        return None
    if camera.direct_mode == "listener":
        # The station waits for the camera; host = local address to bind (optional).
        return f"srt://{camera.direct_host or ''}:{camera.direct_port}?mode=listener"
    if not camera.direct_host:
        return None
    return f"srt://{camera.direct_host}:{camera.direct_port}?mode=caller"


def refresh_url(camera: Camera) -> None:
    """Recompute the effective URL (after a change of source or media server)."""
    url = camera.srt_url_override or computed_url(camera, camera.media_server)
    if url is None:
        raise ConflictError(f"camera '{camera.id}': no SRT URL can be computed from its source")
    camera.media_srt_url = url


def cameras_of_server(session: Session, server_id: str) -> list[Camera]:
    query = select(Camera).where(Camera.media_server_id == server_id).order_by(Camera.id)
    return list(session.scalars(query))


def _apply(session: Session, camera: Camera, data: CameraUpdate) -> None:
    """Copy request data onto the table row (full replacement, except the password)."""
    media = data.media
    camera.label = data.label
    camera.media_source = media.source
    if media.source == "media_server":
        server = session.get(MediaServer, media.media_server_id)
        if server is None:
            raise NotFoundError(f"media server '{media.media_server_id}' not found")
        camera.media_server = server
        camera.media_path = media.path
        camera.direct_mode = camera.direct_host = camera.direct_port = None
    else:
        camera.media_server = None
        camera.media_path = None
        camera.direct_mode = media.mode
        camera.direct_host = media.host
        camera.direct_port = media.port
    computed = computed_url(camera, camera.media_server)
    # Sending back the computed URL (e.g. copied from a GET) is not an override.
    camera.srt_url_override = media.srt_url if media.srt_url != computed else None
    refresh_url(camera)
    camera.media_latency_ms = media.latency_ms
    camera.media_codec = media.codec
    camera.media_width = media.width
    camera.media_height = media.height
    camera.media_fps = media.fps
    camera.control_driver = data.control.driver
    camera.control_host = data.control.host
    camera.control_port = data.control.port
    camera.control_username = data.control.username
    camera.control_options = data.control.options
    if data.control.password is not None:
        camera.control_password = data.control.password or None
