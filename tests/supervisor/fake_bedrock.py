#!/usr/bin/env python3
"""A stand-in for bedrock_server used by supervisor tests.

Behaviour is driven by environment variables so the same binary path can play
different roles:

* ``FAKE_BDS_READY_DELAY``  seconds before printing "Server started." (default 0.2)
* ``FAKE_BDS_NEVER_READY``  if "1", never prints the readiness line
* ``FAKE_BDS_IGNORE_STOP``  if "1", ignores the "stop" command (hung shutdown)
* ``FAKE_BDS_STOP_DELAY``   seconds between receiving "stop" and exiting (default 0.1)
* ``FAKE_BDS_CRASH_AFTER``  if set, exit with code 3 this many seconds after ready
* ``FAKE_BDS_EXIT_CODE``    exit code for a normal stop (default 0)
"""

from __future__ import annotations

import os
import sys
import threading
import time


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def main() -> int:
    out = sys.stdout
    print("[INFO] Starting Server", flush=True)
    print("[INFO] Level Name: Bedrock level", flush=True)

    if os.environ.get("FAKE_BDS_NEVER_READY") == "1":
        # Sit idle producing occasional output but never signal readiness.
        try:
            while True:
                time.sleep(0.1)
                print("[INFO] still loading...", flush=True)
        except KeyboardInterrupt:
            return 0

    time.sleep(env_float("FAKE_BDS_READY_DELAY", 0.2))
    print("[INFO] Server started.", flush=True)

    crash_after = os.environ.get("FAKE_BDS_CRASH_AFTER")
    if crash_after is not None:
        time.sleep(float(crash_after))
        print("[ERROR] simulated crash", flush=True)
        os._exit(3)

    stop_event = threading.Event()

    def reader() -> None:
        for line in sys.stdin:
            cmd = line.strip()
            print(f"[INFO] command: {cmd}", flush=True)
            if cmd == "stop":
                if os.environ.get("FAKE_BDS_IGNORE_STOP") == "1":
                    print("[INFO] ignoring stop", flush=True)
                    continue
                print("[INFO] Stopping server...", flush=True)
                print("[INFO] Saving...", flush=True)
                stop_event.set()
                return

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # Emit a heartbeat so a slow consumer test has a rapid producer.
    while not stop_event.wait(timeout=0.02):
        if os.environ.get("FAKE_BDS_CHATTY") == "1":
            out.write("[INFO] tick\n")
            out.flush()

    time.sleep(env_float("FAKE_BDS_STOP_DELAY", 0.1))
    print("[INFO] Quit correctly", flush=True)
    return int(os.environ.get("FAKE_BDS_EXIT_CODE", "0"))


if __name__ == "__main__":
    sys.exit(main())
