"""Main loop: keep ptzview running with the latest station configuration and
show the camera chosen in the Core's matrix (ADR 0009).

- At start, use the local copies of the last configuration and selection, so
  the station shows pictures even when the Core is unreachable.
- Listen to the Core's event stream (SSE): "select" switches ptzview at once,
  "config_changed" fetches the new configuration. The stream is reopened
  after any break.
- Also ask the Core for a newer configuration every poll_interval_s, as a
  fallback (If-None-Match: a 304 costs almost nothing).
- A new configuration rewrites ptzview.conf and restarts ptzview, which then
  starts on the selected camera.
"""

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import Any

from osmiracam_agent import __version__, ptzview_conf, station_info
from osmiracam_agent.core_client import CoreClient, CoreEvent, CoreUnavailable
from osmiracam_agent.ptzview_client import PtzviewClient, PtzviewUnavailable
from osmiracam_agent.settings import Settings
from osmiracam_agent.station_config import ConfigStore, SelectionStore, SlotsStore, StationConfig
from osmiracam_agent.supervisor import Supervisor

log = logging.getLogger(__name__)

# ptzview has a single video output for now.
OUTPUT = 1
SELECT_RETRY_INTERVAL_S = 0.5


class Agent:
    def __init__(
        self,
        settings: Settings,
        core: CoreClient,
        store: ConfigStore,
        supervisor: Supervisor,
        ptzview: PtzviewClient,
        selection_store: SelectionStore,
        hardware: dict[str, object] | None = None,
    ) -> None:
        self._settings = settings
        self._core = core
        self._store = store
        self._supervisor = supervisor
        self._ptzview = ptzview
        self._selection_store = selection_store
        self._hardware = hardware if hardware is not None else station_info.hardware()
        self._status_error: str | None = None
        self._refresh_lock = asyncio.Lock()
        self._select_task: asyncio.Task[None] | None = None
        self._core_reachable: bool | None = None
        self._events_connected: bool | None = None
        self.config: StationConfig | None = None
        # Camera chosen by the Core for our output (None: no choice).
        self.selected: str | None = None
        # Last ptzview input successfully switched to (for logs and tests).
        self.shown_slot: int | None = None
        # Camera id in each ptzview input (stable across configuration changes).
        self.assignment: list[str | None] | None = None
        self._slots_store = SlotsStore(settings.state_dir)

    # --- start and configuration ----------------------------------------------

    async def start(self) -> None:
        self.selected = self._selection_store.load()
        self.assignment = self._slots_store.load()
        stored = self._store.load()
        if stored is None:
            log.info("no local configuration yet: waiting for the Core")
        elif stored["station"]["id"] != self._settings.station_id:
            log.warning("local configuration belongs to another station: ignored")
        else:
            log.info("starting from the local configuration %s", stored["version"])
            await self._apply(stored)

    async def refresh(self) -> bool:
        """Ask the Core for a newer configuration. True if one was applied."""
        async with self._refresh_lock:  # polling and SSE may ask at the same time
            known = self.config.version if self.config else None
            try:
                data = await self._core.fetch_config(known)
            except CoreUnavailable as exc:
                if self._core_reachable is not False:  # log once per outage
                    log.warning("%s; keeping the current configuration", exc)
                self._core_reachable = False
                return False
            if self._core_reachable is False:
                log.info("Core reachable again")
            self._core_reachable = True
            if data is None or data["version"] == known:
                return False
            log.info("new configuration %s from the Core", data["version"])
            self._store.save(data)
            await self._apply(data)
            return True

    async def _apply(self, data: dict[str, Any]) -> None:
        config = StationConfig.from_json(data)
        ptz = self._settings.ptzview
        if len(config.cameras) > ptz.slots:
            log.warning(
                "%d cameras in the configuration, ptzview has %d inputs: only the first %d shown",
                len(config.cameras),
                ptz.slots,
                ptz.slots,
            )
        tag = self._settings.tag_srt_streamid
        old_config, old_assignment = self.config, self.assignment
        assignment = ptzview_conf.assign_slots(config, ptz.slots, old_assignment)
        text = ptzview_conf.render(config, ptz, self.selected, tag, assignment)
        _write_atomic(ptz.conf_path, text)  # for the next start of ptzview
        self.config, self.assignment = config, assignment
        self._slots_store.save(assignment)

        if not self._supervisor.running:
            self._supervisor.start()
            return
        if old_config is None or ptzview_conf.general(
            old_config, ptz, old_assignment
        ) != ptzview_conf.general(config, ptz, assignment):
            log.info("ptzview settings changed: restarting it")
            await self._supervisor.restart()
            return
        # Only the inputs that changed, without disturbing the picture on screen.
        before = ptzview_conf.slot_inputs(old_config, ptz.slots, old_assignment, tag)
        after = ptzview_conf.slot_inputs(config, ptz.slots, assignment, tag)
        try:
            for slot, (old, new) in enumerate(zip(before, after, strict=True), start=1):
                if new[0] != old[0]:
                    await self._ptzview.set_input(slot, new[0])
                    log.info("input %d: %s", slot, new[0] or "disabled")
                if new[1] != old[1]:
                    await self._ptzview.set_label(slot, new[1])
        except PtzviewUnavailable as exc:
            log.warning("cannot update ptzview inputs live (%s): restarting it", exc)
            await self._supervisor.restart()
            return
        # The shown camera may have left: show the camera chosen by the Core again.
        await self.select(self.selected)

    # --- selection --------------------------------------------------------------

    async def select(self, camera_id: str | None) -> None:
        """Show the camera chosen by the Core (None: first viewable camera)."""
        if camera_id != self.selected:
            self.selected = camera_id
            self._selection_store.save(camera_id)
        if self.config is None:
            return  # applied as start_camera once a configuration arrives
        slots = self._settings.ptzview.slots
        slot = ptzview_conf.display_slot(self.config, slots, camera_id, self.assignment)
        if camera_id is not None and camera_id not in (self.assignment or []):
            log.warning(
                "camera '%s' is not among the ptzview inputs: showing input %d", camera_id, slot
            )
        # Latest choice wins: drop a switch still waiting for ptzview.
        if self._select_task is not None:
            self._select_task.cancel()
        self._select_task = asyncio.create_task(self._push_select(slot), name="ptzview-select")

    async def _push_select(self, slot: int) -> None:
        """Switch ptzview, retrying while it is (re)starting."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.ptzview.select_retry_s
        while True:
            try:
                await self._ptzview.select(slot)
            except PtzviewUnavailable as exc:
                if loop.time() >= deadline:
                    log.warning("could not switch ptzview to input %d: %s", slot, exc)
                    return
                await asyncio.sleep(SELECT_RETRY_INTERVAL_S)
            else:
                self.shown_slot = slot
                log.info("showing input %d (%s)", slot, self.selected or "first viewable camera")
                return

    # --- events from the Core ---------------------------------------------------

    async def on_event(self, event: CoreEvent) -> None:
        current = self.config.version if self.config else None
        if event.name == "state":
            if event.data.get("config_version") != current:
                await self.refresh()
            for item in event.data.get("selections", []):
                if item.get("output") == OUTPUT:
                    await self.select(item.get("camera_id"))
        elif event.name == "select":
            if event.data.get("output") == OUTPUT:
                await self.select(event.data.get("camera_id"))
        elif event.name == "config_changed":
            if event.data.get("version") != current:
                await self.refresh()
        else:
            log.debug("ignoring unknown event %s", event.name)

    async def listen(self, stop: asyncio.Event) -> None:
        """Follow the event stream, reopening it after any break."""
        while not stop.is_set():
            try:
                async for event in self._core.events():
                    if not self._events_connected:
                        log.info("event stream connected")
                        self._events_connected = True
                    await self.on_event(event)
                raise CoreUnavailable("event stream closed by the Core")
            except CoreUnavailable as exc:
                if self._events_connected is not False:  # log once per outage
                    log.warning("%s; retrying every %.0f s", exc, self._settings.events_retry_s)
                self._events_connected = False
            await _wait(stop, self._settings.events_retry_s)

    # --- status report (heartbeat) ----------------------------------------------

    async def status(self) -> dict[str, Any]:
        """What the Core shows about this station (see docs/api.md)."""
        player: dict[str, Any] = {"running": self._supervisor.running, "shown_camera": None}
        cameras: list[dict[str, Any]] = []
        system: dict[str, Any] = {
            "uptime_s": station_info.uptime_s(),
            "temp_c": station_info.temperature_c(),
        }
        ptz_status = None
        if self._supervisor.running:
            with contextlib.suppress(PtzviewUnavailable):
                ptz_status = await self._ptzview.status()
        if ptz_status is not None and self.config is not None:
            slots = ptzview_conf.slot_cameras(
                self.config, self._settings.ptzview.slots, self.assignment
            )
            for entry in ptz_status.get("cameras", []):
                index = int(entry.get("cam", 0)) - 1
                camera = slots[index] if 0 <= index < len(slots) else None
                if camera is None:
                    continue  # free input
                if entry.get("cam") == ptz_status.get("active"):
                    player["shown_camera"] = camera.id
                cameras.append(
                    {
                        "camera_id": camera.id,
                        **{
                            key: entry.get(key)
                            for key in (
                                "state",
                                "fps",
                                "mbps",
                                "width",
                                "height",
                                "connects",
                                "decode_errors",
                                "last_error",
                            )
                        },
                    }
                )
            ptz_system = ptz_status.get("system", {})
            system.update(
                {
                    "temp_c": ptz_system.get("temp_c", system["temp_c"]),
                    "mem_available_mb": ptz_system.get("mem_available_kb", 0) // 1024,
                    "cma_free_mb": ptz_system.get("cma_free_kb", 0) // 1024,
                    "cma_total_mb": ptz_system.get("cma_total_kb", 0) // 1024,
                }
            )
        player["cameras"] = cameras
        return {
            "agent_version": __version__,
            "hostname": station_info.hostname(),
            "addresses": station_info.addresses(),
            "config_version": self.config.version if self.config else None,
            "selected_camera": self.selected,
            "player": player,
            "hardware": self._hardware,
            "system": system,
        }

    async def report(self, stop: asyncio.Event) -> None:
        """Send the status every status_interval_s: the Core's heartbeat."""
        while not stop.is_set():
            try:
                await self._core.post_status(await self.status())
            except CoreUnavailable as exc:
                if str(exc) != self._status_error:  # log each new problem once
                    log.warning("status not delivered: %s", exc)
                self._status_error = str(exc)
            else:
                self._status_error = None
            await _wait(stop, self._settings.status_interval_s)

    # --- main loop ----------------------------------------------------------------

    async def poll(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.refresh()
            await _wait(stop, self._settings.poll_interval_s)

    async def run(self, stop: asyncio.Event) -> None:
        await self.start()
        tasks = [
            asyncio.create_task(self.poll(stop), name="poll"),
            asyncio.create_task(self.listen(stop), name="events"),
            asyncio.create_task(self.report(stop), name="status"),
        ]
        await stop.wait()
        log.info("stopping")
        for task in [*tasks, self._select_task]:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await self._supervisor.stop()


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake up at once when the agent stops."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)


def _write_atomic(path: Path, text: str) -> None:
    """Write then rename: ptzview never reads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
