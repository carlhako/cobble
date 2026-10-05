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
        assert "worlds/Bedrock level/level.dat" in zf.names()


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
            require_single_world(zf.names())


def test_more_than_one_world_is_refused_with_the_count(tmp_path: Path) -> None:
    members = {**world_members("worlds/A/"), **world_members("worlds/B/")}
    p = _write(tmp_path, build_zip(members))
    with open_archive(p) as zf:
        with pytest.raises(ArchiveError, match="2 Bedrock worlds"):
            require_single_world(zf.names())


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


# -- import-backup-archive: forms, tar, kinds ----------------------------
from cobble.worldimport.archive import (  # noqa: E402
    FORM_TAR,
    FORM_ZIP,
    KIND_BACKUP,
    KIND_WORLD,
    sniff,
)

from ._fixtures import backup_members, build_tar  # noqa: E402


def test_sniff_recognises_each_form_by_content(tmp_path: Path) -> None:
    assert sniff(_write(tmp_path, build_zip(world_members("w/")), "a.zip")) == FORM_ZIP
    assert sniff(_write(tmp_path, build_zip({}), "empty.zip")) == FORM_ZIP
    assert sniff(_write(tmp_path, build_tar(world_members("w/")), "a.tar.gz")) == FORM_TAR


def test_a_tarball_named_zip_is_read_as_a_tar(tmp_path: Path) -> None:
    p = _write(tmp_path, build_tar(world_members("My World/")), "world.zip")
    with open_archive(p) as reader:
        assert reader.form == FORM_TAR
        assert inspect(reader).world_prefix == "My World/"


def test_a_file_in_neither_form_is_refused(tmp_path: Path) -> None:
    p = _write(tmp_path, b"\x00\x01\x02 not an archive", "x.tar.gz")
    with pytest.raises(ArchiveError, match="not a readable archive"):
        open_archive(p)


def test_a_truncated_tarball_is_refused(tmp_path: Path) -> None:
    good = build_tar(world_members("w/"))
    p = _write(tmp_path, good[: len(good) // 2], "t.tar.gz")
    with pytest.raises(ArchiveError):
        open_archive(p)


def test_a_tarball_failing_its_crc_is_refused(tmp_path: Path) -> None:
    data = bytearray(build_tar(world_members("w/")))
    data[-8] ^= 0xFF  # gzip trailer: CRC32
    p = _write(tmp_path, bytes(data), "crc.tar.gz")
    with pytest.raises(ArchiveError):
        open_archive(p)


@pytest.mark.parametrize("prefix", ["worlds/My World/", "My World/", "./My World/", ""])
def test_tar_world_layouts_are_located(tmp_path: Path, prefix: str) -> None:
    p = _write(tmp_path, build_tar(world_members(prefix)), "w.tar.gz")
    with open_archive(p) as reader:
        result = inspect(reader)
    assert result.world_prefix == prefix.removeprefix("./")
    assert result.kind == KIND_WORLD
    assert result.last_opened_version == REFERENCE_VERSION
    assert result.seed == REFERENCE_SEED


def test_tar_with_two_worlds_is_refused_with_the_count(tmp_path: Path) -> None:
    members = {**world_members("A/"), **world_members("B/")}
    p = _write(tmp_path, build_tar(members), "two.tar.gz")
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="2 Bedrock worlds"):
            inspect(reader)


def test_tar_parent_traversal_is_refused(tmp_path: Path) -> None:
    members = {**world_members("w/"), "w/../../escape.txt": b"x"}
    p = _write(tmp_path, build_tar(members), "t.tar.gz")
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="outside"):
            validate_members(reader, "w/", tmp_path / "dest")


def test_tar_absolute_member_is_refused(tmp_path: Path) -> None:
    members = {**world_members(""), "/etc/evil": b"x"}
    p = _write(tmp_path, build_tar(members), "t.tar.gz")
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="absolute"):
            validate_members(reader, "", tmp_path / "dest")


def test_tar_escaping_symlink_is_refused(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        build_tar(world_members("w/"), symlinks={"w/link": "../../../etc/passwd"}),
        "t.tar.gz",
    )
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="link"):
            validate_members(reader, "w/", tmp_path / "dest")


def test_tar_absolute_symlink_is_refused(tmp_path: Path) -> None:
    p = _write(tmp_path, build_tar(world_members("w/"), symlinks={"w/link": "/etc"}), "t.tar.gz")
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="link"):
            validate_members(reader, "w/", tmp_path / "dest")


def test_tar_hardlink_is_refused(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        build_tar(world_members("w/"), hardlinks={"w/hard": "w/level.dat"}),
        "t.tar.gz",
    )
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="hard link or special"):
            validate_members(reader, "w/", tmp_path / "dest")


def test_tar_special_file_is_refused(tmp_path: Path) -> None:
    p = _write(tmp_path, build_tar(world_members("w/"), fifos=("w/pipe",)), "t.tar.gz")
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="hard link or special"):
            validate_members(reader, "w/", tmp_path / "dest")


