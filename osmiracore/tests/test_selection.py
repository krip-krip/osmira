import pytest

STATION = {"id": "panelTest", "label": "Cadreur 1", "max_decoders": 4, "outputs": 2}
VIEW = {"decode": True, "view": True}


@pytest.fixture
def setup(client):
    """Station with 2 outputs; cam1..cam3 viewable, cam4 decoded only, cam5 no right."""
    client.post("/api/stations", json=STATION)
    for n in range(1, 6):
        client.post(
            "/api/cameras",
            json={"id": f"cam{n}", "label": f"CAM {n}", "media": {"srt_url": "srt://m"}},
        )
    for n in range(1, 4):
        put_right(client, f"cam{n}", n, **VIEW)
    put_right(client, "cam4", 4, decode=True)
    return client


def put_right(client, camera_id: str, position: int, **levels):
    body = {"position": position, **levels}
    return client.put(f"/api/stations/panelTest/rights/{camera_id}", json=body)


def select(client, output: int, camera_id: str):
    url = f"/api/stations/panelTest/outputs/{output}/selection"
    return client.put(url, json={"camera_id": camera_id})


def outputs(client) -> list:
    return client.get("/api/stations/panelTest/outputs").json()


def test_outputs_start_empty(setup):
    assert outputs(setup) == [
        {"output": 1, "camera_id": None},
        {"output": 2, "camera_id": None},
    ]


def test_select_camera_on_each_output(setup):
    assert select(setup, 1, "cam2").json() == {"output": 1, "camera_id": "cam2"}
    select(setup, 2, "cam3")
    select(setup, 1, "cam1")

    assert outputs(setup) == [
        {"output": 1, "camera_id": "cam1"},
        {"output": 2, "camera_id": "cam3"},
    ]


def test_select_requires_view_right(setup):
    assert select(setup, 1, "cam4").status_code == 409  # decode only
    assert select(setup, 1, "cam5").status_code == 409  # no right


def test_select_unknown_things(setup):
    assert select(setup, 3, "cam1").status_code == 404  # no output 3
    assert select(setup, 0, "cam1").status_code == 404
    assert select(setup, 1, "nope").status_code == 404
    url = "/api/stations/nope/outputs/1/selection"
    assert setup.put(url, json={"camera_id": "cam1"}).status_code == 404


def test_selection_is_not_part_of_config_version(setup):
    before = setup.get("/api/stations/panelTest/config").json()["version"]

    select(setup, 1, "cam2")

    assert setup.get("/api/stations/panelTest/config").json()["version"] == before


@pytest.mark.parametrize(
    "remove",
    [
        lambda c: put_right(c, "cam2", 2, decode=True),  # view removed
        lambda c: c.delete("/api/stations/panelTest/rights/cam2"),
        lambda c: c.delete("/api/cameras/cam2"),
    ],
)
def test_losing_the_view_right_clears_the_selection(setup, remove):
    select(setup, 1, "cam2")
    select(setup, 2, "cam3")

    remove(setup)

    assert outputs(setup) == [
        {"output": 1, "camera_id": None},
        {"output": 2, "camera_id": "cam3"},
    ]


def test_removing_an_output_clears_its_selection(setup):
    select(setup, 2, "cam3")

    update = {"label": "Cadreur 1", "max_decoders": 4}
    assert setup.put("/api/stations/panelTest", json={**update, "outputs": 1}).status_code == 200
    assert setup.put("/api/stations/panelTest", json={**update, "outputs": 2}).status_code == 200

    assert outputs(setup)[1] == {"output": 2, "camera_id": None}


def test_matrix(setup):
    setup.post("/api/stations", json={"id": "other", "label": "Cadreur 2"})
    select(setup, 2, "cam3")

    matrix = setup.get("/api/matrix").json()

    assert [s["camera_id"] for s in matrix["sources"]] == ["cam1", "cam2", "cam3", "cam4", "cam5"]
    assert matrix["destinations"] == [
        {
            "station_id": "panelTest",
            "station_label": "Cadreur 1",
            "output": 1,
            "selected": None,
            "allowed": ["cam1", "cam2", "cam3"],
            "online": False,
        },
        {
            "station_id": "panelTest",
            "station_label": "Cadreur 1",
            "output": 2,
            "selected": "cam3",
            "allowed": ["cam1", "cam2", "cam3"],
            "online": False,
        },
        {
            "station_id": "other",
            "station_label": "Cadreur 2",
            "output": 1,
            "selected": None,
            "allowed": [],
            "online": False,
        },
    ]
