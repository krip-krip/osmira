"""System figures of the station, sent with each status (read from /proc and
/sys; no dependency). Rates (CPU %, Mb/s) are computed between two calls."""

import os
import subprocess
import time
from pathlib import Path
from typing import Any

THROTTLED_SYSFS = Path("/sys/devices/platform/soc/soc:firmware/get_throttled")


class _Reader:
    """File access in one place, so that tests can give their own /proc."""

    def __init__(self, root: Path = Path("/")) -> None:
        self.root = root

    def text(self, path: str) -> str:
        try:
            return (self.root / path.lstrip("/")).read_text(errors="replace")
        except OSError:
            return ""


def throttled_flags() -> int | None:
    """Raspberry Pi power/throttling flags (bit 0 under-voltage now, 2 throttled
    now, 3 soft temperature limit now, 16-19 the same since boot)."""
    try:
        return int(THROTTLED_SYSFS.read_text().strip(), 16)
    except (OSError, ValueError):
        pass
    try:
        out = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2, check=False
        ).stdout
        return int(out.strip().split("=", 1)[1], 16)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None


class SystemMetrics:
    def __init__(self, reader: _Reader | None = None, clock: Any = time.monotonic) -> None:  # noqa: ANN401
        self._r = reader or _Reader()
        self._clock = clock
        self._tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self._prev_cpu: tuple[int, int] | None = None
        self._prev_net: dict[str, tuple[int, int, int, int, int]] = {}
        self._prev_proc: dict[int, int] = {}
        self._prev_t: float | None = None

    def sample(self, throttled: int | None = None) -> dict[str, Any]:
        now = self._clock()
        dt = now - self._prev_t if self._prev_t is not None else None
        self._prev_t = now
        meminfo = self._meminfo()
        result: dict[str, Any] = {
            "cpu_pct": self._cpu_pct(),
            "load1": self._load1(),
            "cpu_mhz": self._cpu_mhz(),
            "temp_c": self._temp_c(),
            "throttled": throttled,
            "mem_total_mb": meminfo.get("MemTotal", 0) // 1024 or None,
            "mem_available_mb": meminfo.get("MemAvailable", 0) // 1024 or None,
            "swap_used_mb": (meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0)) // 1024,
            "cma_total_mb": meminfo.get("CmaTotal", 0) // 1024 or None,
            "cma_free_mb": meminfo.get("CmaFree", 0) // 1024 if "CmaFree" in meminfo else None,
            "disk_used_pct": self._disk_used_pct(),
            "uptime_s": self._uptime_s(),
            "net": self._net(dt),
            "processes": {
                "ptzview": self._process(self._pid_of("ptzview"), dt),
                "agent": self._process(os.getpid(), dt),
            },
        }
        return result

    # --- readers -------------------------------------------------------------------

    def _meminfo(self) -> dict[str, int]:
        found = {}
        for line in self._r.text("/proc/meminfo").splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                found[key] = int(parts[0])  # kB
        return found

    def _cpu_pct(self) -> float | None:
        line = self._r.text("/proc/stat").splitlines()[:1]
        if not line or not line[0].startswith("cpu "):
            return None
        values = [int(x) for x in line[0].split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        prev, self._prev_cpu = self._prev_cpu, (idle, total)
        if prev is None or total <= prev[1]:
            return None
        return round(100 * (1 - (idle - prev[0]) / (total - prev[1])), 1)

    def _load1(self) -> float | None:
        text = self._r.text("/proc/loadavg").split()
        return float(text[0]) if text else None

    def _cpu_mhz(self) -> int | None:
        text = self._r.text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").strip()
        return int(text) // 1000 if text.isdigit() else None

    def _temp_c(self) -> float | None:
        text = self._r.text("/sys/class/thermal/thermal_zone0/temp").strip()
        return round(int(text) / 1000, 1) if text.isdigit() else None

    def _uptime_s(self) -> int | None:
        text = self._r.text("/proc/uptime").split()
        return int(float(text[0])) if text else None

    def _disk_used_pct(self) -> float | None:
        try:
            st = os.statvfs(self._r.root)
        except OSError:
            return None
        if not st.f_blocks:
            return None
        return round(100 * (1 - st.f_bavail / st.f_blocks), 1)

    def _net(self, dt: float | None) -> dict[str, dict[str, float | int | None]]:
        """Per interface: Mb/s received and sent, dropped and error packets since
        the last sample."""
        found: dict[str, dict[str, float | int | None]] = {}
        current: dict[str, tuple[int, int, int, int, int]] = {}
        for line in self._r.text("/proc/net/dev").splitlines()[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            fields = rest.split()
            if name == "lo" or len(fields) < 12:
                continue
            rx_bytes, rx_errs, rx_drop = int(fields[0]), int(fields[2]), int(fields[3])
            tx_bytes, tx_errs = int(fields[8]), int(fields[10])
            current[name] = (rx_bytes, rx_errs, rx_drop, tx_bytes, tx_errs)
            prev = self._prev_net.get(name)
            if prev is None or not dt:
                found[name] = {"rx_mbps": None, "tx_mbps": None, "rx_dropped": None, "errors": None}
                continue
            found[name] = {
                "rx_mbps": round(max(0, rx_bytes - prev[0]) * 8 / dt / 1e6, 2),
                "tx_mbps": round(max(0, tx_bytes - prev[3]) * 8 / dt / 1e6, 2),
                "rx_dropped": max(0, rx_drop - prev[2]),
                "errors": max(0, rx_errs - prev[1]) + max(0, tx_errs - prev[4]),
            }
        self._prev_net = current
        return found

    def _pid_of(self, name: str) -> int | None:
        proc = self._r.root / "proc"
        try:
            entries = [e for e in os.listdir(proc) if e.isdigit()]
        except OSError:
            return None
        for entry in entries:
            if self._r.text(f"/proc/{entry}/comm").strip() == name:
                return int(entry)
        return None

    def _process(self, pid: int | None, dt: float | None) -> dict[str, float | None]:
        """CPU % (100 = one core) and resident memory of a process."""
        if pid is None:
            return {"cpu_pct": None, "rss_mb": None}
        stat = self._r.text(f"/proc/{pid}/stat")
        rss_mb = None
        for line in self._r.text(f"/proc/{pid}/status").splitlines():
            if line.startswith("VmRSS:"):
                rss_mb = round(int(line.split()[1]) / 1024, 1)
        cpu_pct = None
        if stat:
            # Fields after the ")" of the command name: utime is the 12th, stime the 13th.
            fields = stat.rsplit(")", 1)[-1].split()
            ticks = int(fields[11]) + int(fields[12])
            prev = self._prev_proc.get(pid)
            self._prev_proc[pid] = ticks
            if prev is not None and dt:
                cpu_pct = round(100 * (ticks - prev) / self._tck / dt, 1)
        return {"cpu_pct": cpu_pct, "rss_mb": rss_mb}
