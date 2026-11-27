"""SRT statistics collected from the media servers (ADR 0010).

Every few seconds the collector reads the MediaMTX API of each enabled media
server and stores one sample per SRT link:

- camera link (camera -> media server): the static source of a path pulled
  from the camera (MediaMTX caller), or a connection publishing to a path;
- station link (media server -> station): each connection reading a path.
  The agent adds station=<id> to its streamid; MediaMTX shows it as the
  connection "query", even behind NAT.

Nothing real time depends on this: if a server is unreachable, only its
statistics stop.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

import httpx2
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from osmiracore.models import Camera, MediaServer, SrtSample, StationSample
from osmiracore.schemas import ExposedMedia, ExposedPath, MediaServerState, SourceMedia, SrtLink

log = logging.getLogger(__name__)

# MediaMTX track codec names -> names used in the camera media block.
CODECS = {"H265": "hevc", "H264": "h264", "AV1": "av1", "VP9": "vp9", "MPEG-2 Video": "mpeg2"}
PURGE_EVERY_S = 3600.0


# --- matching streams to cameras and stations ------------------------------------


def stream_path(srt_url: str) -> tuple[str, str] | None:
    """(host, MediaMTX path) of an SRT URL like srt://h:8890?streamid=read:cam1."""
    parts = urlsplit(srt_url)
    if parts.hostname is None:
        return None
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "streamid":
            fields = value.split(":")
            if len(fields) >= 2 and fields[0] in ("read", "publish") and fields[1]:
                return parts.hostname, fields[1]
    return None


def station_from_query(query: str | None) -> str | None:
    """station=<id> added by the agent to its streamid (MediaMTX "query")."""
    for key, value in parse_qsl(query or "", keep_blank_values=True):
        if key == "station" and value:
            return value
    return None


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


# --- collector state -----------------------------------------------------------------


@dataclass
class PathInfo:
    ready: bool
    source_type: str | None
    codec: str | None
    width: int | None
    height: int | None


@dataclass
class ServerState:
    reachable: bool | None = None
    last_ok: float | None = None
    last_error: str | None = None
    version: str | None = None
    paths: dict[str, PathInfo] = field(default_factory=dict)

    def public(self) -> MediaServerState:
        return MediaServerState(
            reachable=self.reachable,
            last_ok=_iso(self.last_ok) if self.last_ok else None,
            last_error=self.last_error,
            version=self.version,
            paths=len(self.paths),
        )


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def _num(value: Any) -> float | None:  # noqa: ANN401  (JSON value)
    return float(value) if isinstance(value, int | float) else None


def _int(value: Any) -> int | None:  # noqa: ANN401  (JSON value)
    return int(value) if isinstance(value, int | float) else None


# --- collector -------------------------------------------------------------------------


