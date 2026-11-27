"""SRT statistics: collector against a fake MediaMTX, links, samples, pages."""

import time

import httpx2
import pytest

from osmiracore.models import SrtSample
from osmiracore.services.srt import SrtCollector, station_from_query, stream_path

API = "http://192.168.104.253:9997"


def srt_stats(**overrides) -> dict:
    """SRT statistics fields as MediaMTX v1.21 returns them."""
    stats = {
        "msRTT": 1.1,
        "mbpsReceiveRate": 15.4,
        "mbpsSendRate": 0.0,
        "mbpsLinkCapacity": 14.5,
        "packetsReceived": 1000,
        "packetsReceivedLoss": 0,
        "packetsReceivedRetrans": 0,
        "packetsReceivedDrop": 0,
        "msReceiveBuf": 20,
        "packetsSent": 0,
        "packetsSendLoss": 0,
        "packetsRetrans": 0,
        "packetsSendDrop": 0,
        "msSendBuf": 0,
    }
    stats.update(overrides)
    return stats


class FakeMediaMTX:
    """Answers like MediaMTX: cam1 pulled from a camera (static SRT source),
    read by panelTest and by an unknown reader; cam2 published by a camera."""

    def __init__(self) -> None:
        self.down = False
        self.auth: list[str | None] = []
        self.source = srt_stats(remoteAddr="192.168.105.51:2020")
        self.reader = srt_stats(
            mbpsReceiveRate=0.0,
            mbpsSendRate=16.9,
            packetsSent=2000,
            packetsReceived=0,
            msRTT=6.5,
            msSendBuf=20,
        )

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("connection refused")
        self.auth.append(request.headers.get("authorization"))
        path = request.url.path
        if path == "/v3/info":
            return httpx2.Response(200, json={"version": "v1.21.4"})
        if path == "/v3/paths/list":
            return httpx2.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "cam1",
                            "ready": True,
                            "source": {"type": "srtSource", "id": ""},
                            "tracks2": [
                                {"codec": "H265", "codecProps": {"width": 1920, "height": 1080}},
                                {"codec": "MPEG-4 Audio", "codecProps": {}},
                            ],
                        },
                        {
                            "name": "cam2",
                            "ready": True,
                            "source": {"type": "srtConn", "id": "c2"},
                            "tracks2": [
                                {"codec": "H264", "codecProps": {"width": 1280, "height": 720}}
                            ],
                        },
                        {"name": "program", "ready": False, "source": None, "tracks2": []},
                    ]
                },
            )
        if path == "/v3/paths/static-sources/get/cam1":
            return httpx2.Response(
                200, json={"created": "2026-11-27T17:37:26+01:00", "typeSpecific": self.source}
            )
        if path == "/v3/srtconns/list":
            return httpx2.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "r1",
                            "state": "read",
                            "path": "cam1",
                            "query": "station=panelTest",
                            "remoteAddr": "192.168.104.252:33662",
                            **self.reader,
                        },
                        {
                            "id": "r2",
                            "state": "read",
                            "path": "cam1",
                            "query": "",
                            "remoteAddr": "10.0.0.9:4000",
                            **self.reader,
                        },
                        {
                            "id": "p1",
                            "state": "publish",
                            "path": "cam2",
                            "query": "",
                            "remoteAddr": "192.168.105.52:5000",
                            **srt_stats(),
                        },
                    ]
                },
            )
        return httpx2.Response(404, text="404 page not found")


@pytest.fixture
def mediamtx():
    return FakeMediaMTX()


@pytest.fixture
def setup(client, mediamtx):
    """Cameras on MediaMTX paths cam1/cam2, a media server, and a collector
    talking to the fake MediaMTX (installed in the app)."""
    for n in (1, 2):
        client.post(
            "/api/cameras",
            json={
                "id": f"cam{n}",
                "label": f"CAM {n}",
                "media": {
                    "srt_url": f"srt://192.168.104.253:8890?mode=caller&streamid=read:cam{n}"
                },
            },
        )
    client.post("/api/media-servers", json={"id": "mtx", "label": "MediaMTX", "api_url": API})
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(mediamtx.handler))
    collector = SrtCollector(client.app.state.session_factory, http, interval_s=5, retention_days=7)
    client.app.state.srt_collector = collector
    return client, collector


