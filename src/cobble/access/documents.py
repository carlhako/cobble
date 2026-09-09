"""``allowlist.json`` and ``permissions.json`` modelled as round-trippable
documents (design.md D1, D8).

Both files are lists of objects the Bedrock server owns. Cobble reads and writes
them directly and preserves every field it does not recognise, so an entry
written by BDS or by hand survives a write by cobble — the same discipline
:class:`~cobble.config.properties.PropertiesDocument` applies to
``server.properties``.

Formatting the two files differently is deliberate and matches what BDS itself
emits (design.md Context): ``allowlist.json`` is written compact, one line;
``permissions.json`` is pretty-printed with a three-space indent and a spaced
colon (``"permission" : "operator"``). A document that has not been mutated
serialises byte-for-byte to what was read, so a no-op write produces no diff.

Empty is folded on read (design.md D8): ``null`` — which BDS writes into
``allowlist.json`` when the last entry is removed — an empty array, an empty
file, and an absent file all read as an empty list, and cobble always writes
``[]`` for empty, never ``null``. Content that cannot be parsed is reported as a
condition on the returned document (``readable is False``) rather than raised,
and the file is left untouched.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "AllowlistDocument",
    "AllowlistEntry",
    "AllowlistFile",
    "PermissionEntry",
    "PermissionsDocument",
    "PermissionsFile",
    "UnreadableDocumentError",
    "atomic_write_text",
]


class UnreadableDocumentError(RuntimeError):
    """A backing file held content that could not be interpreted; a write was
    refused rather than clobbering it (design.md D8; task 1.3)."""

    code = "access_document_unreadable"


_VALID_LEVELS = ("visitor", "member", "operator")


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (design.md D1; task 1.5).

    Identical in approach to :meth:`PropertiesDocument.save` — a temp file in the
    same directory, flushed and fsynced, then ``os.replace``d into place. An
    interrupted write leaves the previous file intact and never exposes a
    partially written file at ``path``.
    """
    data = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _trailing_newline(text: str) -> str:
    return "\n" if text.endswith("\n") else ""


# ---------------------------------------------------------------------------
# allowlist.json
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllowlistEntry:
    """One allowlist row. ``name`` is what BDS matches on; ``xuid`` is the stable
    identifier BDS never writes itself but the schema accepts (design.md D4).
    ``extra`` carries every other field verbatim so it round-trips."""

    name: str
    xuid: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def has_identifier(self) -> bool:
        return bool(self.xuid)

    def to_json_obj(self) -> dict:
        # BDS orders ``ignoresPlayerLimit`` before ``name``; keep unrecognised
        # fields first so a hand-authored ordering is largely preserved, then
        # name, then xuid last (BDS omits it, so it reads as cobble's addition).
        obj: dict = dict(self.extra)
        obj["name"] = self.name
        if self.xuid:
            obj["xuid"] = self.xuid
        elif "xuid" in obj:
            del obj["xuid"]
        return obj


