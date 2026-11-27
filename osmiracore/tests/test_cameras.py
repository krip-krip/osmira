import copy

CAM1 = {
    "id": "cam1",
    "label": "CAM 1",
    "media": {
        "srt_url": "srt://192.168.104.253:8890?mode=caller&streamid=read:cam1",
        "latency_ms": 20,
        "codec": "hevc",
        "width": 1920,
        "height": 1080,
        "fps": 50,
    },
    "control": {
        "driver": "panasonic_aw",
        "host": "192.168.105.51",
        "port": 80,
        "username": "admin",
        "password": "secret",
        "options": {},
    },
}


def update_body(camera: dict) -> dict:
    """Same camera, as a PUT body (no id)."""
    body = copy.deepcopy(camera)
    del body["id"]
    return body


def test_create_then_get(client):
    created = client.post("/api/cameras", json=CAM1)

    assert created.status_code == 201
    camera = client.get("/api/cameras/cam1").json()
    assert camera["label"] == "CAM 1"
    for key, value in CAM1["media"].items():
        assert camera["media"][key] == value
    # Only an SRT URL given: direct source, the URL is imposed (override).
    assert camera["media"]["source"] == "direct"
    assert camera["media"]["srt_url_overridden"] is True
    assert camera["control"]["host"] == "192.168.105.51"


def test_password_is_never_returned(client):
    created = client.post("/api/cameras", json=CAM1).json()
    listed = client.get("/api/cameras").json()

    for camera in (created, listed[0]):
        assert "password" not in camera["control"]
        assert camera["control"]["password_set"] is True


def test_minimal_camera_uses_defaults(client):
    body = {"id": "cam2", "label": "CAM 2", "media": {"srt_url": "srt://mediamtx:8890"}}

    camera = client.post("/api/cameras", json=body).json()

    # Format not declared: auto (the stations play what they receive).
    assert camera["media"]["codec"] is None
    assert camera["media"]["width"] is None
    assert camera["media"]["fps"] is None
    assert camera["media"]["latency_ms"] == 20
    assert camera["control"]["driver"] == "none"
    assert camera["control"]["password_set"] is False


def test_list_is_sorted_by_id(client):
    for camera_id in ("cam3", "cam1", "cam2"):
        client.post("/api/cameras", json={**CAM1, "id": camera_id})

    ids = [c["id"] for c in client.get("/api/cameras").json()]

    assert ids == ["cam1", "cam2", "cam3"]


def test_duplicate_id_is_a_conflict(client):
    client.post("/api/cameras", json=CAM1)

    response = client.post("/api/cameras", json=CAM1)

    assert response.status_code == 409


def test_invalid_data_is_rejected(client):
    bad_id = {**CAM1, "id": "cam 1"}
    bad_url = {**CAM1, "media": {**CAM1["media"], "srt_url": "rtsp://cam"}}
    unknown_field = {**CAM1, "colour": "red"}

    for body in (bad_id, bad_url, unknown_field):
        assert client.post("/api/cameras", json=body).status_code == 422


def test_update_replaces_fields(client):
    client.post("/api/cameras", json=CAM1)
    body = update_body(CAM1)
    body["label"] = "WIDE"
    body["media"]["fps"] = 25

    updated = client.put("/api/cameras/cam1", json=body).json()

    assert updated["label"] == "WIDE"
    assert updated["media"]["fps"] == 25


def test_update_without_password_keeps_it(client):
    client.post("/api/cameras", json=CAM1)
    body = update_body(CAM1)
    del body["control"]["password"]

    updated = client.put("/api/cameras/cam1", json=body).json()

    assert updated["control"]["password_set"] is True


def test_update_with_empty_password_clears_it(client):
    client.post("/api/cameras", json=CAM1)
    body = update_body(CAM1)
    body["control"]["password"] = ""

    updated = client.put("/api/cameras/cam1", json=body).json()

    assert updated["control"]["password_set"] is False


def test_delete(client):
    client.post("/api/cameras", json=CAM1)

    assert client.delete("/api/cameras/cam1").status_code == 204
    assert client.get("/api/cameras/cam1").status_code == 404


def test_unknown_camera_is_404(client):
    assert client.get("/api/cameras/nope").status_code == 404
    assert client.put("/api/cameras/nope", json=update_body(CAM1)).status_code == 404
    assert client.delete("/api/cameras/nope").status_code == 404


def test_data_survives_restart(tmp_path):
    from fastapi.testclient import TestClient

    from osmiracore.main import create_app
    from osmiracore.settings import Settings

    settings = Settings(db_path=tmp_path / "core.db")
    with TestClient(create_app(settings)) as first:
        first.post("/api/cameras", json=CAM1)
    with TestClient(create_app(settings)) as second:
        assert second.get("/api/cameras/cam1").status_code == 200
