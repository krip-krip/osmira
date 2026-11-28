"""Local agent settings, read from a TOML file (see agent.toml.example)."""

import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# MAX_CAMS and MAX_OUTPUTS in player/src/ptzview.h.
MAX_SLOTS = 16
MAX_OUTPUTS = 4


@dataclass(frozen=True)
class PtzviewSettings:
    binary: Path
    conf_path: Path
    http_port: int = 8081
    # Inputs of ptzview ("cameras" in ptzview.conf), 1 to MAX_SLOTS. The real
    # limit is the hardware (4 HEVC 1080p50 streams on a Pi 4).
    slots: int = 4
    stop_timeout_s: float = 5.0
    restart_delay_s: float = 2.0
    # How long to keep retrying a switch while ptzview is (re)starting.
    select_retry_s: float = 10.0
    # Extra keys copied as-is into the [general] section of ptzview.conf.
    general: dict[str, str] = field(default_factory=dict)
    # Extra keys of outputs 2.. ([ptzview.output2]...), copied into [outputN].
    # Output 1 is set by `general` (connector, hdmi_mode...).
    outputs: dict[int, dict[str, str]] = field(default_factory=dict)


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
    # Seconds between two status reports to the Core (also the heartbeat).
    status_interval_s: float = 5.0
    # Sign SRT connections with station=<id> in the MediaMTX streamid (ADR 0010).
    tag_srt_streamid: bool = True


def load_settings(path: Path) -> Settings:
    """Read the TOML file. Relative paths are relative to the file's folder."""
    data = tomllib.loads(path.read_text())
    base = path.parent

    def resolve(value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (base / p).resolve()

    pv = data.get("ptzview", {})
    slots = int(pv.get("slots", 4))
    if not 1 <= slots <= MAX_SLOTS:
        raise ValueError(f"{path}: [ptzview] slots = {slots}, expected 1 to {MAX_SLOTS}")
    ptzview = PtzviewSettings(
        binary=resolve(pv.get("binary", "../player/ptzview")),
        conf_path=resolve(pv.get("conf_path", "state/ptzview.conf")),
        http_port=int(pv.get("http_port", 8081)),
        slots=slots,
        stop_timeout_s=float(pv.get("stop_timeout_s", 5.0)),
        restart_delay_s=float(pv.get("restart_delay_s", 2.0)),
        select_retry_s=float(pv.get("select_retry_s", 10.0)),
        general={k: str(v) for k, v in pv.get("general", {}).items()},
        outputs={
            n: {k: str(v) for k, v in pv.get(f"output{n}", {}).items()}
            for n in range(2, MAX_OUTPUTS + 1)
            if f"output{n}" in pv
        },
    )
    return Settings(
        core_url=data["core_url"].rstrip("/"),
        # Defaults to the hostname of the Pi (panelTest...).
        station_id=data.get("station_id") or socket.gethostname(),
        state_dir=resolve(data.get("state_dir", "state")),
        ptzview=ptzview,
        poll_interval_s=float(data.get("poll_interval_s", 10.0)),
        request_timeout_s=float(data.get("request_timeout_s", 5.0)),
        events_retry_s=float(data.get("events_retry_s", 2.0)),
        status_interval_s=float(data.get("status_interval_s", 5.0)),
        tag_srt_streamid=bool(data.get("tag_srt_streamid", True)),
    )
