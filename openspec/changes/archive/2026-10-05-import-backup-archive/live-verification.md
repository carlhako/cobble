# Live verification on cobble-2 (task 9.2)

Run 2026-10-05 against cobble-2 (10.0.1.165) upgraded to the published v0.7.3, Bedrock 1.26.52.3.

| Check | Result |
|---|---|
| Backup captured on the host and downloaded through `GET /api/backups/{archive}` (21.6 MB) | ok |
| That backup uploaded to Import World: the host has two worlds (`Bedrock level`, `Test World Two`) | refused: "the archive is ambiguous: it contains 2 Bedrock worlds" |
| Same backup repacked with one world, uploaded | held as `form: tar`, `kind: backup`, capture time and version 1.26.52.3 reported |
| Changed after the backup: `server-name`, `backup_retention` 7 -> 9, a marker file in the world; backup history 12 entries (the backup holds 11) | - |
| Apply | `ok`, `restarting: true`, safety capture named |
| cobble restart | went down 3 s after the response, back 4 s later (systemd "restart counter is at 1"); journal: staged restore applied before startup, gamerule restore marker set for `Bedrock level`, previously-running server restored |
| After the restart | server running; `server-name` back to "Dedicated Server"; retention back to 7; world marker gone; backup history still 12 (destination's own); `runtime.json` = desired running; payload symlinks recreated |
| World-folder `.tar.gz` (`Bedrock level/`) | held as `kind: world`; applied with `restarting: false`; server running afterwards |
| Safety captures taken while an upload was held | 21.6 MB, the same as an ordinary backup (upload not included) |

Not covered live: player-history continuity after a restore needs a joined player, and the test bot cannot join a NetherNet server. This is covered by `tests/backup/test_pending_startup.py` and the restore unit tests.

Side effect on the host: the restore removed `Test World Two` from cobble-2. It is kept in the safety capture `cobble-backup-20261005T000750.653954Z.tar.gz`.
