"""Database tables. See docs/modele-donnees.md."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from osmiracore.db import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str]

    # Media block: how a station receives the picture.
    media_srt_url: Mapped[str]
    media_latency_ms: Mapped[int]
    media_codec: Mapped[str]
    media_width: Mapped[int]
    media_height: Mapped[int]
    media_fps: Mapped[int]

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
