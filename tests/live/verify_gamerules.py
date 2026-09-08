#!/usr/bin/env python3
"""Live verification of cobble's gamerule behaviour against a real BDS
(gamerule-editing-and-defaults, section 7).

No Bedrock client is needed: a "change made outside cobble" is driven through the
operator console route (``/api/console/command``), which the gamerule service
does not originate.

  7.2  read the set, write a rule, confirm by re-read, restart, value survives
  7.3  a gamerule changed outside cobble is adopted and reported on next readiness
  7.4  a restore is followed by a repair, not an adoption
  7.5  the recorded Bedrock output formats still hold, and no bulk read or write
       appears in the operator console

Prerequisites: COBBLE_LIVE_HOST (+ COBBLE_LIVE_ROOT_PW for 7.4's restore path if
your build guards it), key-based SSH, cobble reachable at localhost:8000 on the
host, running this cobble build. The script restores every gamerule it changed.

Usage:
  python tests/live/verify_gamerules.py                 # 7.2, 7.3, 7.4, 7.5
  python tests/live/verify_gamerules.py --only 72,75
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from remote import HOST, last_json_line, sh
from verify import Checks, api, wait_running

_EXPECTED_RULE_NAMES = {
    "commandBlockOutput", "doDayLightCycle", "doEntityDrops", "doFireTick", "recipesUnlock",
    "doLimitedCrafting", "doMobLoot", "doMobSpawning", "doTileDrops", "doWeatherCycle",
    "drowningDamage", "fallDamage", "fireDamage", "keepInventory", "mobGriefing", "pvp",
    "showCoordinates", "playerWaypoints", "locatorbar", "showDaysPlayed", "naturalRegeneration",
    "tntExplodes", "sendCommandFeedback", "maxCommandChainLength", "doInsomnia",
    "commandBlocksEnabled", "randomTickSpeed", "doImmediateRespawn", "showDeathMessages",
    "functionCommandLimit", "spawnRadius", "showTags", "freezeDamage", "respawnBlocksExplode",
    "showBorderEffect", "showRecipeMessages", "playersSleepingPercentage",
    "projectilesCanBreakBlocks", "tntExplosionDropDecay",
}


def post(path: str, body: dict | None = None):
    data = f" -H 'content-type: application/json' -d '{json.dumps(body)}'" if body else ""
    _, out = sh(f"curl -s -XPOST localhost:8000{path}{data}")
    return last_json_line(out) if out.strip() else {}


def gamerules() -> dict:
    return api("/api/gamerules")


def rule_value(view: dict, name: str):
    for r in view["rules"]:
        if r["name"] == name:
            return r["value"]
    raise KeyError(name)


def console_command(cmd: str) -> None:
    sh(
        "curl -s -XPOST localhost:8000/api/console/command "
        f"-H 'content-type: application/json' -d '{json.dumps({'command': cmd})}' >/dev/null"
    )


def restart_and_wait() -> None:
    post("/api/server/restart")
    time.sleep(3)
    assert wait_running(), "server did not come back after restart"
    # give readiness reconciliation a moment
    time.sleep(3)


def acknowledge() -> None:
    post("/api/gamerules/acknowledge")


# -- 7.2 -------------------------------------------------------------
def task_72(check: Checks) -> None:
    print("== 7.2: write a rule, confirm by re-read, survive a restart ==")
    assert wait_running(), "server is not running"
    view = gamerules()
    check("live set is reported while running", view["liveness"] == "live")
    original = rule_value(view, "doInsomnia")
    target = not original

    res = post("/api/gamerules", {"name": "doInsomnia", "value": target})
    check("write was applied (not queued)", res.get("queued") is False)
    check("re-read value matches what was written", res["rule"]["value"] == target)
    check("GET reflects the new value", rule_value(gamerules(), "doInsomnia") == target)

    restart_and_wait()
    check(
        "the changed value survived a clean restart",
        rule_value(gamerules(), "doInsomnia") == target,
    )

    # restore
    post("/api/gamerules", {"name": "doInsomnia", "value": original})
    acknowledge()


# -- 7.3 -------------------------------------------------------------
def task_73(check: Checks) -> None:
    print("== 7.3: a change made outside cobble is adopted and reported ==")
    assert wait_running(), "server is not running"
    # make sure a record exists for this world
    restart_and_wait()
    before = rule_value(gamerules(), "mobGriefing")
    flipped = not before

    print(f"- flipping mobGriefing to {flipped} via the operator console")
    console_command(f"gamerule mobGriefing {'true' if flipped else 'false'}")
    time.sleep(2)
    restart_and_wait()  # fresh readiness -> reconciliation

    view = gamerules()
    report = view.get("report")
    check("an unacknowledged report is present after readiness", report is not None)
    check("the report is an adoption", report and report["kind"] == "adoption")
    check(
        "the report names mobGriefing with the new value",
        report and report["rules"].get("mobGriefing") == flipped,
    )
    check(
        "the live value was left as set outside cobble",
        rule_value(view, "mobGriefing") == flipped,
    )

    acknowledge()
    check("acknowledging clears the report", gamerules().get("report") is None)

    # restore
    post("/api/gamerules", {"name": "mobGriefing", "value": before})
    acknowledge()


# -- 7.4 -------------------------------------------------------------
def _set_and_settle(check: Checks, name: str, value: bool) -> None:
    """Set a rule via the API, restart so a readiness folds it into the record,
    and acknowledge the resulting adoption."""
    post("/api/gamerules", {"name": name, "value": value})
    restart_and_wait()
    acknowledge()
    check(f"{name} settled to {value} in the record", rule_value(gamerules(), name) == value)


def task_74(check: Checks) -> None:
    print("== 7.4: a restore is followed by a repair, not an adoption ==")
    assert wait_running(), "server is not running"
    restart_and_wait()
    acknowledge()

    baseline = rule_value(gamerules(), "doFireTick")
    backup_value = not baseline  # the value the backup's world will carry

    # 1. put doFireTick at backup_value and let a clean stop write it to level.dat
    _set_and_settle(check, "doFireTick", backup_value)
    print("- capturing a backup (world carries doFireTick =", backup_value, ")")
    cap = post("/api/backups")
    check("backup captured ok", cap.get("ok") is True)
    time.sleep(2)
    assert wait_running()
    backups = api("/api/backups").get("backups", [])
    archive = (
        sorted(backups, key=lambda b: b.get("captured_at") or "")[-1]["archive"]
        if backups
        else None
    )
    check("a backup archive is listed", archive is not None)

    # 2. now move the record to the opposite value, so the record and the
    #    backup's world disagree
    record_value = baseline
    _set_and_settle(check, "doFireTick", record_value)

    # 3. restore: the world's level.dat reverts to backup_value; cobble knows it
    #    restored, so the next readiness repairs (re-applies record_value) rather
    #    than adopting the reverted value.
    print(f"- restoring {archive}")
    res = post(f"/api/backups/{archive}/restore", {"confirm_old_version": True})
    check("restore reported ok", res.get("ok") is True)
    time.sleep(5)
    assert wait_running(), "server did not come back after the restore"
    time.sleep(6)  # readiness + the repair's write-back

    view = gamerules()
    report = view.get("report")
    check("a report is present after the restore's readiness", report is not None)
    check("the report is a repair, not an adoption", report and report["kind"] == "repair")
    check(
        "the repair re-applied the recorded doFireTick",
        report and report["rules"].get("doFireTick") == record_value,
    )
    check(
        "the live value is the recorded one, not the reverted one",
        rule_value(gamerules(), "doFireTick") == record_value,
    )

    acknowledge()
    # 4. the marker was one-shot: a fresh out-of-band change now adopts again
    console_command(f"gamerule doFireTick {'true' if backup_value else 'false'}")
    time.sleep(2)
    restart_and_wait()
    after = gamerules().get("report")
    check(
        "the next start adopts a fresh change rather than repairing",
        after is not None and after["kind"] == "adoption",
    )

    acknowledge()
    post("/api/gamerules", {"name": "doFireTick", "value": baseline})
    acknowledge()


# -- 7.5 -------------------------------------------------------------
def task_75(check: Checks) -> None:
    print("== 7.5: output formats hold; no bulk read/write in the operator console ==")
    assert wait_running(), "server is not running"

    # Capture the operator console stream while we (a) submit `gamerule` as an
    # operator command (echoed, so we can check the format) and (b) drive
    # cobble's own silent bulk read + write, which must NOT appear. The stream
    # replays retained history first, so a nonce command marks where our window
    # starts.
    import subprocess
    import uuid

    nonce = f"cobblemark{uuid.uuid4().hex[:8]}"
    proc = subprocess.Popen(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"{_ssh_user()}@{HOST}",
         "timeout 8 curl -sN localhost:8000/api/console/stream"],
        stdout=subprocess.PIPE, text=True,
    )
    time.sleep(1)
    console_command(nonce)  # window marker
    time.sleep(0.5)
    console_command("gamerule")
    console_command("gamerule doInsomnia true")
    time.sleep(1)
    # also drive a cobble bulk read + write (silent path) during the same window
    gamerules()
    post("/api/gamerules", {"name": "doInsomnia", "value": False})
    time.sleep(2)
    stream, _ = proc.communicate(timeout=20)

    all_lines = [
        json.loads(x[len("data: "):])
        for x in stream.splitlines()
        if x.startswith("data: ") and x[len("data: "):].strip().startswith("{")
    ]
    start = next(
        (i for i, ln in enumerate(all_lines) if ln.get("text") == nonce),
        0,
    )
    lines = all_lines[start:]
    texts = [ln["text"] for ln in lines]

    dump_lines = [t for t in texts if t.count(" = ") >= 5 and ", " in t]
    check(
        "the operator `gamerule` reply is present and has the dump shape",
        len(dump_lines) >= 1,
    )
    if dump_lines:
        names = set()
        for chunk in dump_lines[-1].split(", "):
            name = chunk.split(" = ")[0].strip().split(" ")[-1]
            names.add(name)
        missing = _EXPECTED_RULE_NAMES - names
        check(
            f"all 39 recorded rule names still present (missing: {sorted(missing)})",
            not missing,
        )

    cmd_lines = [ln for ln in lines if ln.get("kind") == "command" and ln.get("text") != nonce]
    # exactly the two operator commands we submitted — cobble's own bulk read and
    # write must not appear as commands or as a second dump.
    check(
        "only the operator's own gamerule commands are echoed",
        sorted(c["text"] for c in cmd_lines) == ["gamerule", "gamerule doInsomnia true"],
    )
    check(
        "cobble's silent bulk read did not add a second dump line",
        len(dump_lines) == 1,
    )

    acknowledge()
    restart_and_wait()
    acknowledge()


def _ssh_user() -> str:
    import os

    return os.environ.get("COBBLE_LIVE_SSH_USER") or os.environ.get("USER") or "root"


TASKS = {"72": task_72, "73": task_73, "74": task_74, "75": task_75}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", help="comma-separated subset: 72,73,74,75")
    args = ap.parse_args()

    if not HOST:
        print("COBBLE_LIVE_HOST is not set", file=sys.stderr)
        return 2

    which = args.only.split(",") if args.only else ["72", "73", "74", "75"]
    check = Checks()
    for key in which:
        TASKS[key.strip()](check)
        print()

    print(f"== {check.total - check.failed}/{check.total} checks passed ==")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
