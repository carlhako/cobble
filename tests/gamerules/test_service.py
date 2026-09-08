"""Reading and writing gamerules on the silent path (tasks 2.4-2.8)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from cobble.console.console import InternalQueryError
from cobble.gamerules.service import (
    GameruleRefusedError,
    GameruleService,
    GameruleUnavailableError,
)
from cobble.supervisor.supervisor import NotRunningError
from tests.gamerules.dump import DUMP_BODY


class FakeConsole:
    """Stands in for :class:`cobble.console.console.Console`. ``responder`` maps
    an issued command to the reply line it yields (or ``None`` to model no reply
    at all, which the real console reports as a timeout)."""

    def __init__(self, responder: Callable[[str], str | None]) -> None:
        self.commands: list[str] = []
        self.responder = responder
        self.running = True

    async def query(self, command: str, matcher, *, reply_timeout: float = 5.0) -> str:
        self.commands.append(command)
        if not self.running:
            raise NotRunningError("the server is not running")
        line = self.responder(command)
        if line is None:
            raise InternalQueryError("no matching reply")
        assert matcher(line), f"matcher rejected the scripted reply: {line!r}"
        return line


def _dump_responder(**overrides: str) -> Callable[[str], str | None]:
    """A responder that answers the bulk read with the fixture dump, with
    optional ``name=value`` string overrides applied to the body."""
    body = DUMP_BODY
    for name, value in overrides.items():
        body = _replace_pair(body, name, value)
    line = f"[2026-09-08 09:00:00:000 INFO] {body}"

    def respond(command: str) -> str | None:
        if command == "gamerule":
            return line
        return None

    return respond


def _replace_pair(body: str, name: str, value: str) -> str:
    parts = []
    for chunk in body.split(", "):
        k = chunk.split(" = ", 1)[0]
        parts.append(f"{name} = {value}" if k == name else chunk)
    return ", ".join(parts)


# -- 2.4 the bulk read -------------------------------------------
async def test_read_live_issues_exactly_gamerule_and_returns_the_parsed_set() -> None:
    console = FakeConsole(_dump_responder())
    svc = GameruleService(console)  # type: ignore[arg-type]

    result = await svc.read_live()
    assert console.commands == ["gamerule"]
    assert len(result) == 39
    assert result.get("mobGriefing").value is True


async def test_read_live_unavailable_when_not_running() -> None:
    console = FakeConsole(_dump_responder())
    console.running = False
    svc = GameruleService(console)  # type: ignore[arg-type]
    with pytest.raises(GameruleUnavailableError):
        await svc.read_live()


async def test_read_live_unavailable_when_no_reply() -> None:
    console = FakeConsole(lambda _c: None)
    svc = GameruleService(console)  # type: ignore[arg-type]
    with pytest.raises(GameruleUnavailableError):
        await svc.read_live()


# -- 2.5 the write is confirmed by a bulk re-read --------------
async def test_write_issues_set_then_bulk_read_never_a_single_rule_query() -> None:
    # The server acknowledges, then the re-read shows the new value.
    def respond(command: str) -> str | None:
        if command == "gamerule mobGriefing false":
            return "[INFO] Game rule mobGriefing has been updated to false"
        if command == "gamerule":
            return f"[INFO] {_replace_pair(DUMP_BODY, 'mobGriefing', 'false')}"
        return None

    console = FakeConsole(respond)
    svc = GameruleService(console)  # type: ignore[arg-type]

    result = await svc.write("mobgriefing", False)
    assert console.commands == ["gamerule mobGriefing false", "gamerule"]
    # No single-rule query anywhere (every issued command is the bulk read or a
    # two-token write).
    for c in console.commands:
        assert c == "gamerule" or len(c.split(" ")) == 3
    assert result.get("mobGriefing").value is False  # from the re-read


async def test_reported_value_comes_from_the_reread_not_the_submission() -> None:
    # Operator submits true, but the re-read reports false (e.g. changed back in
    # game meanwhile). The caller sees the value in effect.
    def respond(command: str) -> str | None:
        if command == "gamerule keepInventory true":
            return "[INFO] Game rule keepInventory has been updated to true"
        if command == "gamerule":
            return f"[INFO] {_replace_pair(DUMP_BODY, 'keepInventory', 'false')}"
        return None

    svc = GameruleService(FakeConsole(respond))  # type: ignore[arg-type]
    result = await svc.write("keepInventory", True)
    assert result.get("keepInventory").value is False


# -- 2.6 acknowledgements suppressed --------------------------
async def test_write_correct_when_server_emits_no_acknowledgement() -> None:
    # sendCommandFeedback is off: the write command produces no line at all.
    def respond(command: str) -> str | None:
        if command == "gamerule":
            return f"[INFO] {_replace_pair(DUMP_BODY, 'mobGriefing', 'false')}"
        return None  # including for the write command

    console = FakeConsole(respond)
    svc = GameruleService(console)  # type: ignore[arg-type]

    result = await svc.write("mobGriefing", "false")
    assert console.commands == ["gamerule mobGriefing false", "gamerule"]
    assert result.get("mobGriefing").value is False


# -- 2.7 pre-validation refuses without sending -------------
async def test_wrong_type_refused_and_nothing_sent() -> None:
    console = FakeConsole(_dump_responder())
    svc = GameruleService(console)  # type: ignore[arg-type]
    with pytest.raises(GameruleRefusedError) as ei:
        await svc.write("mobGriefing", "bananas")
    assert ei.value.rule == "mobGriefing"
    assert console.commands == []


async def test_out_of_range_int_refused_and_nothing_sent() -> None:
    console = FakeConsole(_dump_responder())
    svc = GameruleService(console)  # type: ignore[arg-type]
    with pytest.raises(GameruleRefusedError) as ei:
        await svc.write("randomTickSpeed", 99999)
    assert "4096" in ei.value.reason
    assert console.commands == []

    with pytest.raises(GameruleRefusedError):
        await svc.write("randomTickSpeed", -1)
    assert console.commands == []


async def test_non_enum_member_refused_and_nothing_sent() -> None:
    console = FakeConsole(_dump_responder())
    svc = GameruleService(console)  # type: ignore[arg-type]
    with pytest.raises(GameruleRefusedError):
        await svc.write("playerWaypoints", "nobody")
    assert console.commands == []


# -- 2.8 a server-side refusal is surfaced verbatim --------
async def test_server_refusals_reach_the_caller_verbatim_record_untouched() -> None:
    # Three observed forms, each on a rule/value that clears cobble's own
    # pre-validation so the server is the one refusing.
    cases = [
        # syntax error on the value (uncatalogued rule => no pre-validation)
        (
            "futureRule",
            "bananas",
            'Syntax error: Unexpected "bananas": at "tureRule >>bananas<<"',
        ),
        # syntax error on the rule name (uncatalogued)
        (
            "notarealrule",
            "true",
            'Syntax error: Unexpected "notarealrule": at "/gamerule >>notarealrule<<"',
        ),
        # number too big (maxCommandChainLength has no upper bound in the catalogue)
        (
            "maxCommandChainLength",
            999999999999,
            "The number you have entered (999999999999) is too big, it must be at most 65535",
        ),
    ]
    for name, value, err in cases:
        def respond(command: str, _err: str = err) -> str | None:
            if command.startswith("gamerule ") and command != "gamerule":
                return f"[ERROR] {_err}"
            return None  # a bulk read, if attempted, would return nothing

        console = FakeConsole(respond)
        svc = GameruleService(console)  # type: ignore[arg-type]
        with pytest.raises(GameruleRefusedError) as ei:
            await svc.write(name, value)
        assert ei.value.reason == err  # verbatim, prefix stripped
        # Only the write was issued — no bulk re-read, so the record is untouched.
        assert len(console.commands) == 1
        assert console.commands[0] != "gamerule"
