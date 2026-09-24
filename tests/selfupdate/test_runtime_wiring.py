"""cobble-self-update 2.3: the release check is scheduled without blocking startup."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cobble.app import create_app
from cobble.settings import Settings


def test_startup_completes_while_the_first_check_is_pending(tmp_settings: Settings) -> None:
    settings = tmp_settings.model_copy(update={"release_check_enabled": True})
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        checker = client.app.state.runtime.release_check
        assert checker._task is not None
        assert not checker._task.done()  # still in its initial delay
        assert checker.state.checked_at is None  # nothing contacted yet
    assert checker._task is None  # cancelled on shutdown


def test_disabled_check_makes_no_request(tmp_settings: Settings) -> None:
    with TestClient(create_app(tmp_settings)) as client:
        checker = client.app.state.runtime.release_check
        assert checker._task is None
        assert checker.state.checked_at is None
