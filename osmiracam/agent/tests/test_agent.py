"""The agent with a fake Core (httpx2 MockTransport) and a fake ptzview."""

import asyncio

import httpx2
import pytest
from conftest import FakeSpawner, core_config, until

from osmiracam_agent.agent import Agent
from osmiracam_agent.core_client import CoreClient
from osmiracam_agent.station_config import ConfigStore
from osmiracam_agent.supervisor import Supervisor

pytestmark = pytest.mark.anyio


class FakeCore:
    """Serves a configuration that tests can change, or pretends to be down."""

    def __init__(self, config: dict | None) -> None:
        self.config = config
        self.down = False

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if self.down or self.config is None:
            raise httpx2.ConnectError("connection refused")
        etag = f'"{self.config["version"]}"'
        if request.headers.get("if-none-match") == etag:
            return httpx2.Response(304, headers={"ETag": etag})
        return httpx2.Response(200, json=self.config, headers={"ETag": etag})


def make_agent(settings, core: FakeCore, spawner: FakeSpawner) -> Agent:
    http = httpx2.AsyncClient(
        base_url="http://core.test", transport=httpx2.MockTransport(core.handler)
    )
    supervisor = Supervisor(spawner, restart_delay_s=0.01, stop_timeout_s=0.1)
    return Agent(
        settings, CoreClient(http, "panelTest"), ConfigStore(settings.state_dir), supervisor
    )


async def test_first_start_fetches_config_and_launches_ptzview(settings):
    core = FakeCore(core_config([("cam1", 1, True)]))
    spawner = FakeSpawner()
    agent = make_agent(settings, core, spawner)

    await agent.start()  # nothing stored yet: ptzview not started
    assert spawner.processes == []

    assert await agent.refresh() is True
    await until(lambda: len(spawner.processes) == 1)
    assert "read:cam1" in settings.ptzview.conf_path.read_text()
    assert ConfigStore(settings.state_dir).load()["version"] == "sha256:v1"


async def test_unchanged_config_does_not_restart(settings):
    core = FakeCore(core_config([("cam1", 1, True)]))
    spawner = FakeSpawner()
    agent = make_agent(settings, core, spawner)
    await agent.refresh()
    await until(lambda: len(spawner.processes) == 1)

    assert await agent.refresh() is False
    await asyncio.sleep(0.05)
    assert len(spawner.processes) == 1


async def test_new_config_rewrites_conf_and_restarts(settings):
    core = FakeCore(core_config([("cam1", 1, True)]))
    spawner = FakeSpawner()
    agent = make_agent(settings, core, spawner)
    await agent.refresh()
    await until(lambda: len(spawner.processes) == 1)

    core.config = core_config([("cam1", 1, True), ("cam2", 2, True)], version="sha256:v2")
    assert await agent.refresh() is True

    await until(lambda: len(spawner.processes) == 2)
    assert spawner.processes[0].returncode is not None  # old ptzview stopped
    assert "read:cam2" in settings.ptzview.conf_path.read_text()


async def test_core_down_at_boot_uses_local_copy(settings):
    ConfigStore(settings.state_dir).save(core_config([("cam1", 1, True)]))
    core = FakeCore(None)  # unreachable
    spawner = FakeSpawner()
    agent = make_agent(settings, core, spawner)

    await agent.start()
    assert await agent.refresh() is False

    await until(lambda: len(spawner.processes) == 1)
    assert "read:cam1" in settings.ptzview.conf_path.read_text()


async def test_core_outage_keeps_ptzview_running(settings):
    core = FakeCore(core_config([("cam1", 1, True)]))
    spawner = FakeSpawner()
    agent = make_agent(settings, core, spawner)
    await agent.refresh()
    await until(lambda: len(spawner.processes) == 1)

    core.down = True
    for _ in range(3):
        assert await agent.refresh() is False

    assert spawner.processes[0].returncode is None
    assert agent.config.version == "sha256:v1"


async def test_local_copy_of_another_station_is_ignored(settings):
    other = core_config([("cam1", 1, True)])
    other["station"]["id"] = "otherStation"
    ConfigStore(settings.state_dir).save(other)
    spawner = FakeSpawner()
    agent = make_agent(settings, FakeCore(None), spawner)

    await agent.start()

    assert spawner.processes == []


async def test_run_until_stopped(settings):
    core = FakeCore(core_config([("cam1", 1, True)]))
    spawner = FakeSpawner()
    agent = make_agent(settings, core, spawner)
    stop = asyncio.Event()

    task = asyncio.create_task(agent.run(stop))
    await until(lambda: len(spawner.processes) == 1)
    core.config = core_config([("cam2", 1, True)], version="sha256:v2")
    await until(lambda: len(spawner.processes) == 2)  # picked up by polling
    stop.set()
    await asyncio.wait_for(task, 2)

    assert all(p.returncode is not None for p in spawner.processes)
