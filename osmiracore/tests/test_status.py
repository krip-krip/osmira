"""Station status (heartbeat): POST/GET /api/stations/{id}/status and its display."""

import time

import pytest

from osmiracore.models import Station
from osmiracore.services import status as heartbeat


def status_body(config_version: str | None = None, **extra) -> dict:
    return {
        "agent_version": "0.1.0",
        "hostname": "panelTest",
        "addresses": ["10.7.1.30", "100.83.219.117"],
        "config_version": config_version,
        "selected_camera": "cam1",
        "player": {
            "running": True,
            "shown_camera": "cam1",
            "cameras": [
                {
                    "camera_id": "cam1",
                    "state": "streaming",
                    "fps": 49.9,
                    "mbps": 16.2,
                    "width": 1920,
                    "height": 1080,
                    "connects": 1,
                    "decode_errors": 0,
                },
            ],
        },
        "hardware": {
            "model": "Raspberry Pi 4 Model B Rev 1.5",
            "ram_mb": 905,
            "os": "Debian GNU/Linux 13 (trixie)",
        },
        "system": {"temp_c": 51.6, "cma_free_mb": 71},
        **extra,
    }


@pytest.fixture
def setup(client):
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    client.post(
        "/api/cameras", json={"id": "cam1", "label": "CAM 1", "media": {"srt_url": "srt://m"}}
    )
    client.put(
        "/api/stations/panelTest/rights/cam1", json={"position": 1, "decode": True, "view": True}
    )
    return client


def current_version(client) -> str:
    return client.get("/api/stations/panelTest/config").json()["version"]


def post_status(client, body: dict):
    return client.post("/api/stations/panelTest/status", json=body)


def test_never_seen_station_is_offline(setup):
    st = setup.get("/api/stations/panelTest/status").json()

    assert st == {
        "station_id": "panelTest",
        "online": False,
        "last_seen": None,
        "seconds_since": None,
        "config_up_to_date": None,
        "status": None,
    }


def test_status_makes_the_station_online(setup):
    assert post_status(setup, status_body(current_version(setup))).status_code == 204

    st = setup.get("/api/stations/panelTest/status").json()

    assert st["online"] is True
    assert st["config_up_to_date"] is True
    assert st["status"]["hardware"]["model"].startswith("Raspberry Pi 4")
    assert st["status"]["player"]["cameras"][0]["fps"] == 49.9


def test_config_up_to_date_follows_the_core(setup):
    post_status(setup, status_body(current_version(setup)))

    setup.put("/api/cameras/cam1", json={"label": "WIDE", "media": {"srt_url": "srt://m"}})

    assert setup.get("/api/stations/panelTest/status").json()["config_up_to_date"] is False


def test_unknown_fields_from_a_newer_agent_are_ignored(setup):
    body = status_body(None, gamepad={"connected": True})

    assert post_status(setup, body).status_code == 204


def test_unknown_station_is_404(client):
    response = client.post("/api/stations/nope/status", json=status_body())

    assert response.status_code == 404


def test_offline_after_the_timeout(setup):
    post_status(setup, status_body())
    with setup.app.state.session_factory() as session:
        station = session.get(Station, "panelTest")
        soon = heartbeat.station_status(session, station, timeout_s=15, now=time.time() + 10)
        late = heartbeat.station_status(session, station, timeout_s=15, now=time.time() + 20)

    assert soon.online is True
    assert late.online is False
    assert late.seconds_since >= 20


def test_matrix_shows_online_stations(setup):
    before = setup.get("/api/matrix").json()["destinations"][0]["online"]
    post_status(setup, status_body())
    after = setup.get("/api/matrix").json()["destinations"][0]["online"]

    assert (before, after) == (False, True)


def test_stations_page_shows_status_and_hardware(setup):
    assert "never seen" in setup.get("/stations").text

    post_status(setup, status_body(current_version(setup)))
    table = setup.get("/stations/table").text

    assert 'class="dot online"' in table
    assert "Raspberry Pi 4 Model B Rev 1.5" in table
    assert "✓ up to date" in table
    assert "0.1.0" in table
    assert 'hx-trigger="every 5s"' in table


def test_status_is_deleted_with_its_station(setup):
    post_status(setup, status_body())

    setup.delete("/api/stations/panelTest")
    setup.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})

    assert setup.get("/api/stations/panelTest/status").json()["online"] is False
