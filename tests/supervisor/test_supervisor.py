"""Tasks 3.1, 3.3-3.9."""

from __future__ import annotations

import asyncio

import pytest

from cobble.settings import Settings
from cobble.supervisor.shutdown_record import load_last_shutdown
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import (
    AlreadyRunningError,
    NoInstallationError,
    ReadinessTimeoutError,
    Supervisor,
)

pytestmark = pytest.mark.asyncio


async def _stop_quietly(sup: Supervisor) -> None:
    if sup.state in (RunState.STARTING, RunState.RUNNING, RunState.STOPPING):
        await sup.stop()


async def test_start_spawns_process_and_output_is_readable(make_supervisor) -> None:
    # 3.1 the process starts and its output is readable
    lines: list[str] = []
    sup: Supervisor = make_supervisor(line_sink=lines.append)
    await sup.start()
    assert sup.state is RunState.RUNNING
    assert any("Server started." in line for line in lines)
    await sup.stop()


async def test_concurrent_starts_spawn_one_process(make_supervisor) -> None:
    # 3.2 concurrent start requests spawn only one process; the second fails
    sup: Supervisor = make_supervisor(readiness_timeout=3.0)
    results = await asyncio.gather(sup.start(), sup.start(), return_exceptions=True)
    ok = [r for r in results if r is None]
    errs = [r for r in results if isinstance(r, Exception)]
    assert len(ok) == 1
    assert len(errs) == 1 and isinstance(errs[0], AlreadyRunningError)
    await sup.stop()


async def test_start_without_installation_fails(tmp_settings: Settings) -> None:
    # 3.1 / lifecycle: no installation present
    sup = Supervisor(tmp_settings)
    with pytest.raises(NoInstallationError):
        await sup.start()
    assert sup.state is RunState.STOPPED


async def test_readiness_timeout_moves_to_failed_and_retains_output(make_supervisor) -> None:
    # 3.3 a server that never signals readiness ends in failed, output retrievable
    sup: Supervisor = make_supervisor(readiness_timeout=1.0)
    import os

    os.environ["FAKE_BDS_NEVER_READY"] = "1"
    try:
        with pytest.raises(ReadinessTimeoutError):
            await sup.start()
    finally:
        os.environ.pop("FAKE_BDS_NEVER_READY", None)
    assert sup.state is RunState.FAILED
    history = [line.text for line in sup.console.snapshot()]
    assert any("Starting Server" in t for t in history)


async def test_clean_stop_never_signals_and_is_recorded_clean(make_supervisor) -> None:
    # 3.4 a normal stop never sends a signal; 3.5 recorded, survives restart
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    await sup.stop()
    assert sup.state is RunState.STOPPED
    assert sup.last_shutdown is not None and sup.last_shutdown.clean is True
    # 3.5 persisted and readable after a fresh load
    reloaded = load_last_shutdown(sup._settings.shutdown_record_file)
    assert reloaded is not None and reloaded.clean is True


async def test_hung_process_terminated_only_after_timeout(make_supervisor) -> None:
    # 3.4 a hung process is terminated only after the timeout; recorded unclean
    sup: Supervisor = make_supervisor(shutdown_timeout=1.0)
    import os

    os.environ["FAKE_BDS_IGNORE_STOP"] = "1"
    try:
        await sup.start()
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await sup.stop()
        elapsed = loop.time() - t0
    finally:
        os.environ.pop("FAKE_BDS_IGNORE_STOP", None)
    assert elapsed >= 1.0  # waited the full timeout before escalating
    assert sup.state is RunState.STOPPED
    assert sup.last_shutdown is not None and sup.last_shutdown.clean is False


async def test_restart_from_running_and_from_stopped_reach_running(make_supervisor) -> None:
    # 3.6 restart from both running and stopped states reaches running
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    await sup.restart()
    assert sup.state is RunState.RUNNING
    await sup.stop()
    assert sup.state is RunState.STOPPED
    await sup.restart()
    assert sup.state is RunState.RUNNING
    await sup.stop()


