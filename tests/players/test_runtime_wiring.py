"""The runtime wires the recorder onto the bus and reconciles on startup
(task 2.5, and the startup half of 4.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cobble.players.storage import END_RECONSTRUCTED, open_store
from cobble.runtime import Runtime
from cobble.settings import Settings

pytestmark = pytest.mark.asyncio


async def test_connect_event_is_recorded_end_to_end(install_fake_bedrock) -> None:
    settings: Settings = install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0)
    rt = Runtime(settings)
    await rt.startup()
    try:
        assert rt.player_history is not None
        # The runtime's line sink parses a line and publishes it on the bus; the
        # recorder is a subscriber, exactly like StatusTracker.
        rt.supervisor._sink("[2026-01-01 12:00:00:000 INFO] Player connected: Alex, xuid: 90909")
        assert rt.players is not None
        assert rt.players.open_session_xuids() == ["90909"]
    finally:
        await rt.shutdown()


async def test_startup_reconciles_a_session_left_open_by_a_previous_run(
    install_fake_bedrock,
) -> None:
    settings: Settings = install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0)
    seed = open_store(settings.player_db_file)
    seed.open_session("x1", "Alex", datetime(2026, 1, 1, tzinfo=UTC))
    seed.touch_open_sessions(datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC))
    seed.close()

    rt = Runtime(settings)
    await rt.startup()
    try:
        assert rt.players is not None
        row = rt.players.sessions_for("x1", now=datetime.now(UTC))[0]
        assert row.end_reason == END_RECONSTRUCTED
        assert row.in_progress is False
    finally:
        await rt.shutdown()
