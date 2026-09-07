"""First-run bootstrap: acquire and activate the current version, but only when
no installation exists.

A second run performs no download and leaves the active version unchanged
(installation spec: "Installation already present").

The bootstrap also establishes the separated ``data/`` layout: it lays out the
vendor-payload symlinks and seeds ``data/`` with ``server.properties`` (with the
fresh-install LAN defaults applied), ``allowlist.json`` and ``permissions.json``
from the vendor tree. A freshly bootstrapped install never migrates (task 1.7,
installation spec: "A fresh install requires no migration").
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from cobble.acquisition.installer import _apply_install_defaults, install_version
from cobble.acquisition.layout import MUTABLE_ENTRIES, Layout
from cobble.acquisition.version_source import resolve_current_version
from cobble.logging import get_logger
from cobble.settings import Settings

log = get_logger("acquisition.bootstrap")

# Mutable entries seeded into data/ from the vendor tree on a fresh install.
# worlds/ is left to BDS to create on first launch.
_SEED_FILES = tuple(sorted(MUTABLE_ENTRIES - {"worlds"}))


@dataclass(frozen=True)
class BootstrapOutcome:
    installed: bool
    version: str | None
    message: str


def seed_data_dir(layout: Layout) -> None:
    """Lay out ``data/``: vendor-payload symlinks + seeded operator config.

    Idempotent. Only seeds a mutable file that is not already present, so it
    never overwrites operator edits or a migrated world's config.
    """
    layout.ensure_directories()
    version = layout.installed_version()
    if version is None:
        raise RuntimeError("seed_data_dir called with no active version")
    vdir = layout.version_dir(version)

    layout.ensure_payload_symlinks()

    for name in _SEED_FILES:
        dest = layout.data_dir / name
        src = vdir / name
        if dest.exists() or dest.is_symlink():
            continue
        if src.is_file():
            shutil.copy2(src, dest)
            log.info("seeded data/%s from the vendor tree", name)

    _apply_install_defaults(layout.data_dir)


def bootstrap_if_needed(settings: Settings, layout: Layout | None = None) -> BootstrapOutcome:
    layout = layout or Layout.from_settings(settings)
    layout.ensure_directories()

    existing = layout.installed_version()
    if existing is not None and layout.has_installation():
        log.info("installation already present (%s); no download performed", existing)
        if (layout.version_dir(existing) / "worlds").is_dir():
            # Pre-separation (M1) layout: the one-time migration relocates the
            # world and config into data/ and lays out the symlinks. Seeding
            # data/ here would race it and could impose fresh-install defaults
            # over the operator's real config.
            log.info("M1-shaped installation detected; deferring data/ layout to the migration")
        else:
            seed_data_dir(layout)
        return BootstrapOutcome(False, existing, f"installation already present: {existing}")

    resolved = resolve_current_version(settings)  # raises VersionResolutionError
    install_version(resolved, layout, settings)
    layout.set_active_version(resolved.version)
    seed_data_dir(layout)
    log.info("bootstrapped BDS %s", resolved.version)
    return BootstrapOutcome(True, resolved.version, f"installed and activated {resolved.version}")
