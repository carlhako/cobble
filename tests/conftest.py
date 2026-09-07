from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from cobble.acquisition.layout import Layout
from cobble.settings import Settings
from cobble.supervisor.supervisor import Supervisor

FAKE_BEDROCK = Path(__file__).parent / "supervisor" / "fake_bedrock.py"


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Settings pointed entirely at a scratch directory."""
    bedrock = tmp_path / "srv" / "bedrock"
    state = tmp_path / "var" / "lib" / "cobble"
    backup = tmp_path / "backup"
    for d in (bedrock, state, backup):
        d.mkdir(parents=True, exist_ok=True)
    return Settings(
        bedrock_root=bedrock,
        state_dir=state,
        backup_dir=backup,
        shutdown_timeout=2.0,
        readiness_timeout=2.0,
        crash_restart_threshold=2,
        crash_restart_window=5.0,
        bootstrap_on_start=False,
        download_links_url="http://127.0.0.1:9/never",
    )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(("COBBLE_", "FAKE_BDS_")):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def install_fake_bedrock(tmp_settings: Settings) -> Callable[..., Settings]:
    """Factory: lay down a fake bedrock_server for a version, return settings
    with the given overrides applied."""

    def _install(version: str = "1.99.0.1", **overrides) -> Settings:
        layout = Layout.from_settings(tmp_settings)
        layout.ensure_directories()
        vdir = layout.version_dir(version)
        vdir.mkdir(parents=True, exist_ok=True)
        binary = vdir / "bedrock_server"
        binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_BEDROCK}" "$@"\n')
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        layout.set_active_version(version)
        return tmp_settings.model_copy(update=overrides)

    return _install


@pytest.fixture
def make_supervisor(install_fake_bedrock: Callable[..., Settings]) -> Callable[..., Supervisor]:
    def _make(version: str = "1.99.0.1", *, line_sink=None, **overrides) -> Supervisor:
        settings = install_fake_bedrock(version, **overrides)
        return Supervisor(settings, line_sink=line_sink)

    return _make
