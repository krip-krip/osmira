import httpx2
import pytest
from conftest import core_config

from osmiracam_agent.core_client import CoreClient, CoreUnavailable

pytestmark = pytest.mark.anyio


def client_with(handler) -> CoreClient:
    http = httpx2.AsyncClient(base_url="http://core.test", transport=httpx2.MockTransport(handler))
    return CoreClient(http, "panelTest")


async def test_fetch_config():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200, json=core_config([("cam1", 1, True)]))

    data = await client_with(handler).fetch_config(None)

    assert data["version"] == "sha256:v1"
    assert seen[0].url.path == "/api/stations/panelTest/config"
    assert "if-none-match" not in seen[0].headers


async def test_unchanged_config_returns_none():
    def handler(request):
        assert request.headers["if-none-match"] == '"sha256:v1"'
        return httpx2.Response(304)

    assert await client_with(handler).fetch_config("sha256:v1") is None


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx2.Response(404, json={"detail": "station 'panelTest' not found"}),
        lambda r: httpx2.Response(500),
        lambda r: httpx2.Response(200, text="not json"),
    ],
)
async def test_bad_answers_raise(handler):
    with pytest.raises(CoreUnavailable):
        await client_with(handler).fetch_config(None)


async def test_unreachable_core_raises():
    def handler(request):
        raise httpx2.ConnectError("connection refused")

    with pytest.raises(CoreUnavailable):
        await client_with(handler).fetch_config(None)
