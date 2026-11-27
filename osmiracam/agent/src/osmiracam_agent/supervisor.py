"""Runs ptzview as a child process: restarts it if it dies, on demand
(new configuration), and stops it cleanly when the agent exits."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Protocol

log = logging.getLogger(__name__)


class Process(Protocol):
    """What we need from asyncio.subprocess.Process (faked in tests)."""

    returncode: int | None

    async def wait(self) -> int: ...
    def send_signal(self, sig: int) -> None: ...
    def kill(self) -> None: ...


Spawner = Callable[[], Awaitable[Process]]


def ptzview_spawner(binary: str, conf_path: str) -> Spawner:
    async def spawn() -> Process:
        # stdin closed: ptzview must never wait for keyboard input.
        return await asyncio.create_subprocess_exec(
            binary, conf_path, stdin=asyncio.subprocess.DEVNULL
        )

    return spawn


class Supervisor:
    def __init__(self, spawn: Spawner, restart_delay_s: float, stop_timeout_s: float) -> None:
        self._spawn = spawn
        self._restart_delay_s = restart_delay_s
        self._stop_timeout_s = stop_timeout_s
        self._process: Process | None = None
        self._stopping = False
        self._restart_requested = False
        self._task: asyncio.Task[None] | None = None
        self.starts = 0  # number of launches, useful for tests and logs

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.running:
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="ptzview-supervisor")

    async def restart(self) -> None:
        """Stop the current ptzview; the loop starts it again at once."""
        if not self.running:
            self.start()
            return
        self._restart_requested = True
        await self._terminate()

    async def stop(self) -> None:
        self._stopping = True
        await self._terminate()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stopping:
            try:
                self._process = await self._spawn()
            except OSError as exc:
                log.error("cannot start ptzview: %s", exc)
                await asyncio.sleep(self._restart_delay_s)
                continue
            self.starts += 1
            code = await self._process.wait()
            if self._stopping:
                break
            if self._restart_requested:
                self._restart_requested = False
                log.info("ptzview restarted for a new configuration")
                continue
            log.warning(
                "ptzview exited (code %s), restarting in %.0f s", code, self._restart_delay_s
            )
            await asyncio.sleep(self._restart_delay_s)

    async def _terminate(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        # SIGINT = Ctrl+C: ptzview releases the screen and decoders cleanly.
        process.send_signal(signal.SIGINT)
        try:
            await asyncio.wait_for(process.wait(), self._stop_timeout_s)
        except TimeoutError:
            log.warning("ptzview did not stop within %.0f s, killing it", self._stop_timeout_s)
            process.kill()
            await process.wait()
