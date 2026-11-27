"""What the station is: hardware and system facts sent to the Core with its status."""

import platform
import socket
import subprocess
from pathlib import Path


def _read(path: str) -> str:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def hardware() -> dict[str, object]:
    """Fixed facts, read once at start."""
    model = _read("/proc/device-tree/model").rstrip("\x00\n") or platform.machine()
    ram_kb = 0
    for line in _read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            ram_kb = int(line.split()[1])
    os_name = ""
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            os_name = line.split("=", 1)[1].strip().strip('"')
    return {
        "model": model,
        "arch": platform.machine(),
        "ram_mb": ram_kb // 1024,
        "os": os_name or platform.system(),
        "kernel": platform.release(),
        "python": platform.python_version(),
    }


def hostname() -> str:
    return socket.gethostname()


def addresses() -> list[str]:
    """IPv4 addresses of the station (used later to match SRT connections)."""
    try:
        out = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=2, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [a for a in out.split() if ":" not in a]


def uptime_s() -> int:
    text = _read("/proc/uptime")
    return int(float(text.split()[0])) if text else 0


def temperature_c() -> float | None:
    text = _read("/sys/class/thermal/thermal_zone0/temp").strip()
    return round(int(text) / 1000, 1) if text.isdigit() else None
