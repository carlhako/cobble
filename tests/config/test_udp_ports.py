"""The ``server-udp-ports`` grammar (network-settings tasks 1.1, 1.2)."""

from __future__ import annotations

import pytest

from cobble.config import udp_ports
from cobble.config.udp_ports import Entry, Form, Range

# The examples in the 1.26.51.1 bedrock_server_how_to.html, "UDP port
# configuration for NetherNet".
VENDOR_EXAMPLES = [
    "49152-49200",
    "19132-19232:32000-32100",
    "203.0.113.10:19132-19232:32000-32100",
    "[2001:db8::1]:19132-19232:32000-32100",
]


@pytest.mark.parametrize("value", VENDOR_EXAMPLES)
def test_every_vendor_example_parses(value: str) -> None:
    assert udp_ports.parse(value)


def test_parse_reads_each_form() -> None:
    assert udp_ports.parse("19140") == [Entry(internal=Range(19140, 19140))]
    assert udp_ports.parse("19140-19159") == [Entry(internal=Range(19140, 19159))]
    assert udp_ports.parse("203.0.113.10:19132-19232:32000-32100") == [
        Entry(
            internal=Range(32000, 32100),
            external=Range(19132, 19232),
            address="203.0.113.10",
        )
    ]
    assert udp_ports.parse("[2001:db8::1]:19132:32000") == [
        Entry(internal=Range(32000, 32000), external=Range(19132, 19132), address="[2001:db8::1]")
    ]
    assert len(udp_ports.parse("19140-19149, 19150-19159")) == 2


def test_empty_value_parses_to_no_entries() -> None:
    assert udp_ports.parse("") == []
    assert udp_ports.parse("  ") == []


def test_a_port_mapped_onto_a_range_is_allowed() -> None:
    # Only two ranges must match in length.
    assert udp_ports.parse("19132:32000-32100")


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("19159-19140", "starts after it ends"),
        ("abc", "not a port"),
        ("0", "outside 1-65535"),
        ("65536", "outside 1-65535"),
        ("19132-19140:32000-32100", "internal range has 101"),
        ("1.2.3:1:1", "not an IPv4 address"),
        ("2001:db8::1:19132:32000", "must be in brackets"),
        ("[2001:db8::zz]:1:1", "not an IPv6 address"),
        ("[::1]19132:32000", "followed by external:internal"),
        ("19140,,19150", "empty"),
        ("19140,", "empty"),
    ],
)
def test_malformed_values_raise_with_a_reason(value: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        udp_ports.parse(value)


def test_form_of_a_range_and_a_single_port() -> None:
    r = udp_ports.form("19140-19159")
    assert r == Form("range", 19140, 19159, None, None)
    assert Range(r.start, r.end).size == 20
    single = udp_ports.form("19140")
    assert single == Form("range", 19140, 19140, None, None)
    assert Range(single.start, single.end).size == 1


def test_form_of_empty_is_os() -> None:
    assert udp_ports.form("") == Form("os")


def test_a_mapping_is_a_range_form_with_its_local_and_forward_ports() -> None:
    value = "203.0.113.10:19132-19232:32000-32100"
    assert udp_ports.form(value).kind == "range"
    entries = udp_ports.parse(value)
    assert udp_ports.local_ports(entries) == [Range(32000, 32100)]
    assert udp_ports.forward_ports(entries) == [Range(19132, 19232)]


def test_several_entries_are_custom_and_merge_their_local_ports() -> None:
    value = "19140-19149,19150-19159"
    assert udp_ports.form(value).kind == "custom"
    local = udp_ports.local_ports(udp_ports.parse(value))
    assert local == [Range(19140, 19159)]
    assert udp_ports.port_count(local) == 20


def test_an_unparseable_value_is_custom() -> None:
    assert udp_ports.form("abc").kind == "custom"


def test_form_of_a_mapping_carries_external_and_address() -> None:
    f = udp_ports.form("203.0.113.10:19132-19232:32000-32100")
    assert f == Form("range", 32000, 32100, Range(19132, 19232), "203.0.113.10")
    h = udp_ports.form("play.example.com:19140-19150:19140-19150")
    assert h.address == "play.example.com"
    assert h.external == Range(19140, 19150)
    one = udp_ports.form("19132:19140-19150")
    assert one == Form("range", 19140, 19150, Range(19132, 19132), None)


def test_form_of_several_entries_or_garbage_is_custom() -> None:
    assert udp_ports.form("19140-19149,19160-19169").kind == "custom"
    assert udp_ports.form("abc").kind == "custom"


def test_forward_pairs_keep_external_and_internal_per_entry() -> None:
    assert udp_ports.forward_pairs(udp_ports.parse("19140-19159")) == [
        (Range(19140, 19159), Range(19140, 19159))
    ]
    assert udp_ports.forward_pairs(udp_ports.parse("19132-19142:19140-19150")) == [
        (Range(19132, 19142), Range(19140, 19150))
    ]
    assert udp_ports.forward_pairs(udp_ports.parse("19132:19140,19133-19134:19141-19142")) == [
        (Range(19132, 19132), Range(19140, 19140)),
        (Range(19133, 19134), Range(19141, 19142)),
    ]


@pytest.mark.parametrize(
    "value",
    [
        "play.example.com:19140-19150:19140-19150",
        "localhost:19140:19140",
        f"{'a' * 63}.example:1:1",
        "my-host.example.com:1:1",
    ],
)
def test_hostname_addresses_are_accepted(value: str) -> None:
    assert udp_ports.parse(value)[0].address == value.split(":")[0]


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("1.2.3.999:1:1", "not an IPv4 address"),
        ("1.2.3:1:1", "not an IPv4 address"),
        ("-bad.example:1:1", "valid hostname"),
        ("bad-.example:1:1", "valid hostname"),
        ("my_host:1:1", "valid hostname"),
        ("a..b:1:1", "valid hostname"),
        ("host.:1:1", "valid hostname"),
        (f"{'a' * 64}.example:1:1", "valid hostname"),
        (f"{'a.' * 126}com:1:1", "valid hostname"),
        ("2001:db8::1:19132:32000", "must be in brackets"),
    ],
)
def test_malformed_hostname_addresses_are_rejected(value: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        udp_ports.parse(value)


def test_range_renders_as_the_grammar_writes_it() -> None:
    assert str(Range(19140, 19159)) == "19140-19159"
    assert str(Range(19140, 19140)) == "19140"