def collect(client, collector, now: float) -> int:
    return client.portal.call(collector.collect_once, now)


def samples(client) -> list[SrtSample]:
    with client.app.state.session_factory() as session:
        return list(session.query(SrtSample).order_by(SrtSample.id))


# --- matching ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("srt://192.168.104.253:8890?mode=caller&streamid=read:cam1", ("192.168.104.253", "cam1")),
        ("srt://h:8890?streamid=read:cam1:::station=panelTest", ("h", "cam1")),
        ("srt://h:8890?streamid=publish:live/a", ("h", "live/a")),
        ("srt://h:8890?mode=caller", None),
        ("srt://192.168.105.51:2020", None),
    ],
)
def test_stream_path(url, expected):
    assert stream_path(url) == expected


def test_station_from_query():
    assert station_from_query("station=panelTest") == "panelTest"
    assert station_from_query("a=1&station=s2") == "s2"
    assert station_from_query("") is None
    assert station_from_query(None) is None


# --- collection ------------------------------------------------------------------


def test_one_collection_stores_every_link(setup):
    client, collector = setup

    assert collect(client, collector, now=1000.0) == 4

    rows = {(r.link, r.path, r.connection_id): r for r in samples(client)}
    source = rows[("camera", "cam1", "source:2026-11-27T17:37:26+01:00")]
    assert (source.camera_id, source.station_id) == ("cam1", None)
    assert source.mbps == 15.4 and source.packets == 1000 and source.buffer_ms == 20
    tagged = rows[("station", "cam1", "r1")]
    assert (tagged.camera_id, tagged.station_id) == ("cam1", "panelTest")
    assert tagged.remote_addr == "192.168.104.252:33662"  # behind the relay: matched by tag
    assert tagged.mbps == 16.9 and tagged.packets == 2000 and tagged.rtt_ms == 6.5
    assert rows[("station", "cam1", "r2")].station_id is None  # untagged reader
    assert rows[("camera", "cam2", "p1")].camera_id == "cam2"  # camera publishing


def test_server_state_and_camera_source(setup):
    client, collector = setup
    collect(client, collector, now=time.time())

    server = client.get("/api/media-servers/mtx").json()
    cam1 = client.get("/api/cameras/cam1").json()
    cam2 = client.get("/api/cameras/cam2").json()

    assert server["state"]["reachable"] is True
    assert server["state"]["version"] == "v1.21.4"
    assert server["state"]["paths"] == 3
    assert cam1["source"] == {
        "server_id": "mtx",
        "path": "cam1",
        "ready": True,
        "codec": "hevc",
        "width": 1920,
        "height": 1080,
    }
    assert cam2["source"]["codec"] == "h264"


def test_declared_codec_differing_from_the_server_is_flagged(setup):
    client, collector = setup
    collect(client, collector, now=time.time())

    client.put(
        "/api/cameras/cam2",
        json={
            "label": "CAM 2",
            "media": {
                "srt_url": "srt://192.168.104.253:8890?mode=caller&streamid=read:cam2",
                "codec": "hevc",
            },
        },
    )

    assert client.get("/api/cameras/cam2").json()["warnings"] == [
        "declared hevc, media server has h264"
    ]


def test_unreachable_server_is_reported_and_collection_goes_on(setup, mediamtx):
    client, collector = setup
    mediamtx.down = True

    assert collect(client, collector, now=1000.0) == 0
    state = client.get("/api/media-servers/mtx").json()["state"]
    assert state["reachable"] is False and "ConnectError" in state["last_error"]

    mediamtx.down = False
    assert collect(client, collector, now=1005.0) == 4
    assert client.get("/api/media-servers/mtx").json()["state"]["reachable"] is True


