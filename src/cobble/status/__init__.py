"""Observable state of the managed server (section 6).

:mod:`cobble.status.tracker` derives a single coherent view — run state,
installed version, uptime, online players, last-shutdown cleanliness — from the
supervisor and the event stream, and pushes it to connected clients on change.
"""

from cobble.status.tracker import OnlinePlayer, StatusSnapshot, StatusTracker

__all__ = ["OnlinePlayer", "StatusSnapshot", "StatusTracker"]
