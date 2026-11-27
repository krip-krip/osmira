import pytest

STATION = {"id": "panelTest", "label": "Cadreur 1", "max_decoders": 4, "outputs": 1}
FULL = {"decode": True, "view": True, "control": True}


def camera(camera_id: str) -> dict:
    return {"id": camera_id, "label": camera_id.upper(), "media": {"srt_url": "srt://mediamtx"}}


@pytest.fixture
def setup(client):
    """A station and five cameras, no rights yet."""
    client.post("/api/stations", json=STATION)
    for n in range(1, 6):
        client.post("/api/cameras", json=camera(f"cam{n}"))
    return client


def put_right(client, camera_id: str, position: int, **levels):
    body = {"position": position, **levels}
    return client.put(f"/api/stations/panelTest/rights/{camera_id}", json=body)


# --- stations ---------------------------------------------------------------


def test_station_crud(client):
    assert client.post("/api/stations", json=STATION).status_code == 201
    assert client.post("/api/stations", json=STATION).status_code == 409
    assert client.get("/api/stations").json() == [STATION]

    updated = client.put("/api/stations/panelTest", json={"label": "Cadreur 2"}).json()
    assert updated == {**STATION, "label": "Cadreur 2"}

    assert client.delete("/api/stations/panelTest").status_code == 204
    assert client.get("/api/stations/panelTest").status_code == 404


def test_station_invalid_data(client):
    assert client.post("/api/stations", json={**STATION, "id": "panel test"}).status_code == 422
    assert client.post("/api/stations", json={**STATION, "max_decoders": -1}).status_code == 422


# --- rights -----------------------------------------------------------------


def test_set_and_list_rights_sorted_by_position(setup):
    put_right(setup, "cam2", 2, **FULL)
    put_right(setup, "cam1", 1, decode=True, view=True)

    rights = setup.get("/api/stations/panelTest/rights").json()

    assert [r["camera_id"] for r in rights] == ["cam1", "cam2"]
    assert rights[0] == {
        "camera_id": "cam1",
        "position": 1,
        "decode": True,
        "view": True,
        "control": False,
    }


def test_put_replaces_existing_right(setup):
    put_right(setup, "cam1", 1, **FULL)

    response = put_right(setup, "cam1", 3, decode=True)

    assert response.status_code == 200
    rights = setup.get("/api/stations/panelTest/rights").json()
    assert rights == [
        {"camera_id": "cam1", "position": 3, "decode": True, "view": False, "control": False}
    ]


@pytest.mark.parametrize(
    "levels",
    [{"view": True}, {"decode": True, "control": True}, {"control": True}],
)
def test_levels_must_be_nested(setup, levels):
    # control implies view, view implies decode
    assert put_right(setup, "cam1", 1, **levels).status_code == 422


def test_position_is_unique_per_station(setup):
    put_right(setup, "cam1", 1, decode=True)

    response = put_right(setup, "cam2", 1, decode=True)

    assert response.status_code == 409
    assert "cam1" in response.json()["detail"]


def test_decode_capacity_is_enforced(setup):
    for n in range(1, 5):
        assert put_right(setup, f"cam{n}", n, decode=True).status_code == 200

    assert put_right(setup, "cam5", 5, decode=True).status_code == 409
    # A right without decode does not count.
    assert put_right(setup, "cam5", 5).status_code == 200
    # Replacing an existing decode right is not counted twice.
    assert put_right(setup, "cam4", 4, **FULL).status_code == 200


def test_cannot_lower_capacity_below_current_decodes(setup):
    for n in range(1, 4):
        put_right(setup, f"cam{n}", n, decode=True)

    lowered = {"label": "Cadreur 1", "max_decoders": 2}
    assert setup.put("/api/stations/panelTest", json=lowered).status_code == 409
    lowered["max_decoders"] = 3
    assert setup.put("/api/stations/panelTest", json=lowered).status_code == 200


def test_unknown_station_or_camera_is_404(setup):
    assert put_right(setup, "nope", 1, decode=True).status_code == 404
    assert setup.put("/api/stations/nope/rights/cam1", json={"position": 1}).status_code == 404
    assert setup.get("/api/stations/nope/rights").status_code == 404
    assert setup.delete("/api/stations/panelTest/rights/cam1").status_code == 404


def test_delete_right(setup):
    put_right(setup, "cam1", 1, decode=True)

    assert setup.delete("/api/stations/panelTest/rights/cam1").status_code == 204
    assert setup.get("/api/stations/panelTest/rights").json() == []


def test_deleting_a_camera_removes_its_rights(setup):
    put_right(setup, "cam1", 1, decode=True)
    put_right(setup, "cam2", 2, decode=True)

    setup.delete("/api/cameras/cam1")

    rights = setup.get("/api/stations/panelTest/rights").json()
    assert [r["camera_id"] for r in rights] == ["cam2"]


def test_deleting_a_station_removes_its_rights(setup):
    put_right(setup, "cam1", 1, decode=True)
    setup.delete("/api/stations/panelTest")

    setup.post("/api/stations", json=STATION)

    assert setup.get("/api/stations/panelTest/rights").json() == []
