## 1. Lift session history into a hook

- [x] 1.1 Add `usePlayerSessions(xuid: string | null)` in `web/src/api/usePlayerSessions.ts`, mirroring `usePlayers` / `useAccess`: fetch `api.playerSessions(xuid)` on `[xuid, tick]`, expose `{ sessions, error, reload }`, cancel stale fetches with a `cancelled` flag, and return `null` sessions when `xuid` is `null`. Verify with a new unit test that selecting an id fetches once and `reload()` refetches.
- [x] 1.2 In `usePlayerSessions`, refetch on the same SSE signals the other feeds use — the online-set signature from `status.online_players` and `JSON.stringify(status.access)` — via a `prevKey` ref guard so the first render does not trigger a redundant fetch. Verify with a test that pushes a status update changing `access.ban_count` and asserts a refetch.

## 2. Wire it into the Players section

- [x] 2.1 Replace the local `sessions` / `sessionsError` `useState` + `useEffect` in `web/src/sections/Players.tsx` with `usePlayerSessions(selected)`. Verify existing `players*.test.tsx` still pass and the session panel still renders on selection.
- [x] 2.2 Widen the moderation `onDone` passed to `PlayerAccessPanel` from `reloadAccess` to a callback that also calls `usePlayers`'s `reload` and `usePlayerSessions`'s `reload`. Verify with a test that completing a ban action refetches roster, access, and the selected player's sessions without a page reload.

## 3. Regression coverage for the reported bug

- [x] 3.1 Add a test in `web/src/test/players_moderation.test.tsx`: select an online player with an in-progress session, complete a ban, then deliver an SSE status update that drops the player from `online_players` and bumps `access.ban_count`; assert the session panel updates to show the session as closed/"kicked" without a reload or re-selection.
- [x] 3.2 Run `npm --prefix web test` and `npm --prefix web run lint`; verify both pass.
