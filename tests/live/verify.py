#!/usr/bin/env python3
"""Live verification of cobble's player-history behaviour against a real server.

Drives a running cobble install (over SSH) plus a headless authenticated Bedrock
client (tests/live/bot) to exercise the three things unit tests can't:

  8.3  a real join is recorded; a real leave closes it `observed`; a server stop
       with the player online closes it `server_stop`; no row is left dangling
  8.4  killing cobble abruptly (SIGKILL) leaves the session closed `reconstructed`
       at its last checkpoint on the next start
  8.5  a backup captured with history present restores to a database that opens
       and holds every committed session

Prerequisites:
  * env: COBBLE_LIVE_HOST, COBBLE_LIVE_ROOT_PW (+ COBBLE_LIVE_SSH_USER if not $USER)
  * key-based SSH to that host; cobble reachable at localhost:8000 on it
  * `npm ci` in tests/live/bot, then one interactive `node bot.js` run to complete
    the Microsoft device-code sign-in (token caches outside this repo)
  * `pip install pexpect` locally

Usage:
  python tests/live/verify.py                 # 8.3, 8.4, 8.5 in order
  python tests/live/verify.py --only 84       # one scenario
  python tests/live/verify.py --wipe          # clear player history first
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from remote import HOST, last_json_line, sh

BOT = Path(__file__).parent / "bot"
DB = os.environ.get("COBBLE_LIVE_DB", "/var/lib/cobble/cobble.db")
BACKUP_DIR = os.environ.get("COBBLE_LIVE_BACKUP_DIR", "/backup")
CHECKPOINT_S = 20  # override pushed for 8.4 so the test is quick


# -- probes ---------------------------------------------------------
def api(path: str):
    _, out = sh(f"curl -s localhost:8000{path}")
    return last_json_line(out)


def sessions_raw() -> list[list]:
    _, out = sh(
        'python3 -c "import sqlite3,json; '
        f"print(json.dumps([list(r) for r in sqlite3.connect('{DB}').execute("
        "'SELECT id,xuid,gamertag,connected_at,spawned_at,disconnected_at,end_reason,last_active_at "
        'FROM sessions ORDER BY id\')]))"'
    )
    return last_json_line(out)


def open_count() -> int:
    _, out = sh(
        'python3 -c "import sqlite3; '
        f"print(sqlite3.connect('{DB}').execute("
        "'SELECT count(*) FROM sessions WHERE end_reason IS NULL').fetchone()[0])\""
    )
    return int(out.strip().splitlines()[-1])


def run_bot(username: str, hold: int, *, background: bool = False):
    env = {**os.environ, "BOT_HOST": HOST}
    cmd = ["node", str(BOT / "bot.js"), username, str(hold)]
    if background:
        return subprocess.Popen(
            cmd, cwd=BOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    r = subprocess.run(cmd, cwd=BOT, env=env, capture_output=True, text=True, timeout=hold + 180)
    return r.returncode, r.stdout + r.stderr


def wait_running(tries: int = 40) -> bool:
    for _ in range(tries):
        try:
            if api("/api/status")["run_state"] == "running":
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def wait_online(timeout: int = 70) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        online = [p for p in api("/api/players")["players"] if p["online"]]
        if online:
            return online[0]["xuid"]
    return None


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# -- check accounting --------------------------------------------
class Checks:
    def __init__(self) -> None:
        self.failed = 0
        self.total = 0

    def __call__(self, label: str, cond: bool) -> None:
        self.total += 1
        if not cond:
            self.failed += 1
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")


# -- scenarios --------------------------------------------------
def task_83(check: Checks) -> None:
    print("== 8.3: observed join/leave, then server_stop ==")
    assert wait_running(), "server is not running"
    base = len(sessions_raw())

    print("- bot joins and leaves")
    _, out = run_bot("RosterBot", 10)
    for line in out.strip().splitlines():
        print("   ", line)
    time.sleep(2)
    rows = sessions_raw()
    check("a session was recorded for the join", len(rows) == base + 1)
    sid, xuid, _gt, _conn, spawned, disc, reason, _la = rows[-1]
    check("session has a real numeric xuid", str(xuid).isdigit())
    check("world entry (spawn) was recorded", spawned is not None)
    check("session closed as end_reason='observed'", reason == "observed")
    check("disconnected_at is set", disc is not None)
    check("no dangling open session", open_count() == 0)
    p = next(x for x in api("/api/players")["players"] if x["xuid"] == xuid)
    check("roster shows the player offline", p["online"] is False)
    check("roster total is not approximate", p["approximate"] is False)

    print("- bot rejoins, stays online, server is stopped")
    proc = run_bot("RosterBot", 90, background=True)
    try:
        check("roster shows the player online mid-session", wait_online() == xuid)
        check("exactly one session open while connected", open_count() == 1)
        sess = api(f"/api/players/{xuid}/sessions")["sessions"]
        check("newest session reads in_progress", sess[0]["in_progress"] is True)
        sh("curl -s -XPOST localhost:8000/api/server/stop >/dev/null")
        time.sleep(4)
    finally:
        proc.kill()
    reason2 = sessions_raw()[-1][6]
    check("session closed as end_reason='server_stop'", reason2 == "server_stop")
    check("no dangling open session after the stop", open_count() == 0)
    sess = api(f"/api/players/{xuid}/sessions")["sessions"]
    check("that session is not marked approximate", sess[0]["approximate"] is False)

    sh("curl -s -XPOST localhost:8000/api/server/start >/dev/null")
    wait_running()


def task_84(check: Checks) -> None:
    print("== 8.4: reconciliation after an abrupt cobble kill ==")
    sh(
        f"mkdir -p /etc/cobble && echo 'COBBLE_PLAYER_HISTORY_CHECKPOINT_SECONDS={CHECKPOINT_S}' "
        "> /etc/cobble/cobble.env && systemctl restart cobble",
        root=True,
    )
    time.sleep(8)
    assert wait_running(), "server did not come back after restart"

    proc = run_bot("RosterBot", 240, background=True)
    try:
        xuid = wait_online()
        check("player online for the test", xuid is not None)

        def last_active() -> str:
            return [r for r in sessions_raw() if r[6] is None][-1][7]

        a1 = last_active()
        time.sleep(CHECKPOINT_S + 10)
        a2 = last_active()
        check(f"last_active_at advances while running ({a1} -> {a2})", a2 > a1)

        _, tk = sh("date -u +%Y-%m-%dT%H:%M:%S.%3NZ")
        t_kill = tk.strip().splitlines()[-1]
        print(f"- kill -9 cobble at {t_kill}")
        sh(
            'kill -9 "$(systemctl show -p MainPID --value cobble)"; '
            "pkill -9 bedrock_server || true",
            root=True,
        )
    finally:
        proc.kill()

    up = False
    for _ in range(25):
        time.sleep(3)
        _, act = sh("systemctl is-active cobble || true")
        if act.strip().splitlines()[-1].strip() == "active":
            try:
                if api("/health").get("status") == "ok":
                    up = True
                    break
            except Exception:
                pass
    check("cobble auto-restarted after the SIGKILL", up)

    row = [r for r in sessions_raw() if r[1] == xuid][-1]
    check("session closed as end_reason='reconstructed'", row[6] == "reconstructed")
    p = next(x for x in api("/api/players")["players"] if x["xuid"] == xuid)
    check("roster total is marked approximate", p["approximate"] is True)
    check("no dangling open session", open_count() == 0)
    sess = api(f"/api/players/{xuid}/sessions")["sessions"][0]
    check("the session is reported approximate by the API", sess["approximate"] is True)
    gap = (_parse(t_kill) - _parse(row[5])).total_seconds()
    check(
        f"end time is the last checkpoint, at/just before the kill "
        f"(gap {gap:.1f}s, want 0..{CHECKPOINT_S + 5})",
        -2 <= gap <= CHECKPOINT_S + 5,
    )

    sh("rm -f /etc/cobble/cobble.env && systemctl restart cobble", root=True)
    time.sleep(8)
    wait_running()


def task_85(check: Checks) -> None:
    import json
    import re

    print("== 8.5: backup consistency ==")
    live = sessions_raw()
    check("history is present before the backup", len(live) > 0)
    _, out = sh("curl -s -XPOST localhost:8000/api/backups")
    res = last_json_line(out)
    print("   capture ->", res)
    check("backup reported ok", res.get("ok") is True)
    wait_running()

    script = f"""
