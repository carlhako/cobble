"""First-run bootstrap runs in the background and is retryable (regression for
the container install where a slow ~100 MB download timed out and left the
server unstartable with no recovery short of a restart)."""

from __future__ import annotations

import asyncio

import pytest

from cobble.runtime import Runtime
from cobble.settings import Settings

pytestmark = pytest.mark.asyncio


async def test_startup_does_not_block_on_bootstrap(monkeypatch, tmp_settings: Settings) -> None:
    settings = tmp_settings.model_copy(update={"bootstrap_on_start": True})
    rt = Runtime(settings)

    started = asyncio.Event()
    release = asyncio.Event()

    def slow_bootstrap(_s, _l):
        started.set()
        # simulate a long download
        import time

        while not release.is_set():
            time.sleep(0.01)

        class _O:
            installed = True
            version = "9.9.9.9"
            message = "installed 9.9.9.9"

        return _O()

    monkeypatch.setattr("cobble.runtime.bootstrap_if_needed", slow_bootstrap)

    await asyncio.wait_for(rt.startup(), timeout=1.0)  # returns immediately
    await asyncio.wait_for(started.wait(), timeout=2.0)  # bootstrap is running in bg
    assert rt.bootstrap.state == "running"
    assert rt.status.snapshot().to_dict()["bootstrap"] == "running"

    release.set()
    await asyncio.wait_for(rt._bootstrap_task, timeout=3.0)
    assert rt.bootstrap.state == "done"
    await rt.shutdown()


async def test_failed_bootstrap_is_surfaced_and_retryable(
    monkeypatch, tmp_settings: Settings
) -> None:
    settings = tmp_settings.model_copy(update={"bootstrap_on_start": True})
    rt = Runtime(settings)

    calls = {"n": 0}

    def bootstrap(_s, _l):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("download failed after 4 attempts: read timed out")

        class _O:
            message = "installed 1.2.3.4"

        # make the layout report an installation on the retry
        (rt.layout.versions_dir / "1.2.3.4").mkdir(parents=True, exist_ok=True)
        (rt.layout.version_dir("1.2.3.4") / "bedrock_server").write_text("x")
        rt.layout.set_active_version("1.2.3.4")
        return _O()

    monkeypatch.setattr("cobble.runtime.bootstrap_if_needed", bootstrap)

    await rt.startup()
    await asyncio.wait_for(rt._bootstrap_task, timeout=3.0)
    snap = rt.status.snapshot().to_dict()
    assert snap["bootstrap"] == "failed"
    assert "timed out" in snap["bootstrap_detail"]

    # retry succeeds
    result = await rt.run_bootstrap()
    assert result.state == "done"
    assert rt.status.snapshot().to_dict()["bootstrap"] == "done"
    assert rt.layout.has_installation()
    await rt.shutdown()
