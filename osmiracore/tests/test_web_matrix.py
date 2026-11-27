import pytest

STATION = {"id": "panelTest", "label": "Cadreur 1", "max_decoders": 4, "outputs": 2}


@pytest.fixture
def setup(client):
    client.post("/api/stations", json=STATION)
    for n in (1, 2, 3):
        client.post(
            "/api/cameras",
            json={"id": f"cam{n}", "label": f"CAM {n}", "media": {"srt_url": "srt://m"}},
        )
    for n in (1, 2):
        client.put(
            f"/api/stations/panelTest/rights/cam{n}",
            json={"position": n, "decode": True, "view": True},
        )
    return client


def select(client, camera_id: str, output: int = 1):
    form = {"station_id": "panelTest", "output": str(output), "camera_id": camera_id}
    return client.post("/matrix/select", data=form)


def test_home_redirects_to_matrix(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/matrix"


def test_static_files_are_served(client):
    assert "htmx" in client.get("/static/htmx.min.js").text
    assert client.get("/static/style.css").status_code == 200


def test_empty_matrix_explains_what_to_do(client):
    page = client.get("/matrix").text

    assert "No camera yet" in page and "/cameras/new" in page
    assert "No station yet" in page and "/stations/new" in page


def test_matrix_shows_sources_and_destinations(setup):
    page = setup.get("/matrix").text

    for label in ("CAM 1", "CAM 2", "CAM 3", "Cadreur 1"):
        assert label in page
    assert page.count("out 1") >= 1 and page.count("out 2") >= 1
    # cam3: no view right -> disabled cells, no button for it
    assert '"camera_id": "cam3"' not in page
    assert page.count('class="cell disabled"') == 2  # 2 outputs


def test_click_selects_and_returns_the_grid(setup):
    response = select(setup, "cam2", output=2)

    assert response.status_code == 200
    assert 'id="grid"' in response.text
    assert "<html" not in response.text  # fragment only
    assert response.text.count('aria-pressed="true"') == 1
    outputs = setup.get("/api/stations/panelTest/outputs").json()
    assert outputs == [{"output": 1, "camera_id": None}, {"output": 2, "camera_id": "cam2"}]


def test_refused_selection_shows_the_reason(setup):
    response = select(setup, "cam3")

    assert response.status_code == 200
    assert "no &#39;view&#39; right" in response.text or "no 'view' right" in response.text
    assert setup.get("/api/stations/panelTest/outputs").json()[0]["camera_id"] is None


def test_click_sends_the_event_to_the_station(setup):
    with setup.stream("GET", "/api/stations/panelTest/events") as stream:
        lines = stream.iter_lines()
        while next(lines) != "":  # skip the initial state event
            pass

        select(setup, "cam1")

        assert next(lines) == "event: select"
        assert next(lines) == 'data: {"output": 1, "camera_id": "cam1"}'


def test_grid_fragment_is_polled(setup):
    select(setup, "cam1")

    grid = setup.get("/matrix/grid").text

    assert 'hx-trigger="every 2s"' in grid
    assert grid.count('aria-pressed="true"') == 1
