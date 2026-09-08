"""Section 2: the property schema and value validation (tasks 2.1-2.4)."""

from __future__ import annotations

from cobble.config.schema import SCHEMA, PropertyType, lookup, validate

# The keys a freshly extracted BDS server.properties ships. Keys deliberately
# left unrecognised (float-typed) are listed separately so the intent is explicit
# (task 2.1: every vendor key is either in the table or deliberately absent).
VENDOR_KEYS = {
    "server-name",
    "gamemode",
    "force-gamemode",
    "difficulty",
    "allow-cheats",
    "max-players",
    "online-mode",
    "allow-list",
    "server-port",
    "server-portv6",
    "enable-lan-visibility",
    "view-distance",
    "tick-distance",
    "player-idle-timeout",
    "max-threads",
    "level-name",
    "level-seed",
    "default-player-permission-level",
    "texturepack-required",
    "content-log-file-enabled",
    "compression-threshold",
    "compression-algorithm",
    "server-authoritative-movement",
    "correct-player-movement",
    "server-authoritative-block-breaking",
    "chat-restriction",
    "disable-player-interaction",
    "client-side-chunk-generation-enabled",
    "block-network-ids-are-hashes",
    "disable-persona",
    "disable-custom-skins",
}

DELIBERATELY_UNRECOGNISED = {
    "player-movement-score-threshold",
    "player-movement-action-direction-threshold",
    "player-movement-distance-threshold",
    "player-movement-duration-threshold-in-ms",
    "server-build-radius-ratio",
}


def test_every_vendor_key_is_recognised() -> None:
    assert VENDOR_KEYS <= set(SCHEMA)


def test_deliberately_unrecognised_keys_are_absent() -> None:
    assert DELIBERATELY_UNRECOGNISED.isdisjoint(SCHEMA)


def test_schema_entries_are_internally_consistent() -> None:
    for key, entry in SCHEMA.items():
        assert entry.key == key
        if entry.type is PropertyType.ENUM:
            assert entry.members and entry.default in entry.members
        if entry.type is PropertyType.BOOL:
            assert entry.default in ("true", "false")


def test_lookup_classifies_recognised_and_unrecognised() -> None:
    # 2.2
    assert lookup("difficulty") is not None
    assert lookup("some-operator-key") is None


def test_wrong_type_is_rejected_with_a_reason() -> None:
    # 2.3
    non_int = validate("max-players", "lots")
    assert non_int is not None and non_int.severity == "error"
    non_bool = validate("allow-cheats", "yes")
    assert non_bool is not None and non_bool.severity == "error"
    bad_enum = validate("difficulty", "brutal")
    assert bad_enum is not None and bad_enum.severity == "error"


def test_in_range_and_valid_values_pass() -> None:
    assert validate("max-players", "12") is None
    assert validate("allow-cheats", "true") is None
    assert validate("difficulty", "hard") is None
    assert validate("server-name", "anything at all") is None


def test_out_of_range_value_is_a_warning_not_a_rejection() -> None:
    # 2.4 correct type, outside the recorded range -> warning naming the range
    issue = validate("view-distance", "500")
    assert issue is not None and issue.severity == "warning"
    assert "range" in issue.message


def test_unrecognised_key_is_never_rejected() -> None:
    assert validate("operator-added-key", "whatever") is None