async def test_killed_server_reports_crashed_with_exit_code(make_supervisor) -> None:
    # 3.7 a killed server reports crashed; exit code + preceding output retained
    sup: Supervisor = make_supervisor(crash_restart_threshold=0)
    import os

    os.environ["FAKE_BDS_CRASH_AFTER"] = "0.3"
    try:
        await sup.start()
        await asyncio.wait_for(_wait_state(sup, RunState.CRASHED), timeout=5)
    finally:
        os.environ.pop("FAKE_BDS_CRASH_AFTER", None)
    assert sup.state is RunState.CRASHED
    assert sup.last_exit is not None and sup.last_exit.crashed is True
    assert sup.last_exit.code == 3
    assert any("simulated crash" in line.text for line in sup.console.snapshot())


async def test_requested_stop_reports_stopped_not_crashed(make_supervisor) -> None:
    # 3.7 a requested stop reports stopped
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    await sup.stop()
    assert sup.state is RunState.STOPPED


async def test_repeated_crashes_abandon_recovery_then_manual_start_works(make_supervisor) -> None:
    # 3.8 repeated crashes stop retrying; a manual start still works afterwards
    sup: Supervisor = make_supervisor(
        crash_restart_threshold=2, crash_restart_window=60.0, readiness_timeout=3.0
    )
    import os

    os.environ["FAKE_BDS_CRASH_AFTER"] = "0.2"
    try:
        await sup.start()
        await asyncio.wait_for(_wait_state(sup, RunState.RECOVERY_ABANDONED), timeout=15)
    finally:
        os.environ.pop("FAKE_BDS_CRASH_AFTER", None)
    assert sup.state is RunState.RECOVERY_ABANDONED
    # A manual start still works once the crash cause is gone.
    await sup.start()
    assert sup.state is RunState.RUNNING
    await sup.stop()


async def test_automatic_restart_after_a_single_crash(make_supervisor) -> None:
    # 3.8 automatic restart after a crash
    sup: Supervisor = make_supervisor(
        crash_restart_threshold=3, crash_restart_window=60.0, readiness_timeout=3.0
    )
    import os

    # Crash once, then (because the env var is cleared by the time the restart
    # spawns) the next start succeeds.
    os.environ["FAKE_BDS_CRASH_AFTER"] = "0.2"
    await sup.start()
    await asyncio.sleep(0.5)
    os.environ.pop("FAKE_BDS_CRASH_AFTER", None)
    await asyncio.wait_for(_wait_state(sup, RunState.RUNNING), timeout=15)
    assert sup.state is RunState.RUNNING
    await sup.stop()


async def test_cobble_termination_stops_child_cleanly(make_supervisor) -> None:
    # 3.9 a termination signal to cobble stops the server cleanly
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    await sup.aclose()
    assert sup.state is RunState.STOPPED
    assert sup.last_shutdown is not None and sup.last_shutdown.clean is True


async def test_restore_restarts_previously_running_server(
    make_supervisor, install_fake_bedrock
) -> None:
    # 3.9 restoration of the running state on cobble start
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    await sup.aclose()  # cobble goes down while server was running
    # New Supervisor over the same state dir == a cobble restart.
    settings = sup._settings
    sup2 = Supervisor(settings)
    await sup2.restore()
    assert sup2.state is RunState.RUNNING
    await sup2.stop()


async def _wait_state(sup: Supervisor, target: RunState) -> None:
    async with asyncio.timeout(15):
        await sup.wait_for_state(target)


async def test_last_crash_is_recorded_with_exit_code(make_supervisor) -> None:
    # 10.4 observability: after a crash the supervisor exposes a crash record
    # (exit code + timestamp) so status can show it even after auto-restart.
    sup: Supervisor = make_supervisor(crash_restart_threshold=0)
    import os

    os.environ["FAKE_BDS_CRASH_AFTER"] = "0.3"
    try:
        await sup.start()
        await _wait_state(sup, RunState.CRASHED)
    finally:
        os.environ.pop("FAKE_BDS_CRASH_AFTER", None)
    assert sup.last_crash is not None
    assert sup.last_crash.exit_code == 3
    assert "T" in sup.last_crash.at  # ISO timestamp
    await sup.stop()