class AllowlistDocument:
    """A mutable, round-trippable view of ``allowlist.json``."""

    def __init__(
        self,
        entries: Iterable[AllowlistEntry] = (),
        *,
        readable: bool = True,
        raw: str | None = None,
        trailing_newline: str = "",
    ) -> None:
        self._entries: list[AllowlistEntry] = list(entries)
        self._readable = readable
        self._raw = raw
        self._trailing = trailing_newline
        self._dirty = False

    # -- construction ------------------------------------------------
    @classmethod
    def parse(cls, text: str | None) -> AllowlistDocument:
        if text is None or text.strip() == "":
            return cls(readable=True, raw=None, trailing_newline="\n")
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return cls(readable=False, raw=text, trailing_newline=_trailing_newline(text))
        if data is None:  # BDS writes literal null for an empty list (design.md D8)
            return cls(readable=True, raw=text, trailing_newline=_trailing_newline(text))
        if not isinstance(data, list):
            return cls(readable=False, raw=text, trailing_newline=_trailing_newline(text))
        entries: list[AllowlistEntry] = []
        for item in data:
            if not isinstance(item, dict):
                return cls(readable=False, raw=text, trailing_newline=_trailing_newline(text))
            extra = {k: v for k, v in item.items() if k not in ("name", "xuid")}
            name = item.get("name")
            if not isinstance(name, str):
                return cls(readable=False, raw=text, trailing_newline=_trailing_newline(text))
            xuid = item.get("xuid")
            entries.append(
                AllowlistEntry(
                    name=name,
                    xuid=str(xuid) if xuid not in (None, "") else None,
                    extra=extra,
                )
            )
        return cls(
            entries,
            readable=True,
            raw=text,
            trailing_newline=_trailing_newline(text) or "\n",
        )

    @classmethod
    def load(cls, path: Path) -> AllowlistDocument:
        if not path.is_file():
            return cls(readable=True, raw=None, trailing_newline="\n")
        return cls.parse(path.read_text(encoding="utf-8"))

    # -- reading ---------------------------------------------------
    @property
    def readable(self) -> bool:
        """False when the file held content that could not be interpreted. The
        entry list is empty in that case and no write should be attempted."""
        return self._readable

    @property
    def entries(self) -> tuple[AllowlistEntry, ...]:
        return tuple(self._entries)

    def find(self, *, xuid: str | None = None, name: str | None = None) -> AllowlistEntry | None:
        if xuid:
            for e in self._entries:
                if e.xuid and e.xuid == xuid:
                    return e
        if name:
            low = name.casefold()
            for e in self._entries:
                if e.name.casefold() == low:
                    return e
        return None

    # -- writing -------------------------------------------------
    def upsert(self, name: str, *, xuid: str | None = None) -> bool:
        """Add ``name`` to the allowlist, or update the matching entry's name and
        identifier. Returns whether the document changed."""
        existing = self.find(xuid=xuid, name=name if not xuid else None)
        if existing is None and xuid:
            existing = self.find(name=name)
        if existing is not None:
            if existing.name == name and (existing.xuid or None) == (xuid or None):
                return False
            replacement = AllowlistEntry(
                name=name, xuid=xuid or existing.xuid, extra=existing.extra
            )
            self._entries[self._entries.index(existing)] = replacement
            self._dirty = True
            return True
        extra = {"ignoresPlayerLimit": False}
        self._entries.append(AllowlistEntry(name=name, xuid=xuid, extra=extra))
        self._dirty = True
        return True

    def remove(self, *, xuid: str | None = None, name: str | None = None) -> bool:
        target = self.find(xuid=xuid, name=name)
        if target is None:
            return False
        self._entries.remove(target)
        self._dirty = True
        return True

    # -- serialisation ------------------------------------------
    def serialize(self) -> str:
        if not self._dirty and self._raw is not None:
            return self._raw
        body = json.dumps(
            [e.to_json_obj() for e in self._entries], separators=(",", ":"), ensure_ascii=False
        )
        return body + (self._trailing or "\n")

    def save(self, path: Path) -> None:
        atomic_write_text(path, self.serialize())


# ---------------------------------------------------------------------------
# permissions.json
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionEntry:
    """One permission row: a stable identifier and the level it holds. ``extra``
    round-trips any field cobble does not model."""

    xuid: str
    level: str
    extra: dict = field(default_factory=dict)

    def to_json_obj(self) -> dict:
        obj: dict = dict(self.extra)
        obj["permission"] = self.level
        obj["xuid"] = self.xuid
        return obj


