"""Section 2: the property schema and value validation (tasks 2.1-2.4)."""

from __future__ import annotations

from cobble.config.schema import SCHEMA, PropertyType, lookup, validate

# Every key in the server.properties BDS 1.26.45.1 ships, captured verbatim from
# a freshly installed server (task 2.1: every vendor key is in the table). If a
# newer BDS adds or renames a key, this set and SCHEMA are updated together.
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
    "transport",
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
    "content-log-console-output-enabled",
    "content-log-level",
    "compression-threshold",
    "compression-algorithm",
    "server-authoritative-movement-strict",
    "server-authoritative-dismount-strict",
    "server-authoritative-entity-interactions-strict",
    "player-position-acceptance-threshold",
    "player-movement-action-direction-threshold",
    "server-authoritative-block-breaking-pick-range-scalar",
    "chat-restriction",
    "disable-player-interaction",
    "client-side-chunk-generation-enabled",
    "block-network-ids-are-hashes",
    "disable-persona",
    "disable-custom-skins",
    "server-build-radius-ratio",
    "allow-outbound-script-debugging",
    "allow-inbound-script-debugging",
    "script-debugger-auto-attach",
}


def test_every_vendor_key_is_recognised() -> None:
    missing = VENDOR_KEYS - set(SCHEMA)
    assert not missing, f"vendor keys missing from the schema: {sorted(missing)}"


def test_schema_entries_are_internally_consistent() -> None:
    for key, entry in SCHEMA.items():
        assert entry.key == key
        # A recorded default must itself be a valid value for the key.
        assert validate(key, entry.default) is None, key
        if entry.type is PropertyType.ENUM:
            assert entry.members and entry.default in entry.members
        if entry.type is PropertyType.BOOL:
            assert entry.default in ("true", "false")
        if entry.type in (PropertyType.INT, PropertyType.FLOAT) and entry.minimum is not None:
            assert entry.maximum is None or entry.minimum <= entry.maximum


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


def test_float_keys_accept_decimals_reject_non_numbers_and_warn_out_of_range() -> None:
    assert validate("player-position-acceptance-threshold", "0.75") is None
    bad = validate("player-position-acceptance-threshold", "loose")
    assert bad is not None and bad.severity == "error"
    warn = validate("player-movement-action-direction-threshold", "2.5")  # range 0.0-1.0
    assert warn is not None and warn.severity == "warning"


def test_int_key_still_rejects_a_decimal() -> None:
    issue = validate("max-players", "10.5")
    assert issue is not None and issue.severity == "error"


def test_unrecognised_key_is_never_rejected() -> None:
    assert validate("operator-added-key", "whatever") is None
