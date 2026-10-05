"""import-backup-archive 5.1: cobble restarting its own process."""

from __future__ import annotations

import asyncio

import pytest

import cobble.__main__ as main_mod
from cobble import restart


@pytest.fixture(autouse=True)
def _clean():
    restart.reset()
    restart.set_exit_hook(None)
    yield
    restart.reset()
    restart.set_exit_hook(None)


def test_a_request_sets_the_flag_and_runs_the_hook() -> None:
    calls: list[int] = []
    restart.set_exit_hook(lambda: calls.append(1))
    assert restart.requested() is False
    restart.request("test")
    assert restart.requested() is True
    assert calls == [1]


def test_a_request_without_a_hook_still_records_it() -> None:
    restart.request("test")
    assert restart.requested() is True


class _FakeServer:
    def __init__(self, config, *, then=None) -> None:
        self.config = config
        self.should_exit = False
        self.started = True
        self._then = then

    def run(self) -> None:
        if self._then:
            self._then()


def _patch_server(monkeypatch, then=None, started=True) -> list[_FakeServer]:
    made: list[_FakeServer] = []

    def factory(config):
        srv = _FakeServer(config, then=then)
        srv.started = started
        made.append(srv)
        return srv

    monkeypatch.setattr(main_mod.uvicorn, "Server", factory)
    monkeypatch.setattr(main_mod, "configure_logging", lambda: None)
    return made


def test_main_exits_75_after_a_restart_request(monkeypatch, tmp_settings) -> None:
    monkeypatch.setattr(main_mod, "get_settings", lambda: tmp_settings)
    made = _patch_server(monkeypatch, then=lambda: restart.request("restore"))
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code == restart.EXIT_RESTART
    # The hook asked the server to shut down gracefully, not via a signal.
    assert made[0].should_exit is True


def test_main_returns_normally_without_a_request(monkeypatch, tmp_settings) -> None:
    monkeypatch.setattr(main_mod, "get_settings", lambda: tmp_settings)
    _patch_server(monkeypatch)
    main_mod.main()  # no SystemExit


def test_main_reports_a_server_that_never_started(monkeypatch, tmp_settings) -> None:
    monkeypatch.setattr(main_mod, "get_settings", lambda: tmp_settings)
    _patch_server(monkeypatch, started=False)
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code == 3


def test_runtime_request_restart_is_deferred() -> None:
    from cobble.runtime import Runtime

    async def go() -> tuple[bool, bool]:
        # Uses no runtime state, so no runtime (and no open stores) is needed.
        Runtime.request_restart(object(), "test", delay=0.05)  # type: ignore[arg-type]
        before = restart.requested()
        await asyncio.sleep(0.1)
        return before, restart.requested()

    assert asyncio.run(go()) == (False, True)
