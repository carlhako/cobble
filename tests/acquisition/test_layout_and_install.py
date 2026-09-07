"""Tasks 2.3, 2.4, 2.5, 2.6."""

from __future__ import annotations

import httpx
import pytest

from cobble.acquisition import installer as installer_mod
from cobble.acquisition.bootstrap import bootstrap_if_needed
from cobble.acquisition.installer import InstallError, install_version
from cobble.acquisition.layout import Layout
from cobble.acquisition.version_source import ResolvedVersion
from cobble.settings import Settings

from .conftest import make_bedrock_zip


def _vendor_settings(tmp_settings: Settings, fake_vendor) -> Settings:
    return tmp_settings.model_copy(update={"download_links_url": fake_vendor.links_url})


def test_directory_bootstrap_creates_full_layout(tmp_settings: Settings, tmp_path) -> None:
    # 2.5 first run on an empty host creates the full layout
    fresh = tmp_settings.model_copy(
        update={
            "bedrock_root": tmp_path / "fresh" / "srv" / "bedrock",
            "state_dir": tmp_path / "fresh" / "var" / "lib" / "cobble",
            "backup_dir": tmp_path / "fresh" / "backup",
        }
    )
    layout = Layout.from_settings(fresh)
    assert not layout.bedrock_root.exists()
    layout.ensure_directories()
    assert layout.bedrock_root.is_dir()
    assert layout.versions_dir.is_dir()
    assert layout.state_dir.is_dir()
    assert layout.backup_dir.is_dir()
    layout.ensure_directories()  # idempotent


def test_install_places_files_in_versioned_dir(tmp_settings: Settings, fake_vendor) -> None:
    # 2.3 files placed in a dir identified by version
    layout = Layout.from_settings(tmp_settings)
    layout.ensure_directories()
    resolved = ResolvedVersion(fake_vendor.version, fake_vendor.download_url)
    vdir = install_version(resolved, layout, _vendor_settings(tmp_settings, fake_vendor))
    assert vdir == layout.version_dir(fake_vendor.version)
    assert (vdir / "bedrock_server").is_file()
    assert (vdir / "server.properties").is_file()


def test_truncated_archive_leaves_no_partial_version_dir(
    tmp_settings: Settings, fake_vendor
) -> None:
    # 2.3 a truncated archive leaves no partial version directory
    fake_vendor.zip_bytes = make_bedrock_zip(fake_vendor.version, truncated=True)
    layout = Layout.from_settings(tmp_settings)
    layout.ensure_directories()
    resolved = ResolvedVersion(fake_vendor.version, fake_vendor.download_url)
    with pytest.raises(InstallError):
        install_version(resolved, layout, _vendor_settings(tmp_settings, fake_vendor))
    assert not layout.version_dir(fake_vendor.version).exists()
    assert list(layout.versions_dir.iterdir()) == []


def test_active_version_swap_changes_no_files_and_keeps_previous(
    tmp_settings: Settings, fake_vendor
) -> None:
    # 2.4 switching the active version changes no installation files and leaves
    # the previous version intact
    layout = Layout.from_settings(tmp_settings)
    layout.ensure_directories()
    s = _vendor_settings(tmp_settings, fake_vendor)

    install_version(ResolvedVersion("1.0.0.1", fake_vendor.download_url), layout, s)
    install_version(ResolvedVersion("2.0.0.1", fake_vendor.download_url), layout, s)
    layout.set_active_version("1.0.0.1")
    assert layout.installed_version() == "1.0.0.1"

    v1 = layout.version_dir("1.0.0.1")
    before = {p.name: p.read_bytes() for p in v1.iterdir()}
    v2_before = sorted(p.name for p in layout.version_dir("2.0.0.1").iterdir())

    layout.set_active_version("2.0.0.1")
    assert layout.installed_version() == "2.0.0.1"
    after = {p.name: p.read_bytes() for p in v1.iterdir()}
    assert after == before  # previous version untouched
    assert sorted(p.name for p in layout.version_dir("2.0.0.1").iterdir()) == v2_before
    # no staging symlink left behind
    assert not list(layout.bedrock_root.glob(".current.*.tmp"))


def test_bootstrap_installs_on_first_run_then_is_a_noop(
    tmp_settings: Settings, fake_vendor
) -> None:
    # 2.6 first run acquires + activates; second run performs no download
    s = _vendor_settings(tmp_settings, fake_vendor)
    first = bootstrap_if_needed(s)
    assert first.installed is True
    assert first.version == fake_vendor.version
    layout = Layout.from_settings(s)
    assert layout.has_installation()

    n_requests = len(fake_vendor.requests)
    second = bootstrap_if_needed(s)
    assert second.installed is False
    assert second.version == fake_vendor.version
    assert len(fake_vendor.requests) == n_requests  # no new HTTP traffic
    assert layout.installed_version() == fake_vendor.version


