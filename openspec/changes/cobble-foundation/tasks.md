## 1. Project scaffolding

- [x] 1.1 Create the Python package layout and project metadata with FastAPI and uvicorn as dependencies; verify a bare app starts under uvicorn and answers a health route
- [x] 1.2 Create the React + TypeScript + Vite frontend project; verify `npm run build` emits a static bundle and `npm run dev` serves it with hot reload
- [x] 1.3 Configure the FastAPI app to serve the built frontend as static files with client-side-route fallback; verify a direct request to a nested interface route returns the interface rather than a not-found error
- [x] 1.4 Set up linting, formatting, and the test runner for both languages; verify all checks pass on the empty project
- [x] 1.5 Add a settings module reading configuration from file and environment with documented defaults (paths, shutdown timeout, readiness timeout, crash-restart threshold); verify defaults load with no config file present

## 2. Bedrock acquisition and filesystem layout

- [x] 2.1 Implement a version-resolution client against the vendor download-links source that returns the current Linux server version and download URL, sending a User-Agent on every request; verify against the live source and verify a request without the header is never issued
- [x] 2.2 Implement failure handling for the version source so unreachable or malformed responses are logged and surfaced without raising; verify with a stubbed unreachable source that no exception escapes
- [x] 2.3 Implement download and extraction into `versions/<version>/`, extracting to a temporary location and moving into place only on success; verify a truncated archive leaves no partial version directory
- [x] 2.4 Implement the active-version indirection (`current` symlink) with atomic replacement; verify switching the active version changes no installation files and leaves the previous version intact
- [x] 2.5 Implement directory bootstrap for `/srv/bedrock` and `/var/lib/cobble` with correct ownership; verify a first run on an empty host creates the full layout
- [x] 2.6 Implement first-run bootstrap that acquires and activates the current version only when no installation exists; verify a second run performs no download and leaves the active version unchanged
- [x] 2.7 Implement platform preflight checks for architecture and minimum C library version; verify each failure path produces a message naming the specific unmet requirement

## 3. Process supervision

- [x] 3.1 Implement spawning the Bedrock server as a child process with stdin and stdout held as pipes; verify the process starts and its output is readable
- [x] 3.2 Implement the run-state model (stopped, starting, running, stopping, crashed, failed) with guarded transitions; verify concurrent start requests spawn only one process and the second fails with an already-running error
- [x] 3.3 Implement readiness detection driven by the readiness event, with a timeout that moves the state to failed and retains preceding output; verify a server that never signals readiness ends in failed with its output retrievable
- [x] 3.4 Implement clean shutdown: write `stop` to stdin, wait up to the configured timeout, and escalate to signal termination only after it expires; verify a normal stop never sends a signal and a hung process is terminated only after the timeout
- [x] 3.5 Implement recording of shutdown cleanliness, persisted to cobble's state directory; verify an unclean shutdown is still reported as unclean after cobble restarts
- [x] 3.6 Implement restart as clean stop followed by start, succeeding from the stopped state; verify restart from both running and stopped states reaches running
- [x] 3.7 Implement unexpected-exit detection distinguishing crashes from requested stops, retaining exit code and preceding output; verify a killed server reports crashed and a requested stop reports stopped
- [x] 3.8 Implement automatic crash restart with a failure threshold that abandons recovery and leaves the failure visible; verify repeated crashes stop retrying and a manual start still works afterwards
- [x] 3.9 Implement cobble lifecycle coupling: clean shutdown of the child on cobble termination, and restoration of the running state on cobble start; verify a termination signal to cobble stops the server cleanly rather than orphaning or killing it

## 4. Output parsing and events

- [x] 4.1 Implement the stdout reader as a non-blocking pump that never blocks the child process on output consumption; verify a slow consumer does not stall a server producing output rapidly
- [x] 4.2 Define the typed event model with the raw source line retained on every event; verify each event type round-trips its source line
- [x] 4.3 Implement parsers for player connected, disconnected, and spawned lines extracting gamertag and XUID, treating XUID as the identifier and gamertag as an unstable display name; verify against captured real server output
- [x] 4.4 Implement the readiness parser for the server startup-complete line; verify readiness is produced only on that line and never on process spawn alone
- [x] 4.5 Implement pass-through of unparsed lines as raw output; verify unknown and malformed lines still reach the console and raise no error
- [x] 4.6 Implement multi-consumer event dispatch isolating consumer failures; verify one consumer raising an error does not prevent others receiving the event or affect the server

