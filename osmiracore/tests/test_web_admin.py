"""Admin pages: cameras, stations, rights. Same rules as the REST API."""

import pytest

CAMERA_FORM = {
    "id": "cam1",
    "label": "CAM 1",
    "srt_url": "srt://192.168.104.253:8890?mode=caller&streamid=read:cam1",
    "latency_ms": "20",
    "codec": "hevc",
    "width": "1920",
    "height": "1080",
    "fps": "50",
    "driver": "panasonic_aw",
    "host": "192.168.105.51",
    "port": "80",
    "username": "admin",
    "password": "secret",
    "options": "{}",
}


def camera(client, camera_id: str = "cam1") -> dict:
    return client.get(f"/api/cameras/{camera_id}").json()


# --- cameras ------------------------------------------------------------------


def test_create_camera_from_the_form(client):
    response = client.post("/cameras/new", data=CAMERA_FORM, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/cameras"
    created = camera(client)
    assert created["media"]["latency_ms"] == 20
    assert created["control"]["port"] == 80
    assert created["control"]["password_set"] is True
    page = client.get("/cameras").text
    assert "CAM 1" in page and "secret" not in page


def test_invalid_camera_form_shows_errors_and_keeps_input(client):
    bad = {**CAMERA_FORM, "id": "cam 1", "srt_url": "rtsp://x", "options": "{bad"}

    response = client.post("/cameras/new", data=bad)

    assert response.status_code == 422
    assert "not valid JSON" in response.text
    assert 'value="CAM 1"' in response.text  # what was typed is kept
    assert client.get("/api/cameras").json() == []


def test_invalid_fields_are_all_reported(client):
    bad = {**CAMERA_FORM, "id": "cam 1", "srt_url": "rtsp://x"}

    response = client.post("/cameras/new", data=bad)

    assert response.status_code == 422
    assert "id:" in response.text
    assert "media srt_url:" in response.text


def test_duplicate_camera_is_refused(client):
    client.post("/cameras/new", data=CAMERA_FORM)

    response = client.post("/cameras/new", data=CAMERA_FORM)

    assert response.status_code == 422
    assert "already exists" in response.text


def test_edit_page_never_shows_the_password(client):
    client.post("/cameras/new", data=CAMERA_FORM)

    page = client.get("/cameras/cam1").text

    assert "secret" not in page
    assert "unchanged (set)" in page
    assert 'value="192.168.105.51"' in page


def test_edit_keeps_password_when_left_empty(client):
    client.post("/cameras/new", data=CAMERA_FORM)

    form = {**CAMERA_FORM, "label": "WIDE", "password": ""}
    response = client.post("/cameras/cam1", data=form, follow_redirects=False)

    assert response.status_code == 303
    assert camera(client)["label"] == "WIDE"
    assert camera(client)["control"]["password_set"] is True


def test_edit_can_clear_the_password(client):
    client.post("/cameras/new", data=CAMERA_FORM)

    client.post("/cameras/cam1", data={**CAMERA_FORM, "password": "", "clear_password": "on"})

    assert camera(client)["control"]["password_set"] is False


def test_delete_camera(client):
    client.post("/cameras/new", data=CAMERA_FORM)

    response = client.post("/cameras/cam1/delete", follow_redirects=False)

    assert response.status_code == 303
    assert client.get("/api/cameras/cam1").status_code == 404


def test_unknown_camera_page_is_404(client):
    assert client.get("/cameras/nope").status_code == 404


# --- stations -----------------------------------------------------------------

STATION_FORM = {"id": "panelTest", "label": "Cadreur 1", "max_decoders": "4", "outputs": "1"}


def test_create_station_then_go_to_its_rights(client):
    response = client.post("/stations/new", data=STATION_FORM, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/stations/panelTest/rights"
    assert client.get("/api/stations/panelTest").json()["label"] == "Cadreur 1"


def test_station_list_shows_capacity(client):
    client.post("/stations/new", data=STATION_FORM)

    page = client.get("/stations").text

    assert "Cadreur 1" in page and "0 / 4" in page


def test_edit_station_and_refuse_bad_values(client):
    client.post("/stations/new", data=STATION_FORM)

    ok = client.post("/stations/panelTest", data={**STATION_FORM, "outputs": "2"})
    bad = client.post("/stations/panelTest", data={**STATION_FORM, "outputs": "0"})

    assert ok.status_code == 200  # after the redirect
    assert client.get("/api/stations/panelTest").json()["outputs"] == 2
    assert bad.status_code == 422
    assert "outputs:" in bad.text


def test_delete_station(client):
    client.post("/stations/new", data=STATION_FORM)

    client.post("/stations/panelTest/delete")

    assert client.get("/api/stations/panelTest").status_code == 404


# --- rights -------------------------------------------------------------------


@pytest.fixture
def setup(client):
    client.post("/stations/new", data={**STATION_FORM, "max_decoders": "1"})
    for n in (1, 2):
        client.post("/cameras/new", data={**CAMERA_FORM, "id": f"cam{n}", "label": f"CAM {n}"})
    return client


def save_right(client, camera_id: str, **fields):
    return client.post(f"/stations/panelTest/rights/{camera_id}", data=fields)


def test_rights_page_lists_every_camera(setup):
    page = setup.get("/stations/panelTest/rights").text

    assert "CAM 1" in page and "CAM 2" in page
    assert "Decoding <strong>0</strong> of 1" in page
    assert page.count(">Add<") == 2


def test_add_a_right(setup):
    response = save_right(setup, "cam1", position="1", decode="on", view="on")

    assert response.status_code == 200
    assert 'id="rights"' in response.text and "<html" not in response.text
    rights = setup.get("/api/stations/panelTest/rights").json()
    assert rights == [
        {"camera_id": "cam1", "position": 1, "decode": True, "view": True, "control": False}
    ]


def test_refused_right_shows_the_reason_and_keeps_input(setup):
    save_right(setup, "cam1", position="1", decode="on")

    full = save_right(setup, "cam2", position="2", decode="on")  # capacity is 1
    nested = save_right(setup, "cam2", position="2", view="on")  # view without decode
    taken = save_right(setup, "cam2", position="1")  # position used by cam1

    assert "can decode at most 1" in full.text
    assert "&#39;view&#39; requires &#39;decode&#39;" in nested.text
    assert "already used by &#39;cam1&#39;" in taken.text
    assert 'value="1"' in taken.text
    assert len(setup.get("/api/stations/panelTest/rights").json()) == 1


def test_remove_a_right(setup):
    save_right(setup, "cam1", position="1", decode="on")

    response = setup.post("/stations/panelTest/rights/cam1/delete")

    assert response.status_code == 200
    assert setup.get("/api/stations/panelTest/rights").json() == []


def test_rights_change_reaches_the_station(setup):
    with setup.stream("GET", "/api/stations/panelTest/events") as stream:
        lines = stream.iter_lines()
        while next(lines) != "":  # skip the initial state event
            pass

        save_right(setup, "cam1", position="1", decode="on", view="on")

        assert next(lines) == "event: config_changed"
