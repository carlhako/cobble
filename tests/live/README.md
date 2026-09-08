# Live verification harness

The unit and integration suites cover cobble's logic with a fake Bedrock server.
A few behaviours can only be proven against a **real** server with a **real**
player: that a genuine join is parsed and recorded, that a session closes the way
it should for each shutdown path, and that a captured backup restores to a
working database. This harness does that end to end, with no manual clicking.

It drives:

- a running cobble install, over SSH (`remote.py`);
- a headless, **authenticated** Minecraft Bedrock client (`bot/bot.js`) — a real
  Xbox account, so the join carries a real `xuid` (an offline client has none,
  and cobble correctly ignores it).

Scenarios (`verify.py`): mirror tasks 8.3–8.5 of the `player-history-and-roster`
change — observed join/leave + `server_stop`, `reconstructed` after a SIGKILL,
and backup/restore consistency.

## One-time setup

1. **A target box** running the cobble build under test, reachable at
   `localhost:8000` on that box, with a real Bedrock server it can start.
   Key-based SSH from your machine to a login user there. `su`-to-root for the
   steps that restart the service / read `/backup`.

2. **Local tools:** Node.js, Python 3.11+, and `pip install pexpect`.

3. **The bot's dependencies and sign-in:**

   ```bash
   cd tests/live/bot
   npm ci                       # postinstall stages a prebuilt raknet binary; no compiler
   BOT_HOST=<host> node bot.js SignInBot 5
   ```

   The first run prints a Microsoft device code — open
   <https://www.microsoft.com/link>, enter it, approve. The token is cached under
   `${XDG_CACHE_HOME:-~/.cache}/cobble-live-verify/` — **outside this repo**.
   Nothing secret is committed, and a fresh clone cannot use your account: each
   machine does its own sign-in. Use a throwaway Xbox account if you prefer.

## Running

```bash
export COBBLE_LIVE_HOST=10.0.1.165
export COBBLE_LIVE_ROOT_PW=…            # for the service-restart / backup steps
# export COBBLE_LIVE_SSH_USER=carl      # defaults to $USER

python tests/live/verify.py             # 8.3, 8.4, 8.5 in order
python tests/live/verify.py --only 84   # just one
python tests/live/verify.py --wipe      # clear player history first
```

Exit code is non-zero if any check fails. The harness restores what it changes
(the checkpoint-interval override, the server run state) on its way out.

## Environment reference

| Var | Purpose | Default |
|-----|---------|---------|
| `COBBLE_LIVE_HOST` | target host / IP | — (required) |
| `COBBLE_LIVE_SSH_USER` | SSH login user | `$USER` |
| `COBBLE_LIVE_ROOT_PW` | root password for `su` steps | — (required for 8.4 / 8.5 / `--wipe`) |
| `COBBLE_LIVE_DB` | path to `cobble.db` on the target | `/var/lib/cobble/cobble.db` |
| `COBBLE_LIVE_BACKUP_DIR` | backup directory on the target | `/backup` |
| `BOT_VERSION` | Bedrock protocol version the bot speaks | `1.26.45` |
| `BOT_AUTH_DIR` | token cache location | `~/.cache/cobble-live-verify/msa` |

## Keeping it working

`bot/package.json` pins `bedrock-protocol` to a version that speaks the Bedrock
protocol of the server it was last run against. When BDS updates and the bot can
no longer connect, bump that pin and `BOT_VERSION` together, then `npm ci`.
