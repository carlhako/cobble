#!/usr/bin/env node
// Headless Minecraft Bedrock client for cobble live verification.
//
// Joins a running server, waits for spawn, holds, then leaves — producing real
// `Player connected` / `Player Spawned` / `Player disconnected` lines in the
// server's stdout, which is what cobble's event pipeline consumes.
//
// Authenticated by default (an offline client has no xuid, so cobble correctly
// ignores it). The first authenticated run prints a Microsoft device code to
// enter at https://www.microsoft.com/link; the token is then cached — OUTSIDE
// this repo — and reused silently.
//
// Usage:   node bot.js [username] [holdSeconds]
// Env:
//   BOT_HOST       server host (required)
//   BOT_PORT       server port (default 19132)
//   BOT_USERNAME   fallback for the username arg (default "RosterBot")
//   BOT_VERSION    Bedrock protocol version to speak (default 1.26.45)
//   BOT_AUTH_DIR   token cache dir (default: <XDG_CACHE_HOME|~/.cache>/cobble-live-verify/msa)
//   BOT_OFFLINE=1  skip Microsoft auth (no xuid; for negative testing only)
//
// Exit codes: 0 spawned & left cleanly · 2 kicked before spawn · 3 error before
// spawn · 4 closed before spawn · 5 never spawned (timeout).
const os = require('os')
const path = require('path')
const bp = require('bedrock-protocol')

const host = process.env.BOT_HOST
if (!host) {
  console.error('BOT_HOST is required')
  process.exit(64)
}
const port = parseInt(process.env.BOT_PORT || '19132', 10)
const username = process.argv[2] || process.env.BOT_USERNAME || 'RosterBot'
const hold = parseInt(process.argv[3] || '8', 10)
const version = process.env.BOT_VERSION || '1.26.45'
const offline = process.env.BOT_OFFLINE === '1'
const authDir =
  process.env.BOT_AUTH_DIR ||
  path.join(
    process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'),
    'cobble-live-verify',
    'msa'
  )

const log = (...a) => console.log(new Date().toISOString(), ...a)

const client = bp.createClient({
  host,
  port,
  offline,
  username,
  version,
  profilesFolder: authDir,
  conLog: log,
  onMsaCode: (d) => {
    log('=== MICROSOFT SIGN-IN REQUIRED ===')
    log('Open:', d.verification_uri)
    log('Code:', d.user_code)
    log(`(expires in ${d.expires_in}s; token will cache under ${authDir})`)
    log('==================================')
  }
})

let spawned = false
let ending = false
const end = (code) => {
  if (ending) return
  ending = true
  setTimeout(() => process.exit(code), 800)
}

client.on('join', () => log('event: join (login accepted)'))
client.on('spawn', () => {
  spawned = true
  log(`event: spawn — in world as ${username}; holding ${hold}s`)
  setTimeout(() => {
    log('disconnecting')
    try { client.disconnect('done') } catch {}
    try { client.close() } catch {}
    end(0)
  }, hold * 1000)
})
client.on('kick', (r) => { log('event: kick', JSON.stringify(r)); end(spawned ? 0 : 2) })
client.on('error', (e) => { log('event: error', e.message); end(spawned ? 0 : 3) })
client.on('disconnect', (p) => log('event: disconnect', JSON.stringify(p)))
client.on('close', () => { log('event: close'); end(spawned ? 0 : 4) })

// Generous ceiling so a first-run device-code sign-in has time to complete.
setTimeout(() => {
  if (!spawned) { log('timeout: never spawned'); process.exit(5) }
}, 900000)