## 5. Console

- [x] 5.1 Implement the bounded recent-output buffer retaining most-recent output and surviving a Bedrock restart with the restart distinguishable; verify memory stays bounded past the retention limit
- [x] 5.2 Implement the console output stream over SSE delivering retained history on connect then live output; verify two concurrent clients receive identical output and a client connecting to a stopped server receives output once started
- [x] 5.3 Implement serialized command submission to the child's stdin; verify concurrent submissions are delivered intact with no interleaving
- [x] 5.4 Implement echoing submitted commands into the stream for all clients, and rejecting submission when the server is not running; verify both behaviors
- [x] 5.5 Verify client disconnect and reconnect leave the server and other clients unaffected and redeliver retained history on reconnect

## 6. Status

- [x] 6.1 Implement derived status: run state, installed version, uptime measured from readiness, and last-shutdown cleanliness; verify uptime is absent when stopped and resets on restart
- [x] 6.2 Implement the online-player set derived from player events, cleared when the server stops; verify join and leave update the set and a stop empties it
- [x] 6.3 Implement the incomplete-observation flag for when cobble cannot account for the full connection history; verify the flag is set when cobble attaches to an already-running server
- [x] 6.4 Implement status change push to connected clients; verify a state transition and a crash both notify connected clients

## 7. HTTP interface

- [x] 7.1 Define the API surface for lifecycle, console, and status, with all state-changing routes under a single router with one dependency-injection point for future authentication; verify the generated OpenAPI schema lists every route
- [x] 7.2 Implement lifecycle routes (start, stop, restart) returning structured errors for invalid transitions; verify each rejection case returns a distinguishable error
- [x] 7.3 Implement console routes (output stream, command submission) and status routes (current status, status stream); verify streams stay open and deliver events
- [x] 7.4 Verify no state-changing capability exists outside the programmatic interface by exercising every action as a non-browser client

## 8. Web interface

- [x] 8.1 Build the application shell with navigation and layout structured so sections can be added without restructuring; verify adding a placeholder section requires no shell change
- [x] 8.2 Implement the live-connection layer with disconnect indication and automatic reconnection; verify stopping and restarting the service causes the interface to indicate disconnection then reconnect and refresh state
- [x] 8.3 Build the dashboard showing run state, version, uptime, online players, and last-shutdown cleanliness, updating without user action; verify a state change is reflected with no refresh
- [x] 8.4 Build server controls offering only actions valid for the current state, indicating transitions in progress and reporting failures; verify controls during starting and stopping offer no conflicting action
- [x] 8.5 Build the console view with streamed output, scroll-back, and command input disabled when the server is not running; verify submitted commands and their output appear
- [x] 8.6 Apply the visual design across the shell and both screens and verify legibility at desktop and tablet widths

## 9. Packaging and deployment

- [x] 9.1 Add a GitHub Actions workflow building the frontend and publishing a release tarball containing Python source and the pre-built bundle; verify a tag produces a release asset with no source-only frontend files
- [x] 9.2 Write the systemd unit with restart-on-failure and a stop timeout exceeding the Bedrock shutdown timeout; verify systemd does not terminate cobble before it finishes stopping the child cleanly
- [x] 9.3 Write the install script performing platform preflight, dependency install, tarball fetch, directory creation, and unit installation and enablement; verify it succeeds on a clean container with no JavaScript runtime or compiler present
- [x] 9.4 Document container prerequisites (unprivileged amd64 Debian 13, memory, timezone, UDP 19132/19133, `/backup` bind mount) in the README; verify a fresh container built from the documentation alone reaches a running server

## 10. End-to-end verification

- [x] 10.1 Verify a full first-run flow on a clean LXC: install, bootstrap, start, join from a Bedrock client on the LAN, and observe the join in the online players list and console
- [x] 10.2 Verify a clean stop of a world with real content completes without forcible termination and is recorded as clean, then restarts with the world intact
- [x] 10.3 Verify host reboot brings cobble and the Bedrock server back automatically with no operator action
- [x] 10.4 Verify crash handling by terminating the Bedrock process directly: state becomes crashed, automatic restart occurs, and repeated crashes abandon recovery with the failure visible
- [x] 10.5 Verify cobble service restart leaves a dangling player session and that the resulting state is reported without error, confirming the reconciliation contract later player history work depends on
