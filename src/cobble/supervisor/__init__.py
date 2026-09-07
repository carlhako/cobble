"""Supervision of the Bedrock Dedicated Server child process (section 3).

* :mod:`cobble.supervisor.state` — the run-state model and guarded transitions.
* :mod:`cobble.supervisor.process` — spawning BDS and owning its stdin/stdout.
* :mod:`cobble.supervisor.shutdown_record` — persisted shutdown cleanliness.
* :mod:`cobble.supervisor.supervisor` — the orchestrator the rest of cobble uses.
"""

from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import (
    AlreadyRunningError,
    NoInstallationError,
    Supervisor,
    SupervisorError,
    TransitionError,
)

__all__ = [
    "AlreadyRunningError",
    "NoInstallationError",
    "RunState",
    "Supervisor",
    "SupervisorError",
    "TransitionError",
]
