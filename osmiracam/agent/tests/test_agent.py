"""The agent with a fake Core and a fake ptzview (httpx2 MockTransport), and a
fake ptzview process."""

import asyncio
import json
from urllib.parse import parse_qsl

import httpx2
import pytest
from conftest import FakeSpawner, core_config, until

from osmiracam_agent.agent import Agent
from osmiracam_agent.core_client import CoreClient, CoreEvent
from osmiracam_agent.ptzview_client import PtzviewClient
from osmiracam_agent.station_config import ConfigStore, SelectionStore
from osmiracam_agent.supervisor import Supervisor

pytestmark = pytest.mark.anyio

TWO_CAMS = [("cam1", 1, True), ("cam2", 2, True)]


class FakeCore:
    """Serves a configuration that tests can change, an event stream tests can
    feed, or pretends to be down."""

    def __init__(self, config: dict | None) -> None:
        self.config = config
        self.down = False
        self.connections = 0
        self.statuses: list[dict] = []
        self.unknown_station = False
        self._stream: asyncio.Queue[bytes | None] | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if self.down or self.config is None:
            raise httpx2.ConnectError("connection refused")
        if request.url.path.endswith("/events"):
            return self._events()
        if request.url.path.endswith("/status"):
            if self.unknown_station:
                return httpx2.Response(404, json={"detail": "station 'panelTest' not found"})
            self.statuses.append(json.loads(request.content))
            return httpx2.Response(204)
        etag = f'"{self.config["version"]}"'
        if request.headers.get("if-none-match") == etag:
            return httpx2.Response(304, headers={"ETag": etag})
        return httpx2.Response(200, json=self.config, headers={"ETag": etag})

    def _events(self) -> httpx2.Response:
        self.connections += 1
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._stream = queue

        async def body():
            while (chunk := await queue.get()) is not None:
                yield chunk

        return httpx2.Response(200, headers={"Content-Type": "text/event-stream"}, content=body())

    def push(self, name: str, data: dict) -> None:
        assert self._stream is not None, "no client connected"
        self._stream.put_nowait(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())

    def close_stream(self) -> None:
        assert self._stream is not None
        self._stream.put_nowait(None)


class FakePtzview:
    """ptzview's local HTTP API: records switches, can be down (restarting)."""

    def __init__(self) -> None:
        self.selects: list[int] = []
        self.inputs: list[tuple[int, str]] = []  # (slot, url) set live
        self.labels: list[tuple[int, str]] = []
        self.down = False
        self.old_version = False  # ptzview without /input

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("connection refused")
        path = request.url.path
        if path == "/status":
            return httpx2.Response(200, json=PTZVIEW_STATUS)
        slot = int(path.rsplit("/", 1)[1])
        form = dict(parse_qsl(request.content.decode(), keep_blank_values=True))
        if path.startswith("/input/"):
            if self.old_version:
                return httpx2.Response(404, json={"ok": False})
            self.inputs.append((slot, form["url"]))
        elif path.startswith("/label/"):
            self.labels.append((slot, form["text"]))
        else:
            self.selects.append(slot)
        return httpx2.Response(200, json={})


def ptz_cam(n: int, fps: float) -> dict:
    return {
        "cam": n,
        "label": f"CAM{n}",
        "tally": "off",
        "state": "streaming",
        "connected": True,
        "signal": True,
        "fps": fps,
        "mbps": 16.2,
        "width": 1920,
        "height": 1080,
        "connects": 1,
        "decode_errors": 3,
        "last_error": "",
    }


# ptzview /status with cam2 on screen; inputs 3 and 4 are free.
PTZVIEW_STATUS = {
    "ok": True,
    "active": 2,
    "cameras": [ptz_cam(1, 49.9), ptz_cam(2, 50.0), ptz_cam(3, 0), ptz_cam(4, 0)],
    "system": {
        "mem_available_kb": 461728,
        "cma_total_kb": 524288,
        "cma_free_kb": 73412,
        "temp_c": 51.6,
    },
}


