"""Section 1: project scaffolding."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cobble.app import create_app
from cobble.settings import Settings, get_settings


def test_bare_app_starts_and_answers_health(tmp_settings: Settings) -> None:
    # 1.1 a bare app starts and answers a health route
    app = create_app(tmp_settings)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_defaults_load_with_no_config_file(monkeypatch) -> None:
    # 1.5 defaults load with no config file present
    monkeypatch.delenv("COBBLE_CONFIG_FILE", raising=False)
    monkeypatch.setenv("COBBLE_CONFIG_FILE", "/nonexistent/cobble.toml")
    get_settings.cache_clear()
    s = Settings()
    assert s.bedrock_root == Path("/srv/bedrock")
    assert s.state_dir == Path("/var/lib/cobble")
    assert s.backup_dir == Path("/backup")
    assert s.shutdown_timeout >= 120.0
    assert s.readiness_timeout >= 1.0
    assert s.crash_restart_threshold >= 0
    assert s.versions_dir == Path("/srv/bedrock/versions")
    assert s.current_link == Path("/srv/bedrock/current")


def test_settings_read_from_toml_file(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "cobble.toml"
    cfg.write_text("[cobble]\nshutdown_timeout = 200\nport = 9001\n")
    monkeypatch.setenv("COBBLE_CONFIG_FILE", str(cfg))
    s = Settings()
    assert s.shutdown_timeout == 200.0
    assert s.port == 9001


def test_env_overrides_toml(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "cobble.toml"
    cfg.write_text("shutdown_timeout = 200\n")
    monkeypatch.setenv("COBBLE_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("COBBLE_SHUTDOWN_TIMEOUT", "321")
    s = Settings()
    assert s.shutdown_timeout == 321.0
