"""Links over a period, rebuilt from the SRT samples (media servers) and the
station samples (what each station reports). A link is a pair of ends; its
successive SRT connections and player restarts are added together."""

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from osmiracore.models import SrtSample, StationSample
from osmiracore.schemas import LinkSeries, LinkSummary

SEP = "|"
# A gap longer than this between two station samples (station offline) is
# not counted as time without picture.
MAX_GAP_S = 20.0
DEFAULT_POINTS = 600


def link_id(kind: str, *parts: str | None) -> str:
    return SEP.join([kind, *(p or "" for p in parts)])


def _srt_link_id(row: SrtSample) -> str:
    if row.link == "camera":
        return link_id("camera_server", row.server_id, row.path)
    station = row.station_id or f"?{(row.remote_addr or '').rsplit(':', 1)[0]}"
    return link_id("server_station", row.server_id, row.path, station)


def _station_link_id(row: StationSample) -> str:
    if row.via_server_id:
        return link_id("server_station", row.via_server_id, row.via_path, row.station_id)
    return link_id("camera_station", row.camera_id, row.station_id)


def _ends(lid: str) -> dict[str, str | None]:
    kind, *parts = lid.split(SEP)
    if kind == "camera_server":
        return {"kind": kind, "server_id": parts[0], "path": parts[1]}
    if kind == "server_station":
        return {"kind": kind, "server_id": parts[0], "path": parts[1], "station_id": parts[2]}
    return {"kind": kind, "camera_id": parts[0], "station_id": parts[1]}


def _delta(new: int | None, old: int | None) -> int:
    """Increase of a cumulative counter; after a reset, the new value."""
    if new is None:
        return 0
    if old is None or new < old:
        return new if old is not None else 0
    return new - old


@dataclass
class _Acc:
    first: float = float("inf")
    last: float = 0.0
    camera_id: str | None = None
    # SRT side
    connections: set[str] = field(default_factory=set)
    srt_prev: dict[str, SrtSample] = field(default_factory=dict)
    srt_samples: int = 0
    packets: int = 0
    lost: int = 0
    retrans: int = 0
    dropped: int = 0
    rtt: list[float] = field(default_factory=list)
    mbps: list[float] = field(default_factory=list)
    # Station side
    st_prev: StationSample | None = None
    st_samples: int = 0
    fps: list[float] = field(default_factory=list)
    no_picture_s: float = 0.0
    decode_errors: int = 0
    reconnects: int = 0

    def seen(self, ts: float, camera_id: str | None) -> None:
        self.first = min(self.first, ts)
        self.last = max(self.last, ts)
        self.camera_id = camera_id or self.camera_id

    def add_srt(self, row: SrtSample) -> None:
        self.seen(row.ts, row.camera_id)
        self.srt_samples += 1
        conn = row.connection_id or ""
        self.connections.add(conn)
        prev = self.srt_prev.get(conn)
        if prev is not None:
            self.packets += _delta(row.packets, prev.packets)
            self.lost += _delta(row.packets_lost, prev.packets_lost)
            self.retrans += _delta(row.packets_retrans, prev.packets_retrans)
            self.dropped += _delta(row.packets_dropped, prev.packets_dropped)
        self.srt_prev[conn] = row
        if row.rtt_ms is not None:
            self.rtt.append(row.rtt_ms)
        if row.mbps is not None:
            self.mbps.append(row.mbps)

    def add_station(self, row: StationSample) -> None:
        self.seen(row.ts, row.camera_id)
        self.st_samples += 1
        prev = self.st_prev
        fps = row.fps or 0.0
        self.fps.append(fps)
        if prev is not None:
            gap = row.ts - prev.ts
            if fps < 1 and gap <= MAX_GAP_S:
                self.no_picture_s += gap
            self.decode_errors += _delta(row.decode_errors, prev.decode_errors)
            self.reconnects += _delta(row.connects, prev.connects)
        self.st_prev = row


def _rows(
    session: Session, since: float, until: float
) -> tuple[list[SrtSample], list[StationSample]]:
    srt = session.scalars(
        select(SrtSample)
        .where(SrtSample.ts >= since, SrtSample.ts <= until)
        .order_by(SrtSample.ts, SrtSample.id)
    ).all()
    st = session.scalars(
        select(StationSample)
        .where(
            StationSample.ts >= since,
            StationSample.ts <= until,
            StationSample.camera_id.is_not(None),
        )
        .order_by(StationSample.ts, StationSample.id)
    ).all()
    return list(srt), list(st)


def list_links(
    session: Session,
    since: float,
    until: float | None = None,
    active_s: float = 15.0,
    now: float | None = None,
) -> list[LinkSummary]:
    now = time.time() if now is None else now
    until = now if until is None else until
    srt, st = _rows(session, since, until)
    accs: dict[str, _Acc] = {}
    for row in srt:
        accs.setdefault(_srt_link_id(row), _Acc()).add_srt(row)
    for row in st:
        accs.setdefault(_station_link_id(row), _Acc()).add_station(row)
    links = [_summary(lid, acc, now, active_s) for lid, acc in accs.items()]
    order = {"camera_server": 0, "server_station": 1, "camera_station": 2}
    return sorted(
        links,
        key=lambda x: (x.camera_id or x.path or "", order[x.kind], x.station_id or ""),
    )


