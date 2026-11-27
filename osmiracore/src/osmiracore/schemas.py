"""API request and response bodies (Pydantic). See docs/api.md."""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class StationUpdate(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=64)]
    # Hardware capacity of this station, no global limit (4 for a Pi 4 in 1080p50).
    max_decoders: Annotated[int, Field(ge=0)] = 4
    # Number of video outputs (destinations in the matrix).
    outputs: Annotated[int, Field(ge=1)] = 1


class StationCreate(StationUpdate):
    id: Identifier


class StationOut(StationUpdate):
    id: str


class RightIn(StrictModel):
    position: Annotated[int, Field(ge=1)]
    decode: bool = False
    view: bool = False
    control: bool = False

    @model_validator(mode="after")
    def check_levels(self) -> Self:
        # control implies view, view implies decode (ADR 0002: only a decoded
        # stream can be shown).
        if self.view and not self.decode:
            raise ValueError("'view' requires 'decode'")
        if self.control and not self.view:
            raise ValueError("'control' requires 'view'")
        return self


class RightOut(RightIn):
    camera_id: str


class RightLevels(StrictModel):
    decode: bool
    view: bool
    control: bool


class ConfigCamera(StrictModel):
    id: str
    label: str
    position: int
    rights: RightLevels
    media: Media
    # Camera control (PTZ) is planned but not sent yet: the "control" block
    # will be added here when the agent gets its camera drivers.


class SelectionIn(StrictModel):
    camera_id: Identifier


class OutputSelection(StrictModel):
    output: int
    # None: the Core has not chosen a camera for this output.
    camera_id: str | None


class MatrixSource(StrictModel):
    camera_id: str
    label: str


class MatrixDestination(StrictModel):
    station_id: str
    station_label: str
    output: int
    selected: str | None
    # Cameras this output may show (station has the "view" right on them).
    allowed: list[str]


class Matrix(StrictModel):
    """Routing matrix: sources (cameras) x destinations (station outputs)."""

    sources: list[MatrixSource]
    destinations: list[MatrixDestination]


class StationConfig(StrictModel):
    """Everything a station needs to run on its own. See docs/api.md."""

    station: StationOut
    # "sha256:<hex>" fingerprint of the rest of the document.
    version: str
    cameras: list[ConfigCamera]
