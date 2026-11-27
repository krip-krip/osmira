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
    # Expected format. None = auto: nothing declared, the stations play what
    # they receive and the Core shows what was actually received.
    codec: Literal["hevc", "h264"] | None = None
    width: Annotated[int, Field(gt=0, le=7680)] | None = None
    height: Annotated[int, Field(gt=0, le=4320)] | None = None
    fps: Annotated[int, Field(gt=0, le=120)] | None = None


class ReceivedMedia(StrictModel):
    """Format actually received by a station (from its status report)."""

    station_id: str
    width: int | None
    height: int | None
    fps: float | None
    # Seconds since that station reported it.
    seconds_since: float


class SourceMedia(StrictModel):
    """The camera's stream as the media server sees it."""

    server_id: str
    path: str
    ready: bool
    codec: str | None  # hevc, h264...
    width: int | None
    height: int | None


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
    # What online stations actually receive (None: no station streams it now).
    received: ReceivedMedia | None = None
    # The stream as the media server sees it (None: no media server knows it).
    source: SourceMedia | None = None
    # Declared values that differ from what is received.
    warnings: list[str] = Field(default_factory=list)


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
    # The station reported its status recently.
    online: bool = False


class Matrix(StrictModel):
    """Routing matrix: sources (cameras) x destinations (station outputs)."""

    sources: list[MatrixSource]
    destinations: list[MatrixDestination]


class LenientModel(BaseModel):
    # Sent by the stations: a newer agent may add fields, an older Core ignores them.
    model_config = ConfigDict(extra="ignore")


class PlayerCamera(LenientModel):
    camera_id: str
    state: str | None = None
    fps: float | None = None
    mbps: float | None = None
    width: int | None = None
    height: int | None = None
    connects: int | None = None
    decode_errors: int | None = None
    last_error: str | None = None


class PlayerStatus(LenientModel):
    running: bool = False
    shown_camera: str | None = None
    cameras: list[PlayerCamera] = Field(default_factory=list)


class StationStatusIn(LenientModel):
    """Status a station sends every few seconds; it is also its heartbeat."""

    agent_version: str
    hostname: str | None = None
    addresses: list[str] = Field(default_factory=list)
    # Version of the configuration the station applies.
    config_version: str | None = None
    # Camera the Core chose for output 1, as the station knows it.
    selected_camera: str | None = None
    player: PlayerStatus = Field(default_factory=PlayerStatus)
    # Model, architecture, RAM, OS, kernel...
    hardware: dict[str, Any] = Field(default_factory=dict)
    # Temperature, free memory, CMA, uptime...
    system: dict[str, Any] = Field(default_factory=dict)


class StationStatusOut(StrictModel):
    station_id: str
    online: bool
    # ISO 8601 UTC time of the last status, None if never seen.
    last_seen: str | None
    seconds_since: float | None
    # Does the station run the current configuration? None if unknown.
    config_up_to_date: bool | None
    status: StationStatusIn | None


class StationConfig(StrictModel):
    """Everything a station needs to run on its own. See docs/api.md."""

    station: StationOut
    # "sha256:<hex>" fingerprint of the rest of the document.
    version: str
    cameras: list[ConfigCamera]


class MediaServerUpdate(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=64)]
    api_url: Annotated[str, Field(pattern=r"^https?://", max_length=300)]
    api_username: Annotated[str, Field(max_length=100)] | None = None
    # Write-only. On update: absent or null keeps it, "" clears it.
    api_password: Annotated[str, Field(max_length=200)] | None = None
    enabled: bool = True


class MediaServerCreate(MediaServerUpdate):
    id: Identifier


class MediaServerState(StrictModel):
    """What the collector last saw of this server."""

    reachable: bool | None  # None: not polled yet
    last_ok: str | None
    last_error: str | None
    version: str | None
    paths: int


class MediaServerOut(StrictModel):
    id: str
    label: str
    api_url: str
    api_username: str | None
    password_set: bool
    enabled: bool
    state: MediaServerState


class SrtLink(StrictModel):
    """Latest state of one SRT link, with rates over the last interval."""

    link: Literal["camera", "station"]
    server_id: str
    path: str
    camera_id: str | None
    station_id: str | None
    remote_addr: str | None
    seen: str  # ISO 8601 UTC
    seconds_since: float
    rtt_ms: float | None
    mbps: float | None
    link_capacity_mbps: float | None
    buffer_ms: float | None
    # Over the last interval (None for the first sample of a connection).
    interval_s: float | None
    loss_percent: float | None
    retrans_per_s: float | None
    dropped: int | None
    # Since the connection started.
    packets: int | None
    packets_lost: int | None
    packets_retrans: int | None
    packets_dropped: int | None
