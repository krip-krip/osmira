"""Local agent settings, read from a TOML file (see agent.toml.example)."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PtzviewSettings:
    binary: Path
    conf_path: Path
    http_port: int = 8081
    # Inputs of ptzview: fixed at 4 for now (NCAM in ptzview.c).
    slots: int = 4
    stop_timeout_s: float = 5.0
    restart_delay_s: float = 2.0
    # How long to keep retrying a switch while ptzview is (re)starting.
    select_retry_s: float = 10.0
    # Extra keys copied as-is into the [general] section of ptzview.conf.
    general: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    core_url: str
    station_id: str
    # Where the last configuration received from the Core is kept.
    state_dir: Path
    ptzview: PtzviewSettings
    poll_interval_s: float = 10.0
    request_timeout_s: float = 5.0
    # Pause before reopening the event stream after it broke.
    events_retry_s: float = 2.0


def load_settings(path: Path) -> Settings:
    """Read the TOML file. Relative paths are relative to the file's folder."""
    data = tomllib.loads(path.read_text())
    base = path.parent

    def resolve(value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (base / p).resolve()

    pv = data.get("ptzview", {})
    ptzview = PtzviewSettings(
        binary=resolve(pv.get("binary", "../player/ptzview")),
        conf_path=resolve(pv.get("conf_path", "state/ptzview.conf")),
        http_port=int(pv.get("http_port", 8081)),
        slots=int(pv.get("slots", 4)),
        stop_timeout_s=float(pv.get("stop_timeout_s", 5.0)),
        restart_delay_s=float(pv.get("restart_delay_s", 2.0)),
        select_retry_s=float(pv.get("select_retry_s", 10.0)),
        general={k: str(v) for k, v in pv.get("general", {}).items()},
    )
    return Settings(
        core_url=data["core_url"].rstrip("/"),
        station_id=data["station_id"],
        state_dir=resolve(data.get("state_dir", "state")),
        ptzview=ptzview,
        poll_interval_s=float(data.get("poll_interval_s", 10.0)),
        request_timeout_s=float(data.get("request_timeout_s", 5.0)),
        events_retry_s=float(data.get("events_retry_s", 2.0)),
    )
