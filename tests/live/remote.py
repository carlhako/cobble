"""SSH helpers for the live verification harness.

Target host and credentials come from the environment — nothing is hardcoded:

  COBBLE_LIVE_HOST       hostname / IP of the box running cobble          (required)
  COBBLE_LIVE_SSH_USER   ssh login user                                   (default: $USER)
  COBBLE_LIVE_ROOT_PW    root password, for `su`-elevated steps           (only needed for those)

Key-based SSH to COBBLE_LIVE_SSH_USER is assumed (set it up with `ssh-copy-id`).
Root steps stage a script as the login user, then run it under `su -c`, feeding
COBBLE_LIVE_ROOT_PW to the one password prompt.
"""

from __future__ import annotations

import base64
import os
import subprocess
import time
import uuid

HOST = os.environ.get("COBBLE_LIVE_HOST", "")
USER = os.environ.get("COBBLE_LIVE_SSH_USER") or os.environ.get("USER") or "root"
ROOT_PW = os.environ.get("COBBLE_LIVE_ROOT_PW", "")
_SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]


def _require_host() -> str:
    if not HOST:
        raise SystemExit("COBBLE_LIVE_HOST is not set")
    return HOST


def sh(cmd: str, *, root: bool = False, timeout: int = 240) -> tuple[int, str]:
    """Run a shell snippet on the target host. Returns (exit_code, combined_output)."""
    host = _require_host()
    if not root:
        r = subprocess.run(
            ["ssh", *_SSH_OPTS, f"{USER}@{host}", "bash -e"],
            input=cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout + r.stderr

    if not ROOT_PW:
        raise SystemExit("COBBLE_LIVE_ROOT_PW is not set; needed for a root step")
    try:
        import pexpect
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "the 'pexpect' package is required for root steps: pip install pexpect"
        ) from e

    name = f"/tmp/.cobble-live-{uuid.uuid4().hex}.sh"
    b64 = base64.b64encode(cmd.encode()).decode()
    subprocess.run(
        ["ssh", *_SSH_OPTS, f"{USER}@{host}", f"echo {b64} | base64 -d > {name}"],
        check=True,
        timeout=30,
    )
    child = pexpect.spawn(
        "ssh",
        ["-tt", *_SSH_OPTS, f"{USER}@{host}", f"su -c 'bash {name}' root; rm -f {name}"],
        encoding="utf-8",
        timeout=timeout,
    )
    child.expect(r"[Pp]assword:")
    time.sleep(0.4)
    child.sendline(ROOT_PW)
    child.expect(pexpect.EOF)
    out = child.before or ""
    child.close()
    return child.exitstatus or 0, out


def last_json_line(out: str):
    import json

    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            return json.loads(line)
    raise ValueError(f"no JSON found in output:\n{out}")
