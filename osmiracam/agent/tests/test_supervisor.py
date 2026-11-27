import signal

import pytest
from conftest import FakeSpawner, until

from osmiracam_agent.supervisor import Supervisor

pytestmark = pytest.mark.anyio


def make(spawner: FakeSpawner) -> Supervisor:
    return Supervisor(spawner, restart_delay_s=0.01, stop_timeout_s=0.1)


async def test_start_and_stop_cleanly():
    spawner = FakeSpawner()
    supervisor = make(spawner)

    supervisor.start()
    await until(lambda: supervisor.starts == 1)
    await supervisor.stop()

    assert spawner.processes[0].signals == [signal.SIGINT]
    assert not supervisor.running


async def test_crash_is_restarted():
    spawner = FakeSpawner()
    supervisor = make(spawner)
    supervisor.start()
    await until(lambda: supervisor.starts == 1)

    spawner.processes[0].exit(1)  # ptzview crashes

    await until(lambda: supervisor.starts == 2)
    await supervisor.stop()


async def test_restart_on_demand():
    spawner = FakeSpawner()
    supervisor = make(spawner)
    supervisor.start()
    await until(lambda: supervisor.starts == 1)

    await supervisor.restart()

    await until(lambda: supervisor.starts == 2)
    assert spawner.processes[0].signals == [signal.SIGINT]
    await supervisor.stop()


async def test_kill_if_sigint_is_ignored():
    spawner = FakeSpawner(ignore_sigint=True)
    supervisor = make(spawner)
    supervisor.start()
    await until(lambda: supervisor.starts == 1)

    await supervisor.stop()

    assert spawner.processes[0].killed


async def test_missing_binary_keeps_retrying():
    attempts = []

    async def broken_spawn():
        attempts.append(1)
        raise FileNotFoundError("ptzview")

    supervisor = Supervisor(broken_spawn, restart_delay_s=0.01, stop_timeout_s=0.1)
    supervisor.start()

    await until(lambda: len(attempts) >= 3)
    await supervisor.stop()
