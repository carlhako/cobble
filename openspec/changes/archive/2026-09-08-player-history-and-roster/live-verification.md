# Live verification run sheet — player-history-and-roster (tasks 8.3–8.5)

Target: **cobble-2** (`10.0.1.165`), which was provisioned with `deploy/install.sh`.
You will need a Minecraft Bedrock client to join `10.0.1.165:19132`.

Every command block is labelled **[DEV]** (run in this repo checkout on your
workstation) or **[LXC root]** (run on cobble-2 as root: `ssh carl@10.0.1.165`
then `su -`, password `asdf1234`).

Current state of the box (for reference): cobble 0.3.1, BDS 1.26.45.1, server
running, no `/etc/cobble/cobble.env`, no `sqlite3` CLI (inspection below uses
`python3` only).

Handy shell helpers — **[LXC]** (any user):

```bash
pj()       { python3 -m json.tool; }
roster()   { curl -s localhost:8000/api/players | pj; }
sessions() { curl -s "localhost:8000/api/players/$1/sessions" | pj; }
runstate() { curl -s localhost:8000/api/status | python3 -c "import sys,json;print(json.load(sys.stdin)['run_state'])"; }
opencount(){ python3 -c "import sqlite3;print(sqlite3.connect('/var/lib/cobble/cobble.db').execute('SELECT count(*) FROM sessions WHERE end_reason IS NULL').fetchone()[0])"; }
```

`opencount` prints how many session rows are still open — the "no dangling row" check.

---

## Part 0 — Build and deploy this branch (in-place upgrade via the installer)

The installer is a working in-place upgrade when given a local tarball
(`deploy/install.sh` lines 109–111). Build the same artifact CI would.

### 0.1 [DEV] Build the release tarball

```bash
cd /home/carl/projects/bedrock-server        # this repo checkout

rm -f dist/*.whl                              # drop the stale 0.2.0 wheel
npm --prefix web run build                    # -> src/cobble/static/
test -f src/cobble/static/index.html
.venv/bin/python -m build --wheel --outdir dist
ls dist/cobble-0.3.1-py3-none-any.whl

stage="$(mktemp -d)/cobble"; mkdir -p "$stage"
cp -a dist README.md deploy "$stage/"
tar -czf /tmp/cobble.tar.gz -C "$(dirname "$stage")" cobble

scp /tmp/cobble.tar.gz deploy/install.sh carl@10.0.1.165:/tmp/
```

### 0.2 [LXC root] Run the installer against the local tarball

```bash
COBBLE_TARBALL=/tmp/cobble.tar.gz bash /tmp/install.sh
sleep 5
curl -s localhost:8000/health
```

The installer rebuilds `/opt/cobble/venv`, installs the wheel **by path**, reinstalls
`cobble.service`, and `systemctl restart`s. On this first start the upgraded
cobble creates `/var/lib/cobble/cobble.db`.

### 0.3 [LXC] Smoke-check the new surface

- [ ] `curl -s localhost:8000/openapi.json | python3 -c "import sys,json;p=json.load(sys.stdin)['paths'];print('/api/players' in p, '/api/players/{xuid}/sessions' in p)"` → `True True`
- [ ] `roster` → `{"players": [], "recorded_since": null}` (200, not an error)
- [ ] `ls -l /var/lib/cobble/cobble.db` → exists
- [ ] Browser `http://10.0.1.165:8000/` → a **Players** tab; opening it shows the "No player history yet" explanation and a recorded-since line, styled as info, not an error.

---

## Part 1 — Task 8.3: observed join/leave, then `server_stop`

`runstate` must be `running` (else `curl -XPOST localhost:8000/api/server/start`).

| # | Action | Expected |
|---|--------|----------|
| 1 | Join from your client to `10.0.1.165:19132` | you spawn in the world |
| 2 | `roster` | your player listed, `"online": true`, `"session_count": 1`; note your `xuid` |
| 3 | `sessions <xuid>` | one session, `"in_progress": true`, `"end_reason": null`, `spawned_at` set |
| 4 | Disconnect in the client | — |
| 5 | `sessions <xuid>` | newest session `"in_progress": false`, `"end_reason": "observed"`, `"approximate": false`, `disconnected_at` ≈ when you left |
| 6 | `roster` | your player `"online": false` |
| 7 | Rejoin | — |
| 8 | `roster` | `"session_count": 2`, `"online": true` |
| 9 | **while still online:** `curl -s -XPOST localhost:8000/api/server/stop \| pj` | server stops; you are dropped |
| 10 | `sessions <xuid>` | newest session `"end_reason": "server_stop"`, `"approximate": false`, `disconnected_at` ≈ stop time |
| 11 | `opencount` | `0` |

- [ ] **8.3 passed**

