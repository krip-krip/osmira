"""System figures read from a fake /proc and /sys."""

from pathlib import Path

from osmiracam_agent.metrics import SystemMetrics, _Reader

STAT_1 = "cpu  1000 0 1000 8000 0 0 0 0 0 0\n"
STAT_2 = "cpu  1300 0 1300 8400 0 0 0 0 0 0\n"  # +600 busy, +400 idle -> 60 %
NET_1 = (
    "Inter-|   Receive\n face |bytes packets errs drop ...\n"
    "    lo: 100 1 0 0 0 0 0 0 100 1 0 0 0 0 0 0\n"
    "  eth0: 1000000 10 0 0 0 0 0 0 500000 5 0 0 0 0 0 0\n"
    "   wt0: 2000000 20 0 1 0 0 0 0 0 0 0 0 0 0 0 0\n"
)
NET_2 = (
    "Inter-|   Receive\n face |bytes packets errs drop ...\n"
    "    lo: 100 1 0 0 0 0 0 0 100 1 0 0 0 0 0 0\n"
    "  eth0: 11000000 10 0 0 0 0 0 0 1750000 5 0 0 0 0 0 0\n"  # +10 MB in 5 s = 16 Mb/s
    "   wt0: 2000000 20 2 4 0 0 0 0 0 0 0 0 0 0 0 0\n"  # +3 dropped, +2 errors
)


def write(root: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        target = root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def fake_root(tmp_path: Path, stat: str, net: str, ptz_ticks: int) -> None:
    write(
        tmp_path,
        {
            "/proc/stat": stat,
            "/proc/net/dev": net,
            "/proc/loadavg": "2.66 2.43 2.18 4/206 6830\n",
            "/proc/uptime": "3600.5 1000.0\n",
            "/proc/meminfo": "MemTotal: 927256 kB\nMemAvailable: 432276 kB\nSwapTotal: 926716 kB\n"
            "SwapFree: 916716 kB\nCmaTotal: 524288 kB\nCmaFree: 20616 kB\n",
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq": "1800000\n",
            "/sys/class/thermal/thermal_zone0/temp": "61300\n",
            "/proc/4242/comm": "ptzview\n",
            "/proc/4242/stat": f"4242 (ptzview) S 1 1 1 0 -1 0 0 0 0 0 {ptz_ticks} 0 0 0\n",
            "/proc/4242/status": "Name: ptzview\nVmRSS: 102400 kB\n",
        },
    )


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_first_sample_has_no_rates_second_has_them(tmp_path):
    clock = Clock()
    fake_root(tmp_path, STAT_1, NET_1, ptz_ticks=1000)
    metrics = SystemMetrics(_Reader(tmp_path), clock)

    first = metrics.sample(throttled=0)
    fake_root(tmp_path, STAT_2, NET_2, ptz_ticks=1250)  # +250 ticks in 5 s = 50 %
    clock.t += 5
    second = metrics.sample(throttled=0x50005)

    assert first["cpu_pct"] is None and first["net"]["eth0"]["rx_mbps"] is None
    assert second["cpu_pct"] == 60.0
    assert second["net"]["eth0"] == {"rx_mbps": 16.0, "tx_mbps": 2.0, "rx_dropped": 0, "errors": 0}
    assert second["net"]["wt0"]["rx_dropped"] == 3 and second["net"]["wt0"]["errors"] == 2
    assert "lo" not in second["net"]
    assert second["processes"]["ptzview"] == {"cpu_pct": 50.0, "rss_mb": 100.0}
    assert second["throttled"] == 0x50005


def test_fixed_figures(tmp_path):
    fake_root(tmp_path, STAT_1, NET_1, ptz_ticks=0)

    m = SystemMetrics(_Reader(tmp_path), Clock()).sample()

    assert (m["load1"], m["cpu_mhz"], m["temp_c"], m["uptime_s"]) == (2.66, 1800, 61.3, 3600)
    assert (m["mem_total_mb"], m["mem_available_mb"], m["swap_used_mb"]) == (905, 422, 9)
    assert (m["cma_total_mb"], m["cma_free_mb"]) == (512, 20)
    assert 0 <= m["disk_used_pct"] <= 100


def test_missing_files_give_none(tmp_path):
    m = SystemMetrics(_Reader(tmp_path), Clock()).sample()

    assert m["cpu_pct"] is None and m["temp_c"] is None and m["cma_free_mb"] is None
    assert m["processes"]["ptzview"] == {"cpu_pct": None, "rss_mb": None}
    assert m["net"] == {}