def make_agent(settings, core: FakeCore, spawner: FakeSpawner, ptzview: FakePtzview | None = None):
    core_http = httpx2.AsyncClient(
        base_url="http://core.test", transport=httpx2.MockTransport(core.handler)
    )
    ptzview = ptzview or FakePtzview()
    local_http = httpx2.AsyncClient(
        base_url="http://127.0.0.1:8081", transport=httpx2.MockTransport(ptzview.handler)
    )
    return Agent(
        settings,
        CoreClient(core_http, "panelTest"),
        ConfigStore(settings.state_dir),
        Supervisor(spawner, restart_delay_s=0.01, stop_timeout_s=0.1),
        PtzviewClient(local_http),
        SelectionStore(settings.state_dir),
        hardware={"model": "Raspberry Pi 4 Model B Rev 1.5", "ram_mb": 905},
    )


def start_camera(settings) -> str:
    for line in settings.ptzview.conf_path.read_text().splitlines():
        if line.startswith("start_camera"):
            return line.split("=")[1].strip()
    raise AssertionError("no start_camera")


# --- configuration (polling) ----------------------------------------------------


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


async def test_new_camera_only_touches_its_input(settings):
    core = FakeCore(core_config([("cam1", 1, True)]))
    spawner, ptzview = FakeSpawner(), FakePtzview()
    agent = make_agent(settings, core, spawner, ptzview)
    await agent.refresh()
    await until(lambda: len(spawner.processes) == 1)

    core.config = core_config(TWO_CAMS, version="sha256:v2")
    assert await agent.refresh() is True

    await asyncio.sleep(0.05)
    assert len(spawner.processes) == 1  # no restart: the picture is not cut
    assert ptzview.inputs == [(2, settings_url("cam2"))]
    assert ptzview.labels == [(2, "CAM2")]
    assert "read:cam2" in settings.ptzview.conf_path.read_text()  # for the next start


def settings_url(camera_id: str) -> str:
    return f"srt://192.168.104.253:8890?mode=caller&streamid=read:{camera_id}:::station=panelTest"


async def test_removed_camera_disables_its_input_only(settings):
    four = [("cam1", 1, True), ("cam2", 2, True), ("cam3", 3, True), ("cam4", 4, True)]
    core = FakeCore(core_config(four))
    spawner, ptzview = FakeSpawner(), FakePtzview()
    agent = make_agent(settings, core, spawner, ptzview)
    await agent.refresh()
    await until(lambda: len(spawner.processes) == 1)

    core.config = core_config([c for c in four if c[0] != "cam3"], version="sha256:v2")
    await agent.refresh()

    assert ptzview.inputs == [(3, "")]  # cam4 stays in input 4
    assert agent.assignment == ["cam1", "cam2", None, "cam4"]
    assert len(spawner.processes) == 1


async def test_new_camera_takes_the_free_input(settings):
    core = FakeCore(core_config([("cam1", 1, True), ("cam4", 4, True)]))
    agent = make_agent(settings, core, FakeSpawner(), FakePtzview())
    await agent.refresh()

    core.config = core_config(
        [("cam1", 1, True), ("cam5", 2, True), ("cam4", 4, True)], "sha256:v2"
    )
    await agent.refresh()

    assert agent.assignment == ["cam1", "cam4", "cam5", None]


async def test_latency_change_restarts_ptzview(settings):
    core = FakeCore(core_config(TWO_CAMS))
    spawner = FakeSpawner()
    agent = make_agent(settings, core, spawner, FakePtzview())
    await agent.refresh()
    await until(lambda: len(spawner.processes) == 1)

    data = core_config(TWO_CAMS, version="sha256:v2")
    data["cameras"][0]["media"]["latency_ms"] = 40
    core.config = data
    await agent.refresh()

    await until(lambda: len(spawner.processes) == 2)


async def test_old_ptzview_without_input_route_is_restarted(settings):
    core = FakeCore(core_config([("cam1", 1, True)]))
    spawner, ptzview = FakeSpawner(), FakePtzview()
    ptzview.old_version = True
    agent = make_agent(settings, core, spawner, ptzview)
    await agent.refresh()
    await until(lambda: len(spawner.processes) == 1)

    core.config = core_config(TWO_CAMS, version="sha256:v2")
    await agent.refresh()

    await until(lambda: len(spawner.processes) == 2)