class PermissionsDocument:
    """A mutable, round-trippable view of ``permissions.json`` (design.md D7)."""

    VALID_LEVELS = _VALID_LEVELS

    def __init__(
        self,
        entries: Iterable[PermissionEntry] = (),
        *,
        readable: bool = True,
        raw: str | None = None,
        trailing_newline: str = "",
    ) -> None:
        self._entries: list[PermissionEntry] = list(entries)
        self._readable = readable
        self._raw = raw
        self._trailing = trailing_newline
        self._dirty = False

    # -- construction ------------------------------------------------
    @classmethod
    def parse(cls, text: str | None) -> PermissionsDocument:
        if text is None or text.strip() == "":
            return cls(readable=True, raw=None, trailing_newline="\n")
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return cls(readable=False, raw=text, trailing_newline=_trailing_newline(text))
        if data is None:
            return cls(readable=True, raw=text, trailing_newline=_trailing_newline(text))
        if not isinstance(data, list):
            return cls(readable=False, raw=text, trailing_newline=_trailing_newline(text))
        entries: list[PermissionEntry] = []
        for item in data:
            if not isinstance(item, dict):
                return cls(readable=False, raw=text, trailing_newline=_trailing_newline(text))
            xuid = item.get("xuid")
            level = item.get("permission")
            if not isinstance(xuid, str) or not isinstance(level, str):
                return cls(readable=False, raw=text, trailing_newline=_trailing_newline(text))
            extra = {k: v for k, v in item.items() if k not in ("xuid", "permission")}
            entries.append(PermissionEntry(xuid=xuid, level=level, extra=extra))
        return cls(
            entries,
            readable=True,
            raw=text,
            trailing_newline=_trailing_newline(text) or "\n",
        )

    @classmethod
    def load(cls, path: Path) -> PermissionsDocument:
        if not path.is_file():
            return cls(readable=True, raw=None, trailing_newline="\n")
        return cls.parse(path.read_text(encoding="utf-8"))

    # -- reading ---------------------------------------------------
    @property
    def readable(self) -> bool:
        return self._readable

    @property
    def entries(self) -> tuple[PermissionEntry, ...]:
        return tuple(self._entries)

    def find(self, xuid: str) -> PermissionEntry | None:
        for e in self._entries:
            if e.xuid == xuid:
                return e
        return None

    # -- writing -------------------------------------------------
    def set_level(self, xuid: str, level: str) -> bool:
        """Set ``xuid``'s permission level. ``member`` — BDS's default — removes
        the row, matching how BDS represents an un-elevated player. Returns
        whether the document changed. Raises :class:`ValueError` for a level BDS
        does not define."""
        if level not in _VALID_LEVELS:
            raise ValueError(f"unknown permission level {level!r}")
        existing = self.find(xuid)
        if level == "member":
            if existing is None:
                return False
            self._entries.remove(existing)
            self._dirty = True
            return True
        if existing is not None:
            if existing.level == level:
                return False
            self._entries[self._entries.index(existing)] = PermissionEntry(
                xuid=xuid, level=level, extra=existing.extra
            )
            self._dirty = True
            return True
        self._entries.append(PermissionEntry(xuid=xuid, level=level))
        self._dirty = True
        return True

    # -- serialisation ------------------------------------------
    def serialize(self) -> str:
        if not self._dirty and self._raw is not None:
            return self._raw
        if not self._entries:
            return "[]" + (self._trailing or "\n")
        # BDS's format: three-space indent, spaced colon (design.md Context).
        body = json.dumps(
            [e.to_json_obj() for e in self._entries],
            indent=3,
            separators=(",", " : "),
            ensure_ascii=False,
        )
        return body + (self._trailing or "\n")

    def save(self, path: Path) -> None:
        atomic_write_text(path, self.serialize())


# ---------------------------------------------------------------------------
# file wrappers — never cache, re-read before every write (design.md Risks; 1.6)
# ---------------------------------------------------------------------------


class AllowlistFile:
    """A handle on ``allowlist.json`` that reads fresh on every call. It holds no
    parsed state between operations, so an out-of-band edit (an operator typing
    ``allowlist add`` in the console) is never clobbered by a stale view."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> AllowlistDocument:
        return AllowlistDocument.load(self._path)

    def mutate(self, mutator: Callable[[AllowlistDocument], object]) -> AllowlistDocument:
        """Load the file fresh, apply ``mutator``, and write it back atomically
        only if the mutation changed something. Raises
        :class:`UnreadableDocumentError` without writing if the current file
        cannot be interpreted."""
        doc = AllowlistDocument.load(self._path)
        if not doc.readable:
            raise UnreadableDocumentError(f"{self._path} could not be interpreted")
        mutator(doc)
        if doc._dirty:
            doc.save(self._path)
        return doc


class PermissionsFile:
    """A handle on ``permissions.json`` with the same no-cache discipline."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> PermissionsDocument:
        return PermissionsDocument.load(self._path)

    def mutate(self, mutator: Callable[[PermissionsDocument], object]) -> PermissionsDocument:
        doc = PermissionsDocument.load(self._path)
        if not doc.readable:
            raise UnreadableDocumentError(f"{self._path} could not be interpreted")
        mutator(doc)
        if doc._dirty:
            doc.save(self._path)
        return doc
