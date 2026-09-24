"""Keeping cobble itself current (cobble-self-update spec).

:mod:`cobble.selfupdate.release_check` asks GitHub whether a newer stable cobble
release exists. :mod:`cobble.selfupdate.upgrade` turns an operator's request
into an upgrade request file that the root-owned helper (``deploy/cobble-upgrade``)
acts on, and reports the outcome. Cobble itself never gains privileges.
"""
