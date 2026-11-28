"""Curves of a station's system figures (CPU, temperature, memory, CMA,
network, power flags) and of the streams it receives."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import StationMetric, StationSample
from osmiracore.schemas import StationMetricsSeries
from osmiracore.services.links import counter_delta, station_srt_delta

DEFAULT_POINTS = 600
UNDER_VOLTAGE = 0x1
THROTTLING = 0x2 | 0x4 | 0x8  # frequency capped, throttled, soft temperature limit
SINCE_BOOT = 0xF0000
MAX_GAP_S = 20.0

# Column -> how a bucket is summarised. Minimum for what must not hide a dip.
GAUGES: dict[str, Callable[[list[float]], float]] = {
    "cpu_pct": lambda v: sum(v) / len(v),
    "load1": lambda v: sum(v) / len(v),
    "cpu_mhz": lambda v: sum(v) / len(v),
    "temp_c": max,
    "mem_available_mb": min,
    "swap_used_mb": max,
    "cma_free_mb": min,
    "disk_used_pct": max,
    "ptzview_cpu_pct": lambda v: sum(v) / len(v),
    "ptzview_rss_mb": max,
    "agent_rss_mb": max,
}


def series(
    session: Session,
    station_id: str,
    since: float,
    until: float | None = None,
    points: int = DEFAULT_POINTS,
    now: float | None = None,
) -> StationMetricsSeries:
    now = time.time() if now is None else now
    until = now if until is None else until
    bucket = max(5.0, (until - since) / max(points, 1))
    count = int((until - since) // bucket) + 1
    rows = session.scalars(
        select(StationMetric)
        .where(
            StationMetric.station_id == station_id,
            StationMetric.ts >= since,
            StationMetric.ts <= until,
        )
        .order_by(StationMetric.ts, StationMetric.id)
    ).all()

    gauges: dict[str, list[list[float]]] = {k: [[] for _ in range(count)] for k in GAUGES}
    flags = [0] * count
    has_flags = [False] * count
    net: dict[str, dict[str, list[list[float]]]] = {}
    summary: dict[str, Any] = {
        "cpu_max": None,
        "temp_max": None,
        "cma_free_min": None,
        "mem_available_min": None,
        "under_voltage_s": 0.0,
        "throttled_s": 0.0,
        "reboots": 0,
        "samples": len(rows),
    }
    prev: StationMetric | None = None
    for row in rows:
        i = int((row.ts - since) // bucket)
        for key in GAUGES:
            value = getattr(row, key)
            if value is not None:
                gauges[key][i].append(float(value))
        if row.throttled is not None:
            flags[i] |= row.throttled
            has_flags[i] = True
        for iface, values in (row.net or {}).items():
            per = net.setdefault(
                iface,
                {
                    k: [[] for _ in range(count)]
                    for k in ("rx_mbps", "tx_mbps", "rx_dropped", "errors")
                },
            )
            for key, cells in per.items():
                if isinstance(values.get(key), int | float):
                    cells[i].append(float(values[key]))
        _summarise(summary, row, prev)
        prev = row

    return StationMetricsSeries(
        station_id=station_id,
        bucket_s=round(bucket, 2),
        t=[round(since + i * bucket, 1) for i in range(count)],
        series={
            **{
                k: [_round(GAUGES[k](c)) if c else None for c in cells]
                for k, cells in gauges.items()
            },
            "under_voltage": [
                (1.0 if f & UNDER_VOLTAGE else 0.0) if ok else None
                for f, ok in zip(flags, has_flags, strict=True)
            ],
            "throttled": [
                (1.0 if f & THROTTLING else 0.0) if ok else None
                for f, ok in zip(flags, has_flags, strict=True)
            ],
        },
        net={
            iface: {
                key: [
                    (_round(sum(c)) if key in ("rx_dropped", "errors") else _round(sum(c) / len(c)))
                    if c
                    else None
                    for c in cells
                ]
                for key, cells in per.items()
            }
            for iface, per in sorted(net.items())
        },
        cameras=_camera_series(session, station_id, since, until, bucket, count),
        latest=_latest(rows[-1], now) if rows else None,
        summary=summary,
    )


def _summarise(summary: dict[str, Any], row: StationMetric, prev: StationMetric | None) -> None:
    def keep(key: str, value: float | None, pick: Callable[[float, float], float]) -> None:
        if value is not None:
            summary[key] = value if summary[key] is None else pick(summary[key], value)

    keep("cpu_max", row.cpu_pct, max)
    keep("temp_max", row.temp_c, max)
    keep("cma_free_min", row.cma_free_mb, min)
    keep("mem_available_min", row.mem_available_mb, min)
    if prev is None:
        return
    gap = row.ts - prev.ts
    if gap <= MAX_GAP_S and row.throttled is not None:
        if row.throttled & UNDER_VOLTAGE:
            summary["under_voltage_s"] = round(summary["under_voltage_s"] + gap, 1)
        if row.throttled & THROTTLING:
            summary["throttled_s"] = round(summary["throttled_s"] + gap, 1)
    if row.uptime_s is not None and prev.uptime_s is not None and row.uptime_s < prev.uptime_s:
        summary["reboots"] += 1


def _camera_series(
    session: Session, station_id: str, since: float, until: float, bucket: float, count: int
) -> dict[str, dict[str, list[float | None]]]:
    rows = session.scalars(
        select(StationSample)
        .where(
            StationSample.station_id == station_id,
            StationSample.camera_id.is_not(None),
            StationSample.ts >= since,
            StationSample.ts <= until,
        )
        .order_by(StationSample.ts, StationSample.id)
    ).all()
    fps: dict[str, list[list[float]]] = {}
    errors: dict[str, list[float | None]] = {}
    dropped: dict[str, list[float | None]] = {}
    lost: dict[str, list[int]] = {}
    packets: dict[str, list[int]] = {}
    prev: dict[str, StationSample] = {}
    for row in rows:
        cam = row.camera_id or ""
        i = int((row.ts - since) // bucket)
        fps.setdefault(cam, [[] for _ in range(count)])[i].append(row.fps or 0.0)
        errs = errors.setdefault(cam, [None] * count)
        drops = dropped.setdefault(cam, [None] * count)
        cam_lost = lost.setdefault(cam, [0] * count)
        cam_packets = packets.setdefault(cam, [0] * count)
        before = prev.get(cam)
        if before is not None:
            if row.decode_errors is not None and before.decode_errors is not None:
                errs[i] = (errs[i] or 0) + counter_delta(row.decode_errors, before.decode_errors)
            d = station_srt_delta(row, before)
            if d is not None:
                drops[i] = (drops[i] or 0) + d.dropped
                cam_lost[i] += d.lost
                cam_packets[i] += d.packets
        prev[cam] = row
    return {
        cam: {
            "fps": [_round(sum(c) / len(c)) if c else None for c in cells],
            "decode_errors": errors[cam],
            "srt_dropped": dropped[cam],
            "srt_loss_percent": [
                _round(100 * x / pk) if pk else (0.0 if drop is not None else None)
                for x, pk, drop in zip(lost[cam], packets[cam], dropped[cam], strict=True)
            ],
        }
        for cam, cells in sorted(fps.items())
    }


def _latest(row: StationMetric, now: float) -> dict[str, Any]:
    flags = row.throttled
    return {
        "seen": datetime.fromtimestamp(row.ts, UTC).isoformat(timespec="seconds"),
        "seconds_since": round(max(0.0, now - row.ts), 1),
        **{
            key: getattr(row, key)
            for key in (
                "cpu_pct",
                "load1",
                "cpu_mhz",
                "temp_c",
                "mem_total_mb",
                "mem_available_mb",
                "swap_used_mb",
                "cma_total_mb",
                "cma_free_mb",
                "disk_used_pct",
                "uptime_s",
                "ptzview_cpu_pct",
                "ptzview_rss_mb",
                "agent_cpu_pct",
                "agent_rss_mb",
            )
        },
        "throttled": flags,
        "under_voltage_now": bool(flags & UNDER_VOLTAGE) if flags is not None else None,
        "throttled_now": bool(flags & THROTTLING) if flags is not None else None,
        "since_boot": bool(flags & SINCE_BOOT) if flags is not None else None,
        "net": row.net or {},
    }


def _round(value: float) -> float:
    return round(value, 2)
