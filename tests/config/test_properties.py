"""Section 1: the ``server.properties`` line document (tasks 1.1-1.4)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cobble.config.properties import PropertiesDocument

VENDOR_ISH = (
    "# Bedrock server properties\n"
    "\n"
    "server-name=Dedicated Server\n"
    "  gamemode=survival\n"
    "level-name=Bedrock level\n"
    "level-seed=\n"
    "motd=a=b=c\n"  # inline '=' in the value
    "max-players=10\n"
)


def test_round_trips_byte_for_byte() -> None:
    # 1.1 comments, blank lines, indentation, inline '=' all round-trip unchanged
    doc = PropertiesDocument.parse(VENDOR_ISH)
    assert doc.serialize() == VENDOR_ISH


def test_round_trips_without_trailing_newline() -> None:
    text = "a=1\nb=2"
    assert PropertiesDocument.parse(text).serialize() == text


def test_inline_equals_is_part_of_the_value() -> None:
    doc = PropertiesDocument.parse(VENDOR_ISH)
    assert doc.get("motd") == "a=b=c"


def test_effective_value_is_the_last_assignment() -> None:
    # 1.2 a repeated key resolves to its last assignment, both lines still present
    doc = PropertiesDocument.parse("max-players=10\nmax-players=20\n")
    assert doc.effective()["max-players"] == "20"
    assert doc.serialize().count("max-players=") == 2


def test_set_changes_only_the_matched_line() -> None:
    # 1.3 changing one value leaves every other line identical
    doc = PropertiesDocument.parse(VENDOR_ISH)
    doc.set("max-players", "24")
    out = doc.serialize()
    assert "max-players=24\n" in out
    assert out.replace("max-players=24", "max-players=10") == VENDOR_ISH


def test_set_repeated_key_updates_the_last_occurrence_only() -> None:
    doc = PropertiesDocument.parse("k=1\nk=2\nk=3\n")
    doc.set("k", "9")
    assert doc.serialize() == "k=1\nk=2\nk=9\n"


def test_new_key_is_appended_at_the_end() -> None:
    doc = PropertiesDocument.parse("a=1\n")
    assert doc.set("b", "2") is True
    assert doc.serialize() == "a=1\nb=2\n"


def test_setting_an_identical_value_is_a_no_op() -> None:
    doc = PropertiesDocument.parse("a=1\n")
    assert doc.set("a", "1") is False
    assert doc.serialize() == "a=1\n"


def test_unrecognised_keys_and_comments_survive_a_write() -> None:
    doc = PropertiesDocument.parse(VENDOR_ISH)
    doc.set("gamemode", "creative")
    out = doc.serialize()
    assert "# Bedrock server properties\n" in out
    assert "motd=a=b=c\n" in out
    assert "  gamemode=creative\n" in out  # indentation preserved


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    # 1.4 atomic persistence via a temp file renamed into place
    target = tmp_path / "server.properties"
    target.write_text("a=1\n")
    doc = PropertiesDocument.load(target)
    doc.set("a", "2")
    doc.save(target)
    assert target.read_text() == "a=2\n"
    assert [p.name for p in tmp_path.iterdir()] == ["server.properties"]


def test_interrupted_write_leaves_previous_content_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "server.properties"
    target.write_text("a=1\n")
    doc = PropertiesDocument.load(target)
    doc.set("a", "2")

    real_replace = os.replace

    def boom(src, dst):  # simulate a crash after the temp file is written
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(KeyboardInterrupt):
        doc.save(target)
    monkeypatch.setattr(os, "replace", real_replace)

    assert target.read_text() == "a=1\n"  # untouched
    assert [p.name for p in tmp_path.iterdir()] == ["server.properties"]  # temp cleaned up
