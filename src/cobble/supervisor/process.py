"""Low-level ownership of the Bedrock server child process.

Exactly one process, with stdin and stdout held as pipes for its lifetime
(design.md D1 — BDS has no network control protocol; control *is* stdin/stdout).
stderr is merged into stdout so nothing the server prints is lost.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import AsyncIterator
from pathlib import Path

from cobble.logging import get_logger

log = get_logger("supervisor.process")


class BedrockProcess:
    def __init__(self, binary: Path, cwd: Path) -> None:
        self._binary = binary
        self._cwd = cwd
        self._proc: asyncio.subprocess.Process | None = None
        self._stdin_lock = asyncio.Lock()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode if self._proc else None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        if self._proc is not None:
            raise RuntimeError("process already started")
        env = dict(os.environ)
        env.setdefault("LD_LIBRARY_PATH", str(self._cwd))
        self._proc = await asyncio.create_subprocess_exec(
            str(self._binary),
            cwd=str(self._cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=True,  # own process group; signals don't hit cobble
        )
        log.info("spawned bedrock_server pid=%s", self._proc.pid)

    async def readlines(self) -> AsyncIterator[str]:
        """Yield decoded stdout lines until EOF. Never blocks the child: the
        OS pipe buffer plus this always-draining reader keep BDS writable.
        """
        assert self._proc is not None and self._proc.stdout is not None
        stream = self._proc.stdout
        while True:
            raw = await stream.readline()
            if not raw:
                break
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")

    async def write_line(self, text: str) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        data = (text.rstrip("\n") + "\n").encode("utf-8")
        async with self._stdin_lock:  # serialize concurrent writers
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()

    async def wait(self) -> int:
        assert self._proc is not None
        return await self._proc.wait()

    def send_signal(self, sig: signal.Signals) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.send_signal(sig)

    def kill(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()
