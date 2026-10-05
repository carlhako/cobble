"""Inspecting an operator-supplied world archive (section 1).

Pure filesystem / archive work — no server or event-loop involvement. The
caller (:mod:`cobble.worldimport.service`) runs this in a thread.

Two containers are accepted, recognised by their leading bytes rather than a
file name (the upload is a raw stream): zip (including ``.mcworld``) and
gzip-compressed tar (import-backup-archive design.md D1). Both are read through
:class:`ArchiveReader`, which reduces an archive to a list of :class:`Member`
records so locating, validating, and extracting are written once (D2).

A world is found by *structure*, not by an assumed path: any ``level.dat`` whose
sibling ``db/`` holds a LevelDB ``CURRENT`` marker (design.md D5). That single
rule covers a full server backup (``worlds/<Name>/``), a zipped world folder
(``<Name>/``), a ``.mcworld`` / Realms export with ``level.dat`` at the archive
root, and a cobble backup (``data/worlds/<Name>/``).

What an archive *is* is decided by its contents, independently of its
container: a tar carrying cobble's ``manifest.json`` beside ``data/`` and
``cobble-state/`` is a cobble backup and is applied as a full restore; anything
else is a world archive (import-backup-archive design.md D3).

``level.dat`` is an 8-byte header followed by little-endian NBT. Only three
fields are needed — ``LevelName``, ``RandomSeed``, ``lastOpenedWithVersion`` —
so each tag is located by its name bytes and the fixed-width payload after it is
decoded directly. A field that cannot be parsed is ``None`` and the version
check treats an unreadable version as unknown rather than failing the import.
"""

from __future__ import annotations

import json
import shutil
import stat
import tarfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from cobble.backup.artifact import CONTENT_DATA, CONTENT_STATE, MANIFEST_FORMAT
from cobble.logging import get_logger

log = get_logger("worldimport.archive")

LEVEL_DAT = "level.dat"
MANIFEST_JSON = "manifest.json"
_DB_MARKER = "db/CURRENT"

# Archive forms, recognised from the leading bytes (design.md D1).
FORM_ZIP = "zip"
FORM_TAR = "tar"
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")
_GZIP_MAGIC = b"\x1f\x8b"

# What an archive is (design.md D3).
KIND_WORLD = "world"
KIND_BACKUP = "backup"

# Member kinds.
FILE = "file"
DIR = "dir"
SYMLINK = "symlink"
HARDLINK = "hardlink"
SPECIAL = "special"

# Small members whose bytes are kept from the listing pass; anything larger is
# not a plausible level.dat / manifest and is not buffered.
_SMALL_LIMIT = 16 * 1024 * 1024

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
class BackupInfo:
    """What a cobble backup's embedded ``manifest.json`` records."""

    captured_at: str | None
    bedrock_version: str | None

    def to_dict(self) -> dict:
        return {"captured_at": self.captured_at, "bedrock_version": self.bedrock_version}


@dataclass(frozen=True)
class WorldInspection:
    """What cobble found in a held archive — reported so an operator confirms
    against the archive's identity rather than a file name."""

    world_name: str | None
    world_prefix: str  # "" | "<Name>/" | "worlds/<Name>/" | "data/worlds/<Name>/"
    uncompressed_size: int
    seed: int | None
    last_opened_version: str | None
    extra_server_files: tuple[str, ...]
    form: str = FORM_ZIP
    kind: str = KIND_WORLD
    backup: BackupInfo | None = None

    def to_dict(self) -> dict:
        return {
            "form": self.form,
            "kind": self.kind,
            "world_name": self.world_name,
            "world_prefix": self.world_prefix,
            "uncompressed_size": self.uncompressed_size,
            # A Bedrock seed is a signed 64-bit value that overflows a JS number;
            # send it as a string so the interface shows it exactly.
            "seed": None if self.seed is None else str(self.seed),
            "last_opened_version": self.last_opened_version,
            "extra_server_files": list(self.extra_server_files),
            "backup": None if self.backup is None else self.backup.to_dict(),
        }


