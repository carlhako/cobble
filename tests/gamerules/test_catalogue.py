"""The static rule catalogue (task 2.1)."""

from __future__ import annotations

from cobble.gamerules.catalogue import CATALOGUE, RuleType, catalogue_defaults, lookup
from tests.gamerules.dump import EXPECTED_PAIRS


def test_catalogue_covers_the_39_reported_rules() -> None:
    reported = {name for name, _ in EXPECTED_PAIRS}
    catalogued = {rule.name for rule in CATALOGUE}
    assert catalogued == reported
    assert len(CATALOGUE) == 39


def test_every_rule_has_a_type() -> None:
    for rule in CATALOGUE:
        assert isinstance(rule.type, RuleType)


def test_shape_counts_match_the_spike() -> None:
    kinds = [rule.type for rule in CATALOGUE]
    assert kinds.count(RuleType.BOOL) == 33
    assert kinds.count(RuleType.INT) == 5
    assert kinds.count(RuleType.ENUM) == 1


def test_integer_rules_carry_a_bound() -> None:
    ints = [r for r in CATALOGUE if r.type is RuleType.INT]
    assert {r.name for r in ints} == {
        "maxCommandChainLength",
        "randomTickSpeed",
        "functionCommandLimit",
        "spawnRadius",
        "playersSleepingPercentage",
    }
    for rule in ints:
        assert rule.minimum is not None or rule.maximum is not None
    assert lookup("randomTickSpeed").maximum == 4096  # the server-stated bound


def test_enum_rule_has_members() -> None:
    (enum_rule,) = [r for r in CATALOGUE if r.type is RuleType.ENUM]
    assert enum_rule.name == "playerWaypoints"
    assert "everyone" in enum_rule.members


def test_lookup_is_case_insensitive() -> None:
    assert lookup("MOBGRIEFING").name == "mobGriefing"
    assert lookup("  keepinventory ").name == "keepInventory"
    assert lookup("notarealrule") is None


def test_defaults_match_the_observed_dump() -> None:
    defaults = catalogue_defaults()
    assert defaults["keepInventory"] is False
    assert defaults["mobGriefing"] is True
    assert defaults["randomTickSpeed"] == 1
    assert defaults["maxCommandChainLength"] == 65535
    assert defaults["playerWaypoints"] == "everyone"
