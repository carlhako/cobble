"""Bedrock Dedicated Server acquisition and on-disk layout.

Submodules:

* :mod:`cobble.acquisition.version_source` — resolve the current version and
  download URL from the vendor's published JSON source.
* :mod:`cobble.acquisition.layout` — the per-version directory layout and the
  ``current`` indirection.
* :mod:`cobble.acquisition.installer` — download and extract a version into place.
* :mod:`cobble.acquisition.preflight` — architecture and C-library checks.
* :mod:`cobble.acquisition.bootstrap` — first-run acquisition.
"""
