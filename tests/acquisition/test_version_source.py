"""Tasks 2.1, 2.2."""

from __future__ import annotations

import os

import httpx
import pytest

from cobble.acquisition.version_source import (
    VersionResolutionError,
    resolve_current_version,
    try_resolve_current_version,
)
from cobble.settings import Settings


def test_resolves_version_and_url_from_fake_vendor(tmp_settings: Settings, fake_vendor) -> None:
    s = tmp_settings.model_copy(update={"download_links_url": fake_vendor.links_url})
    resolved = resolve_current_version(s)
    assert resolved.version == fake_vendor.version
    assert resolved.download_url == fake_vendor.download_url


def test_every_request_carries_a_user_agent(tmp_settings: Settings, fake_vendor) -> None:
    s = tmp_settings.model_copy(
        update={"download_links_url": fake_vendor.links_url, "user_agent": "cobble-test/9"}
    )
    resolve_current_version(s)
    assert fake_vendor.requests, "expected at least one request"
    for path, headers in fake_vendor.requests:
        assert headers.get("User-Agent") == "cobble-test/9", f"missing UA on {path}"


def test_request_without_user_agent_is_never_issued(tmp_settings: Settings, fake_vendor) -> None:
    # The fake vendor rejects UA-less requests with 403; if the client ever
    # issued one we would see it recorded with no User-Agent header.
    s = tmp_settings.model_copy(update={"download_links_url": fake_vendor.links_url})
    resolve_current_version(s)
    assert all("User-Agent" in headers for _, headers in fake_vendor.requests)


def test_unreachable_source_raises_named_error(tmp_settings: Settings) -> None:
    s = tmp_settings.model_copy(
        update={"download_links_url": "http://127.0.0.1:9/never"}  # discard port
    )
    with pytest.raises(VersionResolutionError) as ei:
        resolve_current_version(s)
    assert "unreachable" in str(ei.value)


def test_malformed_response_raises_named_error(tmp_settings: Settings, fake_vendor) -> None:
    fake_vendor.zip_bytes = b""
    s = tmp_settings.model_copy(update={"download_links_url": fake_vendor.download_url})
    # Pointing the links URL at the .zip endpoint yields non-JSON.
    with pytest.raises(VersionResolutionError):
        resolve_current_version(s)


def test_try_resolve_swallows_failure_and_returns_none(tmp_settings: Settings, caplog) -> None:
    s = tmp_settings.model_copy(update={"download_links_url": "http://127.0.0.1:9/never"})
    result = try_resolve_current_version(s)
    assert result is None
    assert any("version resolution failed" in r.message for r in caplog.records)


@pytest.mark.skipif(
    os.environ.get("COBBLE_LIVE_TESTS") != "1",
    reason="live vendor test; set COBBLE_LIVE_TESTS=1 to run",
)
def test_resolves_against_live_vendor_source() -> None:
    s = Settings()
    resolved = resolve_current_version(s)
    assert resolved.version.count(".") >= 2
    assert resolved.download_url.startswith("https://")
    assert resolved.download_url.endswith(".zip")


def test_client_helper_sets_user_agent_header(tmp_settings: Settings) -> None:
    from cobble.acquisition.version_source import _client

    with _client(tmp_settings) as c:
        assert c.headers["user-agent"] == tmp_settings.user_agent
    assert isinstance(_client(tmp_settings), httpx.Client)
