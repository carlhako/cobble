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

from cobble.access.enforcement import Enforcement, EnforcementTracker
from cobble.acquisition.layout import Layout
from cobble.config.properties import PropertiesDocument
from cobble.config.schema import PropertySchema, ValidationIssue, lookup, validate
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import MaintenanceInProgressError, Supervisor

log = get_logger("config.service")

_DEFAULT_LEVEL_NAME = "Bedrock level"

# ``allow-list`` is applied to the running server when saved (design.md D5), so
# it is never "pending until restart" the way every other setting is (task 2.6).
_LIVE_APPLIED_KEYS = frozenset({"allow-list"})

__all__ = [
    "ConfigService",
    "ConfigWriteResult",
    "EnforcementView",
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
class EnforcementView:
    """The allowlist-enforcement comparison reported in place of a pending entry
    for ``allow-list`` (server-config spec; task 2.6)."""

    saved: bool
    in_effect: str  # "on" | "off" | "unknown"
    running: bool
    disagreement: bool

    def to_dict(self) -> dict:
        return {
            "saved": self.saved,
            "in_effect": self.in_effect,
            "running": self.running,
            "disagreement": self.disagreement,
        }


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
        enforcement: EnforcementTracker | None = None,
        apply_enforcement: Callable[[bool], None] | None = None,
    ) -> None:
        self._settings = settings
        self._layout = layout
        self._sup = supervisor
        self._on_change = on_change
        # Live allowlist-enforcement state (observed) and the hook that pushes a
        # saved change to the running server (design.md D5; tasks 2.5, 2.6).
        self._enforcement = enforcement
        self._apply_enforcement = apply_enforcement

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
            if key in _LIVE_APPLIED_KEYS:
                continue  # reported via enforcement_view(), never as pending (task 2.6)
            saved_value = saved.get(key)
            effective_value = snapshot.get(key)
            if saved_value != effective_value:
                out.append(PendingChange(key=key, saved=saved_value, in_effect=effective_value))
        return out

    def _saved_allow_list(self) -> bool:
        raw = (self._document().get("allow-list") or "false").strip().lower()
        return raw == "true"

    def saved_allow_list(self) -> bool:
        """The persisted ``allow-list`` value (``server.properties``), regardless
        of what the running server is enforcing."""
        return self._saved_allow_list()

    def enforcement_view(self) -> EnforcementView:
        """The saved ``allow-list`` value against the enforcement the running
        server is actually applying (server-config spec; task 2.6). ``in_effect``
        is ``"unknown"`` until a transition has been observed."""
        saved = self._saved_allow_list()
        running = self._sup.state is RunState.RUNNING
        live = self._enforcement.state if self._enforcement is not None else Enforcement.UNKNOWN
        if not running:
            return EnforcementView(
                saved=saved, in_effect="unknown", running=False, disagreement=False
            )
        in_effect = live.value
        disagreement = live is not Enforcement.UNKNOWN and (live is Enforcement.ON) != saved
        return EnforcementView(
            saved=saved, in_effect=in_effect, running=True, disagreement=disagreement
        )

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

        # ``allow-list`` is applied to the running server as well as the file
        # (design.md D5). The instruction is only issued once the file write
        # above has succeeded — a failed persist raises out of doc.save() and
        # never reaches here (task 2.5).
        if "allow-list" in changes and self._apply_enforcement is not None:
            want_on = changes["allow-list"].strip().lower() == "true"
            try:
                self._apply_enforcement(want_on)
            except Exception:
                log.exception("applying allow-list enforcement to the running server failed")

        return ConfigWriteResult(
            ok=True,
            errors=(),
            warnings=tuple(warnings),
            changed=tuple(changed),
            notes=tuple(notes),
            pending=tuple(self.pending()),
        )
