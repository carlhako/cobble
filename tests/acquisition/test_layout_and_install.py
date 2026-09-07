"""Tasks 2.3, 2.4, 2.5, 2.6."""

from __future__ import annotations

import pytest

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