def _summary(lid: str, acc: _Acc, now: float, active_s: float) -> LinkSummary:
    ends = _ends(lid)
    has_srt = acc.srt_samples > 0
    has_station = acc.st_samples > 0
    return LinkSummary(
        id=lid,
        kind=ends["kind"],  # checked by the schema
        camera_id=ends.get("camera_id") or acc.camera_id,
        server_id=ends.get("server_id"),
        path=ends.get("path"),
        station_id=ends.get("station_id"),
        active=now - acc.last <= active_s,
        first_seen=_iso(acc.first),
        last_seen=_iso(acc.last),
        duration_s=round(acc.last - acc.first, 1),
        connections=len(acc.connections) if has_srt else None,
        packets=acc.packets if has_srt else None,
        packets_lost=acc.lost if has_srt else None,
        packets_retrans=acc.retrans if has_srt else None,
        packets_dropped=acc.dropped if has_srt else None,
        loss_percent=round(100 * acc.lost / acc.packets, 3) if has_srt and acc.packets else None,
        rtt_avg_ms=_avg(acc.rtt),
        rtt_max_ms=round(max(acc.rtt), 2) if acc.rtt else None,
        mbps_avg=_avg(acc.mbps),
        fps_avg=_avg(acc.fps) if has_station else None,
        fps_min=round(min(acc.fps), 1) if has_station else None,
        no_picture_s=round(acc.no_picture_s, 1) if has_station else None,
        decode_errors=acc.decode_errors if has_station else None,
        reconnects=acc.reconnects if has_station else None,
    )


def series(
    session: Session,
    lid: str,
    since: float,
    until: float | None = None,
    points: int = DEFAULT_POINTS,
    now: float | None = None,
) -> LinkSeries:
    """Curves of one link, averaged (or summed for counts) in time buckets."""
    now = time.time() if now is None else now
    until = now if until is None else until
    bucket = max(5.0, (until - since) / max(points, 1))
    count = int((until - since) // bucket) + 1
    srt, st = _rows(session, since, until)
    b = _Buckets(count)
    prev_srt: dict[str, SrtSample] = {}
    for row in srt:
        if _srt_link_id(row) != lid:
            continue
        i = int((row.ts - since) // bucket)
        conn = row.connection_id or ""
        prev = prev_srt.get(conn)
        if row.rtt_ms is not None:
            b.rtt[i].append(row.rtt_ms)
        if row.mbps is not None:
            b.mbps[i].append(row.mbps)
        if prev is not None:
            b.packets[i] += _delta(row.packets, prev.packets)
            b.lost[i] += _delta(row.packets_lost, prev.packets_lost)
            b.retrans[i] += _delta(row.packets_retrans, prev.packets_retrans)
            b.dropped[i] += _delta(row.packets_dropped, prev.packets_dropped)
            b.srt_seconds[i] += row.ts - prev.ts
            b.has_srt[i] = True
        prev_srt[conn] = row
    prev_st: StationSample | None = None
    for row in st:
        if _station_link_id(row) != lid:
            continue
        i = int((row.ts - since) // bucket)
        b.fps[i].append(row.fps or 0.0)
        if row.mbps is not None:
            b.st_mbps[i].append(row.mbps)
        if prev_st is not None:
            b.decode[i] += _delta(row.decode_errors, prev_st.decode_errors)
            b.has_st[i] = True  # a count needs two samples, like the SRT losses
        prev_st = row
    return LinkSeries(
        id=lid,
        bucket_s=round(bucket, 2),
        t=[round(since + i * bucket, 1) for i in range(count)],
        rtt_ms=[_avg(x) for x in b.rtt],
        mbps=[_avg(x) for x in b.mbps],
        loss_percent=[
            round(100 * lost / pk, 3) if ok and pk else (0.0 if ok else None)
            for lost, pk, ok in zip(b.lost, b.packets, b.has_srt, strict=True)
        ],
        retrans_per_s=[
            round(r / sec, 2) if ok and sec else None
            for r, sec, ok in zip(b.retrans, b.srt_seconds, b.has_srt, strict=True)
        ],
        dropped=[d if ok else None for d, ok in zip(b.dropped, b.has_srt, strict=True)],
        fps=[_avg(x) for x in b.fps],
        station_mbps=[_avg(x) for x in b.st_mbps],
        decode_errors=[d if ok else None for d, ok in zip(b.decode, b.has_st, strict=True)],
    )


class _Buckets:
    def __init__(self, n: int) -> None:
        self.rtt: list[list[float]] = [[] for _ in range(n)]
        self.mbps: list[list[float]] = [[] for _ in range(n)]
        self.fps: list[list[float]] = [[] for _ in range(n)]
        self.st_mbps: list[list[float]] = [[] for _ in range(n)]
        self.packets = [0] * n
        self.lost = [0] * n
        self.retrans = [0] * n
        self.dropped = [0] * n
        self.decode = [0] * n
        self.srt_seconds = [0.0] * n
        self.has_srt = [False] * n
        self.has_st = [False] * n


def _avg(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(sum(values) / len(values), 2) if values else None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")
