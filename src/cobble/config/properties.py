"""The ``server.properties`` file modelled as an ordered line document (design.md D1).

`server.properties` is parsed into a sequence of lines, each classified as a
comment, a blank, or a ``key=value`` assignment, with the original text of every
line retained. A write mutates the value of a matched assignment line in place
and appends a genuinely new key at the end; comments, blank lines, key order,
duplicate keys, and keys cobble does not recognise all survive untouched.

The obvious alternative — parse to a ``dict`` and write it back — discards every
comment and reorders keys, so the first save from the browser would produce a
large, alarming diff for anyone watching the file over SSH. This module is the
line-in-place discipline of ``_apply_install_defaults()`` generalised.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

__all__ = ["PropertiesDocument"]


@dataclass
class _Line:
    """One physical line of the file.

    ``key`` is set only for assignment lines. ``raw`` is the exact original text
    including the line terminator; it is what serialisation emits unless the line
    has been mutated, in which case the assignment is re-rendered from
    ``prefix``/``key``/``value``/``newline``.
    """

    raw: str
    key: str | None
    value: str | None
    prefix: str
    newline: str
    dirty: bool = False

    def text(self) -> str:
        if self.key is not None and self.dirty:
            return f"{self.prefix}{self.key}={self.value}{self.newline}"
        return self.raw


def _split_terminator(raw: str) -> tuple[str, str]:
    if raw.endswith("\r\n"):
        return raw[:-2], "\r\n"
    if raw.endswith("\n"):
        return raw[:-1], "\n"
    if raw.endswith("\r"):
        return raw[:-1], "\r"
    return raw, ""


def _parse_line(raw: str) -> _Line:
    body, newline = _split_terminator(raw)
    stripped = body.lstrip()
    prefix = body[: len(body) - len(stripped)]
    # Blank, comment (``#`` or ``!`` per the properties convention), or a line
    # with no ``=`` at all: opaque, preserved verbatim, never an assignment.
    if stripped == "" or stripped[:1] in ("#", "!") or "=" not in stripped:
        return _Line(raw=raw, key=None, value=None, prefix=prefix, newline=newline)
    name, _, value = stripped.partition("=")
    return _Line(raw=raw, key=name.strip(), value=value, prefix=prefix, newline=newline)


class PropertiesDocument:
    """An ordered, mutable view of a parsed ``server.properties`` file."""

    def __init__(self, lines: list[_Line]) -> None:
        self._lines = lines

    # -- construction ------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> PropertiesDocument:
        return cls([_parse_line(raw) for raw in text.splitlines(keepends=True)])

    @classmethod
    def load(cls, path: Path) -> PropertiesDocument:
        return cls.parse(path.read_text(encoding="utf-8"))

    # -- serialisation ---------------------------------------------
    def serialize(self) -> str:
        return "".join(line.text() for line in self._lines)

    # -- reading --------------------------------------------------
    def effective(self) -> dict[str, str]:
        """The map the Bedrock server would use: last assignment of each key wins."""
        out: dict[str, str] = {}
        for line in self._lines:
            if line.key is not None:
                out[line.key] = line.value or ""
        return out

    def keys(self) -> list[str]:
        """Every assigned key, in first-appearance order, without duplicates."""
        seen: list[str] = []
        for line in self._lines:
            if line.key is not None and line.key not in seen:
                seen.append(line.key)
        return seen

    def get(self, key: str) -> str | None:
        value: str | None = None
        for line in self._lines:
            if line.key == key:
                value = line.value or ""
        return value

    def __contains__(self, key: str) -> bool:
        return any(line.key == key for line in self._lines)

    # -- writing --------------------------------------------------
    def _dominant_newline(self) -> str:
        for line in self._lines:
            if line.newline:
                return line.newline
        return "\n"

    def set(self, key: str, value: str) -> bool:
        """Set ``key`` to ``value``.

        Rewrites the *last* assignment of an existing key in place (BDS reads the
        last occurrence; earlier ones are left as-is). Appends a new key at the
        end. Returns ``True`` if the document changed.
        """
        target: _Line | None = None
        for line in self._lines:
            if line.key == key:
                target = line
        if target is not None:
            if (target.value or "") == value:
                return False
            target.value = value
            target.dirty = True
            return True

        newline = self._dominant_newline()
        if self._lines:
            last = self._lines[-1]
            if not last.text().endswith(("\n", "\r")):
                # The file's final line has no terminator — give it one so the
                # appended assignment starts on its own line.
                if last.key is not None and last.dirty:
                    last.newline = newline
                else:
                    last.raw = last.raw + newline
        self._lines.append(
            _Line(raw="", key=key, value=value, prefix="", newline=newline, dirty=True)
        )
        return True

    def apply(self, changes: dict[str, str]) -> list[str]:
        """Apply several changes. Returns the keys that actually changed."""
        return [key for key, value in changes.items() if self.set(key, value)]

    # -- persistence --------------------------------------------
    def save(self, path: Path) -> None:
        """Write the document to ``path`` atomically (design.md D7).

        The content is written to a temporary file in the same directory, flushed
        and fsynced, then ``os.replace``d into place. An interrupted write leaves
        the previous file intact and never exposes a partially written file at
        ``path``.
        """
        data = self.serialize().encode("utf-8")
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
