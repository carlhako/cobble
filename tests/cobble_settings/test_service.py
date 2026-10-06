"""cobble-settings: the timezone store, validation and host-zone detection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cobble.cobble_settings.service import CobbleSettingsService, InvalidTimezone, format_offset
from cobble.cobble_settings.store import CobbleSettingsStore

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _service(tmp_path: Path, *, env=None, tz_file=None, localtime=None, on_change=None):
    return CobbleSettingsService(
        CobbleSettingsStore(tmp_path / "cobble_settings.json"),
        on_change=on_change,
        env={} if env is None else env,
        etc_timezone=tz_file or tmp_path / "no-etc-timezone",
        etc_localtime=localtime or tmp_path / "no-etc-localtime",
        clock=lambda: _NOW,
    )


def test_set_clear_and_persist_across_a_new_store(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    assert svc.timezone is None
    svc.set_timezone("Australia/Brisbane")
    assert svc.timezone == "Australia/Brisbane"
    assert _service(tmp_path).timezone == "Australia/Brisbane"
    svc.set_timezone(None)
    assert _service(tmp_path).timezone is None


def test_unknown_name_is_rejected_and_the_saved_value_is_unchanged(tmp_path: Path) -> None:
    called: list[int] = []
    svc = _service(tmp_path, on_change=lambda: called.append(1))
    svc.set_timezone("Europe/London")
    called.clear()
    with pytest.raises(InvalidTimezone, match="not recognised"):
        svc.set_timezone("Mars/Olympus_Mons")
    assert svc.timezone == "Europe/London"
    assert _service(tmp_path).timezone == "Europe/London"
    assert called == []


def test_on_change_fires_after_a_successful_write(tmp_path: Path) -> None:
    called: list[int] = []
    svc = _service(tmp_path, on_change=lambda: called.append(1))
    svc.set_timezone("UTC")
    assert called == [1]


@pytest.mark.parametrize("content", ["{not json", "[]", '{"timezone": 5}', '{"timezone": ""}'])
def test_corrupt_file_reads_as_unset(tmp_path: Path, content: str) -> None:
    (tmp_path / "cobble_settings.json").write_text(content)
    assert _service(tmp_path).timezone is None


def test_saved_name_that_is_no_longer_valid_falls_back_to_the_host(tmp_path: Path) -> None:
    (tmp_path / "cobble_settings.json").write_text(json.dumps({"timezone": "Mars/Base"}))
    svc = _service(tmp_path, env={"TZ": "Europe/Berlin"})
    assert svc.effective_zone_name() == "Europe/Berlin"


def test_effective_zone_prefers_the_saved_name_over_the_host(tmp_path: Path) -> None:
    svc = _service(tmp_path, env={"TZ": "Europe/Berlin"})
    svc.set_timezone("Australia/Brisbane")
    assert svc.effective_zone_name() == "Australia/Brisbane"
    assert svc.effective_offset() == "+10:00"
    assert svc.host_zone_name() == "Europe/Berlin"


def test_host_zone_prefers_tz_then_etc_timezone_then_localtime_then_offset(
    tmp_path: Path,
) -> None:
    tz_file = tmp_path / "timezone"
    tz_file.write_text("Asia/Tokyo\n")
    link = tmp_path / "localtime"
    link.symlink_to("/usr/share/zoneinfo/Europe/Paris")

    svc = _service(tmp_path, env={"TZ": "Europe/Berlin"}, tz_file=tz_file, localtime=link)
    assert svc.host_zone_name() == "Europe/Berlin"

    svc = _service(tmp_path, env={}, tz_file=tz_file, localtime=link)
    assert svc.host_zone_name() == "Asia/Tokyo"

    tz_file.unlink()
    assert svc.host_zone_name() == "Europe/Paris"

    link.unlink()
    assert svc.host_zone_name() == format_offset(_NOW.astimezone().utcoffset())


def test_invalid_tz_env_and_etc_timezone_are_skipped(tmp_path: Path) -> None:
    tz_file = tmp_path / "timezone"
    tz_file.write_text("Not/AZone\n")
    link = tmp_path / "localtime"
    link.symlink_to("/usr/share/zoneinfo/Europe/Paris")
    svc = _service(tmp_path, env={"TZ": "garbage"}, tz_file=tz_file, localtime=link)
    assert svc.host_zone_name() == "Europe/Paris"


def test_leading_colon_in_tz_is_accepted(tmp_path: Path) -> None:
    assert _service(tmp_path, env={"TZ": ":UTC"}).host_zone_name() == "UTC"


def test_view_reports_set_host_effective_and_the_name_list(tmp_path: Path) -> None:
    svc = _service(tmp_path, env={"TZ": "UTC"})
    svc.set_timezone("Australia/Brisbane")
    view = svc.view()
    assert view["timezone"] == "Australia/Brisbane"
    assert view["host_timezone"] == "UTC"
    assert view["effective_timezone"] == "Australia/Brisbane"
    assert view["effective_offset"] == "+10:00"
    assert "Europe/Berlin" in view["timezones"]


def test_format_offset() -> None:
    from datetime import timedelta

    assert format_offset(timedelta(hours=10)) == "+10:00"
    assert format_offset(timedelta(hours=-3, minutes=-30)) == "-03:30"
    assert format_offset(None) == "+00:00"
