"""Inspecting an operator-supplied world archive (section 1).

Pure filesystem / zip work — no server or event-loop involvement. The caller
(:mod:`cobble.worldimport.service`) runs this in a thread.

A world is found by *structure*, not by an assumed path: any ``level.dat`` whose
sibling ``db/`` holds a LevelDB ``CURRENT`` marker (design.md D5). That single
rule covers a full server backup (``worlds/<Name>/``), a zipped world folder
(``<Name>/``), and a ``.mcworld`` / Realms export with ``level.dat`` at the
archive root.

``level.dat`` is an 8-byte header followed by little-endian NBT. Only three
fields are needed — ``LevelName``, ``RandomSeed``, ``lastOpenedWithVersion`` —
so each tag is located by its name bytes and the fixed-width payload after it is
decoded directly. A field that cannot be parsed is ``None`` and the version
check treats an unreadable version as unknown rather than failing the import.
"""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cobble.logging import get_logger

log = get_logger("worldimport.archive")

LEVEL_DAT = "level.dat"
_DB_MARKER = "db/CURRENT"

# Non-world server files a full-server-backup archive carries alongside the
# world. Their presence is reported; an import never applies them — the
# configuration and access capabilities own those files (proposal.md).
SERVER_FILE_NAMES: tuple[str, ...] = (
    "server.properties",
    "allowlist.json",
    "permissions.json",
)

# NBT tag ids used by the three fields read from level.dat.
_NBT_INT = 0x03
_NBT_LONG = 0x04
_NBT_STRING = 0x08
_NBT_LIST = 0x09


class ArchiveError(RuntimeError):
    """An uploaded archive cannot be read, holds no single importable world, or
    is unsafe to extract."""


@dataclass(frozen=True)
class LevelData:
    name: str | None
    seed: int | None
    last_opened_version: str | None


@dataclass(frozen=True)
class WorldInspection:
    """What cobble found in a held archive — reported so an operator confirms
    against the world's identity rather than a file name."""

    world_name: str | None
    world_prefix: str  # "" | "<Name>/" | "worlds/<Name>/"
    uncompressed_size: int
    seed: int | None
    last_opened_version: str | None
    extra_server_files: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "world_name": self.world_name,
            "world_prefix": self.world_prefix,
            "uncompressed_size": self.uncompressed_size,
            # A Bedrock seed is a signed 64-bit value that overflows a JS number;
            # send it as a string so the interface shows it exactly.
            "seed": None if self.seed is None else str(self.seed),
            "last_opened_version": self.last_opened_version,
            "extra_server_files": list(self.extra_server_files),
        }


def _norm(name: str) -> str:
    return name.replace("\\", "/")


