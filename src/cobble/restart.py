"""Cobble restarting its own process (import-backup-archive design.md D7).

After a restore, cobble's state is staged for the next start, so the process
must go round once. :func:`request` records that and asks the server to shut
down gracefully through a hook the entry point registers; :mod:`cobble.__main__`
then exits with :data:`EXIT_RESTART`, a non-zero status the installed unit's
``Restart=on-failure`` restarts.

The hook sets uvicorn's ``should_exit`` rather than signalling the process:
uvicorn re-raises a captured SIGTERM after shutdown, and systemd treats death by
SIGTERM as a clean stop that ``on-failure`` does not restart.
"""

from __future__ import annotations

from collections.abc import Callable

from cobble.logging import get_logger

log = get_logger("restart")

# EX_TEMPFAIL: "try again" — any non-zero status restarts under on-failure.
EXIT_RESTART = 75

_requested = False
_exit_hook: Callable[[], None] | None = None


def set_exit_hook(hook: Callable[[], None] | None) -> None:
    """Register how to begin a graceful shutdown of the serving process."""
    global _exit_hook
    _exit_hook = hook


def requested() -> bool:
    return _requested


def request(reason: str) -> None:
    """Record that cobble must restart, and begin the graceful shutdown."""
    global _requested
    _requested = True
    if _exit_hook is None:
        log.warning("cobble must restart (%s), but no entry point can stop it; restart it", reason)
        return
    log.info("cobble is restarting: %s", reason)
    _exit_hook()


def reset() -> None:
    """Clear the request — for tests."""
    global _requested
    _requested = False
