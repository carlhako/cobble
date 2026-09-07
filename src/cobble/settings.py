"""Configuration for cobble.

Settings are read, in decreasing precedence, from:

1. Environment variables prefixed ``COBBLE_`` (e.g. ``COBBLE_SHUTDOWN_TIMEOUT=180``).
2. A TOML config file, whose path is taken from ``COBBLE_CONFIG_FILE`` and
   otherwise defaults to ``/etc/cobble/cobble.toml``.
3. The documented defaults below.

Every value has a default, so cobble loads with no config file and no
environment set. This is the state on a fresh container before first run.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

DEFAULT_CONFIG_FILE = Path("/etc/cobble/cobble.toml")


class _TomlConfigSource(PydanticBaseSettingsSource):
    """Loads settings from the TOML file named by ``COBBLE_CONFIG_FILE``."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        import os

        raw_path = os.environ.get("COBBLE_CONFIG_FILE")
        path = Path(raw_path) if raw_path else DEFAULT_CONFIG_FILE
        if not path.is_file():
            return {}
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        # Accept either a flat table or a ``[cobble]`` section.
        if "cobble" in data and isinstance(data["cobble"], dict):
            data = data["cobble"]
        return {str(k).lower(): v for k, v in data.items()}


class Settings(BaseSettings):
    """Runtime configuration.

    Paths default to the layout described in ``design.md`` (D5).
    """

    model_config = SettingsConfigDict(
        env_prefix="COBBLE_",
        env_file=None,
        extra="ignore",
    )

    # --- Filesystem layout -------------------------------------------------
    bedrock_root: Path = Field(
        default=Path("/srv/bedrock"),
        description="Root holding per-version Bedrock installations and the 'current' symlink.",
    )
    state_dir: Path = Field(
        default=Path("/var/lib/cobble"),
        description="Cobble's own durable state directory. Captured as a unit by backups.",
    )
    backup_dir: Path = Field(
        default=Path("/backup"),
        description="Default backup destination. Treated as a plain filesystem path.",
    )

    # --- Timeouts and thresholds ----------------------------------------
    shutdown_timeout: float = Field(
        default=120.0,
        ge=1.0,
        description=(
            "Seconds to wait after issuing 'stop' before forcibly terminating the "
            "Bedrock server. Default is at least 120s so LevelDB can flush a large world."
        ),
    )
    readiness_timeout: float = Field(
        default=120.0,
        ge=1.0,
        description=(
            "Seconds to wait for the server's startup-complete line before declaring "
            "the start attempt failed."
        ),
    )
    crash_restart_threshold: int = Field(
        default=3,
        ge=0,
        description=(
            "Number of crashes within crash_restart_window seconds after which cobble "
            "abandons automatic restart and leaves the failure visible. 0 disables "
            "automatic restart entirely."
        ),
    )
    crash_restart_window: float = Field(
        default=300.0,
        ge=1.0,
        description="Sliding window, in seconds, over which crash_restart_threshold is counted.",
    )

    # --- Networking -----------------------------------------------------
    host: str = Field(default="0.0.0.0", description="Address the HTTP service binds to.")
    port: int = Field(default=8000, ge=1, le=65535, description="Port the HTTP service binds to.")

    # --- Acquisition --------------------------------------------------
    user_agent: str = Field(
        default="cobble/0.1 (+https://github.com/cobble)",
        description=(
            "User-Agent sent on every request to the vendor download source. The vendor "
            "rejects requests without one."
        ),
    )
    download_links_url: str = Field(
        default="https://net-secondary.web.minecraft-services.net/api/v1.0/download/links",
        description="Vendor endpoint listing current Bedrock download URLs.",
    )

    console_buffer_lines: int = Field(
        default=2000,
        ge=1,
        description="Maximum console lines retained in the in-memory history buffer.",
    )
    bootstrap_on_start: bool = Field(
        default=True,
        description=(
            "On startup, acquire and activate the current Bedrock version if no "
            "installation is present. Disable to manage installations out of band."
        ),
    )

    @property
    def versions_dir(self) -> Path:
        return self.bedrock_root / "versions"

    @property
    def current_link(self) -> Path:
        return self.bedrock_root / "current"

    @property
    def shutdown_record_file(self) -> Path:
        return self.state_dir / "last_shutdown.json"

    @property
    def runtime_state_file(self) -> Path:
        return self.state_dir / "runtime.json"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _TomlConfigSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
