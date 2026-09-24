"""Vendor defaults: following a Bedrock default that changed across an update, and
the transport view that compares the running transport with the shipped one."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from cobble.acquisition.layout import Layout
from cobble.config.service import ConfigService
from cobble.config.vendor_defaults import (
    DefaultChange,
    carry_vendor_defaults,
    vendor_default,
    vendor_defaults,
)
from cobble.settings import Settings
from cobble.supervisor.supervisor import Supervisor

# The two vendor files that motivated this: 1.26.51.1 flipped transport.
OLD_VENDOR = (
    "server-name=Dedicated Server\n"
    "allow-list=true\n"
    "transport=raknet\n"
    "# Which transport protocol the server should use.\n"
    "view-distance=32\n"
)
NEW_VENDOR = OLD_VENDOR.replace("transport=raknet", "transport=nethernet")


def _vendor(layout: Layout, version: str, text: str) -> None:
    vdir = layout.version_dir(version)
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "server.properties").write_text(text)


@pytest.fixture
def layout(tmp_settings: Settings) -> Layout:
    layout = Layout.from_settings(tmp_settings)
    layout.ensure_directories()
    _vendor(layout, "1.26.45.1", OLD_VENDOR)
    _vendor(layout, "1.26.51.1", NEW_VENDOR)
    return layout


def _operator(layout: Layout, text: str) -> None:
    (layout.data_dir / "server.properties").write_text(text)


def _operator_text(layout: Layout) -> str:
    return (layout.data_dir / "server.properties").read_text()


def test_vendor_defaults_read_the_versions_own_file(layout: Layout) -> None:
    assert vendor_defaults(layout, "1.26.45.1")["transport"] == "raknet"
    assert vendor_default(layout, "1.26.51.1", "transport") == "nethernet"
    assert vendor_defaults(layout, "9.9.9.9") is None
    assert vendor_default(layout, None, "transport") is None


def test_a_setting_left_at_the_old_default_follows_the_new_one(layout: Layout) -> None:
    # cobble's own seed: the vendor file with allow-list turned off.
    _operator(layout, OLD_VENDOR.replace("allow-list=true", "allow-list=false"))
    changes = carry_vendor_defaults(layout, "1.26.45.1", "1.26.51.1")
    assert changes == [DefaultChange("transport", "raknet", "nethernet")]
    text = _operator_text(layout)
    assert "transport=nethernet" in text
    # Only that line changed: comments, order and every other value survive.
    assert text == OLD_VENDOR.replace("allow-list=true", "allow-list=false").replace(
        "transport=raknet", "transport=nethernet"
    )


def test_a_setting_the_operator_changed_is_left_alone(layout: Layout) -> None:
    _vendor(layout, "1.26.51.1", NEW_VENDOR.replace("view-distance=32", "view-distance=24"))
    _operator(layout, OLD_VENDOR.replace("view-distance=32", "view-distance=12"))
    changes = carry_vendor_defaults(layout, "1.26.45.1", "1.26.51.1")
    # transport was untouched by the operator and follows; view-distance was theirs.
    assert changes == [DefaultChange("transport", "raknet", "nethernet")]
    assert "view-distance=12" in _operator_text(layout)


def test_nothing_changes_when_no_default_changed(layout: Layout) -> None:
    _operator(layout, OLD_VENDOR)
    assert carry_vendor_defaults(layout, "1.26.45.1", "1.26.45.1") == []
    assert _operator_text(layout) == OLD_VENDOR


@pytest.mark.parametrize("previous", [None, "1.0.0.0"])
def test_nothing_changes_without_the_old_versions_file(layout: Layout, previous) -> None:
    # The previous version is unknown or its directory was pruned: there is no
    # way to tell a default from a choice, so nothing is touched.
    _operator(layout, OLD_VENDOR)
    assert carry_vendor_defaults(layout, previous, "1.26.51.1") == []
    assert _operator_text(layout) == OLD_VENDOR


def test_nothing_changes_without_an_operator_file(layout: Layout) -> None:
    assert carry_vendor_defaults(layout, "1.26.45.1", "1.26.51.1") == []


# -- the transport view ---------------------------------------------------------
@pytest.fixture
def wired(install_fake_bedrock: Callable[..., Settings]):
    settings = install_fake_bedrock("1.26.51.1", readiness_timeout=3.0, shutdown_timeout=3.0)
    layout = Layout.from_settings(settings)
    _vendor(layout, "1.26.51.1", NEW_VENDOR)
    sup = Supervisor(settings)
    return layout, sup, ConfigService(settings, layout, sup)


def test_stopped_server_on_the_old_transport_is_not_recommended(wired) -> None:
    layout, _sup, svc = wired
    _operator(layout, OLD_VENDOR)
    view = svc.transport_view()
    assert view.value == "raknet" and view.recommended == "nethernet"
    assert view.is_recommended is False
    assert view.running is False and view.pending_restart is False


def test_a_missing_key_means_the_versions_default(wired) -> None:
    layout, _sup, svc = wired
    _operator(layout, "server-name=x\n")
    view = svc.transport_view()
    assert view.value == "nethernet" and view.is_recommended is True


def test_unknown_recommendation_gives_no_advice(wired) -> None:
    layout, _sup, svc = wired
    (layout.version_dir("1.26.51.1") / "server.properties").unlink()
    _operator(layout, OLD_VENDOR)
    view = svc.transport_view()
    assert view.recommended is None and view.is_recommended is True


@pytest.mark.asyncio
async def test_running_server_reports_its_transport_and_a_pending_switch(wired) -> None:
    layout, sup, svc = wired
    _operator(layout, OLD_VENDOR)
    await sup.start()
    try:
        assert svc.transport_view().value == "raknet"
        result = svc.write({"transport": "nethernet"})
        assert result.ok
        view = svc.transport_view()
        # Still running raknet until a restart; the saved value is the fix.
        assert view.value == "raknet" and view.saved == "nethernet"
        assert view.is_recommended is False and view.pending_restart is True
        await sup.restart()
        view = svc.transport_view()
        assert view.value == "nethernet" and view.is_recommended is True
        assert view.pending_restart is False
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_saving_a_non_default_transport_is_flagged_before_the_restart(wired) -> None:
    layout, sup, svc = wired
    _operator(layout, NEW_VENDOR)
    await sup.start()
    try:
        assert svc.transport_view().is_recommended is True
        svc.write({"transport": "raknet"})
        view = svc.transport_view()
        assert view.value == "nethernet" and view.saved == "raknet"
        assert view.is_recommended is False and view.pending_restart is True
    finally:
        await sup.stop()


def test_transport_rejects_an_unknown_protocol(wired) -> None:
    layout, _sup, svc = wired
    _operator(layout, OLD_VENDOR)
    result = svc.write({"transport": "carrier-pigeon"})
    assert result.ok is False
    assert "transport=raknet" in _operator_text(layout)
