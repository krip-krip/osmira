"""SRT figures seen by the stations (receiver side, ADR 0013): stored with
each status, added up per link across reconnections, curves and pages."""

import pytest

from osmiracore.models import StationSample
from osmiracore.schemas import PlayerCamera, PlayerSrt, PlayerStatus, StationStatusIn
from osmiracore.services import links, station_metrics
from osmiracore.services import status as heartbeat

T0 = 1_000_000.0
VIA_SERVER = "server_station|mtx|cam1|panelTest"
DIRECT = "camera_station|cam5|panelTest"


def srt(packets: int, lost: int, dropped: int, rtt: float = 4.0, latency: int = 20) -> PlayerSrt:
    return PlayerSrt(
        rtt_ms=rtt,
        recv_mbps=12.0,
        bandwidth_mbps=600.0,
        latency_ms=latency,
        buffer_ms=1,
        packets=packets,
        lost=lost,
        retrans=lost,
        dropped=dropped,
        belated=0,
    )


def status(*cams: tuple[str, int, PlayerSrt | None]) -> StationStatusIn:
    """cams: (camera_id, connects, srt)."""
    return StationStatusIn(
        agent_version="0.1.0",
        player=PlayerStatus(
            running=True,
            cameras=[
                PlayerCamera(camera_id=c, state="streaming", fps=50.0, connects=n, srt=s)
                for c, n, s in cams
            ],
        ),
        system={},
    )


def make_setup(client):
    client.post(
        "/api/media-servers", json={"id": "mtx", "label": "MediaMTX", "api_url": "http://m:9997"}
    )
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    client.post(
        "/api/cameras",
        json={
            "id": "cam1",
            "label": "CAM 1",
            "media": {"source": "media_server", "media_server_id": "mtx", "path": "cam1"},
        },
    )
    client.post(
        "/api/cameras",
        json={
            "id": "cam5",
            "label": "CAM 5",
            "media": {"source": "direct", "mode": "caller", "host": "192.168.105.55", "port": 2020},
        },
    )


@pytest.fixture
def setup(client):
    make_setup(client)
    # cam1 (via mtx): 1000 then 3000 packets on one connection, then a
    # reconnection whose counters start again at 500.
    # cam5 (direct): an older player without SRT figures, then figures.
    reports = [
        (T0, ("cam1", 1, srt(1000, 10, 0, rtt=4.0)), ("cam5", 1, None)),
        (T0 + 5, ("cam1", 1, srt(3000, 50, 3, rtt=6.0)), ("cam5", 1, srt(100, 0, 0))),
        (T0 + 10, ("cam1", 2, srt(500, 5, 1, rtt=8.0, latency=80)), ("cam5", 1, srt(400, 3, 0))),
    ]
    with client.app.state.session_factory() as session:
        for ts, *cams in reports:
            heartbeat.record_status(session, "panelTest", status(*cams), now=ts)
    return client


def summaries(client) -> dict[str, links.LinkSummary]:
    with client.app.state.session_factory() as session:
        found = links.list_links(session, since=T0 - 1, until=T0 + 100, now=T0 + 20)
    return {x.id: x for x in found}


def test_srt_figures_are_stored(setup):
    with setup.app.state.session_factory() as session:
        rows = (
            session.query(StationSample)
            .filter(StationSample.camera_id == "cam1")
            .order_by(StationSample.ts)
            .all()
        )

    last = rows[-1]
    assert (last.srt_packets, last.srt_lost, last.srt_dropped) == (500, 5, 1)
    assert (last.srt_rtt_ms, last.srt_latency_ms, last.srt_mbps) == (8.0, 80, 12.0)


def test_status_without_srt_is_accepted(setup):
    with setup.app.state.session_factory() as session:
        first = (
            session.query(StationSample)
            .filter(StationSample.camera_id == "cam5")
            .order_by(StationSample.ts)
            .first()
        )

    assert first.srt_packets is None


def test_station_side_of_a_link_through_the_server(setup):
    link = summaries(setup)[VIA_SERVER]

    # 2000 on the first connection, then the whole 500 of the new one.
    assert (link.station_packets, link.station_lost, link.station_dropped) == (2500, 45, 4)
    assert link.station_loss_percent == 1.8
    assert link.station_rtt_avg_ms == 6.0
    assert link.station_latency_ms == 80  # the last one negotiated
    assert link.packets is None  # no media server sample in this test


def test_direct_link_gets_srt_figures(setup):
    link = summaries(setup)[DIRECT]

    # No figures before T0 + 5 (input not connected, or older player): the
    # first figures count whole, like after a reconnection.
    assert (link.station_packets, link.station_lost) == (400, 3)
    assert link.station_loss_percent == 0.75


def test_series_station_side(setup):
    with setup.app.state.session_factory() as session:
        s = links.series(session, VIA_SERVER, since=T0, until=T0 + 10, points=2)

    assert s.station_rtt_ms == [4.0, 6.0, 8.0]
    assert s.station_loss_percent == [None, 2.0, 1.0]
    assert s.station_dropped == [None, 3, 1]
    assert s.station_retrans_per_s == [None, 8.0, 1.0]


def test_station_page_curves_per_camera(setup):
    with setup.app.state.session_factory() as session:
        s = station_metrics.series(session, "panelTest", since=T0, until=T0 + 10, now=T0 + 12)

    assert s.cameras["cam1"]["srt_dropped"] == [None, 3, 1]
    assert s.cameras["cam1"]["srt_loss_percent"] == [None, 2.0, 1.0]
    assert s.cameras["cam5"]["srt_dropped"] == [None, 0, 0]


def test_pages_show_the_station_side(client):
    make_setup(client)
    for packets, lost, dropped in ((1000, 0, 0), (3000, 40, 7)):
        body = status(("cam5", 1, srt(packets, lost, dropped))).model_dump()
        assert client.post("/api/stations/panelTest/status", json=body).status_code == 204

    table = client.get("/links/table").text
    detail = client.get("/links/detail", params={"id": DIRECT}).text

    assert "station" in table and "2.00 %" in table
    assert "Dropped (station)" in detail
    assert 'data-chart="rtt"' in detail  # a direct link now has SRT curves
    assert 'data-chart="srt"' in client.get("/stations/panelTest/metrics").text