set -e
ARCHIVE=$(ls -t {BACKUP_DIR}/*.tar.gz | head -1)
echo "ARCHIVE=$ARCHIVE"
rm -rf /tmp/cobble-live-scratch && mkdir /tmp/cobble-live-scratch
tar xzf "$ARCHIVE" -C /tmp/cobble-live-scratch
echo "STATE_DIR_LISTING:"
ls -l /tmp/cobble-live-scratch/cobble-state/
python3 - <<'PY'
import sqlite3, json
c = sqlite3.connect('/tmp/cobble-live-scratch/cobble-state/cobble.db')
print('integrity:', c.execute('PRAGMA integrity_check').fetchone()[0])
print('schema_version:', c.execute('SELECT version FROM schema_version').fetchone()[0])
print('SESSIONS:' + json.dumps([list(r) for r in c.execute(
    'SELECT id,xuid,gamertag,connected_at,disconnected_at,end_reason FROM sessions ORDER BY id')]))
PY
rm -rf /tmp/cobble-live-scratch
"""
    _, out = sh(script, root=True)
    for line in out.strip().splitlines():
        print("   ", line)
    check("archive database passes PRAGMA integrity_check", "integrity: ok" in out)
    wal = next((l for l in out.splitlines() if l.rstrip().endswith("cobble.db-wal")), "")
    wal_size = int(wal.split()[4]) if len(wal.split()) >= 5 else -1
    check(f"WAL sidecar in the archive is empty (size={wal_size})", wal_size == 0)
    m = re.search(r"SESSIONS:(\[.*\])", out)
    restored = json.loads(m.group(1)) if m else []
    live_ids = {r[0] for r in live}
    restored_ids = {r[0] for r in restored}
    check(
        f"every committed session is in the restored db "
        f"({len(restored_ids)} rows, need >= {len(live_ids)})",
        live_ids <= restored_ids,
    )


TASKS = {"83": task_83, "84": task_84, "85": task_85}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated subset: 83,84,85")
    ap.add_argument("--wipe", action="store_true", help="clear player history before running")
    args = ap.parse_args()

    if not HOST:
        print("COBBLE_LIVE_HOST is not set", file=sys.stderr)
        return 2

    if args.wipe:
        print("- wiping player history")
        sh(
            f"systemctl stop cobble && rm -f {DB} {DB}-wal {DB}-shm && systemctl start cobble",
            root=True,
        )
        time.sleep(8)
        wait_running()

    which = args.only.split(",") if args.only else ["83", "84", "85"]
    check = Checks()
    for key in which:
        TASKS[key.strip()](check)
        print()

    print(f"== {check.total - check.failed}/{check.total} checks passed ==")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
