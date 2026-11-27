import asyncio
from pathlib import Path

import pytest

from osmiracam_agent.settings import PtzviewSettings, Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


def core_config(cameras: list[tuple[str, int, bool]], version: str = "sha256:v1") -> dict:
    """Configuration as sent by OsmiraCore: cameras = [(id, position, view), ...]."""
    return {
        "station": {"id": "panelTest", "label": "Cadreur 1", "max_decoders": 4, "outputs": 1},
        "version": version,
        "cameras": [
            {
                "id": camera_id,
                "label": camera_id.upper(),
                "position": position,
                "rights": {"decode": True, "view": view, "control": False},
                "media": {
                    "srt_url": f"srt://192.168.104.253:8890?mode=caller&streamid=read:{camera_id}",
                    "latency_ms": 20,
                    "codec": "hevc",
                    "width": 1920,
                    "height": 1080,
                    "fps": 50,
                },
            }
            for camera_id, position, view in cameras
        ],
    }


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        core_url="http://core.test",
        station_id="panelTest",
        state_dir=tmp_path / "state",
        poll_interval_s=0.01,
        events_retry_s=0.01,
        ptzview=PtzviewSettings(
            binary=tmp_path / "ptzview",
            conf_path=tmp_path / "state" / "ptzview.conf",
            restart_delay_s=0.01,
            stop_timeout_s=0.2,
            select_retry_s=1.0,
            general={"hdmi_mode": "1920x1080@50"},
        ),
    )


class FakeProcess:
    """Stands for a running ptzview. Ends on SIGINT unless told to ignore it."""

    def __init__(self, ignore_sigint: bool = False) -> None:
        self.returncode: int | None = None
        self.signals: list[int] = []
        self.killed = False
        self._ignore_sigint = ignore_sigint
        self._done = asyncio.Event()

    async def wait(self) -> int:
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        if not self._ignore_sigint:
            self.exit(0)

    def kill(self) -> None:
        self.killed = True
        self.exit(-9)

    def exit(self, code: int) -> None:
        """Simulate ptzview ending on its own (crash, or clean exit)."""
        if self.returncode is None:
            self.returncode = code
            self._done.set()


class FakeSpawner:
    def __init__(self, ignore_sigint: bool = False) -> None:
        self.processes: list[FakeProcess] = []
        self._ignore_sigint = ignore_sigint

    async def __call__(self) -> FakeProcess:
        process = FakeProcess(self._ignore_sigint)
        self.processes.append(process)
        return process


async def until(condition, timeout: float = 2.0) -> None:
    """Wait for a condition set by background tasks."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)
