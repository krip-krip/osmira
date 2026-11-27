"""Command line entry point: uv run osmiracam-agent -c agent.toml"""

import argparse
import asyncio
import logging
import signal
from pathlib import Path

import httpx2

from osmiracam_agent import __version__
from osmiracam_agent.agent import Agent
from osmiracam_agent.core_client import CoreClient
from osmiracam_agent.settings import Settings, load_settings
from osmiracam_agent.station_config import ConfigStore
from osmiracam_agent.supervisor import Supervisor, ptzview_spawner


async def run(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    ptz = settings.ptzview
    supervisor = Supervisor(
        ptzview_spawner(str(ptz.binary), str(ptz.conf_path)),
        restart_delay_s=ptz.restart_delay_s,
        stop_timeout_s=ptz.stop_timeout_s,
    )
    async with httpx2.AsyncClient(
        base_url=settings.core_url, timeout=settings.request_timeout_s
    ) as http:
        agent = Agent(
            settings,
            CoreClient(http, settings.station_id),
            ConfigStore(settings.state_dir),
            supervisor,
        )
        await agent.run(stop)


def main() -> None:
    parser = argparse.ArgumentParser(description="OsmiraCam station agent")
    parser.add_argument(
        "-c", "--config", type=Path, default=Path("agent.toml"), help="settings file (TOML)"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # One line per request every poll_interval_s would flood the journal.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    settings = load_settings(args.config)
    logging.getLogger(__name__).info(
        "osmiracam-agent %s, station %s, Core %s",
        __version__,
        settings.station_id,
        settings.core_url,
    )
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
