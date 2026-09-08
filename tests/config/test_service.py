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
    settings = {s.key: s for s in env.service().read()}
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
    assert {s.key: s.value for s in env.service().read()} == {"max-players": "25"}


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
