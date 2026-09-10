"""Synthesised world archives for the world-import unit tests.

No binary fixtures are committed: a minimal ``level.dat`` (8-byte header + the
three little-endian NBT tags cobble reads) and the surrounding world tree are
built here. The reference Crafty archive's own values are reproduced so a test
can assert against ``1.26.43.1`` / seed ``-7302393117572340386``.
"""

from __future__ import annotations

import io
import zipfile

REFERENCE_VERSION = "1.26.43.1"
REFERENCE_SEED = -7302393117572340386


def _string_tag(name: str, value: str) -> bytes:
    raw = value.encode("utf-8")
    return (
        bytes([0x08])
        + len(name).to_bytes(2, "little")
        + name.encode("ascii")
        + len(raw).to_bytes(2, "little")
        + raw
    )


def _long_tag(name: str, value: int) -> bytes:
    return (
        bytes([0x04])
        + len(name).to_bytes(2, "little")
        + name.encode("ascii")
        + value.to_bytes(8, "little", signed=True)
    )


def _int_list_tag(name: str, values: list[int]) -> bytes:
    body = bytes([0x03]) + len(values).to_bytes(4, "little")
    for v in values:
        body += v.to_bytes(4, "little", signed=True)
    return bytes([0x09]) + len(name).to_bytes(2, "little") + name.encode("ascii") + body


def make_level_dat(
    *,
    name: str = "Bedrock level",
    seed: int | None = REFERENCE_SEED,
    version: list[int] | None = None,
    truncated: bool = False,
) -> bytes:
    """A ``level.dat`` body wrapped in the 8-byte header. ``truncated`` lops off
    most of the NBT so every field fails to parse."""
    if version is None:
        version = [1, 26, 43, 1, 0]
    payload = bytes([0x0A]) + b"\x00\x00"  # opening TAG_Compound, empty name
    if name is not None:
        payload += _string_tag("LevelName", name)
    if seed is not None:
        payload += _long_tag("RandomSeed", seed)
    if version:
        payload += _int_list_tag("lastOpenedWithVersion", version)
    payload += bytes([0x00])  # TAG_End
    header = (10).to_bytes(4, "little") + len(payload).to_bytes(4, "little")
    blob = header + payload
    if truncated:
        blob = blob[: 8 + 6]
    return blob


def build_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in members.items():
            zf.writestr(arcname, data)
    return buf.getvalue()


def world_members(prefix: str, *, level_dat: bytes | None = None) -> dict[str, bytes]:
    """A minimal valid world subtree under ``prefix`` (``""`` for a root-level
    layout)."""
    if level_dat is None:
        level_dat = make_level_dat()
    return {
        f"{prefix}level.dat": level_dat,
        f"{prefix}levelname.txt": b"Bedrock level",
        f"{prefix}db/CURRENT": b"MANIFEST-000001\n",
        f"{prefix}db/MANIFEST-000001": b"\x00" * 64,
        f"{prefix}db/000003.log": b"\x00" * 128,
    }


def reference_archive_bytes() -> bytes:
    """A stand-in for the reference Crafty full-server backup: the world under
    ``worlds/Bedrock level/`` beside a large ``bedrock_server`` binary and the
    three non-world server files."""
    members = world_members("worlds/Bedrock level/")
    members["bedrock_server"] = b"\x7fELF" + b"\x00" * 4096
    members["server.properties"] = b"level-name=Bedrock level\n"
    members["allowlist.json"] = b"[]\n"
    members["permissions.json"] = b"[]\n"
    members["worlds/Bedrock level/behavior_packs/"] = b""
    return build_zip(members)
