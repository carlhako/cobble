"""Bringing an externally-supplied Bedrock world archive onto the server (M7).

The package owns archive inspection (:mod:`cobble.worldimport.archive`), the
single-slot upload staging area (:mod:`cobble.worldimport.staging`), and the
stop / capture / replace / start import sequence
(:mod:`cobble.worldimport.service`). Everything here is additive: nothing in an
existing capability changes.
"""

from __future__ import annotations

from cobble.worldimport.archive import ArchiveError

__all__ = ["ArchiveError"]
