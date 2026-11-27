"""Camera source: via a media server or direct (caller / listener), computed
SRT URL, override and back, live media list from MediaMTX."""

import httpx2
import pytest

API = "http://192.168.104.253:9997"
VIA_MTX = {"source": "media_server", "media_server_id": "mtx", "path": "cam1"}


class FakeMediaMTX:
    def __init__(self) -> None:
        self.down = False

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("connection refused")
        if request.url.path == "/v3/config/global/get":
            return httpx2.Response(
                200, json={"srt": True, "srtAddress": ":8890", "apiAddress": ":9997"}
            )
        if request.url.path == "/v3/paths/list":
            return httpx2.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "cam2",
                            "ready": True,
                            "source": {"type": "srtSource"},
                            "readers": [{}],
                            "tracks2": [
                                {"codec": "H265", "codecProps": {"width": 1920, "height": 1080}}
                            ],
                        },
                        {
                            "name": "cam1",
                            "ready": True,
                            "source": {"type": "srtSource"},
                            "readers": [],
                            "tracks2": [
                                {"codec": "H265", "codecProps": {"width": 1920, "height": 1080}}
                            ],
                        },
                        {
                            "name": "program",
                            "ready": False,
                            "source": None,
                            "readers": [],
                            "tracks2": [],
                        },
                    ]
                },
            )
        return httpx2.Response(404)


@pytest.fixture
def mtx(client):
    """A media server 'mtx' and a fake MediaMTX behind it."""
    fake = FakeMediaMTX()
    client.app.state.http = httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handler))
    client.post("/api/media-servers", json={"id": "mtx", "label": "MediaMTX", "api_url": API})
    return fake


def create(client, camera_id: str = "cam1", **media):
    return client.post(
        "/api/cameras", json={"id": camera_id, "label": camera_id.upper(), "media": media}
    )


def media(client, camera_id: str = "cam1") -> dict:
    return client.get(f"/api/cameras/{camera_id}").json()["media"]


# --- computed URL ------------------------------------------------------------


def test_media_server_srt_address_defaults_to_the_api_host(client, mtx):
    assert client.get("/api/media-servers/mtx").json()["srt_address"] == "192.168.104.253:8890"


def test_url_via_a_media_server(client, mtx):
    assert create(client, **VIA_MTX).status_code == 201

    m = media(client)

    assert m["srt_url"] == "srt://192.168.104.253:8890?mode=caller&streamid=read:cam1"
    assert m["srt_url_computed"] == m["srt_url"]
    assert m["srt_url_overridden"] is False


@pytest.mark.parametrize(
    ("source", "url"),
    [
        (
            {"mode": "caller", "host": "192.168.105.51", "port": 2020},
            "srt://192.168.105.51:2020?mode=caller",
        ),
        ({"mode": "listener", "port": 9000}, "srt://:9000?mode=listener"),
        (
            {"mode": "listener", "host": "10.7.1.30", "port": 9000},
            "srt://10.7.1.30:9000?mode=listener",
        ),
    ],
)
def test_url_direct_from_the_camera(client, source, url):
    assert create(client, source="direct", **source).status_code == 201

    assert media(client)["srt_url"] == url


@pytest.mark.parametrize(
    "bad",
    [
        {"source": "media_server", "path": "cam1"},  # no server
        {"source": "media_server", "media_server_id": "mtx"},  # no path
        {"source": "direct", "mode": "caller", "port": 2020},  # caller without host
        {"source": "direct", "mode": "listener"},  # no port
        {**VIA_MTX, "path": "cam 1"},
    ],
)
def test_incomplete_source_is_refused(client, mtx, bad):
    assert create(client, **bad).status_code == 422


def test_unknown_media_server_is_404(client):
    assert (
        create(client, source="media_server", media_server_id="nope", path="cam1").status_code
        == 404
    )


# --- override and back -------------------------------------------------------


def test_override_then_back_to_the_computed_url(client, mtx):
    create(client, **VIA_MTX, srt_url="srt://10.0.0.1:8890?streamid=read:cam1")
    overridden = media(client)

    client.put("/api/cameras/cam1", json={"label": "CAM1", "media": VIA_MTX})  # no srt_url
    back = media(client)

    assert overridden["srt_url"] == "srt://10.0.0.1:8890?streamid=read:cam1"
    assert overridden["srt_url_overridden"] is True
    assert (
        overridden["srt_url_computed"]
        == "srt://192.168.104.253:8890?mode=caller&streamid=read:cam1"
    )
    assert back["srt_url"] == back["srt_url_computed"]
    assert back["srt_url_overridden"] is False


def test_sending_back_the_computed_url_is_not_an_override(client, mtx):
    create(client, **VIA_MTX)
    m = media(client)
    body = {k: m[k] for k in ("source", "media_server_id", "path", "srt_url", "latency_ms")}

    client.put("/api/cameras/cam1", json={"label": "CAM1", "media": body})

    assert media(client)["srt_url_overridden"] is False


def test_override_works_in_every_mode(client):
    create(client, source="direct", mode="listener", port=9000, srt_url="srt://:9001?mode=listener")

    assert media(client)["srt_url"] == "srt://:9001?mode=listener"
    assert media(client)["srt_url_computed"] == "srt://:9000?mode=listener"


# --- media server changes ----------------------------------------------------


