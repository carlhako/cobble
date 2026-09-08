"""Section 8: update + backup HTTP routes (tasks 8.1-8.4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cobble.app import create_app
from cobble.settings import Settings


@pytest.fixture
def app_settings(install_fake_bedrock) -> Settings:
    return install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        yield c


# -- 8.1 / 8.2 OpenAPI surface -----------------------------------
def test_openapi_lists_update_and_backup_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for expected in (
        "/api/updates/check",
        "/api/updates/apply",
        "/api/updates/clear-failed",
        "/api/updates/diagnostics",
        "/api/backups",
        "/api/backups/{archive}",
        "/api/backups/{archive}/restore",
    ):
        assert expected in paths, f"{expected} missing from OpenAPI schema"


# -- 8.2 structured conflict errors --------------------------
def test_capture_while_a_restore_is_in_progress_returns_a_distinguishable_error(
    client: TestClient,
) -> None:
    runtime = client.app.state.runtime
    runtime.backup._busy = "restore"
    resp = client.post("/api/backups")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "backup_in_progress"
    runtime.backup._busy = None


def test_apply_while_an_update_is_in_progress_returns_a_distinguishable_error(
    client: TestClient,
) -> None:
    runtime = client.app.state.runtime
    runtime.update._busy = "update"
    resp = client.post("/api/updates/apply")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "update_in_progress"
    runtime.update._busy = None


def test_restore_of_a_missing_backup_is_reported_not_raised(client: TestClient) -> None:
    resp = client.post("/api/backups/does-not-exist.tar.gz/restore")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and "not found" in body["error"]


# -- 8.1 check + apply reachable ---------------------------
def test_check_returns_a_result_even_when_the_vendor_is_unreachable(client: TestClient) -> None:
    # tmp_settings points download_links_url at a dead port
    resp = client.post("/api/updates/check")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is not None
    assert body["available"] is None


def test_backups_list_is_empty_and_healthy_initially(client: TestClient) -> None:
    resp = client.get("/api/backups")
    assert resp.status_code == 200
    assert resp.json() == {"backups": [], "unhealthy": None}


def test_capture_via_route_produces_a_listable_backup(client: TestClient) -> None:
    made = client.post("/api/backups")
    assert made.status_code == 200 and made.json()["ok"] is True
    listed = client.get("/api/backups").json()["backups"]
    assert len(listed) == 1 and listed[0]["restorable"] is True


# -- download a held backup as a single file --------------------
def test_download_returns_the_archive_bytes(client: TestClient) -> None:
    client.post("/api/backups")
    name = client.get("/api/backups").json()["backups"][0]["archive"]

    resp = client.get(f"/api/backups/{name}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    assert "attachment" in resp.headers["content-disposition"]
    assert name in resp.headers["content-disposition"]

    on_disk = client.app.state.runtime.backup.store.dir / name
    assert resp.content == on_disk.read_bytes()


def test_download_of_an_unknown_name_is_404(client: TestClient) -> None:
    resp = client.get("/api/backups/nope.tar.gz")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "not_found"


def test_download_rejects_a_name_with_an_encoded_separator(client: TestClient) -> None:
    # An encoded slash keeps this a single path segment, so it reaches the route
    # and must be refused rather than joined onto the backup directory.
    resp = client.get("/api/backups/foo%2Fbar.tar.gz")
    assert resp.status_code == 404
    assert b"root:" not in resp.content


def test_download_of_a_not_restorable_backup_still_succeeds(client: TestClient) -> None:
    client.post("/api/backups")
    store = client.app.state.runtime.backup.store
    name = client.get("/api/backups").json()["backups"][0]["archive"]
    # Corrupt the archive body; the sidecar (manifest) stays intact so the entry
    # is still listed, now as not restorable.
    (store.dir / name).write_bytes(b"not a tar")
    listed = client.get("/api/backups").json()["backups"][0]
    assert listed["restorable"] is False

    resp = client.get(f"/api/backups/{name}")
    assert resp.status_code == 200
    assert resp.content == b"not a tar"


# -- 8.3 status payload carries the new blocks --------------
def test_status_payload_has_version_update_backup_and_maintenance_fields(
    client: TestClient,
) -> None:
    body = client.get("/api/status").json()
    for key in ("maintenance", "version_info", "update", "backup"):
        assert key in body, f"status payload missing '{key}'"
    assert body["maintenance"] is None
    assert body["version_info"]["installed"] == "1.2.3.4"
    assert body["version_info"]["available"] is None  # no check yet
    assert body["backup"]["count"] == 0


# -- 8.4 diagnostics route --------------------------------
def test_diagnostics_route_is_null_before_any_failure(client: TestClient) -> None:
    resp = client.get("/api/updates/diagnostics")
    assert resp.status_code == 200
    assert resp.json() == {"diagnostics": None}


def test_clear_failed_route_accepts_a_version_and_reports_cleared(client: TestClient) -> None:
    runtime = client.app.state.runtime
    runtime.update._store.add_failed("9.9.9.9", "readiness", "boom")
    resp = client.post("/api/updates/clear-failed", json={"version": "9.9.9.9"})
    assert resp.status_code == 200
    assert resp.json()["cleared"] == ["9.9.9.9"]
    assert runtime.update._store.is_failed("9.9.9.9") is False
