"""The network view (network-settings task 4.1)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from cobble.acquisition.layout import Layout
from cobble.config.service import ConfigService
from cobble.settings import Settings
from cobble.supervisor.supervisor import Supervisor


class Net:
    def __init__(self, layout: Layout, svc: ConfigService) -> None:
        self.layout = layout
        self.svc = svc

    def vendor(self, transport: str) -> None:
        vdir = self.layout.version_dir("1.26.51.1")
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "server.properties").write_text(f"server-port=19132\ntransport={transport}\n")

    def view(self, text: str) -> dict:
        (self.layout.data_dir / "server.properties").write_text(text)
        return self.svc.network()


@pytest.fixture
def net(install_fake_bedrock: Callable[..., Settings]) -> Net:
    settings = install_fake_bedrock("1.26.51.1")
    layout = Layout.from_settings(settings)
    n = Net(layout, ConfigService(settings, layout, Supervisor(settings)))
    n.vendor("nethernet")
    return n


def _settings(layout: dict) -> dict[str, dict]:
    return {s["key"]: s for s in layout["settings"]}


def test_nethernet_with_a_pinned_range(net: Net) -> None:
    view = net.view("transport=nethernet\nserver-port=19132\nserver-udp-ports=19140-19159\n")
    assert view["layout"] == "nethernet"
    layout = view["layouts"]["nethernet"]
    settings = _settings(layout)
    assert list(settings) == ["server-port", "server-ip", "server-udp-ports"]
    assert settings["server-port"]["protocol"] == "tcp"
    assert settings["server-ip"] == {
        "key": "server-ip",
        "value": "",
        "present": False,
        "protocol": None,
        "label": "Bind address",
    }
    assert layout["udp_range"] == {"form": "range", "start": 19140, "end": 19159, "size": 20}
    assert layout["lan_discovery"] == {"protocol": "udp", "port": 7551}
    assert layout["forward"] == [
        {"protocol": "tcp", "ports": "19132"},
        {"protocol": "udp", "ports": "19140-19159"},
    ]
    assert layout["pin_required"] is False
    assert view["conflicts"] == []


def test_nethernet_with_the_os_picking_ports_requires_a_pin(net: Net) -> None:
    layout = net.view("transport=nethernet\nserver-port=19132\n")["layouts"]["nethernet"]
    assert layout["udp_range"] == {"form": "os"}
    assert layout["pin_required"] is True
    assert layout["forward"] == [{"protocol": "tcp", "ports": "19132"}]


def test_nethernet_custom_mapping_forwards_the_external_ports(net: Net) -> None:
    value = "203.0.113.10:19132-19232:32000-32100"
    layout = net.view(f"transport=nethernet\nserver-udp-ports={value}\n")["layouts"]["nethernet"]
    assert layout["udp_range"] == {
        "form": "custom",
        "value": value,
        "local": [{"start": 32000, "end": 32100}],
        "size": 101,
    }
    # server-port absent: its default applies.
    assert layout["forward"] == [
        {"protocol": "tcp", "ports": "19132"},
        {"protocol": "udp", "ports": "19132-19232"},
    ]
    assert layout["pin_required"] is False


def test_raknet_lists_udp_ports_with_ipv6_marked(net: Net) -> None:
    view = net.view(
        "transport=raknet\nserver-port=19132\nserver-portv6=19133\nserver-udp-ports=19140\n"
    )
    assert view["layout"] == "raknet"
    layout = view["layouts"]["raknet"]
    settings = _settings(layout)
    assert list(settings) == ["server-port", "server-portv6"]
    assert {s["protocol"] for s in settings.values()} == {"udp"}
    assert layout["forward"] == [
        {"protocol": "udp", "ports": "19132"},
        {"protocol": "udp", "ports": "19133", "note": "Only needed for IPv6 players."},
    ]
    assert layout["udp_range"] is None and layout["lan_discovery"] is None
    assert layout["pin_required"] is False
    assert view["conflicts"] == []  # a small range is irrelevant under RakNet


def test_an_absent_transport_resolves_to_the_version_default(net: Net) -> None:
    assert net.view("server-name=x\n")["layout"] == "nethernet"
    net.vendor("raknet")
    view = net.view("server-name=x\n")
    assert view["layout"] == "raknet"
    assert view["transport"]["recommended"] == "raknet"


def test_the_view_carries_the_capacity_conflict(net: Net) -> None:
    view = net.view("transport=nethernet\nmax-players=10\nserver-udp-ports=19140-19144\n")
    assert [c["key"] for c in view["conflicts"]] == ["server-udp-ports"]
