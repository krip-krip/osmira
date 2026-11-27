import pytest

STATION = {"id": "panelTest", "label": "Cadreur 1", "max_decoders": 4, "outputs": 1}
CONFIG_URL = "/api/stations/panelTest/config"


def camera(n: int) -> dict:
    return {
        "id": f"cam{n}",
        "label": f"CAM {n}",
        "media": {"srt_url": f"srt://192.168.104.253:8890?mode=caller&streamid=read:cam{n}"},
        "control": {"driver": "panasonic_aw", "host": f"192.168.105.5{n}", "password": "secret"},
    }


@pytest.fixture
def setup(client):
    client.post("/api/stations", json=STATION)
    for n in range(1, 6):
        client.post("/api/cameras", json=camera(n))
    return client


def put_right(client, n: int, position: int, **levels):
    body = {"position": position, **levels}
    return client.put(f"/api/stations/panelTest/rights/cam{n}", json=body)


def test_config_lists_decoded_cameras_by_position(setup):
    put_right(setup, 1, 2, decode=True, view=True)
    put_right(setup, 2, 1, decode=True)
    put_right(setup, 3, 3)  # no decode: not sent

    config = setup.get(CONFIG_URL).json()

    assert config["station"] == STATION
    assert [(c["id"], c["position"]) for c in config["cameras"]] == [("cam2", 1), ("cam1", 2)]
    cam1 = config["cameras"][1]
    assert cam1["rights"] == {"decode": True, "view": True, "control": False}
    assert cam1["media"]["srt_url"].endswith("read:cam1")


def test_config_never_contains_camera_control(setup):
    put_right(setup, 1, 1, decode=True, view=True, control=True)

    response = setup.get(CONFIG_URL)

    assert "control" not in response.json()["cameras"][0]
    assert "secret" not in response.text
    assert "192.168.105.51" not in response.text


def test_empty_config(setup):
    config = setup.get(CONFIG_URL).json()

    assert config["cameras"] == []
    assert config["version"].startswith("sha256:")


def test_unknown_station_is_404(client):
    assert client.get("/api/stations/nope/config").status_code == 404


def test_version_is_stable_without_changes(setup):
    put_right(setup, 1, 1, decode=True)

    first = setup.get(CONFIG_URL)
    second = setup.get(CONFIG_URL)

    assert first.json()["version"] == second.json()["version"]
    assert first.headers["ETag"] == f'"{first.json()["version"]}"'


def version(client) -> str:
    return client.get(CONFIG_URL).json()["version"]


def test_version_changes_with_rights(setup):
    put_right(setup, 1, 1, decode=True)
    before = version(setup)

    put_right(setup, 2, 2, decode=True)

    assert version(setup) != before


def test_version_changes_when_a_camera_changes(setup):
    put_right(setup, 1, 1, decode=True)
    before = version(setup)

    body = camera(1)
    del body["id"]
    body["media"]["latency_ms"] = 40
    setup.put("/api/cameras/cam1", json=body)

    assert version(setup) != before


def test_unrelated_changes_keep_the_version(setup):
    put_right(setup, 1, 1, decode=True)
    before = version(setup)

    # cam5 is not on this station; another station gets rights.
    body = camera(5)
    del body["id"]
    body["label"] = "OTHER"
    setup.put("/api/cameras/cam5", json=body)
    setup.post("/api/stations", json={"id": "other", "label": "Other"})
    setup.put("/api/stations/other/rights/cam1", json={"position": 1, "decode": True})

    assert version(setup) == before


def test_if_none_match_returns_304(setup):
    put_right(setup, 1, 1, decode=True)
    etag = setup.get(CONFIG_URL).headers["ETag"]

    unchanged = setup.get(CONFIG_URL, headers={"If-None-Match": etag})
    put_right(setup, 2, 2, decode=True)
    changed = setup.get(CONFIG_URL, headers={"If-None-Match": etag})

    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert changed.status_code == 200


def test_no_global_camera_limit(setup):
    # Only the station's own capacity limits decoding.
    setup.put("/api/stations/panelTest", json={"label": "Big", "max_decoders": 40})
    for n in range(6, 31):
        setup.post("/api/cameras", json=camera(n))
    for n in range(1, 31):
        assert put_right(setup, n, n * 10, decode=True, view=True).status_code == 200

    assert len(setup.get(CONFIG_URL).json()["cameras"]) == 30
