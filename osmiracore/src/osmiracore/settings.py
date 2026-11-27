"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # SQLite database file (created on first start).
    db_path: Path
    # A station is offline when its last status is older than this (it sends
    # one every 5 s by default).
    online_timeout_s: float = 15.0


def load_settings() -> Settings:
    return Settings(
        db_path=Path(os.environ.get("OSMIRACORE_DB_PATH", "osmiracore.db")),
        online_timeout_s=float(os.environ.get("OSMIRACORE_ONLINE_TIMEOUT_S", "15")),
    )
