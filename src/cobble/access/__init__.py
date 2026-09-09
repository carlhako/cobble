"""Who may join this server and what they may do once in (server-access spec).

This package owns the two JSON documents the Bedrock server reads for access
control — ``allowlist.json`` and ``permissions.json`` — their atomic
round-tripping (:mod:`cobble.access.documents`), cobble's durable ban record
(:mod:`cobble.access.store`), and the service that composes ban / unban / kick /
op and keeps the files, the running server, and the record consistent
(:mod:`cobble.access.service`).
"""

from __future__ import annotations

__all__: list[str] = []