def test_disabled_server_is_not_polled(setup, mediamtx):
    client, collector = setup
    client.put(
        "/api/media-servers/mtx", json={"label": "MediaMTX", "api_url": API, "enabled": False}
    )

    assert collect(client, collector, now=1000.0) == 0
    assert mediamtx.auth == []


def test_api_credentials_are_used_and_never_returned(setup, mediamtx):
    client, collector = setup
    client.put(
        "/api/media-servers/mtx",
        json={
            "label": "MediaMTX",
            "api_url": API,
            "api_username": "osmira",
            "api_password": "secret",
        },
    )

    collect(client, collector, now=1000.0)
    server = client.get("/api/media-servers/mtx").json()

    assert mediamtx.auth[-1].startswith("Basic ")
    assert server["password_set"] is True
    assert "secret" not in str(server)


def test_old_samples_are_purged(setup):
    client, collector = setup
    collect(client, collector, now=1000.0)

    collect(client, collector, now=1000.0 + 8 * 86400)  # 8 days later, retention is 7

    assert {r.ts for r in samples(client)} == {1000.0 + 8 * 86400}


# --- links and samples ------------------------------------------------------------


def test_links_give_rates_over_the_last_interval(setup, mediamtx):
    client, collector = setup
    now = time.time()
    collect(client, collector, now=now - 5)
    # 5 s later: the reader sent 1000 more packets, 20 lost and retransmitted.
    mediamtx.reader = {
        **mediamtx.reader,
        "packetsSent": 3000,
        "packetsSendLoss": 20,
        "packetsRetrans": 20,
    }
    collect(client, collector, now=now)

    links = client.get("/api/srt/links").json()
    tagged = next(x for x in links if x["link"] == "station" and x["station_id"] == "panelTest")

    assert len(links) == 4
    assert tagged["interval_s"] == 5.0
    assert tagged["loss_percent"] == 2.0
    assert tagged["retrans_per_s"] == 4.0
    assert tagged["dropped"] == 0


def test_counter_reset_gives_no_rate(setup, mediamtx):
    client, collector = setup
    now = time.time()
    collect(client, collector, now=now - 5)
    mediamtx.reader = {**mediamtx.reader, "packetsSent": 10}  # same id, counters restarted
    collect(client, collector, now=now)

    tagged = next(x for x in client.get("/api/srt/links").json() if x["station_id"] == "panelTest")

    assert tagged["loss_percent"] is None


def test_samples_endpoint_filters(setup):
    client, collector = setup
    collect(client, collector, now=time.time())

    url = "/api/srt/samples?since=2020-01-01T00:00:00Z"
    everything = client.get(url).json()
    station = client.get(url + "&station_id=panelTest").json()
    cameras = client.get(url + "&link=camera").json()

    assert len(everything) == 4
    assert [s["connection_id"] for s in station] == ["r1"]
    assert {s["path"] for s in cameras} == {"cam1", "cam2"}


# --- pages ------------------------------------------------------------------------


def test_media_server_pages(setup):
    client, collector = setup
    collect(client, collector, now=time.time())

    listing = client.get("/media-servers").text
    created = client.post(
        "/media-servers/new",
        data={"id": "mtx2", "label": "Backup", "api_url": "http://10.0.0.2:9997", "enabled": "on"},
        follow_redirects=False,
    )
    refused = client.post(
        "/media-servers/new", data={"id": "bad", "label": "x", "api_url": "ftp://x"}
    )

    assert "reachable" in listing and "v1.21.4" in listing
    assert created.status_code == 303
    assert client.get("/api/media-servers/mtx2").json()["enabled"] is True
    assert refused.status_code == 422


def test_camera_page_shows_the_codec(setup):
    client, collector = setup
    collect(client, collector, now=time.time())

    page = client.get("/cameras").text

    assert "HEVC" in page and "mtx/cam1" in page
