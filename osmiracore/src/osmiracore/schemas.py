"""API request and response bodies (Pydantic). See docs/api.md."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Text identifiers chosen by the user: cam1, panelTest...
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]


class StrictModel(BaseModel):
    # Reject unknown fields: a typo in a curl command must not be silently ignored.
    model_config = ConfigDict(extra="forbid")


class Media(StrictModel):
    srt_url: Annotated[str, Field(pattern=r"^srt://", max_length=500)]
    latency_ms: Annotated[int, Field(ge=0, le=10_000)] = 20
    codec: Literal["hevc", "h264"] = "hevc"
    width: Annotated[int, Field(gt=0, le=7680)] = 1920
    height: Annotated[int, Field(gt=0, le=4320)] = 1080
    fps: Annotated[int, Field(gt=0, le=120)] = 50


class ControlBase(StrictModel):
    # Name of the agent-side driver; "none" means the camera cannot be driven.
    driver: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,32}$")] = "none"
    host: Annotated[str, Field(max_length=253)] | None = None
    port: Annotated[int, Field(ge=1, le=65535)] | None = None
    username: Annotated[str, Field(max_length=100)] | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ControlIn(ControlBase):
    # Write-only. On update: absent or null keeps the stored password, "" clears it.
    password: Annotated[str, Field(max_length=200)] | None = None


class ControlOut(ControlBase):
    password_set: bool


class CameraUpdate(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=64)]
    media: Media
    control: ControlIn = Field(default_factory=ControlIn)


class CameraCreate(CameraUpdate):
    id: Identifier


class CameraOut(StrictModel):
    id: str
    label: str
    media: Media
    control: ControlOut
