"""Camera format: auto by default, received format from the stations, warnings."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from osmiracore.db import OutdatedSchema
from osmiracore.main import create_app
from osmiracore.settings import Settings


def player_camera(fps: float, width: int = 1920, height: int = 1080) -> dict:
    return {"camera_id": "cam1", "state": "streaming", "fps": fps, "width": width, "height": height}


def report(client, *cams: dict) -> None:
    body = {"agent_version": "0.1.0", "player": {"running": True, "cameras": list(cams)}}
    assert client.post("/api/stations/panelTest/status", json=body).status_code == 204


@pytest.fixture
def setup(client):
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    client.post(
        "/api/cameras", json={"id": "cam1", "label": "CAM 1", "media": {"srt_url": "srt://m"}}
    )
    return client


def declare(client, **media) -> None:
    body = {"label": "CAM 1", "media": {"srt_url": "srt://m", **media}}
    assert client.put("/api/cameras/cam1", json=body).status_code == 200


def test_nothing_received_yet(setup):
    camera = setup.get("/api/cameras/cam1").json()

    assert camera["received"] is None
    assert camera["warnings"] == []


def test_received_format_comes_from_the_stations(setup):
    report(setup, player_camera(49.9))

    camera = setup.get("/api/cameras/cam1").json()

    assert camera["received"]["station_id"] == "panelTest"
    assert (camera["received"]["width"], camera["received"]["height"]) == (1920, 1080)
    assert camera["received"]["fps"] == 49.9
    assert camera["warnings"] == []  # auto: nothing to compare


def test_a_camera_without_picture_is_not_received(setup):
    report(setup, player_camera(0))

    assert setup.get("/api/cameras/cam1").json()["received"] is None


def test_declared_values_matching_the_stream(setup):
    declare(setup, width=1920, height=1080, fps=50, codec="hevc")
    report(setup, player_camera(49.2))

    assert setup.get("/api/cameras/cam1").json()["warnings"] == []


def test_declared_values_differing_from_the_stream(setup):
    declare(setup, width=1920, height=1080, fps=50)
    report(setup, player_camera(25.0, 1280, 720))

    warnings = setup.get("/api/cameras/cam1").json()["warnings"]

    assert warnings == [
        "declared 1920x1080, received 1280x720",
        "declared 50 fps, received 25.0 fps",
    ]


def test_form_blank_fields_mean_auto(setup):
    form = {
        "label": "CAM 1",
        "srt_url": "srt://m",
        "latency_ms": "40",
        "codec": "",
        "width": "",
        "height": "",
        "fps": "",
        "driver": "none",
        "options": "{}",
    }

    setup.post("/cameras/cam1", data=form)

    media = setup.get("/api/cameras/cam1").json()["media"]
    assert media == {
        "srt_url": "srt://m",
        "latency_ms": 40,
        "codec": None,
        "width": None,
        "height": None,
        "fps": None,
    }


def test_cameras_page_shows_auto_received_and_warnings(setup):
    page = setup.get("/cameras").text
    assert ">auto<" in page

    declare(setup, fps=25)
    report(setup, player_camera(50.0))
    page = setup.get("/cameras").text

    assert "1920x1080 · 50.0 fps" in page
    assert "via panelTest" in page
    assert "⚠ declared 25 fps, received 50.0 fps" in page


def test_outdated_database_is_refused_with_a_clear_message(tmp_path):
    # A database created before the format became optional (NOT NULL columns).
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE cameras (id VARCHAR(32) PRIMARY KEY, label VARCHAR NOT NULL,"
            " media_srt_url VARCHAR NOT NULL, media_latency_ms INTEGER NOT NULL,"
            " media_codec VARCHAR NOT NULL, media_width INTEGER NOT NULL,"
            " media_height INTEGER NOT NULL, media_fps INTEGER NOT NULL,"
            " control_driver VARCHAR NOT NULL, control_host VARCHAR, control_port INTEGER,"
            " control_username VARCHAR, control_password VARCHAR, control_options JSON NOT NULL)"
        )

    with pytest.raises(OutdatedSchema, match="delete this file"):
        with TestClient(create_app(Settings(db_path=db))):
            pass
