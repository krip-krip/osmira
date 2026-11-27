"""Main loop: keep ptzview running with the latest station configuration.

- At start, use the local copy of the last configuration (if any), so the
  station shows pictures even when the Core is unreachable.
- Then ask the Core for a newer configuration every poll_interval_s
  (If-None-Match: a 304 costs almost nothing). The SSE stream will make this
  immediate in a later step; polling stays as a fallback.
- A new configuration rewrites ptzview.conf and restarts ptzview.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from osmiracam_agent import ptzview_conf
from osmiracam_agent.core_client import CoreClient, CoreUnavailable
from osmiracam_agent.settings import Settings
from osmiracam_agent.station_config import ConfigStore, StationConfig
from osmiracam_agent.supervisor import Supervisor

log = logging.getLogger(__name__)


class Agent:
    def __init__(
        self, settings: Settings, core: CoreClient, store: ConfigStore, supervisor: Supervisor
    ) -> None:
        self._settings = settings
        self._core = core
        self._store = store
        self._supervisor = supervisor
        self._core_reachable: bool | None = None
        self.config: StationConfig | None = None

    async def start(self) -> None:
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

    async def run(self, stop: asyncio.Event) -> None:
        await self.start()
        while not stop.is_set():
            await self.refresh()
            try:
                await asyncio.wait_for(stop.wait(), self._settings.poll_interval_s)
            except TimeoutError:
                pass
        log.info("stopping")
        await self._supervisor.stop()

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
        _write_atomic(ptz.conf_path, ptzview_conf.render(config, ptz))
        self.config = config
        if self._supervisor.running:
            await self._supervisor.restart()
        else:
            self._supervisor.start()


def _write_atomic(path: Path, text: str) -> None:
    """Write then rename: ptzview never reads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