def test_cameras_follow_a_new_srt_address(client, mtx):
    create(client, "cam1", **VIA_MTX)
    create(
        client, "cam2", **{**VIA_MTX, "path": "cam2"}, srt_url="srt://fixed:1?streamid=read:cam2"
    )

    client.put(
        "/api/media-servers/mtx",
        json={"label": "MediaMTX", "api_url": API, "srt_address": "100.64.0.1:8890"},
    )

    assert (
        media(client, "cam1")["srt_url"] == "srt://100.64.0.1:8890?mode=caller&streamid=read:cam1"
    )
    assert media(client, "cam2")["srt_url"] == "srt://fixed:1?streamid=read:cam2"  # override kept


def test_config_sends_the_effective_url_only(client, mtx):
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    create(client, **VIA_MTX)
    client.put("/api/stations/panelTest/rights/cam1", json={"position": 1, "decode": True})

    sent = client.get("/api/stations/panelTest/config").json()["cameras"][0]["media"]

    assert sent == {
        "srt_url": "srt://192.168.104.253:8890?mode=caller&streamid=read:cam1",
        "latency_ms": 20,
        "codec": None,
        "width": None,
        "height": None,
        "fps": None,
    }


def test_a_used_media_server_cannot_be_deleted(client, mtx):
    create(client, **VIA_MTX)

    refused = client.delete("/api/media-servers/mtx")
    client.delete("/api/cameras/cam1")
    accepted = client.delete("/api/media-servers/mtx")

    assert refused.status_code == 409 and "cam1" in refused.json()["detail"]
    assert accepted.status_code == 204


# --- live media list ---------------------------------------------------------


def test_exposed_media_read_live(client, mtx):
    create(client, **VIA_MTX)

    found = client.get("/api/media-servers/mtx/paths").json()

    assert found["reachable"] is True
    assert found["srt_address_detected"] == "192.168.104.253:8890"
    assert [p["name"] for p in found["paths"]] == ["cam1", "cam2", "program"]
    cam1, cam2 = found["paths"][0], found["paths"][1]
    assert cam1["cameras"] == ["cam1"] and cam1["codec"] == "hevc" and cam1["width"] == 1920
    assert cam2["readers"] == 1 and cam2["cameras"] == []


def test_exposed_media_of_an_unreachable_server(client, mtx):
    mtx.down = True

    found = client.get("/api/media-servers/mtx/paths").json()

    assert found["reachable"] is False and "ConnectError" in found["error"]


# --- pages -------------------------------------------------------------------


def test_new_camera_form_starts_with_the_source(client, mtx):
    page = client.get("/cameras/new").text

    assert page.index('name="source"') < page.index('name="label"')
    assert 'value="media_server" checked' in page
    assert "MediaMTX (mtx)" in page


def test_source_block_shows_the_computed_url(client, mtx):
    via = client.post(
        "/cameras/source", data={"source": "media_server", "media_server_id": "mtx", "path": "cam2"}
    )
    listener = client.post(
        "/cameras/source",
        data={"source": "direct", "direct_mode": "listener", "direct_port": "9000"},
    )
    overridden = client.post("/cameras/source", data={"source": "direct", "srt_url": "srt://x:1"})

    assert "srt://192.168.104.253:8890?mode=caller&amp;streamid=read:cam2" in via.text
    assert "srt://:9000?mode=listener" in listener.text
    assert "Only one" in listener.text  # listener caveat
    assert "Override active" in overridden.text
    assert "— incomplete source —" in overridden.text


def test_create_a_camera_via_media_server_from_the_form(client, mtx):
    form = {
        "id": "cam1",
        "label": "CAM 1",
        "source": "media_server",
        "media_server_id": "mtx",
        "path": "cam1",
        "latency_ms": "20",
        "driver": "none",
        "options": "{}",
    }

    response = client.post("/cameras/new", data=form, follow_redirects=False)

    assert response.status_code == 303
    assert media(client)["srt_url"] == "srt://192.168.104.253:8890?mode=caller&streamid=read:cam1"


def test_path_options_come_from_mediamtx(client, mtx):
    options = client.get("/media-servers/mtx/path-options").text

    assert '<option value="cam1">' in options and "HEVC 1920x1080" in options
    assert "3 paths on mtx" in options


def test_exposed_media_page_offers_to_create_cameras(client, mtx):
    create(client, **VIA_MTX)

    page = client.get("/media-servers/mtx/media").text

    assert "cam1" in page and "cam2" in page
    assert page.count("Create camera") == 2  # cam2 and program, not cam1 (already used)
    assert "/cameras/new?source=media_server&amp;media_server_id=mtx&amp;path=cam2" in page


def test_prefilled_camera_form(client, mtx):
    page = client.get(
        "/cameras/new?source=media_server&media_server_id=mtx&path=cam2&id=cam2&label=CAM2"
    ).text

    assert 'value="cam2"' in page
    assert "streamid=read:cam2" in page


def test_detect_button(client, mtx):
    response = client.post("/media-servers/detect", data={"api_url": API})

    assert 'value="192.168.104.253:8890"' in response.text
    assert "detected in MediaMTX" in response.text


def test_deleting_a_used_server_from_the_page_explains_why(client, mtx):
    create(client, **VIA_MTX)

    response = client.post("/media-servers/mtx/delete")

    assert response.status_code == 422
    assert "used by cameras cam1" in response.text