`curl -XPOST localhost:8000/api/server/start` for the next part.

---

## Part 2 — Task 8.4: reconciliation after an abrupt cobble kill

### 2.1 [LXC root] Shorten the checkpoint interval so the test is quick

```bash
mkdir -p /etc/cobble
echo 'COBBLE_PLAYER_HISTORY_CHECKPOINT_SECONDS=20' > /etc/cobble/cobble.env
systemctl restart cobble
sleep 5
```

Start the server if needed (`runstate`).

| # | Action | Expected |
|---|--------|----------|
| 1 | Join from your client | spawned |
| 2 | `roster` | `"online": true`; note your `xuid` |
| 3 | Wait ~45 s. Run this twice, ~25 s apart: `python3 -c "import sqlite3;[print(r) for r in sqlite3.connect('/var/lib/cobble/cobble.db').execute('SELECT xuid,last_active_at FROM sessions WHERE end_reason IS NULL')]"` | `last_active_at` **advances** between the two reads |
| 4 | `date -u +%FT%TZ` — record this as **T_kill** | — |
| 5 | `kill -9 "$(systemctl show -p MainPID --value cobble)"` | cobble dies with no cleanup |
| 6 | `pkill -9 bedrock_server` | orphaned server killed so cobble's auto-restart comes back clean |
| 7 | Wait ~10 s (`Restart=on-failure`, `RestartSec=3`), then `systemctl is-active cobble` and `curl -s localhost:8000/health` | `active`; health OK |
| 8 | `sessions <xuid>` | newest session `"end_reason": "reconstructed"`, `"approximate": true`; `disconnected_at` equals the last checkpoint — at or before **T_kill**, within 20 s of it (the gap until restart is **not** credited) |
| 9 | `opencount` | `0` |
| 10 | `roster` | your player's totals carry `"approximate": true` |

- [ ] **8.4 passed**

### 2.2 [LXC root] Revert the override

```bash
rm -f /etc/cobble/cobble.env
systemctl restart cobble
```

---

## Part 3 — Task 8.5: backup consistency

History from Parts 1–2 should be present (`roster` lists players).

| # | Action | Expected |
|---|--------|----------|
| 1 | `curl -s -XPOST localhost:8000/api/backups \| pj` | `"ok": true` (server briefly stops/restarts around the capture) |
| 2 | `ARCHIVE=$(ls -t /backup/*.tar.gz \| head -1); echo "$ARCHIVE"` | newest archive path |
| 3 | `rm -rf /tmp/scratch && mkdir /tmp/scratch && tar xzf "$ARCHIVE" -C /tmp/scratch` | extracts |
| 4 | `ls -l /tmp/scratch/cobble-state/` | `cobble.db` present; `cobble.db-wal` absent or 0 bytes (quiesced before capture) |
| 5 | run the script below | `integrity: ok`; every session from Parts 1–2 present with the same `end_reason`s |
| 6 | `rm -rf /tmp/scratch` | cleanup |

```bash
python3 - <<'EOF'
import sqlite3
c = sqlite3.connect('/tmp/scratch/cobble-state/cobble.db')
print('integrity:', c.execute('PRAGMA integrity_check').fetchone()[0])
print('schema_version:', c.execute('SELECT version FROM schema_version').fetchone()[0])
print('players:', c.execute('SELECT count(*) FROM players').fetchone()[0])
for row in c.execute(
    'SELECT xuid, gamertag, connected_at, disconnected_at, end_reason FROM sessions ORDER BY id'
):
    print(row)
EOF
```

- [ ] **8.5 passed**

---

## Part 4 — Cleanup

```bash
# [LXC root]
rm -f /etc/cobble/cobble.env          # if not already removed in 2.2
systemctl restart cobble
curl -s localhost:8000/api/status | python3 -m json.tool   # confirm healthy
```

Optional — wipe the test history:

```bash
# [LXC root]
systemctl stop cobble
rm -f /var/lib/cobble/cobble.db /var/lib/cobble/cobble.db-wal /var/lib/cobble/cobble.db-shm
systemctl start cobble
```

Roll the code back to the published release:

```bash
# [LXC root]
RELEASE_TAG=latest bash /tmp/install.sh      # or point COBBLE_TARBALL at a prior tarball
```

---

## Pass criteria summary

| Task | Passes when |
|------|-------------|
| 8.3 | join → session open; leave → closes `observed`; stop while online → closes `server_stop`; `opencount` is `0` after each close |
| 8.4 | after `kill -9` + auto-restart, the open session is closed `reconstructed` / `approximate` at its last checkpoint (≤ 20 s before the kill); `opencount` is `0` |
| 8.5 | the captured archive's `cobble-state/cobble.db` opens with `integrity_check` = `ok` and holds every session committed before the capture |
