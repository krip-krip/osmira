"""HTML form models and their conversion to the API schemas.

HTML forms only send text (and nothing for an unchecked box): these flat
models receive the raw fields, then the same Pydantic schemas as the REST API
validate them, so both interfaces apply exactly the same rules.
"""

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from osmiracore.models import Camera, MediaServer, Right, Station
from osmiracore.schemas import (
    CameraCreate,
    CameraUpdate,
    MediaServerCreate,
    MediaServerUpdate,
    RightIn,
    StationCreate,
    StationUpdate,
)

M = TypeVar("M", bound=BaseModel)


class FormError(Exception):
    """Invalid form: messages to show next to the form."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


class CameraForm(BaseModel):
    id: str = ""
    label: str = ""
    # Source of the picture (see schemas.Media).
    source: str = "media_server"
    media_server_id: str = ""
    path: str = ""
    direct_mode: str = "caller"
    direct_host: str = ""
    direct_port: str = ""
    # Imposed URL; empty: the computed URL is used.
    srt_url: str = ""
    latency_ms: str = "20"
    # Empty = auto: nothing declared.
    codec: str = ""
    width: str = ""
    height: str = ""
    fps: str = ""
    driver: str = "none"
    host: str = ""
    port: str = ""
    username: str = ""
    password: str = ""  # empty on edit: keep the stored password
    clear_password: bool = False
    options: str = "{}"

    @classmethod
    def from_camera(cls, camera: Camera) -> "CameraForm":
        return cls(
            id=camera.id,
            label=camera.label,
            source=camera.media_source,
            media_server_id=camera.media_server_id or "",
            path=camera.media_path or "",
            direct_mode=camera.direct_mode or "caller",
            direct_host=camera.direct_host or "",
            direct_port=_text(camera.direct_port),
            srt_url=camera.srt_url_override or "",
            latency_ms=str(camera.media_latency_ms),
            codec=camera.media_codec or "",
            width=_text(camera.media_width),
            height=_text(camera.media_height),
            fps=_text(camera.media_fps),
            driver=camera.control_driver,
            host=camera.control_host or "",
            port="" if camera.control_port is None else str(camera.control_port),
            username=camera.control_username or "",
            options=json.dumps(camera.control_options),
        )

    def to_update(self) -> CameraUpdate:
        return _validate(CameraUpdate, self._body())

    def to_create(self) -> CameraCreate:
        return _validate(CameraCreate, {"id": self.id.strip(), **self._body()})

    def _body(self) -> dict[str, Any]:
        try:
            options = json.loads(self.options or "{}")
        except ValueError as exc:
            raise FormError([f"control options: not valid JSON ({exc})"]) from exc
        if not isinstance(options, dict):
            raise FormError(['control options: must be a JSON object, like {"key": "value"}'])
        if self.clear_password:
            password: str | None = ""
        else:
            password = self.password or None
        return {
            "label": self.label.strip(),
            "media": {
                "source": self.source,
                **(
                    {
                        "media_server_id": self.media_server_id or None,
                        "path": self.path.strip() or None,
                    }
                    if self.source == "media_server"
                    else {
                        "mode": self.direct_mode,
                        "host": self.direct_host.strip() or None,
                        "port": self.direct_port.strip() or None,
                    }
                ),
                "srt_url": self.srt_url.strip() or None,
                "latency_ms": self.latency_ms,
                "codec": self.codec or None,
                "width": self.width.strip() or None,
                "height": self.height.strip() or None,
                "fps": self.fps.strip() or None,
            },
            "control": {
                "driver": self.driver.strip() or "none",
                "host": self.host.strip() or None,
                "port": self.port.strip() or None,
                "username": self.username.strip() or None,
                "password": password,
                "options": options,
            },
        }


class StationForm(BaseModel):
    id: str = ""
    label: str = ""
    max_decoders: str = "4"
    outputs: str = "1"

    @classmethod
    def from_station(cls, station: Station) -> "StationForm":
        return cls(
            id=station.id,
            label=station.label,
            max_decoders=str(station.max_decoders),
            outputs=str(station.outputs),
        )

    def to_update(self) -> StationUpdate:
        return _validate(StationUpdate, self._body())

    def to_create(self) -> StationCreate:
        return _validate(StationCreate, {"id": self.id.strip(), **self._body()})

    def _body(self) -> dict[str, Any]:
        return {
            "label": self.label.strip(),
            "max_decoders": self.max_decoders,
            "outputs": self.outputs,
        }


class RightForm(BaseModel):
    position: str = ""
    decode: bool = False
    view: bool = False
    control: bool = False

    @classmethod
    def from_right(cls, right: Right) -> "RightForm":
        return cls(
            position=str(right.position),
            decode=right.decode,
            view=right.view,
            control=right.control,
        )

    def to_right(self) -> RightIn:
        return _validate(
            RightIn,
            {
                "position": self.position.strip(),
                "decode": self.decode,
                "view": self.view,
                "control": self.control,
            },
        )


class MediaServerForm(BaseModel):
    id: str = ""
    label: str = ""
    api_url: str = ""
    srt_address: str = ""  # empty: API host, port 8890
    api_username: str = ""
    api_password: str = ""  # empty on edit: keep the stored password
    clear_password: bool = False
    enabled: bool = False  # unchecked box: not sent

    @classmethod
    def from_server(cls, server: MediaServer) -> "MediaServerForm":
        return cls(
            id=server.id,
            label=server.label,
            api_url=server.api_url,
            srt_address=server.srt_address,
            api_username=server.api_username or "",
            enabled=server.enabled,
        )

    def to_update(self) -> MediaServerUpdate:
        return _validate(MediaServerUpdate, self._body())

    def to_create(self) -> MediaServerCreate:
        return _validate(MediaServerCreate, {"id": self.id.strip(), **self._body()})

    def _body(self) -> dict[str, Any]:
        password = "" if self.clear_password else (self.api_password or None)
        return {
            "label": self.label.strip(),
            "api_url": self.api_url.strip(),
            "srt_address": self.srt_address.strip() or None,
            "api_username": self.api_username.strip() or None,
            "api_password": password,
            "enabled": self.enabled,
        }


def _text(value: int | None) -> str:
    return "" if value is None else str(value)


def _validate(model: type[M], data: dict[str, Any]) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise FormError([_message(error) for error in exc.errors()]) from exc


def _message(error: Any) -> str:  # noqa: ANN401  (pydantic error dict)
    where = " ".join(str(part) for part in error["loc"] if part not in ("body",))
    text = error["msg"].removeprefix("Value error, ")
    return f"{where}: {text}" if where else text


def preview_camera(form: CameraForm, server: MediaServer | None) -> Camera:
    """Unsaved camera built from the form, to compute its URL while typing."""
    port = form.direct_port.strip()
    return Camera(
        id=form.id or "new",
        media_source=form.source,
        media_server=server if form.source == "media_server" else None,
        media_server_id=server.id if server and form.source == "media_server" else None,
        media_path=form.path.strip() or None,
        direct_mode=form.direct_mode,
        direct_host=form.direct_host.strip() or None,
        direct_port=int(port) if port.isdigit() else None,
    )