class SrtCollector:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        http: httpx2.AsyncClient,
        interval_s: float,
        retention_days: float,
    ) -> None:
        self._session_factory = session_factory
        self._http = http
        self._interval_s = interval_s
        self._retention_s = retention_days * 86400
        self._last_purge = 0.0
        self.states: dict[str, ServerState] = {}
        # Host of each server's API, to match camera SRT URLs (refreshed each run).
        self._server_hosts: dict[str, str] = {}

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.collect_once()
            except Exception:  # never let a bad answer kill the collector
                log.exception("SRT statistics collection failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), self._interval_s)

    async def collect_once(self, now: float | None = None) -> int:
        """Read every enabled server once; returns the number of samples stored."""
        now = time.time() if now is None else now
        servers, cameras = await asyncio.to_thread(self._load)
        samples: list[SrtSample] = []
        for server in servers:
            state = self.states.setdefault(server.id, ServerState())
            try:
                samples += await self._collect_server(server, cameras, state, now)
            except (httpx2.HTTPError, ValueError, KeyError, TypeError) as exc:
                if state.reachable is not False or state.last_error != str(exc):
                    log.warning("media server %s: %s", server.id, exc)
                state.reachable = False
                state.last_error = f"{type(exc).__name__}: {exc}"
            else:
                state.reachable = True
                state.last_ok = now
                state.last_error = None
        for server_id in set(self.states) - {s.id for s in servers}:
            del self.states[server_id]  # deleted or disabled
        await asyncio.to_thread(self._store, samples, now)
        return len(samples)

    def source_of(self, camera: Camera) -> SourceMedia | None:
        """The camera's stream as a media server sees it (codec, size, ready)."""
        if camera.media_server_id and camera.media_path:
            state = self.states.get(camera.media_server_id)
            info = state.paths.get(camera.media_path) if state else None
            if info is None:
                return None
            return SourceMedia(
                server_id=camera.media_server_id,
                path=camera.media_path,
                ready=info.ready,
                codec=info.codec,
                width=info.width,
                height=info.height,
            )
        found = stream_path(camera.media_srt_url)
        if found is None:
            return None
        host, path = found
        for server_id, state in self.states.items():
            info = state.paths.get(path)
            if info is not None and self._server_hosts.get(server_id) == host:
                return SourceMedia(
                    server_id=server_id,
                    path=path,
                    ready=info.ready,
                    codec=info.codec,
                    width=info.width,
                    height=info.height,
                )
        return None

    # --- internals ---------------------------------------------------------------------

    def _load(self) -> tuple[list[MediaServer], list[Camera]]:
        with self._session_factory() as session:
            servers = list(session.scalars(select(MediaServer).where(MediaServer.enabled)))
            cameras = list(session.scalars(select(Camera)))
            session.expunge_all()
        self._server_hosts = {s.id: _host(s.api_url) for s in servers}
        return servers, cameras

    def _store(self, samples: list[SrtSample], now: float) -> None:
        with self._session_factory() as session:
            session.add_all(samples)
            if now - self._last_purge >= PURGE_EVERY_S:
                limit = now - self._retention_s
                session.execute(delete(SrtSample).where(SrtSample.ts < limit))
                session.execute(delete(StationSample).where(StationSample.ts < limit))
                self._last_purge = now
            session.commit()

    async def _get(self, server: MediaServer, path: str) -> Any:  # noqa: ANN401  (JSON)
        return await mediamtx_get(self._http, server, path)

    async def _collect_server(
        self, server: MediaServer, cameras: Iterable[Camera], state: ServerState, now: float
    ) -> list[SrtSample]:
        camera_of_path = cameras_by_path(server, cameras)

        info = await self._get(server, "/v3/info")
        state.version = info.get("version")
        paths = (await self._get(server, "/v3/paths/list?itemsPerPage=1000"))["items"]
        state.paths = {p["name"]: _path_info(p) for p in paths}

        samples: list[SrtSample] = []
        for p in paths:
            source = p.get("source") or {}
            if source.get("type") != "srtSource":
                continue
            try:
                static = await self._get(server, f"/v3/paths/static-sources/get/{quote(p['name'])}")
            except httpx2.HTTPStatusError:
                continue  # older MediaMTX without this endpoint, or source just gone
            stats = static.get("typeSpecific") or {}
            samples.append(
                _sample(
                    now,
                    server.id,
                    "camera",
                    p["name"],
                    camera_of_path.get(p["name"]),
                    None,
                    f"source:{static.get('created', '')}",
                    stats.get("remoteAddr"),
                    stats,
                )
            )

        conns = (await self._get(server, "/v3/srtconns/list?itemsPerPage=1000"))["items"]
        for conn in conns:
            if conn.get("state") == "read":
                link, station = "station", station_from_query(conn.get("query"))
            elif conn.get("state") == "publish":
                link, station = "camera", None
            else:
                continue
            samples.append(
                _sample(
                    now,
                    server.id,
                    link,
                    conn.get("path", ""),
                    camera_of_path.get(conn.get("path", "")),
                    station,
                    conn.get("id"),
                    conn.get("remoteAddr"),
                    conn,
                )
            )
        return samples


def cameras_by_path(server: MediaServer, cameras: Iterable[Camera]) -> dict[str, str]:
    """MediaMTX path -> camera id: cameras declared on this server first, then
    cameras whose SRT URL points to the server's host (override, older data)."""
    found: dict[str, str] = {}
    for camera in cameras:
        if camera.media_server_id == server.id and camera.media_path:
            found.setdefault(camera.media_path, camera.id)
    host = _host(server.api_url)
    for camera in cameras:
        url_path = stream_path(camera.media_srt_url)
        if url_path is not None and url_path[0] == host:
            found.setdefault(url_path[1], camera.id)
    return found


async def mediamtx_get(http: httpx2.AsyncClient, server: MediaServer, path: str) -> Any:  # noqa: ANN401
    """GET on the MediaMTX API of a server (JSON), with its credentials if any."""
    auth = (server.api_username, server.api_password or "") if server.api_username else None
    response = await http.get(f"{server.api_url}{path}", auth=auth)
    response.raise_for_status()
    return response.json()


async def exposed_media(
    http: httpx2.AsyncClient, server: MediaServer, cameras: Iterable[Camera]
) -> ExposedMedia:
    """What the media server exposes right now, read live from its API."""
    users: dict[str, list[str]] = {}
    for camera in cameras:
        if camera.media_server_id == server.id and camera.media_path:
            users.setdefault(camera.media_path, []).append(camera.id)
    try:
        config = await mediamtx_get(http, server, "/v3/config/global/get")
        items = (await mediamtx_get(http, server, "/v3/paths/list?itemsPerPage=1000"))["items"]
    except (httpx2.HTTPError, ValueError, KeyError, TypeError) as exc:
        return ExposedMedia(
            server_id=server.id,
            reachable=False,
            error=f"{type(exc).__name__}: {exc}",
            srt_address_detected=None,
            paths=[],
        )
    srt = str(config.get("srtAddress") or "")
    port = srt.rsplit(":", 1)[-1] if ":" in srt else ""
    detected = f"{_host(server.api_url)}:{port}" if config.get("srt", True) and port else None
    paths = []
    for item in sorted(items, key=lambda i: i.get("name", "")):
        info = _path_info(item)
        paths.append(
            ExposedPath(
                name=item["name"],
                ready=info.ready,
                source_type=info.source_type,
                codec=info.codec,
                width=info.width,
                height=info.height,
                readers=len(item.get("readers") or []),
                cameras=users.get(item["name"], []),
            )
        )
    return ExposedMedia(
        server_id=server.id, reachable=True, error=None, srt_address_detected=detected, paths=paths
    )


def _path_info(path: dict[str, Any]) -> PathInfo:
    video = next(
        (t for t in path.get("tracks2") or [] if t.get("codec") in CODECS),
        None,
    )
    props = (video or {}).get("codecProps") or {}
    return PathInfo(
        ready=bool(path.get("ready")),
        source_type=(path.get("source") or {}).get("type"),
        codec=CODECS.get(video["codec"]) if video else None,
        width=_int(props.get("width")),
        height=_int(props.get("height")),
    )


def _sample(
    now: float,
    server_id: str,
    link: str,
    path: str,
    camera_id: str | None,
    station_id: str | None,
    connection_id: str | None,
    remote_addr: str | None,
    s: dict[str, Any],
) -> SrtSample:
    """One sample, from the receiver side (camera link) or sender side (station link)."""
    receiving = link == "camera"
    return SrtSample(
        ts=now,
        server_id=server_id,
        link=link,
        path=path,
        camera_id=camera_id,
        station_id=station_id,
        connection_id=connection_id,
        remote_addr=remote_addr,
        rtt_ms=_num(s.get("msRTT")),
        mbps=_num(s.get("mbpsReceiveRate" if receiving else "mbpsSendRate")),
        link_capacity_mbps=_num(s.get("mbpsLinkCapacity")),
        packets=_int(s.get("packetsReceived" if receiving else "packetsSent")),
        packets_lost=_int(s.get("packetsReceivedLoss" if receiving else "packetsSendLoss")),
        packets_retrans=_int(s.get("packetsReceivedRetrans" if receiving else "packetsRetrans")),
        packets_dropped=_int(s.get("packetsReceivedDrop" if receiving else "packetsSendDrop")),
        buffer_ms=_num(s.get("msReceiveBuf" if receiving else "msSendBuf")),
    )


# --- reading the samples --------------------------------------------------------------


def latest_links(session: Session, active_s: float, now: float | None = None) -> list[SrtLink]:
    """Links seen in the last active_s seconds, with rates over their last interval."""
    now = time.time() if now is None else now
    rows = session.scalars(
        select(SrtSample).where(SrtSample.ts >= now - max(active_s * 3, 60)).order_by(SrtSample.ts)
    ).all()
    last: dict[tuple[str, str, str, str | None], SrtSample] = {}
    previous: dict[tuple[str, str, str, str | None], SrtSample] = {}
    for row in rows:
        key = (row.link, row.server_id, row.path, row.connection_id)
        if key in last:
            previous[key] = last[key]
        last[key] = row
    links = [
        _link(row, previous.get(key), now) for key, row in last.items() if now - row.ts <= active_s
    ]
    return sorted(links, key=lambda x: (x.link, x.camera_id or x.path, x.station_id or ""))


def _link(row: SrtSample, prev: SrtSample | None, now: float) -> SrtLink:
    interval = loss = retrans = dropped = None
    if prev is not None and row.ts > prev.ts:
        interval = row.ts - prev.ts
        packets = _delta(row.packets, prev.packets)
        lost = _delta(row.packets_lost, prev.packets_lost)
        if packets and lost is not None:
            loss = round(100 * lost / packets, 3)
        sent_again = _delta(row.packets_retrans, prev.packets_retrans)
        if sent_again is not None:
            retrans = round(sent_again / interval, 2)
        dropped = _delta(row.packets_dropped, prev.packets_dropped)
    return SrtLink(
        link=row.link,  # "camera" or "station", checked by the schema
        server_id=row.server_id,
        path=row.path,
        camera_id=row.camera_id,
        station_id=row.station_id,
        remote_addr=row.remote_addr,
        seen=_iso(row.ts),
        seconds_since=round(max(0.0, now - row.ts), 1),
        rtt_ms=row.rtt_ms,
        mbps=row.mbps,
        link_capacity_mbps=row.link_capacity_mbps,
        buffer_ms=row.buffer_ms,
        interval_s=round(interval, 2) if interval else None,
        loss_percent=loss,
        retrans_per_s=retrans,
        dropped=dropped,
        packets=row.packets,
        packets_lost=row.packets_lost,
        packets_retrans=row.packets_retrans,
        packets_dropped=row.packets_dropped,
    )


def _delta(new: int | None, old: int | None) -> int | None:
    if new is None or old is None or new < old:  # counters restart with the connection
        return None
    return new - old