async def test_inputs_survive_an_agent_restart(settings):
    core = FakeCore(core_config([("cam1", 1, True), ("cam4", 4, True)]))
    first = make_agent(settings, core, FakeSpawner(), FakePtzview())
    await first.refresh()
    core.config = core_config([("cam4", 4, True)], "sha256:v2")
    await first.refresh()

    second = make_agent(settings, FakeCore(None), FakeSpawner(), FakePtzview())
    await second.start()

    assert second.assignment == [None, "cam4", None, None]


async def test_core_down_at_boot_uses_local_copies(settings):
    ConfigStore(settings.state_dir).save(core_config(TWO_CAMS))
    SelectionStore(settings.state_dir).save("cam2")
    spawner = FakeSpawner()
    agent = make_agent(settings, FakeCore(None), spawner)

    await agent.start()
    assert await agent.refresh() is False

    await until(lambda: len(spawner.processes) == 1)
    assert "read:cam1" in settings.ptzview.conf_path.read_text()
    assert start_camera(settings) == "2"  # last camera chosen by the Core


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


# --- events from the Core -------------------------------------------------------


async def test_select_event_switches_ptzview(settings):
    ptzview = FakePtzview()
    agent = make_agent(settings, FakeCore(core_config(TWO_CAMS)), FakeSpawner(), ptzview)
    await agent.refresh()

    await agent.on_event(CoreEvent("select", {"output": 1, "camera_id": "cam2"}))

    await until(lambda: ptzview.selects == [2])
    assert SelectionStore(settings.state_dir).load() == "cam2"


async def test_select_null_shows_first_viewable_camera(settings):
    ptzview = FakePtzview()
    config = core_config([("cam1", 1, False), ("cam2", 2, True)])
    agent = make_agent(settings, FakeCore(config), FakeSpawner(), ptzview)
    await agent.refresh()

    await agent.on_event(CoreEvent("select", {"output": 1, "camera_id": None}))

    await until(lambda: ptzview.selects == [2])


async def test_other_outputs_are_ignored(settings):
    ptzview = FakePtzview()
    agent = make_agent(settings, FakeCore(core_config(TWO_CAMS)), FakeSpawner(), ptzview)
    await agent.refresh()

    await agent.on_event(CoreEvent("select", {"output": 2, "camera_id": "cam2"}))
    await asyncio.sleep(0.05)

    assert ptzview.selects == []


async def test_select_waits_for_ptzview_to_be_ready(settings):
    ptzview = FakePtzview()
    ptzview.down = True  # still starting
    agent = make_agent(settings, FakeCore(core_config(TWO_CAMS)), FakeSpawner(), ptzview)
    await agent.refresh()

    await agent.on_event(CoreEvent("select", {"output": 1, "camera_id": "cam2"}))
    await asyncio.sleep(0.1)
    ptzview.down = False

    await until(lambda: ptzview.selects == [2])


async def test_latest_select_wins(settings):
    ptzview = FakePtzview()
    ptzview.down = True
    agent = make_agent(settings, FakeCore(core_config(TWO_CAMS)), FakeSpawner(), ptzview)
    await agent.refresh()

    await agent.on_event(CoreEvent("select", {"output": 1, "camera_id": "cam2"}))
    await agent.on_event(CoreEvent("select", {"output": 1, "camera_id": "cam1"}))
    ptzview.down = False

    await until(lambda: ptzview.selects == [1])
    await asyncio.sleep(0.6)  # the cancelled switch to cam2 never comes
    assert ptzview.selects == [1]


async def test_new_config_keeps_the_selected_camera(settings):
    core = FakeCore(core_config(TWO_CAMS))
    ptzview = FakePtzview()
    agent = make_agent(settings, core, FakeSpawner(), ptzview)
    await agent.refresh()
    await agent.on_event(CoreEvent("select", {"output": 1, "camera_id": "cam2"}))

    core.config = core_config([("cam3", 1, True), *TWO_CAMS[:1], ("cam2", 3, True)], "sha256:v2")
    await agent.on_event(CoreEvent("config_changed", {"version": "sha256:v2"}))

    assert agent.config.version == "sha256:v2"
    assert agent.assignment[:3] == ["cam1", "cam2", "cam3"]  # cam2 did not move
    assert start_camera(settings) == "2"
    await until(lambda: ptzview.selects[-1:] == [2])


