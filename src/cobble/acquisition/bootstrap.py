"""First-run bootstrap: acquire and activate the current version, but only when
no installation exists.

A second run performs no download and leaves the active version unchanged
(installation spec: "Installation already present").
"""

from __future__ import annotations

from dataclasses import dataclass

from cobble.acquisition.installer import install_version
from cobble.acquisition.layout import Layout
from cobble.acquisition.version_source import resolve_current_version
from cobble.logging import get_logger
from cobble.settings import Settings

log = get_logger("acquisition.bootstrap")


@dataclass(frozen=True)
class BootstrapOutcome:
    installed: bool
    version: str | None
    message: str


def bootstrap_if_needed(settings: Settings, layout: Layout | None = None) -> BootstrapOutcome:
    layout = layout or Layout.from_settings(settings)
    layout.ensure_directories()

    existing = layout.installed_version()
    if existing is not None and layout.has_installation():
        log.info("installation already present (%s); no download performed", existing)
        return BootstrapOutcome(False, existing, f"installation already present: {existing}")

    resolved = resolve_current_version(settings)  # raises VersionResolutionError
    install_version(resolved, layout, settings)
    layout.set_active_version(resolved.version)
    log.info("bootstrapped BDS %s", resolved.version)
    return BootstrapOutcome(True, resolved.version, f"installed and activated {resolved.version}")
