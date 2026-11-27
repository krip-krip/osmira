"""Database tables. See docs/modele-donnees.md."""

from typing import Any

from sqlalchemy import JSON, String
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
