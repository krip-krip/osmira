"""API request and response bodies (Pydantic). See docs/api.md."""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Text identifiers chosen by the user: cam1, panelTest...
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]


class StrictModel(BaseModel):
    # Reject unknown fields: a typo in a curl command must not be silently ignored.
    model_config = ConfigDict(extra="forbid")


SrtUrl = Annotated[str, Field(pattern=r"^srt://", max_length=500)]


class Media(StrictModel):
    """How the stations receive the picture.

    source "media_server": a path of a media server (the station calls it).
    source "direct": straight from the camera, the station as SRT caller (it
    calls host:port) or listener (it waits for the camera on port).
    srt_url: send it only to impose a URL instead of the computed one; null or
    the computed URL itself means "use the computed URL".
    """

    source: Literal["media_server", "direct"] = "direct"
    media_server_id: Identifier | None = None
    path: Annotated[str, Field(pattern=r"^[^\s:?&]{1,200}$")] | None = None
    mode: Literal["caller", "listener"] = "caller"
    host: Annotated[str, Field(pattern=r"^[A-Za-z0-9.\-\[\]:]{1,253}$")] | None = None
    port: Annotated[int, Field(ge=1, le=65535)] | None = None
    srt_url: SrtUrl | None = None
    latency_ms: Annotated[int, Field(ge=0, le=10_000)] = 20
    # Expected format. None = auto: nothing declared, the stations play what
    # they receive and the Core shows what was actually received.
    codec: Literal["hevc", "h264"] | None = None
    width: Annotated[int, Field(gt=0, le=7680)] | None = None
    height: Annotated[int, Field(gt=0, le=4320)] | None = None
    fps: Annotated[int, Field(gt=0, le=120)] | None = None

    @model_validator(mode="after")
    def check_source(self) -> Self:
        if self.source == "media_server":
            if not self.media_server_id:
                raise ValueError("a media server is required for source 'media_server'")
            if not self.path and not self.srt_url:
                raise ValueError("a path (or an SRT URL) is required for source 'media_server'")
        elif not self.srt_url:
            if not self.port:
                raise ValueError("a port (or an SRT URL) is required for source 'direct'")
            if self.mode == "caller" and not self.host:
                raise ValueError("a host (or an SRT URL) is required in caller mode")
        return self


class MediaOut(Media):
    # Effective URL sent to the stations (override or computed).
    srt_url: str
    # URL computed from the source (None if it cannot be computed).
    srt_url_computed: str | None
    srt_url_overridden: bool

    @model_validator(mode="after")
    def check_source(self) -> Self:  # stored data is already valid
        return self


class ConfigMedia(StrictModel):
    """What a station needs to receive the picture."""

    srt_url: str
    latency_ms: int
    codec: str | None
    width: int | None
    height: int | None
    fps: int | None


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
    media: MediaOut
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
    media: ConfigMedia
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


class PlayerSrt(LenientModel):
    """SRT figures seen by the station (receiver side, ADR 0013). Counters
    are cumulative since the connection started."""

    rtt_ms: float | None = None
    recv_mbps: float | None = None
    bandwidth_mbps: float | None = None
    latency_ms: int | None = None  # negotiated with the sender
    buffer_ms: int | None = None
    packets: int | None = None
    lost: int | None = None
    retrans: int | None = None
    dropped: int | None = None  # never arrived in time: picture damage
    belated: int | None = None


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
    srt: PlayerSrt | None = None  # None: not connected, or an older player


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
    # CPU, load, frequency, power flags, memory, CMA, disk, network, processes.
    metrics: dict[str, Any] = Field(default_factory=dict)


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
    # host:port where stations read SRT; empty: API host and port 8890.
    srt_address: Annotated[str, Field(pattern=r"^[A-Za-z0-9.\-\[\]]+:\d{1,5}$")] | None = None
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
    srt_address: str
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


class ExposedPath(StrictModel):
    """A media exposed by a media server, read live from its API."""

    name: str
    ready: bool
    source_type: str | None
    codec: str | None
    width: int | None
    height: int | None
    readers: int
    # Cameras of the Core already using this path.
    cameras: list[str] = Field(default_factory=list)


class ExposedMedia(StrictModel):
    server_id: str
    reachable: bool
    error: str | None
    # host:port read in the MediaMTX configuration (srtAddress).
    srt_address_detected: str | None
    paths: list[ExposedPath]


LinkKind = Literal["camera_server", "server_station", "camera_station"]


class LinkSummary(StrictModel):
    """One link (pair of ends) over a period, all its connections together.

    camera_server: camera -> media server (MediaMTX, receiver side);
    server_station: media server -> station (MediaMTX sender side, plus what
    the station reports); camera_station: direct, station reports only.
    """

    id: str
    kind: LinkKind
    camera_id: str | None
    server_id: str | None
    path: str | None
    station_id: str | None
    active: bool
    first_seen: str
    last_seen: str
    duration_s: float
    # SRT, from the media server (None for direct links).
    connections: int | None
    packets: int | None
    packets_lost: int | None
    packets_retrans: int | None
    packets_dropped: int | None
    loss_percent: float | None
    rtt_avg_ms: float | None
    rtt_max_ms: float | None
    mbps_avg: float | None
    # SRT seen by the station (receiver side, ADR 0013); None when the
    # station does not report it (camera -> server links, older players).
    station_packets: int | None
    station_lost: int | None
    station_retrans: int | None
    station_dropped: int | None
    station_loss_percent: float | None
    station_rtt_avg_ms: float | None
    station_latency_ms: int | None  # last negotiated SRT latency
    # What the station reports (None for camera -> server links).
    fps_avg: float | None
    fps_min: float | None
    no_picture_s: float | None
    decode_errors: int | None
    reconnects: int | None


class LinkSeries(StrictModel):
    """Time series of one link, in buckets (None: no data in the bucket)."""

    id: str
    bucket_s: float
    t: list[float]  # bucket start, seconds since the epoch
    rtt_ms: list[float | None]
    mbps: list[float | None]
    loss_percent: list[float | None]
    retrans_per_s: list[float | None]
    dropped: list[int | None]
    fps: list[float | None]
    station_mbps: list[float | None]
    decode_errors: list[int | None]
    # SRT seen by the station (receiver side).
    station_rtt_ms: list[float | None]
    station_loss_percent: list[float | None]
    station_retrans_per_s: list[float | None]
    station_dropped: list[int | None]


class StationMetricsSeries(StrictModel):
    """Curves of a station's system figures, in time buckets (None: no data)."""

    station_id: str
    bucket_s: float
    t: list[float]
    # cpu_pct, load1, cpu_mhz, temp_c, mem_available_mb (min), swap_used_mb,
    # cma_free_mb (min), disk_used_pct, ptzview_cpu_pct, ptzview_rss_mb,
    # agent_rss_mb, under_voltage (0/1), throttled (0/1: capped, throttled or
    # temperature limit)
    series: dict[str, list[float | None]]
    # interface -> rx_mbps, tx_mbps, rx_dropped, errors
    net: dict[str, dict[str, list[float | None]]]
    # camera -> fps, decode_errors, srt_dropped, srt_loss_percent
    cameras: dict[str, dict[str, list[float | None]]]
    # Latest row (None if the station never sent figures) and its age.
    latest: dict[str, Any] | None
    # Over the period: cpu_max, temp_max, cma_free_min, mem_available_min,
    # under_voltage_s, throttled_s, reboots, samples.
    summary: dict[str, Any]
