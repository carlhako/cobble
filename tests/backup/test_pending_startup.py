"""import-backup-archive 4.4: a staged restore is applied before the runtime
opens its stores."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from cobble.app import create_app
from cobble.backup.pending import marker_path, stage_state, write_marker
from cobble.settings import Settings


def test_a_staged_state_is_what_the_runtime_opens(install_fake_bedrock, tmp_path) -> None:
    settings: Settings = install_fake_bedrock("1.2.3.4")
    state = settings.state_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / "maintenance_settings.json").write_text(json.dumps({"backup_retention": 3}))

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "maintenance_settings.json").write_text(json.dumps({"backup_retention": 11}))
    write_marker(
        state,
        entries=stage_state(extracted, state),
        label="cobble-backup-x.tar.gz",
        level_name="Bedrock level",
        replaced_capture="cobble-backup-replaced.tar.gz",
        was_running=False,
    )

    app = create_app(settings)
    runtime = app.state.runtime
    assert runtime.maintenance_settings.effective_backup_retention() == 11
    assert not marker_path(state).exists()
    assert runtime.gamerule_store is not None
    assert runtime.gamerule_store.restore_marker() == "Bedrock level"
    with TestClient(app):
        pass


def test_a_failed_swap_is_surfaced_as_backup_health(install_fake_bedrock, monkeypatch) -> None:
    import cobble.backup.pending as pending_mod

    settings: Settings = install_fake_bedrock("1.2.3.4")
    state = settings.state_dir
    state.mkdir(parents=True, exist_ok=True)
    extracted = state.parent / "extracted"
    extracted.mkdir()
    (extracted / "cobble.db").write_text("x")
    write_marker(
        state,
        entries=stage_state(extracted, state),
        label="cobble-backup-x.tar.gz",
        level_name=None,
        replaced_capture="cobble-backup-replaced.tar.gz",
        was_running=False,
    )

    def failing_move(src, dst):
        raise OSError("read-only file system")

    monkeypatch.setattr(pending_mod.shutil, "move", failing_move)
    app = create_app(settings)
    health = app.state.runtime.backup.health
    assert health is not None
    assert "read-only file system" in health
    assert "cobble-backup-replaced.tar.gz" in health