def _mock_client_factory(handler):
    """Return a callable matching httpx.Client(...) that routes through a
    MockTransport, so installer._download's own Client() is intercepted."""
    real = installer_mod.httpx.Client

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_download_resumes_across_stalls_and_assembles_the_full_file(
    tmp_settings: Settings, monkeypatch, tmp_path
) -> None:
    # 2.3 (robustness): a CDN that stalls partway through does not force a
    # restart from zero — the partial file is kept and the Range request
    # continues from where it stopped.
    monkeypatch.setattr(installer_mod, "_DOWNLOAD_BACKOFF", 0.0)
    monkeypatch.setattr(installer_mod, "_download_with_tool", lambda *a: False)
    payload = bytes(range(256)) * 400  # 102_400 bytes
    served = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(payload))})
        start = 0
        rng = request.headers.get("range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
        served["n"] += 1
        # Hand back only ~30 KB per attempt, then "stall" (short read).
        end = min(start + 30_000, len(payload))
        body = payload[start:end]
        status = 206 if rng else 200
        headers = {"content-range": f"bytes {start}-{end - 1}/{len(payload)}"} if rng else {}
        return httpx.Response(status, content=body, headers=headers)

    monkeypatch.setattr(installer_mod.httpx, "Client", _mock_client_factory(handler))
    dest = tmp_path / "z.zip"
    installer_mod._download("http://cdn/y.zip", dest, tmp_settings)
    assert dest.read_bytes() == payload
    assert served["n"] >= 4  # took multiple resumed requests


def test_download_aborts_after_repeated_no_progress(
    tmp_settings: Settings, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(installer_mod, "_DOWNLOAD_BACKOFF", 0.0)
    monkeypatch.setattr(installer_mod, "_DOWNLOAD_MAX_STALLED", 3)
    monkeypatch.setattr(installer_mod, "_download_with_tool", lambda *a: False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": "999999"})
        raise httpx.ReadTimeout("the read operation timed out")

    monkeypatch.setattr(installer_mod.httpx, "Client", _mock_client_factory(handler))
    with pytest.raises(InstallError) as ei:
        installer_mod._download("http://cdn/y.zip", tmp_path / "z.zip", tmp_settings)
    assert "stalled" in str(ei.value)


def test_download_prefers_curl_and_fetches_the_file(tmp_settings: Settings, fake_vendor, tmp_path):
    # The system downloader (curl/wget) is used when present.
    calls = {"tool": 0, "httpx": 0}
    real_tool = installer_mod._download_with_tool
    real_httpx = installer_mod._download_httpx

    def tool_spy(url, dest):
        calls["tool"] += 1
        return real_tool(url, dest)

    def httpx_spy(url, dest, settings):
        calls["httpx"] += 1
        return real_httpx(url, dest, settings)

    installer_mod_patched = pytest.MonkeyPatch()
    installer_mod_patched.setattr(installer_mod, "_download_with_tool", tool_spy)
    installer_mod_patched.setattr(installer_mod, "_download_httpx", httpx_spy)
    try:
        dest = tmp_path / "bds.zip"
        installer_mod._download(fake_vendor.download_url, dest, tmp_settings)
    finally:
        installer_mod_patched.undo()

    assert dest.read_bytes() == fake_vendor.zip_bytes
    assert calls["tool"] == 1
    assert calls["httpx"] == 0  # curl succeeded; no fallback needed


def test_download_falls_back_to_builtin_when_no_tool(tmp_settings: Settings, fake_vendor, tmp_path):
    mp = pytest.MonkeyPatch()
    mp.setattr(installer_mod.shutil, "which", lambda _name: None)  # hide curl + wget
    try:
        dest = tmp_path / "bds.zip"
        installer_mod._download(fake_vendor.download_url, dest, tmp_settings)
    finally:
        mp.undo()
    assert dest.read_bytes() == fake_vendor.zip_bytes


def test_install_defaults_allowlist_off_for_lan(tmp_settings: Settings, fake_vendor):
    # A fresh install must be joinable on a LAN without hand-building an
    # allowlist: cobble flips the vendor's allow-list=true to false on extract.
    layout = Layout.from_settings(tmp_settings)
    layout.ensure_directories()
    resolved = ResolvedVersion(fake_vendor.version, fake_vendor.download_url)
    vdir = install_version(resolved, layout, _vendor_settings(tmp_settings, fake_vendor))
    props = (vdir / "server.properties").read_text()
    assert "allow-list=false" in props
    assert "allow-list=true" not in props
    assert "online-mode=true" in props  # other settings untouched
