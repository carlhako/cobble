"""Task 7.3 (live): the SSE endpoints stay open over a real socket and deliver
events as they occur — verified against an actual uvicorn server, not TestClient
(which buffers streaming responses).
"""

from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest
import uvicorn

from cobble.app import create_app
from cobble.settings import Settings


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
async def live_server(install_fake_bedrock):
    settings: Settings = install_fake_bedrock(
        "1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0
    )
    port = _free_port()
    config = uvicorn.Config(
        create_app(settings), host="127.0.0.1", port=port, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)


async def test_status_stream_pushes_a_transition_live(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server, timeout=10) as client:
        seen: list[str] = []
        async with client.stream("GET", "/api/status/stream") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")

            async def drive() -> None:
                await asyncio.sleep(0.3)
                await client.post("/api/server/start")

            driver = asyncio.create_task(drive())
            try:
                async with asyncio.timeout(15):
                    async for line in r.aiter_lines():
                        if line.startswith("data: "):
                            snap = json.loads(line[6:])
                            seen.append(snap["run_state"])
                            if snap["run_state"] == "running":
                                break
            finally:
                driver.cancel()
        await client.post("/api/server/stop")

    assert seen[0] == "stopped"  # initial snapshot on connect
    assert "running" in seen  # transition pushed without polling


async def test_console_stream_delivers_live_command_and_output(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server, timeout=10) as client:
        await client.post("/api/server/start")
        texts: list[str] = []
        async with client.stream("GET", "/api/console/stream") as r:
            assert r.status_code == 200

            async def drive() -> None:
                await asyncio.sleep(0.3)
                await client.post("/api/console/command", json={"command": "list"})

            driver = asyncio.create_task(drive())
            try:
                async with asyncio.timeout(15):
                    async for line in r.aiter_lines():
                        if line.startswith("data: "):
                            texts.append(json.loads(line[6:])["text"])
                            if any("command: list" in t for t in texts):
                                break
            finally:
                driver.cancel()
        await client.post("/api/server/stop")

    assert "list" in texts  # echoed command reached the stream
    assert any("command: list" in t for t in texts)  # server's response to it
