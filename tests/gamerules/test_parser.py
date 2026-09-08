"""The bulk-dump parser and value coercion (tasks 2.2, 2.3)."""

from __future__ import annotations

from cobble.gamerules.parser import (
    looks_like_bulk_dump,
    parse_bulk_dump,
    parse_pairs,
)
from tests.gamerules.dump import DUMP_BODY, DUMP_LINE, EXPECTED_PAIRS


# -- 2.2 the verbatim 39-rule line -----------------------------------
def test_parses_all_39_names_and_values() -> None:
    pairs = parse_pairs(DUMP_LINE)
    assert len(pairs) == 39
    assert list(pairs.items()) == list(EXPECTED_PAIRS)
    assert pairs["playerWaypoints"] == "everyone"
    assert pairs["maxCommandChainLength"] == "65535"


def test_prefix_is_optional() -> None:
    assert parse_pairs(DUMP_BODY) == parse_pairs(DUMP_LINE)


def test_shape_matcher_accepts_the_dump_and_rejects_noise() -> None:
    assert looks_like_bulk_dump(DUMP_LINE)
    assert looks_like_bulk_dump(DUMP_BODY)
    assert not looks_like_bulk_dump("[INFO] mobgriefing = true")
    assert not looks_like_bulk_dump("[INFO] Player connected: Steve, xuid: 123")
    assert not looks_like_bulk_dump("[INFO] Game rule mobgriefing has been updated to false")


# -- 2.3 coercion by type ------------------------------------------
def test_booleans_are_bool_and_ints_are_int() -> None:
    gs = parse_bulk_dump(DUMP_LINE)
    assert gs.get("mobGriefing").value is True
    assert gs.get("keepInventory").value is False
    assert gs.get("randomTickSpeed").value == 1
    assert isinstance(gs.get("randomTickSpeed").value, int)
    assert gs.get("maxCommandChainLength").value == 65535
    assert gs.get("playerWaypoints").value == "everyone"
    for rule in gs:
        assert rule.recognised is True


def test_value_map_is_typed() -> None:
    vm = parse_bulk_dump(DUMP_LINE).value_map()
    assert vm["mobGriefing"] is True
    assert vm["spawnRadius"] == 10
    assert len(vm) == 39


# -- 2.3 an uncatalogued rule survives, marked unrecognised -------
def test_unknown_rule_carried_through_with_raw_value_and_marker() -> None:
    injected = DUMP_LINE + ", futureRule = wobble"
    gs = parse_bulk_dump(injected)
    assert len(gs) == 40
    unknown = gs.get("futureRule")
    assert unknown is not None
    assert unknown.recognised is False
    assert unknown.type is None
    assert unknown.raw == "wobble"
    assert unknown.value == "wobble"  # carried through unchanged
    # recognised rules are still coerced alongside it
    assert gs.get("mobGriefing").value is True
