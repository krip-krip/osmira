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


def counter_delta(new: int | None, old: int | None) -> int:
    """Increase of a cumulative counter; after a reset, the new value."""
    if new is None:
        return 0
    if old is None or new < old:
        return new if old is not None else 0
    return new - old


@dataclass
class StationSrtDelta:
    """Increase of the station's SRT counters between two station samples."""

    packets: int = 0
    lost: int = 0
    retrans: int = 0
    dropped: int = 0


def station_srt_delta(row: StationSample, prev: StationSample) -> StationSrtDelta | None:
    """None when the station reported no SRT figures. The counters start
    again with each connection: after a reconnection (connects changed), the
    whole new value counts."""
    if row.srt_packets is None:
        return None
    if row.connects != prev.connects or prev.srt_packets is None:
        return StationSrtDelta(
            row.srt_packets, row.srt_lost or 0, row.srt_retrans or 0, row.srt_dropped or 0
        )
    return StationSrtDelta(
        counter_delta(row.srt_packets, prev.srt_packets),
        counter_delta(row.srt_lost, prev.srt_lost),
        counter_delta(row.srt_retrans, prev.srt_retrans),
        counter_delta(row.srt_dropped, prev.srt_dropped),
    )


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
    # SRT seen by the station
    st_srt: StationSrtDelta | None = None
    st_rtt: list[float] = field(default_factory=list)
    st_latency: int | None = None

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
            self.packets += counter_delta(row.packets, prev.packets)
            self.lost += counter_delta(row.packets_lost, prev.packets_lost)
            self.retrans += counter_delta(row.packets_retrans, prev.packets_retrans)
            self.dropped += counter_delta(row.packets_dropped, prev.packets_dropped)
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
        if row.srt_rtt_ms is not None:
            self.st_rtt.append(row.srt_rtt_ms)
        if row.srt_latency_ms is not None:
            self.st_latency = row.srt_latency_ms
        if prev is not None:
            gap = row.ts - prev.ts
            if fps < 1 and gap <= MAX_GAP_S:
                self.no_picture_s += gap
            self.decode_errors += counter_delta(row.decode_errors, prev.decode_errors)
            self.reconnects += counter_delta(row.connects, prev.connects)
            d = station_srt_delta(row, prev)
            if d is not None:
                t = self.st_srt = self.st_srt or StationSrtDelta()
                t.packets += d.packets
                t.lost += d.lost
                t.retrans += d.retrans
                t.dropped += d.dropped
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
    st = acc.st_srt
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
        station_packets=st.packets if st else None,
        station_lost=st.lost if st else None,
        station_retrans=st.retrans if st else None,
        station_dropped=st.dropped if st else None,
        station_loss_percent=round(100 * st.lost / st.packets, 3) if st and st.packets else None,
        station_rtt_avg_ms=_avg(acc.st_rtt),
        station_latency_ms=acc.st_latency,
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
            b.packets[i] += counter_delta(row.packets, prev.packets)
            b.lost[i] += counter_delta(row.packets_lost, prev.packets_lost)
            b.retrans[i] += counter_delta(row.packets_retrans, prev.packets_retrans)
            b.dropped[i] += counter_delta(row.packets_dropped, prev.packets_dropped)
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
        if row.srt_rtt_ms is not None:
            b.st_rtt[i].append(row.srt_rtt_ms)
        if prev_st is not None:
            b.decode[i] += counter_delta(row.decode_errors, prev_st.decode_errors)
            b.has_st[i] = True  # a count needs two samples, like the SRT losses
            d = station_srt_delta(row, prev_st)
            if d is not None:
                b.st_packets[i] += d.packets
                b.st_lost[i] += d.lost
                b.st_retrans[i] += d.retrans
                b.st_dropped[i] += d.dropped
                b.st_srt_seconds[i] += row.ts - prev_st.ts
                b.has_st_srt[i] = True
        prev_st = row
    return LinkSeries(
        id=lid,
        bucket_s=round(bucket, 2),
        t=[round(since + i * bucket, 1) for i in range(count)],
        rtt_ms=[_avg(x) for x in b.rtt],
        mbps=[_avg(x) for x in b.mbps],
        loss_percent=_loss(b.lost, b.packets, b.has_srt),
        retrans_per_s=_per_s(b.retrans, b.srt_seconds, b.has_srt),
        dropped=[d if ok else None for d, ok in zip(b.dropped, b.has_srt, strict=True)],
        fps=[_avg(x) for x in b.fps],
        station_mbps=[_avg(x) for x in b.st_mbps],
        decode_errors=[d if ok else None for d, ok in zip(b.decode, b.has_st, strict=True)],
        station_rtt_ms=[_avg(x) for x in b.st_rtt],
        station_loss_percent=_loss(b.st_lost, b.st_packets, b.has_st_srt),
        station_retrans_per_s=_per_s(b.st_retrans, b.st_srt_seconds, b.has_st_srt),
        station_dropped=[
            d if ok else None for d, ok in zip(b.st_dropped, b.has_st_srt, strict=True)
        ],
    )


def _loss(lost: list[int], packets: list[int], ok: list[bool]) -> list[float | None]:
    return [
        round(100 * x / pk, 3) if has and pk else (0.0 if has else None)
        for x, pk, has in zip(lost, packets, ok, strict=True)
    ]


def _per_s(counts: list[int], seconds: list[float], ok: list[bool]) -> list[float | None]:
    return [
        round(c / sec, 2) if has and sec else None
        for c, sec, has in zip(counts, seconds, ok, strict=True)
    ]


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
        # SRT seen by the station
        self.st_rtt: list[list[float]] = [[] for _ in range(n)]
        self.st_packets = [0] * n
        self.st_lost = [0] * n
        self.st_retrans = [0] * n
        self.st_dropped = [0] * n
        self.st_srt_seconds = [0.0] * n
        self.has_st_srt = [False] * n


def _avg(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(sum(values) / len(values), 2) if values else None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")
