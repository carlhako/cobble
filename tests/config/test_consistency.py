"""The UDP capacity rule (network-settings task 3.4)."""

from __future__ import annotations

from cobble.config.consistency import consistency

NETHERNET = {"transport": "nethernet", "max-players": "10"}


def test_nethernet_with_a_small_range_warns_naming_both_numbers() -> None:
    [issue] = consistency({**NETHERNET, "server-udp-ports": "19140-19144"}, None)
    assert issue.key == "server-udp-ports" and issue.severity == "warning"
    assert "5 UDP ports" in issue.message and "max-players is 10" in issue.message


def test_a_range_covering_the_limit_is_fine() -> None:
    assert consistency({**NETHERNET, "server-udp-ports": "19140-19159"}, None) == []
    assert consistency({**NETHERNET, "server-udp-ports": "19140-19149"}, None) == []


def test_no_range_pinned_is_fine() -> None:
    assert consistency(NETHERNET, None) == []
    assert consistency({**NETHERNET, "server-udp-ports": ""}, None) == []


def test_raknet_ignores_a_small_range() -> None:
    effective = {"transport": "raknet", "max-players": "10", "server-udp-ports": "19140"}
    assert consistency(effective, None) == []


def test_an_absent_transport_falls_back_to_the_recommended_one() -> None:
    effective = {"max-players": "10", "server-udp-ports": "19140-19144"}
    assert consistency(effective, "raknet") == []
    assert len(consistency(effective, "nethernet")) == 1
    # Version default unknown: cobble's schema default (nethernet) applies.
    assert len(consistency(effective, None)) == 1


def test_a_non_integer_max_players_skips_the_rule() -> None:
    effective = {**NETHERNET, "max-players": "lots", "server-udp-ports": "19140"}
    assert consistency(effective, None) == []


def test_a_malformed_range_skips_the_rule() -> None:
    assert consistency({**NETHERNET, "server-udp-ports": "abc"}, None) == []


def test_a_multi_entry_value_counts_its_local_ports() -> None:
    value = "19140-19144,[::1]:1-4:32000-32003"  # 5 + 4 local ports
    [issue] = consistency({**NETHERNET, "server-udp-ports": value}, None)
    assert "9 UDP ports" in issue.message
    assert consistency({**NETHERNET, "max-players": "9", "server-udp-ports": value}, None) == []
