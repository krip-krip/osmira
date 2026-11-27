"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # SQLite database file (created on first start).
    db_path: Path


def load_settings() -> Settings:
    return Settings(
        db_path=Path(os.environ.get("OSMIRACORE_DB_PATH", "osmiracore.db")),
    )
