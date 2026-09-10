## Why

The players section keeps the roster and the access panels live off the SSE
status stream, but the per-player session-history panel is fetched once when a
player is selected and never again. When an operator bans (or kicks) a player,
the server closes that player's open session a few seconds later, and the panel
keeps showing the stale "in progress" row until the operator reloads the whole
page. That contradicts the promise that a moderation action is reflected without
reloading.

## What Changes

- The per-player session-history panel refetches itself when a moderation action
  on that player completes, and when the SSE status stream signals a change that
  can close a session (the online set changes, or the recorded ban count
  changes) — the same signals the roster and access panels already react to.
- The moderation `onDone` callback refreshes the roster and the selected
  player's sessions in addition to the access view, so a ban/unban/kick/
  permission change updates every panel that depends on it at once.
- No polling timer is introduced; this stays on the existing SSE stream plus an
  explicit post-action refresh.

## Capabilities

### New Capabilities

- _None._

### Modified Capabilities

- `web-ui-shell`: tighten the player-roster and moderation requirements so the
  displayed session history — not only the roster entry and access state — is
  covered by "reflects the new state without the operator reloading", including
  the delayed session close that a ban or kick causes.

## Impact

- `web/src/sections/Players.tsx`: session state lifted out of the component;
  `onDone` widened to refresh roster + sessions + access.
- `web/src/api/`: new `usePlayerSessions` hook mirroring `usePlayers` /
  `useAccess` (fetch on id change, `reload()`, refetch on SSE status signals).
- `web/src/test/players*.test.tsx`: coverage for the post-action and
  SSE-driven refresh of the session panel.
- No server-side or API changes.
