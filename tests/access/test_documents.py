"""``allowlist.json`` / ``permissions.json`` round-tripping (tasks 1.1-1.6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cobble.access.documents import (
    AllowlistDocument,
    AllowlistFile,
    PermissionsDocument,
    PermissionsFile,
    UnreadableDocumentError,
)

# The verbatim BDS format from design.md Context: three-space indent, spaced
# colon, and BDS omits the xuid from allowlist entries it writes.
BDS_PERMISSIONS = (
    '[\n   {\n      "permission" : "operator",\n      "xuid" : "2535411234567890"\n   }\n]\n'
)
BDS_ALLOWLIST = '[{"ignoresPlayerLimit":false,"name":"Alex"}]'


# -- 1.1 round-trip preserves unrecognised fields ------------------
def test_allowlist_round_trips_an_unknown_field(tmp_path: Path) -> None:
    src = json.dumps([{"name": "Sam", "ignoresPlayerLimit": True, "mysteryField": {"a": 1}}])
    doc = AllowlistDocument.parse(src)
    (entry,) = doc.entries
    assert entry.extra["mysteryField"] == {"a": 1}
    # a mutation elsewhere still preserves the unknown field on this entry
    doc.upsert("NewPlayer")
    round_tripped = json.loads(doc.serialize())
    sam = next(e for e in round_tripped if e["name"] == "Sam")
    assert sam["mysteryField"] == {"a": 1}
    assert sam["ignoresPlayerLimit"] is True


def test_permissions_round_trips_an_unknown_field(tmp_path: Path) -> None:
    src = json.dumps([{"xuid": "1", "permission": "operator", "note": "founder"}])
    doc = PermissionsDocument.parse(src)
    doc.set_level("2", "operator")
    obj = json.loads(doc.serialize())
    founder = next(e for e in obj if e["xuid"] == "1")
    assert founder["note"] == "founder"


# -- 1.2 empty is folded; empty writes as [] ----------------------
@pytest.mark.parametrize("text", ["null", "[]", "", "   \n"])
def test_allowlist_empty_forms_read_as_empty(text: str) -> None:
    doc = AllowlistDocument.parse(text)
    assert doc.readable is True
    assert doc.entries == ()


def test_allowlist_literal_null_from_design_context() -> None:
    # design.md D8 / Context: BDS writes literal ``null`` when the last entry is
    # removed. It must read as empty with no exception.
    doc = AllowlistDocument.parse("null")
    assert doc.entries == ()


def test_allowlist_absent_file_reads_empty(tmp_path: Path) -> None:
    doc = AllowlistDocument.load(tmp_path / "nope.json")
    assert doc.readable is True
    assert doc.entries == ()


def test_writing_empty_allowlist_produces_bracket_pair(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text('[{"name":"Only"}]')
    AllowlistFile(path).mutate(lambda d: d.remove(name="Only"))
    assert path.read_text().strip() == "[]"


def test_writing_empty_permissions_produces_bracket_pair() -> None:
    doc = PermissionsDocument.parse('[{"xuid":"1","permission":"operator"}]')
    doc.set_level("1", "member")  # member removes the row
    assert doc.serialize().strip() == "[]"


# -- 1.3 unparseable reports a condition, file untouched ---------
def test_unparseable_allowlist_is_reported_not_raised(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text("{ this is not json ]")
    doc = AllowlistFile(path).read()
    assert doc.readable is False
    assert doc.entries == ()


def test_mutating_an_unreadable_file_refuses_and_leaves_it_untouched(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    original = "{ not json"
    path.write_text(original)
    with pytest.raises(UnreadableDocumentError):
        AllowlistFile(path).mutate(lambda d: d.upsert("Anyone"))
    assert path.read_text() == original


# -- 1.4 permissions.json byte-identical round-trip -------------
def test_permissions_bds_format_round_trips_byte_identical(tmp_path: Path) -> None:
    path = tmp_path / "permissions.json"
    path.write_text(BDS_PERMISSIONS)
    doc = PermissionsFile(path).read()
    assert doc.serialize() == BDS_PERMISSIONS
    # a no-op mutate does not rewrite the file
    PermissionsFile(path).mutate(lambda d: d.set_level("2535411234567890", "operator"))
    assert path.read_text() == BDS_PERMISSIONS


def test_permissions_write_uses_bds_indent_and_spaced_colon() -> None:
    doc = PermissionsDocument.parse("[]")
    doc.set_level("999", "operator")
    text = doc.serialize()
    assert '"permission" : "operator"' in text
    assert "\n   {\n" in text  # three-space indent


def test_allowlist_bds_compact_form_round_trips_byte_identical(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text(BDS_ALLOWLIST)
    doc = AllowlistFile(path).read()
    assert doc.serialize() == BDS_ALLOWLIST


# -- 1.5 atomic write survives interruption ---------------------
def test_interrupted_write_leaves_the_previous_file_intact(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text(BDS_ALLOWLIST)

    import cobble.access.documents as mod

    real_replace = mod.os.replace

    def boom(src, dst):
        raise OSError("interrupted before the rename")

    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError):
        AllowlistFile(path).mutate(lambda d: d.upsert("Bailey"))
    monkeypatch.setattr(mod.os, "replace", real_replace)
    assert path.read_text() == BDS_ALLOWLIST
    # no stray temp files left behind
    assert list(tmp_path.glob(".allowlist.json.*")) == []


# -- 1.6 re-read before every write (no stale view) -------------
def test_write_is_based_on_the_newest_content(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text('[{"ignoresPlayerLimit":false,"name":"Alex"}]')
    handle = AllowlistFile(path)

    first_view = handle.read()
    assert [e.name for e in first_view.entries] == ["Alex"]

    # an out-of-band edit lands between the read above and the write below
    path.write_text(
        '[{"ignoresPlayerLimit":false,"name":"Alex"},{"ignoresPlayerLimit":false,"name":"Robin"}]'
    )

    handle.mutate(lambda d: d.upsert("Casey"))
    names = {e.name for e in handle.read().entries}
    assert names == {"Alex", "Robin", "Casey"}  # Robin (the out-of-band add) survived


# -- identifier reporting (server-access spec) -------------------
def test_entry_identifier_is_distinguishable() -> None:
    doc = AllowlistDocument.parse(
        json.dumps([{"name": "WithId", "xuid": "5"}, {"name": "NameOnly"}])
    )
    by = {e.name: e for e in doc.entries}
    assert by["WithId"].has_identifier is True
    assert by["NameOnly"].has_identifier is False
    assert by["NameOnly"].xuid is None


def test_name_with_spaces_survives_a_write() -> None:
    doc = AllowlistDocument.parse("[]")
    doc.upsert("Some Player With Spaces")
    obj = json.loads(doc.serialize())
    assert obj[0]["name"] == "Some Player With Spaces"
