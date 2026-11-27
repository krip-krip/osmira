"""HTML form models and their conversion to the API schemas.

HTML forms only send text (and nothing for an unchecked box): these flat
models receive the raw fields, then the same Pydantic schemas as the REST API
validate them, so both interfaces apply exactly the same rules.
"""

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from osmiracore.models import Camera, Right, Station
from osmiracore.schemas import (
    CameraCreate,
    CameraUpdate,
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
    srt_url: str = ""
    latency_ms: str = "20"
    codec: str = "hevc"
    width: str = "1920"
    height: str = "1080"
    fps: str = "50"
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
            srt_url=camera.media_srt_url,
            latency_ms=str(camera.media_latency_ms),
            codec=camera.media_codec,
            width=str(camera.media_width),
            height=str(camera.media_height),
            fps=str(camera.media_fps),
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
                "srt_url": self.srt_url.strip(),
                "latency_ms": self.latency_ms,
                "codec": self.codec,
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
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


def _validate(model: type[M], data: dict[str, Any]) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise FormError([_message(error) for error in exc.errors()]) from exc


def _message(error: Any) -> str:  # noqa: ANN401  (pydantic error dict)
    where = " ".join(str(part) for part in error["loc"] if part not in ("body",))
    text = error["msg"].removeprefix("Value error, ")
    return f"{where}: {text}" if where else text