@dataclass(frozen=True)
class Member:
    """One archive entry, independent of the container it came from."""

    name: str  # normalised: forward slashes, no trailing slash
    size: int
    kind: str  # FILE | DIR | SYMLINK | HARDLINK | SPECIAL
    link_target: str | None = None
    raw_name: str = ""  # as recorded in the archive, for error messages


def _norm(name: str) -> str:
    n = name.replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    return n.rstrip("/") if n not in ("/", "") else n


def _is_small_wanted(name: str) -> bool:
    return name == MANIFEST_JSON or name == LEVEL_DAT or name.endswith("/" + LEVEL_DAT)


def sniff(path: Path) -> str:
    """The archive form of ``path`` from its leading bytes (design.md D1)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError as exc:
        raise ArchiveError(f"the uploaded file cannot be read: {exc}") from exc
    if head in _ZIP_MAGIC:
        return FORM_ZIP
    if head[:2] == _GZIP_MAGIC:
        return FORM_TAR
    raise ArchiveError(
        "the uploaded file is not a readable archive: expected a zip or a gzip-compressed tar"
    )


class ArchiveReader:
    """The container-neutral view of an archive. Readers are context managers;
    :meth:`members` is computed once when the reader is opened."""

    form: str

    def __init__(self, path: Path) -> None:
        self.path = path
        self._members: list[Member] = []
        self._small: dict[str, bytes] = {}

    def __enter__(self) -> ArchiveReader:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:  # pragma: no cover - overridden where needed
        return None

    def members(self) -> list[Member]:
        return self._members

    def names(self) -> list[str]:
        return [m.name for m in self._members]

    def read_small(self, name: str) -> bytes | None:
        """The bytes of a small member kept from the listing pass — every
        ``level.dat`` and the top-level ``manifest.json`` — or ``None``."""
        return self._small.get(name)

    def extract(self, prefix: str, destination: Path) -> None:
        """Write the regular files and directories under ``prefix`` into
        ``destination`` (relative to ``prefix``). Symbolic links are never
        created; hard links and special files are refused (design.md D4). The
        caller runs :func:`validate_members` first."""
        raise NotImplementedError


def _target(destination: Path, prefix: str, name: str) -> Path | None:
    if not _in_subtree(name, prefix):
        return None
    rel = name[len(prefix) :] if prefix else name
    if not rel:
        return None
    return destination / rel


class ZipReader(ArchiveReader):
    form = FORM_ZIP

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        try:
            self._zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveError(f"the uploaded file is not a readable archive: {exc}") from exc
        try:
            bad = self._zf.testzip()
        except (zipfile.BadZipFile, OSError, RuntimeError, zlib.error) as exc:
            self._zf.close()
            raise ArchiveError(f"the archive is corrupt: {exc}") from exc
        if bad is not None:
            self._zf.close()
            raise ArchiveError(f"the archive is corrupt (first bad entry: {bad})")
        try:
            self._scan()
        except BaseException:
            self._zf.close()
            raise

    def _scan(self) -> None:
        for info in self._zf.infolist():
            name = _norm(info.filename)
            if not name:
                continue
            mode = info.external_attr >> 16
            target: str | None = None
            if info.is_dir():
                kind = DIR
            elif stat.S_ISLNK(mode):
                kind = SYMLINK
                try:
                    target = self._zf.read(info).decode("utf-8", "replace")
                except (KeyError, zipfile.BadZipFile, OSError) as exc:
                    raise ArchiveError(f"unreadable link member {info.filename!r}: {exc}") from exc
            elif mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                kind = SPECIAL
            else:
                kind = FILE
            self._members.append(Member(name, info.file_size, kind, target, info.filename))
            if kind == FILE and _is_small_wanted(name) and info.file_size <= _SMALL_LIMIT:
                try:
                    self._small[name] = self._zf.read(info)
                except (KeyError, zipfile.BadZipFile, OSError):
                    pass

    def close(self) -> None:
        self._zf.close()

    def extract(self, prefix: str, destination: Path) -> None:
        by_name = {_norm(i.filename): i for i in self._zf.infolist()}
        for m in self._members:
            target = _target(destination, prefix, m.name)
            if target is None:
                continue
            if m.kind == DIR:
                target.mkdir(parents=True, exist_ok=True)
            elif m.kind == FILE:
                target.parent.mkdir(parents=True, exist_ok=True)
                with self._zf.open(by_name[m.name]) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
            elif m.kind in (HARDLINK, SPECIAL):
                raise ArchiveError(f"archive member is not a regular file: {m.raw_name!r}")
            # SYMLINK: never created.


def _tar_kind(ti: tarfile.TarInfo) -> str:
    if ti.isdir():
        return DIR
    if ti.issym():
        return SYMLINK
    if ti.islnk():
        return HARDLINK
    if ti.isreg():
        return FILE
    return SPECIAL


_TAR_ERRORS = (tarfile.TarError, EOFError, OSError, zlib.error)


class TarReader(ArchiveReader):
    """A gzip tar has no central directory, so listing is one streaming pass
    over the whole archive. Reading it through to the end makes gzip verify its
    CRC and length, so the listing pass is also the integrity check (D2)."""

    form = FORM_TAR

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        try:
            with tarfile.open(path, mode="r:gz") as tar:
                for ti in tar:
                    name = _norm(ti.name)
                    if not name:
                        continue
                    kind = _tar_kind(ti)
                    target = ti.linkname if kind in (SYMLINK, HARDLINK) else None
                    size = ti.size if kind == FILE else 0
                    self._members.append(Member(name, size, kind, target, ti.name))
                    if kind == FILE and _is_small_wanted(name) and ti.size <= _SMALL_LIMIT:
                        fh = tar.extractfile(ti)
                        if fh is not None:
                            self._small[name] = fh.read()
                # Drain to the end of the gzip stream so its trailer is checked.
                raw: BinaryIO = tar.fileobj  # type: ignore[assignment]
                while raw.read(1 << 20):
                    pass
        except _TAR_ERRORS as exc:
            raise ArchiveError(
                f"the archive is not a readable gzip tar or is corrupt: {exc}"
            ) from exc

    def extract(self, prefix: str, destination: Path) -> None:
        try:
            with tarfile.open(self.path, mode="r:gz") as tar:
                for ti in tar:
                    name = _norm(ti.name)
                    target = _target(destination, prefix, name)
                    if target is None:
                        continue
                    kind = _tar_kind(ti)
                    if kind == DIR:
                        target.mkdir(parents=True, exist_ok=True)
                    elif kind == FILE:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        src = tar.extractfile(ti)
                        if src is None:  # pragma: no cover - isreg() guarantees a file
                            continue
                        with src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                    elif kind in (HARDLINK, SPECIAL):
                        raise ArchiveError(f"archive member is not a regular file: {ti.name!r}")
                    # SYMLINK: never created.
        except (tarfile.TarError, EOFError, zlib.error) as exc:
            raise ArchiveError(f"the archive could not be extracted: {exc}") from exc


def open_archive(path: Path) -> ArchiveReader:
    """Open ``path`` as whichever form its leading bytes name, refusing one that
    is not a readable archive or fails an integrity check (task 1.1). The caller
    closes the reader."""
    form = sniff(path)
    return ZipReader(path) if form == FORM_ZIP else TarReader(path)


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


def read_level_dat(reader: ArchiveReader, world_prefix: str) -> LevelData:
    """Read ``<world_prefix>level.dat`` from ``reader``. A missing or truncated
    file yields all-``None`` without raising."""
    raw = reader.read_small(world_prefix + LEVEL_DAT)
    if raw is None:
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


def validate_members(reader: ArchiveReader, prefix: str, destination: Path) -> None:
    """Refuse the archive if any member under ``prefix`` would write outside
    ``destination`` — an absolute path, ``..`` traversal once normalised, or a
    link whose target escapes it — or is a hard link or special file (task 1.5 /
    design.md D7; import-backup-archive design.md D4)."""
    dest = destination.resolve()
    for m in reader.members():
        raw = m.raw_name.replace("\\", "/") or m.name
        if not _in_subtree(m.name, prefix) and not _in_subtree(raw, prefix):
            continue
        if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
            raise ArchiveError(f"archive member has an absolute path: {m.raw_name!r}")
        rel = m.name[len(prefix) :] if prefix and m.name.startswith(prefix) else m.name
        if not rel:
            continue
        target = (dest / rel).resolve()
        if not _within(target, dest):
            raise ArchiveError(
                f"archive member would be written outside the destination: {m.raw_name!r}"
            )
        if m.kind in (HARDLINK, SPECIAL):
            raise ArchiveError(
                f"archive member is a hard link or special file, which is not accepted: "
                f"{m.raw_name!r}"
            )
        if m.kind == SYMLINK:
            link_target = m.link_target or ""
            resolved = (target.parent / link_target).resolve()
            if link_target.startswith("/") or not _within(resolved, dest):
                raise ArchiveError(
                    f"archive contains a link pointing outside the destination: "
                    f"{m.raw_name!r} -> {link_target!r}"
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


def read_backup_manifest(reader: ArchiveReader) -> BackupInfo | None:
    """The embedded manifest of a cobble backup, or ``None`` when ``reader``
    holds none, or one this cobble cannot read."""
    raw = reader.read_small(MANIFEST_JSON)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        fmt = int(data.get("format"))
    except (ValueError, TypeError, AttributeError):
        return None
    if fmt < 1 or fmt > MANIFEST_FORMAT:
        return None
    captured = data.get("captured_at")
    version = data.get("bedrock_version")
    return BackupInfo(
        captured_at=None if captured is None else str(captured),
        bedrock_version=None if version is None else str(version),
    )


def _has_top_dir(names: list[str], top: str) -> bool:
    return any(n == top or n.startswith(top + "/") for n in names)


def classify(reader: ArchiveReader) -> tuple[str, BackupInfo | None]:
    """``(kind, manifest)``: a tar holding a readable cobble manifest beside
    ``data/`` and ``cobble-state/`` is a backup; everything else is a world
    archive (design.md D3). A zip is never a backup."""
    manifest = read_backup_manifest(reader)
    if reader.form != FORM_TAR or manifest is None:
        return KIND_WORLD, manifest
    names = reader.names()
    if _has_top_dir(names, CONTENT_DATA) and _has_top_dir(names, CONTENT_STATE):
        return KIND_BACKUP, manifest
    return KIND_WORLD, manifest


def inspect(reader: ArchiveReader) -> WorldInspection:
    """Locate the single world and describe the archive — form, kind, world
    name, size, seed, last-opened version (falling back to a cobble manifest's
    recorded version), and any non-world server files present (task 1.6)."""
    names = reader.names()
    prefix = require_single_world(names)
    kind, manifest = classify(reader)
    # A backup is applied whole, so its whole size is what needs room.
    scope = "" if kind == KIND_BACKUP else prefix
    size = sum(m.size for m in reader.members() if m.kind == FILE and _in_subtree(m.name, scope))
    level = read_level_dat(reader, prefix)
    version = level.last_opened_version
    if version is None and manifest is not None:
        version = manifest.bedrock_version
    return WorldInspection(
        world_name=level.name,
        world_prefix=prefix,
        uncompressed_size=size,
        seed=level.seed,
        last_opened_version=version,
        extra_server_files=_extra_server_files(names, prefix),
        form=reader.form,
        kind=kind,
        backup=manifest if kind == KIND_BACKUP else None,
    )
