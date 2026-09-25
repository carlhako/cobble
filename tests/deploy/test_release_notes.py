"""cobble-version-page 5.2: the release workflow's CHANGELOG.md extraction."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "release-notes.sh"

if sys.platform != "linux":  # pragma: no cover
    pytest.skip("linux-only release tooling", allow_module_level=True)

CHANGELOG = """# Changelog

Intro text.

## 0.5.10 - 2026-10-01

- ten

## 0.5.1 - 2026-09-24

### Fixes

- one fix

## 0.5.0 - 2026-09-24

## 0.4.0

- last section
"""


def _run(version: str, changelog: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), version, str(changelog)],
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture
def changelog(tmp_path: Path) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG)
    return path


def test_prints_the_section_trimmed_with_subheadings(changelog: Path) -> None:
    res = _run("0.5.1", changelog)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "### Fixes\n\n- one fix\n"


def test_accepts_a_tag_and_matches_the_version_exactly(changelog: Path) -> None:
    res = _run("v0.5.1", changelog)
    assert res.returncode == 0 and "0.5.10" not in res.stdout and "ten" not in res.stdout


def test_last_section_runs_to_end_of_file(changelog: Path) -> None:
    res = _run("0.4.0", changelog)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "- last section\n"


def test_missing_section_fails_naming_the_version(changelog: Path) -> None:
    res = _run("0.9.9", changelog)
    assert res.returncode != 0
    assert res.stdout == ""
    assert "no CHANGELOG.md entry for 0.9.9" in res.stderr


def test_empty_section_fails(changelog: Path) -> None:
    res = _run("0.5.0", changelog)
    assert res.returncode != 0
    assert "no CHANGELOG.md entry for 0.5.0" in res.stderr


def test_every_published_version_in_the_repo_changelog_has_notes() -> None:
    for version in ("0.4.0", "0.5.0", "0.5.1", "0.6.0", "0.7.0", "0.7.1", "0.7.2"):
        res = _run(version, REPO / "CHANGELOG.md")
        assert res.returncode == 0, res.stderr
        assert res.stdout.strip()