async def test_state_event_syncs_config_and_selection(settings):
    ptzview = FakePtzview()
    core = FakeCore(core_config(TWO_CAMS, version="sha256:v2"))
    ConfigStore(settings.state_dir).save(core_config([("cam1", 1, True)]))  # older copy
    agent = make_agent(settings, core, FakeSpawner(), ptzview)
    await agent.start()

    state = {"config_version": "sha256:v2", "selections": [{"output": 1, "camera_id": "cam2"}]}
    await agent.on_event(CoreEvent("state", state))

    assert agent.config.version == "sha256:v2"
    await until(lambda: ptzview.selects[-1:] == [2])


async def test_full_run_with_event_stream(settings):
    """Real loops: the event stream drives ptzview and reconnects after a break."""
    core = FakeCore(core_config(TWO_CAMS))
    ptzview = FakePtzview()
    spawner = FakeSpawner()
    agent = make_agent(settings, core, spawner, ptzview)
    stop = asyncio.Event()
    task = asyncio.create_task(agent.run(stop))

    await until(lambda: core.connections == 1 and len(spawner.processes) == 1)
    core.push("select", {"output": 1, "camera_id": "cam2"})
    await until(lambda: ptzview.selects[-1:] == [2])

    core.close_stream()  # Core restarted, or network cut
    await until(lambda: core.connections == 2)
    core.push("select", {"output": 1, "camera_id": "cam1"})
    await until(lambda: ptzview.selects[-1:] == [1])

    stop.set()
    await asyncio.wait_for(task, 2)
    assert all(p.returncode is not None for p in spawner.processes)


# --- status report (heartbeat) ------------------------------------------------


async def test_status_before_any_configuration(settings):
    agent = make_agent(settings, FakeCore(None), FakeSpawner())

    status = await agent.status()

    assert status["config_version"] is None
    assert status["player"] == {"running": False, "shown_camera": None, "cameras": []}
    assert status["hardware"]["model"].startswith("Raspberry Pi 4")
    assert status["agent_version"] and status["hostname"]


async def test_status_maps_ptzview_inputs_to_cameras(settings):
    spawner = FakeSpawner()
    agent = make_agent(settings, FakeCore(core_config(TWO_CAMS)), spawner)
    await agent.refresh()
    await until(lambda: len(spawner.processes) == 1)

    status = await agent.status()

    assert status["config_version"] == "sha256:v1"
    assert status["player"]["running"] is True
    assert status["player"]["shown_camera"] == "cam2"
    cams = status["player"]["cameras"]
    assert [c["camera_id"] for c in cams] == ["cam1", "cam2"]  # free inputs left out
    assert cams[0]["fps"] == 49.9 and cams[0]["width"] == 1920 and cams[0]["decode_errors"] == 3
    assert status["system"]["cma_free_mb"] == 71
    assert status["system"]["temp_c"] == 51.6


async def test_run_reports_status_regularly(settings):
    core = FakeCore(core_config(TWO_CAMS))
    agent = make_agent(settings, core, FakeSpawner())
    stop = asyncio.Event()
    task = asyncio.create_task(agent.run(stop))

    await until(lambda: len(core.statuses) >= 3)  # status_interval_s is short in tests
    stop.set()
    await asyncio.wait_for(task, 2)

    assert core.statuses[-1]["config_version"] == "sha256:v1"


async def test_unknown_station_is_logged_once(settings, caplog):
    core = FakeCore(core_config(TWO_CAMS))
    core.unknown_station = True
    agent = make_agent(settings, core, FakeSpawner())
    stop = asyncio.Event()

    task = asyncio.create_task(agent.report(stop))
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(task, 2)

    refused = [r for r in caplog.records if "status not delivered" in r.message]
    assert len(refused) == 1
    assert "404" in refused[0].message
