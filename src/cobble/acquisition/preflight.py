"""Platform preflight checks (design.md — Platform limits).

BDS is x86-64 only and needs glibc >= 2.26. Each failure names the specific
unmet requirement so the operator does not get an obscure exec-format or
symbol-lookup error at runtime.
"""

from __future__ import annotations

import ctypes
import platform
import re
from dataclasses import dataclass

MIN_GLIBC = (2, 26)
_SUPPORTED_MACHINES = {"x86_64", "amd64"}


class PreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    failures: list[str]

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise PreflightError("; ".join(self.failures))


def _check_architecture() -> str | None:
    machine = platform.machine().lower()
    if machine not in _SUPPORTED_MACHINES:
        return (
            f"the Bedrock Dedicated Server is unavailable for this architecture "
            f"({machine or 'unknown'}); it is published only for 64-bit x86 (amd64)"
        )
    return None


def _glibc_version() -> tuple[int, int] | None:
    # Preferred: the libc tuple platform exposes on glibc systems.
    try:
        name, version = platform.libc_ver()
    except OSError:
        name, version = "", ""
    if name == "glibc" and version:
        parts = version.split(".")
        try:
            return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            pass
    # Fallback: ask libc directly.
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.gnu_get_libc_version.restype = ctypes.c_char_p
        raw = libc.gnu_get_libc_version().decode()
        match = re.match(r"(\d+)\.(\d+)", raw)
        if match:
            return int(match.group(1)), int(match.group(2))
    except (OSError, AttributeError):
        pass
    return None


def _check_glibc() -> str | None:
    version = _glibc_version()
    if version is None:
        return (
            "could not determine the system C library version; the Bedrock server "
            f"requires glibc {MIN_GLIBC[0]}.{MIN_GLIBC[1]} or newer"
        )
    if version < MIN_GLIBC:
        return (
            f"system C library is glibc {version[0]}.{version[1]}; the Bedrock server "
            f"requires at least glibc {MIN_GLIBC[0]}.{MIN_GLIBC[1]}"
        )
    return None


def run_preflight() -> PreflightResult:
    failures = [msg for msg in (_check_architecture(), _check_glibc()) if msg]
    return PreflightResult(ok=not failures, failures=failures)
