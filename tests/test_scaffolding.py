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
    assert s.data_dir == Path("/srv/bedrock/data")
    # M2 settings — each with a documented default (task 11.1)
    assert s.maintenance_time == "04:00"
    assert s.backup_enabled is True
    assert s.update_enabled is True
    assert s.backup_retention == 7
    assert s.update_grace_seconds == 60.0


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


def test_version_matches_pyproject() -> None:
    # cobble-self-update 1.2: __version__ is what the header and release check
    # compare against, so it must not drift from the packaged version.
    import tomllib

    import cobble

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert cobble.__version__ == declared


def test_user_agent_default_carries_the_running_version(monkeypatch) -> None:
    # cobble-self-update 1.1
    import cobble

    monkeypatch.setenv("COBBLE_CONFIG_FILE", "/nonexistent/cobble.toml")
    s = Settings()
    assert s.user_agent == f"cobble/{cobble.__version__} (+https://github.com/carlhako/cobble)"


def test_self_update_settings_defaults_and_env_overrides(monkeypatch) -> None:
    # cobble-self-update 1.3
    monkeypatch.setenv("COBBLE_CONFIG_FILE", "/nonexistent/cobble.toml")
    s = Settings()
    assert s.release_repo == "carlhako/cobble"
    assert s.release_api_url == "https://api.github.com"
    assert s.release_check_enabled is True
    assert s.release_check_interval_hours == 12.0
    assert s.upgrade_helper_path == Path("/usr/local/libexec/cobble/cobble-upgrade")
    assert s.upgrade_status_dir == Path("/var/lib/cobble-upgrade")
    assert s.upgrade_request_dir == Path("/var/lib/cobble/upgrade")

    monkeypatch.setenv("COBBLE_RELEASE_CHECK_ENABLED", "false")
    monkeypatch.setenv("COBBLE_RELEASE_CHECK_INTERVAL_HOURS", "6")
    monkeypatch.setenv("COBBLE_RELEASE_REPO", "someone/fork")
    s = Settings()
    assert s.release_check_enabled is False
    assert s.release_check_interval_hours == 6.0
    assert s.release_repo == "someone/fork"
