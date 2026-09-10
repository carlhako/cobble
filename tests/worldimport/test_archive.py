"""Section 1: archive inspection — opening, locating, reading, validating."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobble.worldimport.archive import (
    ArchiveError,
    inspect,
    locate_worlds,
    open_archive,
    read_level_data,
    require_single_world,
    validate_members,
)

from ._fixtures import (
    REFERENCE_SEED,
    REFERENCE_VERSION,
    build_zip,
    make_level_dat,
    reference_archive_bytes,
    world_members,
)


def _write(tmp_path: Path, data: bytes, name: str = "archive.zip") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# -- 1.1 open / integrity ------------------------------------------------
def test_open_rejects_a_truncated_file(tmp_path: Path) -> None:
    good = reference_archive_bytes()
    p = _write(tmp_path, good[: len(good) // 2])
    with pytest.raises(ArchiveError):
        open_archive(p)


def test_open_rejects_a_non_zip_file(tmp_path: Path) -> None:
    p = _write(tmp_path, b"this is plainly not a zip archive at all")
    with pytest.raises(ArchiveError):
        open_archive(p)


def test_open_accepts_a_valid_zip(tmp_path: Path) -> None:
    p = _write(tmp_path, reference_archive_bytes())
    with open_archive(p) as zf:
        assert "worlds/Bedrock level/level.dat" in zf.namelist()


# -- 1.2 world locator -------------------------------------------------
@pytest.mark.parametrize(
    ("prefix", "label"),
    [("worlds/My World/", "full server backup"), ("My World/", "zipped folder"), ("", "mcworld")],
)
def test_locator_finds_the_world_in_each_layout(prefix: str, label: str) -> None:
    data = build_zip(world_members(prefix))
    import zipfile

    with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
        assert locate_worlds(zf.namelist()) == [prefix], label


def test_locator_ignores_a_level_dat_without_a_sibling_db() -> None:
    data = build_zip({"loose/level.dat": make_level_dat(), "loose/readme.txt": b"x"})
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert locate_worlds(zf.namelist()) == []


# -- 1.3 zero / many ------------------------------------------------
def test_zero_worlds_is_refused_and_never_extracts(tmp_path: Path) -> None:
    p = _write(tmp_path, build_zip({"notes.txt": b"nothing here"}))
    with open_archive(p) as zf:
        with pytest.raises(ArchiveError, match="no Bedrock world"):
            require_single_world(zf.namelist())


def test_more_than_one_world_is_refused_with_the_count(tmp_path: Path) -> None:
    members = {**world_members("worlds/A/"), **world_members("worlds/B/")}
    p = _write(tmp_path, build_zip(members))
    with open_archive(p) as zf:
        with pytest.raises(ArchiveError, match="2 Bedrock worlds"):
            require_single_world(zf.namelist())


# -- 1.4 level.dat reader -----------------------------------------
def test_reads_reference_version_and_seed() -> None:
    level = read_level_data(make_level_dat()[8:])
    assert level.name == "Bedrock level"
    assert level.last_opened_version == REFERENCE_VERSION
    assert level.seed == REFERENCE_SEED


def test_truncated_level_dat_yields_all_none() -> None:
    level = read_level_data(make_level_dat(truncated=True)[8:])
    assert level.name is None
    assert level.seed is None
    assert level.last_opened_version is None


# -- 1.5 member validation --------------------------------------
def _zip_with_member(
    tmp_path: Path, extra: dict[str, bytes], *, symlink: str | None = None
) -> Path:
    import io
    import zipfile

    buf = io.BytesIO()
    members = world_members("world/")
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in {**members, **extra}.items():
            zf.writestr(name, data)
        if symlink is not None:
            info = zipfile.ZipInfo("world/link")
            info.external_attr = (0o120777 | 0o100000) << 16  # S_IFLNK
            zf.writestr(info, symlink)
    return _write(tmp_path, buf.getvalue())


def test_parent_traversal_member_refuses_the_archive(tmp_path: Path) -> None:
    p = _zip_with_member(tmp_path, {"world/../../escape.txt": b"x"})
    with open_archive(p) as zf:
        with pytest.raises(ArchiveError):
            validate_members(zf, "world/", tmp_path / "dest")


def test_absolute_path_member_refuses_the_archive(tmp_path: Path) -> None:
    p = _zip_with_member(tmp_path, {"/etc/evil": b"x"})
    with open_archive(p) as zf:
        # the absolute member is outside the world subtree; put one inside too
        with pytest.raises(ArchiveError):
            validate_members(zf, "", tmp_path / "dest")


def test_escaping_symlink_member_refuses_the_archive(tmp_path: Path) -> None:
    p = _zip_with_member(tmp_path, {}, symlink="../../../../etc/passwd")
    with open_archive(p) as zf:
        with pytest.raises(ArchiveError, match="link"):
            validate_members(zf, "world/", tmp_path / "dest")


# -- 1.6 inspection result ------------------------------------
def test_inspection_reports_world_and_all_three_extra_files(tmp_path: Path) -> None:
    p = _write(tmp_path, reference_archive_bytes())
    with open_archive(p) as zf:
        result = inspect(zf)
    assert result.world_name == "Bedrock level"
    assert result.world_prefix == "worlds/Bedrock level/"
    assert result.seed == REFERENCE_SEED
    assert result.last_opened_version == REFERENCE_VERSION
    assert result.uncompressed_size > 0
    assert set(result.extra_server_files) == {
        "server.properties",
        "allowlist.json",
        "permissions.json",
    }
