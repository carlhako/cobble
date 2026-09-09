"""``allow-list`` is applied live and reported by observation (tasks 2.5, 2.6)."""

from __future__ import annotations

import pytest

from cobble.access.enforcement import EnforcementTracker
from cobble.acquisition.layout import Layout
from cobble.config.service import ConfigService
from cobble.events.model import AllowlistDisabled, AllowlistEnabled
from cobble.settings import Settings
from cobble.supervisor.state import RunState

SAMPLE = "difficulty=easy\nallow-list=false\nmax-players=10\n"


class FakeSupervisor:
    def __init__(self, *, running=True) -> None:
        self.maintenance = None
        self.state = RunState.RUNNING if running else RunState.STOPPED
        self._level = "Bedrock level"

    @property
    def config_snapshot(self):
        if self.state is not RunState.RUNNING:
            return None
        return {"allow-list": "false", "difficulty": "easy"}


@pytest.fixture
def layout(tmp_settings: Settings) -> Layout:
    lo = Layout.from_settings(tmp_settings)
    lo.ensure_directories()
    (lo.data_dir / "server.properties").write_text(SAMPLE)
    return lo


def _service(tmp_settings, layout, *, running=True, tracker=None, calls=None):
    return ConfigService(
        tmp_settings,
        layout,
        FakeSupervisor(running=running),
        enforcement=tracker or EnforcementTracker(),
        apply_enforcement=(calls.append if calls is not None else None),
    )


# -- 2.5 saving allow-list writes the file and instructs the server ----
def test_saving_allow_list_persists_and_instructs(tmp_settings, layout) -> None:
    calls: list[bool] = []
    svc = _service(tmp_settings, layout, calls=calls)
    result = svc.write({"allow-list": "true"})
    assert result.ok
    assert "allow-list=true" in (layout.data_dir / "server.properties").read_text()
    assert calls == [True]


def test_a_failed_write_issues_no_command(tmp_settings, layout, monkeypatch) -> None:
    calls: list[bool] = []
    svc = _service(tmp_settings, layout, calls=calls)

    import cobble.config.properties as props

    def boom(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(props.PropertiesDocument, "save", boom)
    with pytest.raises(OSError):
        svc.write({"allow-list": "true"})
    assert calls == []  # the server was never instructed


# -- 2.6 allow-list is never pending; live-vs-saved is reported instead ----
def test_allow_list_is_excluded_from_pending(tmp_settings, layout) -> None:
    tracker = EnforcementTracker()
    svc = _service(tmp_settings, layout, tracker=tracker)
    svc.write({"allow-list": "true", "difficulty": "hard"})
    pending_keys = {c.key for c in svc.pending()}
    assert "allow-list" not in pending_keys
    assert "difficulty" in pending_keys  # a normal setting is still pending


def test_out_of_band_enforcement_change_is_reported_as_a_disagreement(tmp_settings, layout) -> None:
    tracker = EnforcementTracker()
    svc = _service(tmp_settings, layout, tracker=tracker)
    # file says off; the server was turned on by hand in the console
    tracker.on_event(AllowlistEnabled(raw="Turned on the allowlist"))
    view = svc.enforcement_view()
    assert view.saved is False
    assert view.in_effect == "on"
    assert view.disagreement is True


def test_enforcement_view_is_unknown_until_observed(tmp_settings, layout) -> None:
    svc = _service(tmp_settings, layout, tracker=EnforcementTracker())
    view = svc.enforcement_view()
    assert view.in_effect == "unknown"
    assert view.disagreement is False


def test_agreement_is_not_a_disagreement(tmp_settings, layout) -> None:
    tracker = EnforcementTracker()
    svc = _service(tmp_settings, layout, tracker=tracker)
    svc.write({"allow-list": "true"})
    tracker.on_event(AllowlistEnabled(raw="Turned on the allowlist"))
    view = svc.enforcement_view()
    assert view.saved is True
    assert view.in_effect == "on"
    assert view.disagreement is False
    _ = AllowlistDisabled  # imported for symmetry in future edits
