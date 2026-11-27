"""Station system page."""

import time

import pytest

from osmiracore.schemas import PlayerCamera, PlayerStatus, StationStatusIn
from osmiracore.services import status as heartbeat


def status(cma: int, temp: float, throttled: int) -> StationStatusIn:
    return StationStatusIn(
        agent_version="0.1.0",
        player=PlayerStatus(running=True, cameras=[PlayerCamera(camera_id="cam1", fps=50.0)]),
        metrics={
            "cpu_pct": 40.0,
            "temp_c": temp,
            "cma_free_mb": cma,
            "cma_total_mb": 512,
            "throttled": throttled,
            "uptime_s": 3600,
            "mem_available_mb": 430,
            "mem_total_mb": 905,
            "net": {"eth0": {"rx_mbps": 64.0, "tx_mbps": 1.0}},
        },
    )


@pytest.fixture
def setup(client):
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    client.app.state.started_at = time.time() - 60
    return client


def test_station_without_figures(setup):
    page = setup.get("/stations/panelTest/metrics").text

    assert "No system figures in this period" in page
    assert 'data-chart="cma"' not in page and 'data-chart="memory"' in page


def test_cards_and_alerts(setup):
    with setup.app.state.session_factory() as session:
        heartbeat.record_status(session, "panelTest", status(cma=20, temp=72.0, throttled=0x50005))

    page = setup.get("/stations/panelTest/metrics").text

    assert "under-voltage" in page  # power card, bad
    assert "<strong>20 MB</strong>" in page and "card warn" in page  # CMA below 32 MB
    assert "72.0 °C" in page
    assert "/api/stations/panelTest/metrics?since=" in page
    assert "/static/station_metrics.js" in page


def test_link_from_the_stations_page(setup):
    assert 'href="/stations/panelTest/metrics"' in setup.get("/stations/table").text


def test_unknown_station_is_404(client):
    assert client.get("/stations/nope/metrics").status_code == 404