def open_archive(path: Path) -> zipfile.ZipFile:
    """Open ``path`` as a zip, refusing one that is not a readable archive or
    fails an integrity check (task 1.1). The caller closes the handle."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveError(f"the uploaded file is not a readable archive: {exc}") from exc
    try:
        bad = zf.testzip()
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        zf.close()
        raise ArchiveError(f"the archive is corrupt: {exc}") from exc
    if bad is not None:
        zf.close()
        raise ArchiveError(f"the archive is corrupt (first bad entry: {bad})")
    return zf


def locate_worlds(names: list[str]) -> list[str]:
    """Every world-root prefix in ``names`` — a ``level.dat`` with a sibling
    ``db/CURRENT`` (design.md D5). May be empty, one, or several."""
    norm = {_norm(n) for n in names}
    prefixes: list[str] = []
    for n in norm:
        if n == LEVEL_DAT:
            prefix = ""
        elif n.endswith("/" + LEVEL_DAT):
            prefix = n[: -len(LEVEL_DAT)]
        else:
            continue
        if prefix + _DB_MARKER in norm:
            prefixes.append(prefix)
    return sorted(prefixes)


def require_single_world(names: list[str]) -> str:
    """The one world-root prefix in ``names``. Refuses zero and more-than-one,
    each with a reason naming the count (task 1.3)."""
    worlds = locate_worlds(names)
    if not worlds:
        raise ArchiveError("no Bedrock world was found in the archive")
    if len(worlds) > 1:
        raise ArchiveError(f"the archive is ambiguous: it contains {len(worlds)} Bedrock worlds")
    return worlds[0]


def _named_payload(blob: bytes, tag_type: int, tag_name: str) -> int | None:
    """Offset of the payload immediately after a named NBT tag header, or
    ``None`` when the tag is absent."""
    needle = bytes([tag_type]) + len(tag_name).to_bytes(2, "little") + tag_name.encode("ascii")
    idx = blob.find(needle)
    if idx < 0:
        return None
    return idx + len(needle)


def _read_level_name(blob: bytes) -> str | None:
    off = _named_payload(blob, _NBT_STRING, "LevelName")
    if off is None or off + 2 > len(blob):
        return None
    try:
        length = int.from_bytes(blob[off : off + 2], "little")
        raw = blob[off + 2 : off + 2 + length]
        if len(raw) != length:
            return None
        return raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _read_seed(blob: bytes) -> int | None:
    off = _named_payload(blob, _NBT_LONG, "RandomSeed")
    if off is None or off + 8 > len(blob):
        return None
    return int.from_bytes(blob[off : off + 8], "little", signed=True)


def _read_version(blob: bytes) -> str | None:
    off = _named_payload(blob, _NBT_LIST, "lastOpenedWithVersion")
    if off is None or off + 5 > len(blob):
        return None
    if blob[off] != _NBT_INT:
        return None
    count = int.from_bytes(blob[off + 1 : off + 5], "little")
    if count <= 0 or count > 16 or off + 5 + 4 * count > len(blob):
        return None
    nums = [
        int.from_bytes(blob[off + 5 + 4 * i : off + 9 + 4 * i], "little", signed=True)
        for i in range(count)
    ]
    # Bedrock records five components; the fifth is a revision marker that is not
    # part of the dotted server version. Compare on the first four.
    return ".".join(str(n) for n in nums[:4])


def read_level_data(blob: bytes) -> LevelData:
    """Read the three fields from a ``level.dat`` NBT body. Never raises; an
    unparseable field is ``None`` (design.md D5)."""
    return LevelData(
        name=_read_level_name(blob),
        seed=_read_seed(blob),
        last_opened_version=_read_version(blob),
    )


def read_level_dat(zf: zipfile.ZipFile, world_prefix: str) -> LevelData:
    """Read ``<world_prefix>level.dat`` from ``zf``. A missing or truncated file
    yields all-``None`` without raising."""
    member = world_prefix + LEVEL_DAT
    try:
        raw = zf.read(member)
    except (KeyError, zipfile.BadZipFile, OSError):
        return LevelData(None, None, None)
    body = raw[8:] if len(raw) >= 8 else raw
    return read_level_data(body)


def _in_subtree(name: str, prefix: str) -> bool:
    return name.startswith(prefix) if prefix else True


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def world_member_names(names: list[str], world_prefix: str) -> list[str]:
    """The archive members that make up the located world subtree."""
    return [n for n in names if _in_subtree(_norm(n), world_prefix)]


def validate_members(zf: zipfile.ZipFile, world_prefix: str, destination: Path) -> None:
    """Refuse the archive if any member of the world subtree would write outside
    ``destination`` — an absolute path, ``..`` traversal once normalised, or a
    link whose target escapes it (task 1.5 / design.md D7)."""
    dest = destination.resolve()
    for info in zf.infolist():
        name = _norm(info.filename)
        if not _in_subtree(name, world_prefix):
            continue
        rel = name[len(world_prefix) :]
        if not rel or rel.endswith("/"):
            continue
        if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
            raise ArchiveError(f"archive member has an absolute path: {info.filename!r}")
        target = (dest / rel).resolve()
        if not _within(target, dest):
            raise ArchiveError(
                f"archive member would be written outside the destination: {info.filename!r}"
            )
        if stat.S_ISLNK(info.external_attr >> 16):
            try:
                link_target = zf.read(info.filename).decode("utf-8", "replace")
            except (KeyError, zipfile.BadZipFile, OSError) as exc:
                raise ArchiveError(f"unreadable link member {info.filename!r}: {exc}") from exc
            resolved = (target.parent / link_target).resolve()
            if not _within(resolved, dest):
                raise ArchiveError(
                    f"archive contains a link pointing outside the destination: "
                    f"{info.filename!r} -> {link_target!r}"
                )


def _extra_server_files(norm_names: list[str], world_prefix: str) -> tuple[str, ...]:
    present: list[str] = []
    for wanted in SERVER_FILE_NAMES:
        for n in norm_names:
            if _in_subtree(n, world_prefix):
                continue
            if n.rsplit("/", 1)[-1] == wanted:
                present.append(wanted)
                break
    return tuple(present)


def inspect(zf: zipfile.ZipFile) -> WorldInspection:
    """Locate the single world and describe it — name, uncompressed size, seed,
    last-opened version, and any non-world server files present (task 1.6)."""
    names = zf.namelist()
    norm_names = [_norm(n) for n in names]
    prefix = require_single_world(names)
    size = sum(
        info.file_size for info in zf.infolist() if _in_subtree(_norm(info.filename), prefix)
    )
    level = read_level_dat(zf, prefix)
    return WorldInspection(
        world_name=level.name,
        world_prefix=prefix,
        uncompressed_size=size,
        seed=level.seed,
        last_opened_version=level.last_opened_version,
        extra_server_files=_extra_server_files(norm_names, prefix),
    )
