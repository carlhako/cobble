"""Resolves cobble's effective timezone and validates changes to it
(cobble-settings spec; design.md D1, D2).

The effective zone is the operator's saved IANA name when one is set and
otherwise the host's local zone. The host zone is resolved on every call, not
cached, so it stays correct if the host is reconfigured.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta, tzinfo
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from cobble.cobble_settings.store import CobbleSettingsStore
from cobble.logging import get_logger

log = get_logger("cobble_settings")

_ETC_TIMEZONE = Path("/etc/timezone")
_ETC_LOCALTIME = Path("/etc/localtime")


class InvalidTimezone(ValueError):
    """A timezone name cobble cannot resolve."""


@lru_cache(maxsize=1)
def timezone_names() -> tuple[str, ...]:
    return tuple(sorted(available_timezones()))


def _valid_zone(name: str) -> ZoneInfo | None:
    """The zone for ``name``, or ``None`` if it is not a known IANA name."""
    if name not in timezone_names():
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def format_offset(delta: timedelta | None) -> str:
    """``+10:00``-style rendering of a UTC offset."""
    total = int((delta or timedelta(0)).total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


class CobbleSettingsService:
    def __init__(
        self,
        store: CobbleSettingsStore,
        *,
        on_change: Callable[[], None] | None = None,
        env: Mapping[str, str] | None = None,
        etc_timezone: Path = _ETC_TIMEZONE,
        etc_localtime: Path = _ETC_LOCALTIME,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._on_change = on_change
        self._env = os.environ if env is None else env
        self._etc_timezone = etc_timezone
        self._etc_localtime = etc_localtime
        self._clock = clock

    def set_on_change(self, cb: Callable[[], None] | None) -> None:
        self._on_change = cb

    # -- host zone -----------------------------------------------------
    def _host_zone(self) -> tuple[str, tzinfo]:
        """The host's zone and its name: the IANA name when the host makes one
        available (``TZ``, ``/etc/timezone``, the ``/etc/localtime`` symlink),
        otherwise the process's fixed local offset named by that offset."""
        tz_env = self._env.get("TZ", "").strip().lstrip(":")
        if tz_env and (zone := _valid_zone(tz_env)) is not None:
            return tz_env, zone

        try:
            name = self._etc_timezone.read_text().strip()
        except OSError:
            name = ""
        if name and (zone := _valid_zone(name)) is not None:
            return name, zone

        try:
            target = os.readlink(self._etc_localtime)
        except OSError:
            target = ""
        marker = "zoneinfo/"
        if marker in target:
            name = target.rsplit(marker, 1)[1]
            if (zone := _valid_zone(name)) is not None:
                return name, zone

        local = self._clock().astimezone().tzinfo
        assert local is not None
        return format_offset(local.utcoffset(None)), local

    def host_zone_name(self) -> str:
        return self._host_zone()[0]

    # -- effective zone ---------------------------------------------------
    @property
    def timezone(self) -> str | None:
        """The operator's saved name, or ``None`` while unset."""
        return self._store.timezone

    def effective_zone(self) -> tzinfo:
        name = self._store.timezone
        if name is not None:
            zone = _valid_zone(name)
            if zone is not None:
                return zone
            log.warning("saved timezone %r is not recognised; using the host zone", name)
        return self._host_zone()[1]

    def effective_zone_name(self) -> str:
        name = self._store.timezone
        if name is not None and _valid_zone(name) is not None:
            return name
        return self._host_zone()[0]

    def effective_offset(self) -> str:
        return format_offset(self._clock().astimezone(self.effective_zone()).utcoffset())

    # -- writes ----------------------------------------------------------
    def set_timezone(self, name: str | None) -> None:
        """Save ``name`` (an IANA zone) or clear the setting with ``None``.
        An unknown name raises :class:`InvalidTimezone` and changes nothing."""
        if name is not None:
            if _valid_zone(name) is None:
                raise InvalidTimezone(f"timezone {name!r} is not recognised")
        self._store.set_timezone(name)
        if self._on_change is not None:
            self._on_change()

    def view(self) -> dict:
        host_name = self.host_zone_name()
        return {
            "timezone": self._store.timezone,
            "host_timezone": host_name,
            "effective_timezone": self.effective_zone_name(),
            "effective_offset": self.effective_offset(),
            "timezones": list(timezone_names()),
        }
