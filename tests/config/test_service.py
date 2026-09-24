"""Section 3: the configuration service (tasks 3.1-3.5)."""

from __future__ import annotations

import pytest

from cobble.acquisition.layout import Layout
from cobble.config.service import ConfigService
from cobble.settings import Settings
from cobble.supervisor.supervisor import MaintenanceInProgressError

SAMPLE = (
    "# vendor comment\n"
    "server-name=Dedicated Server\n"
    "gamemode=survival\n"
    "difficulty=easy\n"
    "max-players=10\n"
    "view-distance=32\n"
    "level-name=Bedrock level\n"
    "operator-added-key=kept\n"
)


class FakeSupervisor:
    def __init__(self, *, maintenance=None, config_snapshot=None) -> None:
        self.maintenance = maintenance
        self.config_snapshot = config_snapshot


class Env:
    def __init__(self, settings: Settings, layout: Layout) -> None:
        self.settings = settings
        self.layout = layout
        self.props = layout.data_dir / "server.properties"
        self.calls: list[int] = []

    def service(self, **super_kw) -> ConfigService:
        return ConfigService(
            self.settings,
            self.layout,
            FakeSupervisor(**super_kw),
            on_change=lambda: self.calls.append(1),
        )

    def text(self) -> str:
        return self.props.read_text()


@pytest.fixture
def env(tmp_settings: Settings) -> Env:
    layout = Layout.from_settings(tmp_settings)
    layout.ensure_directories()
    (layout.data_dir / "server.properties").write_text(SAMPLE)
    return Env(tmp_settings, layout)


def test_read_returns_every_setting_with_schema_for_recognised(env: Env) -> None:
    # 3.1
    settings = {s.key: s for s in env.service().read() if s.present}
    assert set(settings) == {
        "server-name",
        "gamemode",
        "difficulty",
        "max-players",
        "view-distance",
        "level-name",
        "operator-added-key",
    }
    assert settings["difficulty"].recognised
    assert settings["difficulty"].schema is not None
    assert settings["difficulty"].schema.default == "easy"
    assert not settings["operator-added-key"].recognised
    assert settings["operator-added-key"].schema is None


def test_read_succeeds_while_the_server_is_stopped(env: Env) -> None:
    assert env.service(config_snapshot=None).read()  # no error, non-empty


def test_read_reports_the_effective_value_for_a_repeated_key(env: Env) -> None:
    env.props.write_text("max-players=10\nmax-players=25\n")
    assert {s.key: s.value for s in env.service().read() if s.present} == {"max-players": "25"}


def test_batch_write_is_all_or_nothing_on_an_invalid_value(env: Env) -> None:
    # 3.2
    svc = env.service()
    before = env.text()
    result = svc.write({"difficulty": "hard", "max-players": "not-a-number"})
    assert not result.ok
    assert [i.key for i in result.errors] == ["max-players"]
    assert env.text() == before
    assert env.calls == []  # no status push on a rejected write


def test_batch_write_persists_all_valid_values(env: Env) -> None:
    result = env.service().write({"difficulty": "hard", "gamemode": "creative"})
    assert result.ok and set(result.changed) == {"difficulty", "gamemode"}
    assert "difficulty=hard\n" in env.text() and "gamemode=creative\n" in env.text()
    assert env.calls == [1]


def test_write_of_identical_values_leaves_the_file_untouched(env: Env) -> None:
    before = env.text()
    result = env.service().write({"difficulty": "easy"})
    assert result.ok and result.changed == ()
    assert env.text() == before
    assert env.calls == []


def test_out_of_range_value_is_persisted_with_a_warning(env: Env) -> None:
    # 2.4 / 3.2 through the service
    result = env.service().write({"view-distance": "500"})
    assert result.ok
    assert [i.key for i in result.warnings] == ["view-distance"]
    assert "view-distance=500\n" in env.text()


def test_unrecognised_key_write_is_persisted(env: Env) -> None:
    result = env.service().write({"operator-added-key": "changed", "brand-new-key": "v"})
    assert result.ok
    assert "operator-added-key=changed\n" in env.text()
    assert env.text().rstrip().endswith("brand-new-key=v")


def test_write_is_refused_during_maintenance_and_read_still_works(env: Env) -> None:
    # 3.3
    svc = env.service(maintenance="updating")
    before = env.text()
    with pytest.raises(MaintenanceInProgressError):
        svc.write({"difficulty": "hard"})
    assert env.text() == before
    assert svc.read()  # reads remain available


def test_worlds_enumeration_marks_the_current_and_the_missing(env: Env) -> None:
    # 3.4
    (env.layout.data_dir / "worlds" / "Bedrock level").mkdir(parents=True)
    (env.layout.data_dir / "worlds" / "Creative Flats").mkdir()
    view = env.service().worlds()
    assert [w.name for w in view.worlds] == ["Bedrock level", "Creative Flats"]
    assert view.current == "Bedrock level"
    assert view.current_present
    assert [w.name for w in view.worlds if w.is_current] == ["Bedrock level"]


def test_worlds_reports_the_current_value_when_its_directory_is_absent(env: Env) -> None:
    env.props.write_text("level-name=Nether Only\n")
    view = env.service().worlds()
    assert view.current == "Nether Only"
    assert not view.current_present


def test_worlds_returns_empty_without_error_when_none_exist(env: Env) -> None:
    assert env.service().worlds().worlds == ()


