"""Console entrypoint: ``cobble`` / ``python -m cobble``."""

from __future__ import annotations

import sys

import uvicorn

from cobble import restart
from cobble.logging import configure_logging
from cobble.settings import get_settings

# uvicorn.run's own status for a server that never started.
_STARTUP_FAILURE = 3


def main() -> None:
    configure_logging()
    settings = get_settings()
    config = uvicorn.Config(
        "cobble.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,
        # SSE connections stay open indefinitely; don't let them hold up the
        # shutdown that stops the Bedrock child cleanly. systemd's
        # TimeoutStopSec covers this plus the BDS shutdown timeout.
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)
    # Owning the server lets cobble shut itself down gracefully to restart
    # after a restore (import-backup-archive design.md D7).
    restart.set_exit_hook(lambda: setattr(server, "should_exit", True))
    server.run()
    if restart.requested():
        sys.exit(restart.EXIT_RESTART)
    if not server.started:
        sys.exit(_STARTUP_FAILURE)


if __name__ == "__main__":
    main()
