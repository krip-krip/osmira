"""Camera management."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import Camera
from osmiracore.schemas import (
    CameraCreate,
    CameraOut,
    CameraUpdate,
    ControlOut,
    Media,
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
    media = Media(
        srt_url=camera.media_srt_url,
        latency_ms=camera.media_latency_ms,
        codec=camera.media_codec,  # validated on write
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
    _apply(camera, data)
    session.add(camera)
    session.commit()
    return camera


def update_camera(session: Session, camera_id: str, data: CameraUpdate) -> Camera:
    camera = get_camera(session, camera_id)
    _apply(camera, data)
    session.commit()
    return camera


def delete_camera(session: Session, camera_id: str) -> None:
    session.delete(get_camera(session, camera_id))
    session.commit()


def _apply(camera: Camera, data: CameraUpdate) -> None:
    """Copy request data onto the table row (full replacement, except the password)."""
    camera.label = data.label
    camera.media_srt_url = data.media.srt_url
    camera.media_latency_ms = data.media.latency_ms
    camera.media_codec = data.media.codec
    camera.media_width = data.media.width
    camera.media_height = data.media.height
    camera.media_fps = data.media.fps
    camera.control_driver = data.control.driver
    camera.control_host = data.control.host
    camera.control_port = data.control.port
    camera.control_username = data.control.username
    camera.control_options = data.control.options
    if data.control.password is not None:
        camera.control_password = data.control.password or None
