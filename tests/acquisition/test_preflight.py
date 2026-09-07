"""Task 2.7."""

from __future__ import annotations

import pytest

from cobble.acquisition import preflight
from cobble.acquisition.preflight import PreflightError, run_preflight


def test_unsupported_architecture_names_the_requirement(monkeypatch) -> None:
    monkeypatch.setattr(preflight.platform, "machine", lambda: "aarch64")
    result = run_preflight()
    assert not result.ok
    assert any("architecture" in f and "aarch64" in f for f in result.failures)
    with pytest.raises(PreflightError, match="architecture"):
        result.raise_if_failed()


def test_old_glibc_names_the_minimum_version(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_glibc_version", lambda: (2, 17))
    result = run_preflight()
    assert not result.ok
    assert any("2.26" in f and "2.17" in f for f in result.failures)


def test_undeterminable_glibc_names_the_minimum_version(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_glibc_version", lambda: None)
    result = run_preflight()
    assert not result.ok
    assert any("2.26" in f for f in result.failures)


def test_current_host_passes_or_fails_explicitly() -> None:
    # This CI host is amd64 with modern glibc; the check should pass here.
    result = run_preflight()
    if not result.ok:
        pytest.skip(f"host does not meet BDS requirements: {result.failures}")
    assert result.ok
    result.raise_if_failed()
