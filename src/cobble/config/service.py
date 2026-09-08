"""The configuration service (server-config spec).

Owns the read and write paths for ``server.properties``: exposing it as typed
settings, applying a batch of changes all-or-nothing, enumerating the worlds that
back ``level-name``, and deriving the pending-versus-live comparison from the
snapshot the supervisor takes when it spawns BDS (design.md D5).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cobble.acquisition.layout import Layout
from cobble.config.properties import PropertiesDocument
from cobble.config.schema import PropertySchema, ValidationIssue, lookup, validate
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.supervisor.supervisor import MaintenanceInProgressError, Supervisor

log = get_logger("config.service")

_DEFAULT_LEVEL_NAME = "Bedrock level"

__all__ = [
    "ConfigService",
    "ConfigWriteResult",
    "PendingChange",
    "Setting",
    "WorldInfo",
    "WorldsView",
]


@dataclass(frozen=True)
class Setting:
    key: str
    value: str
    recognised: bool
    schema: PropertySchema | None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "recognised": self.recognised,
            "schema": self.schema.to_dict() if self.schema is not None else None,
        }


@dataclass(frozen=True)
class WorldInfo:
    name: str
    is_current: bool

    def to_dict(self) -> dict:
        return {"name": self.name, "is_current": self.is_current}


@dataclass(frozen=True)
class WorldsView:
    worlds: tuple[WorldInfo, ...]
    current: str
    current_present: bool

    def to_dict(self) -> dict:
        return {
            "worlds": [w.to_dict() for w in self.worlds],
            "current": self.current,
            "current_present": self.current_present,
        }


@dataclass(frozen=True)
class PendingChange:
    key: str
    saved: str | None
    in_effect: str | None

    def to_dict(self) -> dict:
        return {"key": self.key, "saved": self.saved, "in_effect": self.in_effect}


@dataclass(frozen=True)
class ConfigWriteResult:
    ok: bool
    errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]
    changed: tuple[str, ...]
    notes: tuple[str, ...]
    pending: tuple[PendingChange, ...]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "changed": list(self.changed),
            "notes": list(self.notes),
            "pending": [c.to_dict() for c in self.pending],
        }


class ConfigService:
    def __init__(
        self,
        settings: Settings,
        layout: Layout,
        supervisor: Supervisor,
        *,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings
        self._layout = layout
        self._sup = supervisor
        self._on_change = on_change

    # -- paths --------------------------------------------------
    @property
    def _path(self) -> Path:
        return self._layout.data_dir / "server.properties"

    @property
    def _worlds_dir(self) -> Path:
        return self._layout.data_dir / "worlds"

    def _document(self) -> PropertiesDocument:
        if not self._path.is_file():
            return PropertiesDocument.parse("")
        return PropertiesDocument.load(self._path)

    # -- reads --------------------------------------------------
    def read(self) -> list[Setting]:
        """Every setting present in the file, in file order, deduplicated to the
        value BDS would use. Recognised settings carry their schema."""
        doc = self._document()
        settings: list[Setting] = []
        for key in doc.keys():
            schema = lookup(key)
            settings.append(
                Setting(
                    key=key,
                    value=doc.get(key) or "",
                    recognised=schema is not None,
                    schema=schema,
                )
            )
        return settings

    def worlds(self) -> WorldsView:
        current = (self._document().get("level-name") or "").strip() or _DEFAULT_LEVEL_NAME
        names: list[str] = []
        if self._worlds_dir.is_dir():
            names = sorted(p.name for p in self._worlds_dir.iterdir() if p.is_dir())
        return WorldsView(
            worlds=tuple(WorldInfo(name=n, is_current=(n == current)) for n in names),
            current=current,
            current_present=current in names,
        )

    def pending(self) -> list[PendingChange]:
        """Settings whose saved value differs from the value the running server
        was started with. Empty while the server is not running (the supervisor
        holds no snapshot then)."""
        snapshot = self._sup.config_snapshot
        if snapshot is None:
            return []
        saved = self._document().effective()
        out: list[PendingChange] = []
        for key in sorted(set(saved) | set(snapshot)):
            saved_value = saved.get(key)
            effective_value = snapshot.get(key)
            if saved_value != effective_value:
                out.append(PendingChange(key=key, saved=saved_value, in_effect=effective_value))
        return out

    # -- writes -------------------------------------------------
    def write(self, changes: dict[str, str]) -> ConfigWriteResult:
        """Apply ``changes`` all-or-nothing.

        Rejected (nothing written) if any value is the wrong type for a
        recognised key. Out-of-range values of the right type are persisted and
        returned as warnings. Refused with the maintenance error while an
        update, backup, or restore is in progress.
        """
        if self._sup.maintenance is not None:
            raise MaintenanceInProgressError(f"a {self._sup.maintenance} operation is in progress")

        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        for key, value in changes.items():
            issue = validate(key, value)
            if issue is None:
                continue
            (errors if issue.severity == "error" else warnings).append(issue)

        if errors:
            return ConfigWriteResult(
                ok=False,
                errors=tuple(errors),
                warnings=tuple(warnings),
                changed=(),
                notes=(),
                pending=tuple(self.pending()),
            )

        doc = self._document()
        changed = doc.apply(changes)

        notes: list[str] = []
        if "level-name" in changes:
            name = changes["level-name"].strip()
            if name and not (self._worlds_dir / name).is_dir():
                notes.append(
                    f"No world named {name!r} exists yet; a new, empty world will be "
                    "created when the server next starts. The existing worlds are kept."
                )

        if changed:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(self._path)
            log.info("configuration updated: %s", ", ".join(changed))
            if self._on_change is not None:
                self._on_change()

        return ConfigWriteResult(
            ok=True,
            errors=(),
            warnings=tuple(warnings),
            changed=tuple(changed),
            notes=tuple(notes),
            pending=tuple(self.pending()),
        )
