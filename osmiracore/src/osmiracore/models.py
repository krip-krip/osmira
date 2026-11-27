"""Database tables. See docs/modele-donnees.md."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from osmiracore.db import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str]

    # Media block: how a station receives the picture.
    # Source: "media_server" (path of a MediaMTX) or "direct" (from the camera).
    media_source: Mapped[str] = mapped_column(default="direct")
    media_server_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_servers.id", ondelete="RESTRICT")
    )
    media_path: Mapped[str | None]
    # Direct: "caller" (the station calls the camera) or "listener" (the camera
    # calls the station).
    direct_mode: Mapped[str | None]
    direct_host: Mapped[str | None]
    direct_port: Mapped[int | None]
    media_server: Mapped["MediaServer | None"] = relationship(lazy="joined")
    # URL imposed by the user instead of the computed one (None: computed).
    srt_url_override: Mapped[str | None]
    # Effective URL sent to the stations: the override, or the computed URL.
    media_srt_url: Mapped[str]
    media_latency_ms: Mapped[int]
    # Expected format; None = auto (not declared, the real stream is shown).
    media_codec: Mapped[str | None]
    media_width: Mapped[int | None]
    media_height: Mapped[int | None]
    media_fps: Mapped[int | None]

    # Control block: how a station drives the camera (directly, never via the Core).
    control_driver: Mapped[str]
    control_host: Mapped[str | None]
    control_port: Mapped[int | None]
    control_username: Mapped[str | None]
    control_password: Mapped[str | None]
    control_options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Station(Base):
    """An OsmiraCam station (one Raspberry Pi), called "poste" in the docs."""

    __tablename__ = "stations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str]
    # Streams the station can decode permanently (ADR 0002).
    max_decoders: Mapped[int]
    # Video outputs (HDMI) of the station: the destinations of the matrix.
    outputs: Mapped[int] = mapped_column(default=1)


class Right(Base):
    """What a station may do with a camera. No row means no right."""

    __tablename__ = "rights"
    __table_args__ = (UniqueConstraint("station_id", "position"),)

    station_id: Mapped[str] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True
    )
    camera_id: Mapped[str] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True
    )
    # Camera order on the station (cam1..camN in ptzview).
    position: Mapped[int]
    decode: Mapped[bool]
    view: Mapped[bool]
    control: Mapped[bool]


class Selection(Base):
    """Camera shown on a station output, as chosen from the Core (ADR 0009).

    Runtime state, not part of the versioned configuration. No row means
    the Core has not chosen a camera for this output.
    """

    __tablename__ = "selections"

    station_id: Mapped[str] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True
    )
    output: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))


class StationStatus(Base):
    """Last status reported by a station (POST /api/stations/{id}/status).

    Kept in the database so that "last seen" survives a Core restart.
    """

    __tablename__ = "station_status"

    station_id: Mapped[str] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True
    )
    # Core clock, seconds since the epoch (UTC).
    received_at: Mapped[float]
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class MediaServer(Base):
    """A MediaMTX server whose API the Core reads for SRT statistics (ADR 0010)."""

    __tablename__ = "media_servers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str]
    # MediaMTX API, e.g. http://192.168.104.253:9997
    api_url: Mapped[str]
    # Where stations read SRT streams, host:port, e.g. 192.168.104.253:8890.
    srt_address: Mapped[str]
    api_username: Mapped[str | None]
    api_password: Mapped[str | None]
    enabled: Mapped[bool] = mapped_column(default=True)


class SrtSample(Base):
    """One reading of one SRT link, every few seconds (ADR 0010).

    link = "camera": camera -> media server (the server receives);
    link = "station": media server -> station (the server sends).
    Counters are cumulative since the connection started, as MediaMTX gives
    them; rates over an interval come from two consecutive samples.
    """

    __tablename__ = "srt_samples"
    __table_args__ = (
        Index("ix_srt_samples_ts", "ts"),
        Index("ix_srt_samples_camera", "camera_id", "ts"),
        Index("ix_srt_samples_station", "station_id", "ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[float]  # Core clock, seconds since the epoch (UTC)
    server_id: Mapped[str]
    link: Mapped[str]
    path: Mapped[str]
    # Not foreign keys: samples outlive the cameras and stations they describe.
    camera_id: Mapped[str | None]
    station_id: Mapped[str | None]
    connection_id: Mapped[str | None]
    remote_addr: Mapped[str | None]
    rtt_ms: Mapped[float | None]
    mbps: Mapped[float | None]  # receive rate (camera link) or send rate (station link)
    link_capacity_mbps: Mapped[float | None]
    packets: Mapped[int | None]  # received (camera link) or sent (station link)
    packets_lost: Mapped[int | None]
    packets_retrans: Mapped[int | None]
    packets_dropped: Mapped[int | None]  # too late to be played: picture damage
    buffer_ms: Mapped[float | None]


class StationSample(Base):
    """What a station reports about each stream it receives, every few seconds
    (from its status). Gives the receiver side of every link, and the only
    statistics of direct camera -> station links for now.

    camera_id None: station-wide figures (temperature, free CMA).
    """

    __tablename__ = "station_samples"
    __table_args__ = (
        Index("ix_station_samples_ts", "ts"),
        Index("ix_station_samples_station", "station_id", "ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[float]  # Core clock when the status was received
    station_id: Mapped[str]
    camera_id: Mapped[str | None]
    # How the camera reached the station at that time (None, None: direct).
    via_server_id: Mapped[str | None]
    via_path: Mapped[str | None]
    state: Mapped[str | None]
    fps: Mapped[float | None]
    mbps: Mapped[float | None]
    width: Mapped[int | None]
    height: Mapped[int | None]
    connects: Mapped[int | None]  # cumulative since the player started
    decode_errors: Mapped[int | None]  # cumulative since the player started
    temp_c: Mapped[float | None]
    cma_free_mb: Mapped[float | None]


class StationMetric(Base):
    """System figures of a station, one row per status (every few seconds)."""

    __tablename__ = "station_metrics"
    __table_args__ = (Index("ix_station_metrics_station", "station_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[float]
    station_id: Mapped[str]
    cpu_pct: Mapped[float | None]
    load1: Mapped[float | None]
    cpu_mhz: Mapped[int | None]
    temp_c: Mapped[float | None]
    # Raspberry Pi flags: bit 0 under-voltage, 1 frequency capped, 2 throttled,
    # 3 soft temperature limit (now); bits 16-19: the same since boot.
    throttled: Mapped[int | None]
    mem_total_mb: Mapped[int | None]
    mem_available_mb: Mapped[int | None]
    swap_used_mb: Mapped[int | None]
    cma_total_mb: Mapped[int | None]
    cma_free_mb: Mapped[int | None]
    disk_used_pct: Mapped[float | None]
    uptime_s: Mapped[int | None]
    ptzview_cpu_pct: Mapped[float | None]
    ptzview_rss_mb: Mapped[float | None]
    agent_cpu_pct: Mapped[float | None]
    agent_rss_mb: Mapped[float | None]
    # Per interface: rx_mbps, tx_mbps, rx_dropped, errors (since the last row).
    net: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
