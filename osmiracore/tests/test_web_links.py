"""Links page and link detail page."""

import time

import pytest

from osmiracore.models import SrtSample
from osmiracore.schemas import PlayerCamera, PlayerStatus, StationStatusIn
from osmiracore.services import status as heartbeat


def srt(ts, link, conn, packets, lost, dropped=0, station=None) -> SrtSample:
    return SrtSample(
        ts=ts,
        server_id="mtx",
        link=link,
        path="cam1",
        camera_id="cam1",
        station_id=station,
        connection_id=conn,
        remote_addr="1.2.3.4:5",
        rtt_ms=5.0,
        mbps=16.0,
        link_capacity_mbps=None,
        packets=packets,
        packets_lost=lost,
        packets_retrans=lost,
        packets_dropped=dropped,
        buffer_ms=20.0,
    )


@pytest.fixture
def setup(client):
    client.post(
        "/api/media-servers",
        json={"id": "mtx", "label": "MediaMTX régie", "api_url": "http://m:9997"},
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
            "media": {"source": "direct", "host": "192.168.105.55", "port": 2020},
        },
    )
    now = time.time()
    client.app.state.started_at = now - 60  # the Core "started" before these samples
    with client.app.state.session_factory() as session:
        session.add_all(
            [
                srt(now - 10, "camera", "A", 1000, 0),
                srt(now - 5, "camera", "A", 2000, 0),
                srt(now - 10, "station", "r1", 1000, 0, station="panelTest"),
                srt(now - 5, "station", "r1", 2000, 50, dropped=3, station="panelTest"),
            ]
        )
        session.commit()
        for ts, fps in ((now - 10, 50.0), (now - 5, 0.0)):
            heartbeat.record_status(
                session,
                "panelTest",
                StationStatusIn(
                    agent_version="0.1.0",
                    player=PlayerStatus(
                        running=True,
                        cameras=[
                            PlayerCamera(
                                camera_id="cam5",
                                state="streaming",
                                fps=fps,
                                connects=1,
                                decode_errors=0,
                            )
                        ],
                    ),
                ),
                now=ts,
            )
    return client


def test_empty_links_page(client):
    page = client.get("/links").text

    assert "No link in this period" in page
    assert "Since the Core started" in page


def test_links_page_lists_every_kind(setup):
    page = setup.get("/links").text

    assert "CAM 1 → MediaMTX régie" in page
    assert "MediaMTX régie → panelTest" in page
    assert "CAM 5 → panelTest" in page and ">direct<" in page
    assert "5.00 %" in page  # 50 lost of 1000
    assert 'class="bad">3<' in page  # dropped packets stand out
    assert "3 links" in page


def test_table_is_refreshed_for_a_live_period(setup):
    live = setup.get("/links/table?period=1h").text
    fixed = setup.get(
        "/links/table?period=custom&since=2026-01-01T00:00&until=2026-01-02T00:00"
    ).text

    assert 'hx-trigger="every 10s"' in live
    assert "hx-trigger" not in fixed
    assert "No link in this period" in fixed


def test_bad_custom_dates_fall_back_to_the_default(setup):
    page = setup.get("/links?period=custom&since=nonsense").text

    assert 'value="core" onchange="this.form.submit()" checked' in page


def test_detail_page(setup):
    page = setup.get(
        "/links/detail", params={"id": "server_station|mtx|cam1|panelTest", "period": "1h"}
    ).text

    assert "MediaMTX régie → panelTest" in page
    assert "/api/links/series?id=server_station%7Cmtx%7Ccam1%7CpanelTest" in page
    assert 'data-chart="rtt"' in page and 'data-chart="fps"' in page
    assert "/static/uPlot.iife.min.js" in page


def test_direct_detail_has_no_srt_charts(setup):
    page = setup.get("/links/detail", params={"id": "camera_station|cam5|panelTest"}).text

    assert 'data-chart="fps"' in page
    assert 'data-chart="rtt"' not in page
    assert "No picture" in page


def test_unknown_link_is_404(setup):
    assert setup.get("/links/detail", params={"id": "camera_station|nope|x"}).status_code == 404


def test_chart_files_are_served(client):
    assert client.get("/static/uPlot.iife.min.js").status_code == 200
    assert client.get("/static/uPlot.min.css").status_code == 200
    assert "uPlot" in client.get("/static/links.js").text