def test_selecting_a_nonexistent_world_is_accepted_with_a_note(env: Env) -> None:
    # 3.5
    result = env.service().write({"level-name": "Brand New World"})
    assert result.ok
    assert any("new, empty world will be created" in n for n in result.notes)
    assert "level-name=Brand New World\n" in env.text()


def test_selecting_an_existing_world_carries_no_new_world_note(env: Env) -> None:
    (env.layout.data_dir / "worlds" / "Existing").mkdir(parents=True)
    result = env.service().write({"level-name": "Existing"})
    assert result.ok and result.notes == ()


# -- network-settings: unset recognised settings (task 3.2) -----------------


def test_a_recognised_key_absent_from_the_file_is_read_as_not_set(env: Env) -> None:
    before = env.text()
    settings = {s.key: s for s in env.service().read()}
    udp = settings["server-udp-ports"]
    assert udp.present is False and udp.recognised and udp.value == ""
    assert udp.to_dict()["present"] is False
    assert settings["difficulty"].present is True
    # Unset keys come after every key in the file, which keep file order.
    keys = [s.key for s in env.service().read()]
    assert keys[:7] == [
        "server-name",
        "gamemode",
        "difficulty",
        "max-players",
        "view-distance",
        "level-name",
        "operator-added-key",
    ]
    assert env.text() == before  # reading never writes


def test_writing_an_unset_key_adds_it_and_it_then_reads_as_present(env: Env) -> None:
    svc = env.service()
    result = svc.write({"server-udp-ports": "19140-19159"})
    assert result.ok and result.changed == ("server-udp-ports",)
    assert env.text().endswith("server-udp-ports=19140-19159\n")
    udp = {s.key: s for s in svc.read()}["server-udp-ports"]
    assert udp.present is True and udp.value == "19140-19159"


def test_a_malformed_udp_range_is_rejected_and_nothing_is_written(env: Env) -> None:
    before = env.text()
    result = env.service().write({"server-udp-ports": "19159-19140", "difficulty": "hard"})
    assert not result.ok
    assert [i.key for i in result.errors] == ["server-udp-ports"]
    assert env.text() == before


# -- network-settings: the accumulating key (task 3.3) ----------------------

SPLIT = (
    SAMPLE
    + "server-udp-ports=19140-19149\n"
    + "# more\n"
    + "server-udp-ports=\n"
    + "server-udp-ports=19150-19159\n"
)


def test_a_split_udp_range_reads_as_its_entries_combined(env: Env) -> None:
    env.props.write_text(SPLIT)
    udp = {s.key: s for s in env.service().read()}["server-udp-ports"]
    assert udp.present and udp.value == "19140-19149,19150-19159"


def test_a_write_to_a_split_udp_range_is_rejected_and_the_file_is_unchanged(env: Env) -> None:
    env.props.write_text(SPLIT)
    result = env.service().write({"server-udp-ports": "19140-19169"})
    assert not result.ok
    assert [i.key for i in result.errors] == ["server-udp-ports"]
    assert "by hand" in result.errors[0].message
    assert env.text() == SPLIT


def test_resubmitting_a_split_udp_range_unchanged_leaves_its_lines_alone(env: Env) -> None:
    env.props.write_text(SPLIT)
    result = env.service().write({"server-udp-ports": "19140-19149,19150-19159"})
    assert result.ok and result.changed == ()
    assert env.text() == SPLIT


# -- network-settings: capacity conflicts on read and write (task 3.5) -------


def _pinned(env: Env, udp: str, players: str = "10") -> None:
    env.props.write_text(
        SAMPLE.replace("max-players=10", f"max-players={players}")
        + f"transport=nethernet\nserver-udp-ports={udp}\n"
    )


def test_a_read_reports_the_capacity_conflict(env: Env) -> None:
    _pinned(env, "19140-19144")
    [conflict] = env.service().conflicts()
    assert conflict.key == "server-udp-ports" and conflict.severity == "warning"


def test_raising_max_players_past_the_range_is_accepted_with_the_warning(env: Env) -> None:
    _pinned(env, "19140-19149")
    svc = env.service()
    assert svc.conflicts() == []
    result = svc.write({"max-players": "20"})
    assert result.ok and "max-players=20\n" in env.text()
    assert [i.key for i in result.warnings] == ["server-udp-ports"]
    assert "10 UDP ports" in result.warnings[0].message
    assert list(result.conflicts) == list(result.warnings)


def test_narrowing_the_range_below_max_players_is_accepted_with_the_warning(env: Env) -> None:
    _pinned(env, "19140-19159")
    result = env.service().write({"server-udp-ports": "19140-19144"})
    assert result.ok and "server-udp-ports=19140-19144\n" in env.text()
    assert [i.key for i in result.warnings] == ["server-udp-ports"]
    assert [i.key for i in result.conflicts] == ["server-udp-ports"]


def test_widening_the_range_clears_the_conflict_on_the_write_and_later_reads(env: Env) -> None:
    _pinned(env, "19140-19144")
    svc = env.service()
    result = svc.write({"server-udp-ports": "19140-19159"})
    assert result.ok and result.warnings == () and result.conflicts == ()
    assert svc.conflicts() == []


def test_an_unrelated_write_reports_conflicts_but_no_new_warning(env: Env) -> None:
    _pinned(env, "19140-19144")
    result = env.service().write({"difficulty": "hard"})
    assert result.ok and result.warnings == ()
    assert [i.key for i in result.conflicts] == ["server-udp-ports"]
