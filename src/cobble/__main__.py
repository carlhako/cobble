"""Console entrypoint: ``cobble`` / ``python -m cobble``."""

from __future__ import annotations

import uvicorn

from cobble.logging import configure_logging
from cobble.settings import get_settings


def main() -> None:
    configure_logging()
    settings = get_settings()
    uvicorn.run(
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


if __name__ == "__main__":
    main()