def test_unsafe_members_outside_the_extracted_part_are_ignored(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        build_tar(world_members("w/"), hardlinks={"other/hard": "w/level.dat"}),
        "t.tar.gz",
    )
    with open_archive(p) as reader:
        validate_members(reader, "w/", tmp_path / "dest")


@pytest.mark.parametrize("builder", [build_tar, build_zip])
def test_an_in_destination_symlink_is_never_created(tmp_path: Path, builder) -> None:
    if builder is build_tar:
        data = build_tar(world_members("w/"), symlinks={"w/link": "level.dat"})
    else:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, blob in world_members("w/").items():
                zf.writestr(name, blob)
            info = zipfile.ZipInfo("w/link")
            info.external_attr = (0o120777 | 0o100000) << 16
            zf.writestr(info, "level.dat")
        data = buf.getvalue()
    p = _write(tmp_path, data, "a.bin")
    dest = tmp_path / "dest"
    dest.mkdir()
    with open_archive(p) as reader:
        validate_members(reader, "w/", dest)
        reader.extract("w/", dest)
    assert (dest / "level.dat").is_file()
    assert (dest / "db" / "CURRENT").read_bytes() == b"MANIFEST-000001\n"
    assert not (dest / "link").exists() and not (dest / "link").is_symlink()


# -- kind detection / version fallback ---------------------------------
def test_a_cobble_backup_tarball_is_a_backup(tmp_path: Path) -> None:
    p = _write(tmp_path, build_tar(backup_members()), "b.tar.gz")
    with open_archive(p) as reader:
        result = inspect(reader)
    assert result.kind == KIND_BACKUP
    assert result.world_prefix == "data/worlds/Bedrock level/"
    assert result.backup is not None
    assert result.backup.captured_at == "2026-10-01T03:00:00+00:00"
    assert result.to_dict()["backup"]["bedrock_version"] == "1.26.43.1"
    # A backup is applied whole: its size covers cobble-state as well.
    assert result.uncompressed_size > sum(len(v) for v in world_members("x/").values())


def test_a_real_capture_is_recognised_as_a_backup(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from cobble.acquisition.layout import Layout
    from cobble.backup.capture import capture_archive

    layout = Layout(tmp_path / "bedrock", tmp_path / "state", tmp_path / "backups")
    for name, blob in world_members("worlds/Bedrock level/").items():
        f = layout.data_dir / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(blob)
    layout.state_dir.mkdir(parents=True)
    (layout.state_dir / "runtime.json").write_text("{}")
    manifest = capture_archive(
        layout,
        layout.backup_dir,
        bedrock_version="1.26.43.1",
        shutdown_clean=True,
        now=datetime(2026, 10, 1, tzinfo=UTC),
    )
    with open_archive(layout.backup_dir / manifest.archive) as reader:
        result = inspect(reader)
    assert result.kind == KIND_BACKUP
    assert result.form == FORM_TAR


def test_a_zip_laid_out_like_a_backup_is_a_world_archive(tmp_path: Path) -> None:
    p = _write(tmp_path, build_zip(backup_members()), "b.zip")
    with open_archive(p) as reader:
        result = inspect(reader)
    assert result.kind == KIND_WORLD
    assert result.backup is None


def test_a_backup_with_two_worlds_is_refused(tmp_path: Path) -> None:
    p = _write(tmp_path, build_tar(backup_members(worlds=("A", "B"))), "b.tar.gz")
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="2 Bedrock worlds"):
            inspect(reader)


def test_a_backup_with_no_world_is_refused(tmp_path: Path) -> None:
    p = _write(tmp_path, build_tar(backup_members(worlds=())), "b.tar.gz")
    with open_archive(p) as reader:
        with pytest.raises(ArchiveError, match="no Bedrock world"):
            inspect(reader)


def test_manifest_version_stands_in_for_an_unreadable_world_version(tmp_path: Path) -> None:
    unreadable = make_level_dat(version=[])
    p = _write(
        tmp_path,
        build_tar(backup_members(level_dat=unreadable, bedrock_version="1.21.0.3")),
        "b.tar.gz",
    )
    with open_archive(p) as reader:
        assert inspect(reader).last_opened_version == "1.21.0.3"


def test_level_dat_version_wins_over_the_manifest(tmp_path: Path) -> None:
    p = _write(tmp_path, build_tar(backup_members(bedrock_version="1.21.0.3")), "b.tar.gz")
    with open_archive(p) as reader:
        assert inspect(reader).last_opened_version == REFERENCE_VERSION


def test_neither_version_is_unknown(tmp_path: Path) -> None:
    unreadable = make_level_dat(version=[])
    p = _write(
        tmp_path,
        build_tar(backup_members(level_dat=unreadable, bedrock_version=None)),
        "b.tar.gz",
    )
    with open_archive(p) as reader:
        assert inspect(reader).last_opened_version is None
