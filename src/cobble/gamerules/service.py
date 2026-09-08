"""Reading and writing the live gamerule set (server-gamerules spec; design.md
D1, D2, D3).

Cobble issues exactly two console forms, both on the silent path:

* ``gamerule`` — read every rule (:meth:`GameruleService.read_live`);
* ``gamerule <name> <value>`` — write one rule (:meth:`GameruleService.write`),
  whose outcome is taken from a fresh bulk read, never from the acknowledgement
  (which ``sendCommandFeedback`` can suppress).

A single-rule query (``gamerule <name>``) is never issued.
"""

from __future__ import annotations

import re

from cobble.console.console import Console, InternalQueryError
from cobble.gamerules.catalogue import GameRule, RuleType, lookup
from cobble.gamerules.parser import GameruleSet, looks_like_bulk_dump, parse_bulk_dump
from cobble.logging import get_logger
from cobble.supervisor.supervisor import NotRunningError

log = get_logger("gamerules.service")

_READ_TIMEOUT = 5.0
# A write acknowledgement, when it comes, is near-instant; a couple of seconds
# covers it and the two observed refusal forms. When sendCommandFeedback is off
# and the write succeeds there is no line at all and this simply elapses before
# the authoritative re-read (design.md D2).
_WRITE_REPLY_TIMEOUT = 2.0

_PREFIX_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?")
_WRITE_ACK_RE = re.compile(r"Game rule .+ has been updated to ", re.IGNORECASE)
_WRITE_ERROR_RE = re.compile(
    r"(Syntax error:|The number you have entered)", re.IGNORECASE
)


class GameruleError(RuntimeError):
    code = "gamerule_error"


class GameruleUnavailableError(GameruleError):
    """The live gamerule set could not be read from the server."""

    code = "gamerule_unavailable"


class GameruleRefusedError(GameruleError):
    """A submitted value was refused — by cobble's pre-validation against the
    catalogue, or by the server itself (surfaced verbatim)."""

    code = "gamerule_refused"

    def __init__(self, rule: str, reason: str) -> None:
        super().__init__(reason)
        self.rule = rule
        self.reason = reason


def _strip_prefix(line: str) -> str:
    return _PREFIX_RE.sub("", line).strip()


def _write_reply_shape(text: str) -> bool:
    return bool(_WRITE_ACK_RE.search(text) or _WRITE_ERROR_RE.search(text))


def _coerce_submit_value(
    rule: GameRule | None, name: str, value: object
) -> tuple[str, str]:
    """Validate ``value`` against the catalogue and return the canonical
    ``(name, value)`` strings to send. Raises :class:`GameruleRefusedError`
    without anything being sent to the server (server-gamerules spec, task 2.7).
    """
    if rule is None:
        # Uncatalogued: cobble has no type to check against; pass it through and
        # let the server be the judge (design.md D9).
        return name, str(value).strip()

    if rule.type is RuleType.BOOL:
        b = _as_bool(value)
        if b is None:
            raise GameruleRefusedError(
                rule.name, f"{rule.name} is a true/false rule; {value!r} is not true or false"
            )
        return rule.name, "true" if b else "false"

    if rule.type is RuleType.INT:
        try:
            n = int(str(value).strip())
        except (TypeError, ValueError):
            raise GameruleRefusedError(
                rule.name, f"{rule.name} takes a whole number; {value!r} is not a number"
            ) from None
        low, high = rule.minimum, rule.maximum
        if (low is not None and n < low) or (high is not None and n > high):
            if low is not None and high is not None:
                bound = f"between {low} and {high}"
            elif high is not None:
                bound = f"at most {high}"
            else:
                bound = f"at least {low}"
            raise GameruleRefusedError(
                rule.name, f"{rule.name} must be {bound}; {n} is out of range"
            )
        return rule.name, str(n)

    # ENUM
    s = str(value).strip()
    if rule.members and s.lower() not in {m.lower() for m in rule.members}:
        raise GameruleRefusedError(
            rule.name,
            f"{rule.name} must be one of: {', '.join(rule.members)}; {s!r} is not",
        )
    return rule.name, s


# Public alias: the manager pre-validates a queued stopped-server write with the
# same rules (task 5.5).
coerce_submit_value = _coerce_submit_value


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    return None


class GameruleService:
    def __init__(self, console: Console) -> None:
        self._console = console

    async def read_live(self) -> GameruleSet:
        """Issue ``gamerule`` on the silent path and return the parsed set.

        Raises :class:`GameruleUnavailableError` if the server is not running or
        produces no reply of the expected shape in time — the caller keeps
        whatever record it holds (server-gamerules spec)."""
        try:
            line = await self._console.query(
                "gamerule", looks_like_bulk_dump, reply_timeout=_READ_TIMEOUT
            )
        except NotRunningError as exc:
            raise GameruleUnavailableError("the server is not running") from exc
        except InternalQueryError as exc:
            raise GameruleUnavailableError(
                "the server did not return the gamerule set"
            ) from exc
        return parse_bulk_dump(line)

    async def write(self, name: str, value: object) -> GameruleSet:
        """Apply ``gamerule <name> <value>`` and return a fresh bulk read.

        Pre-validates ``value`` against the catalogue and sends nothing on a
        rejection. A server-side refusal is raised verbatim as
        :class:`GameruleRefusedError`. On success the acknowledgement is
        discarded and the returned set comes from the re-read (design.md D1, D2).
        """
        rule = lookup(name)
        canonical, submit_value = _coerce_submit_value(rule, name.strip(), value)

        command = f"gamerule {canonical} {submit_value}"
        try:
            reply: str | None = await self._console.query(
                command, _write_reply_shape, reply_timeout=_WRITE_REPLY_TIMEOUT
            )
        except NotRunningError as exc:
            raise GameruleUnavailableError("the server is not running") from exc
        except InternalQueryError:
            # No line at all: sendCommandFeedback is off and the write succeeded.
            reply = None

        if reply is not None and _WRITE_ERROR_RE.search(reply):
            raise GameruleRefusedError(canonical, _strip_prefix(reply))

        # Acknowledgement (if any) discarded; the re-read is authoritative.
        return await self.read_live()

    async def apply_many(self, values: dict[str, object]) -> GameruleSet:
        """Send a ``gamerule <name> <value>`` write for each entry, then one
        bulk read. For reconciliation (repair, first-sight defaults), where many
        rules are set at once. Each value is pre-validated; a value that fails
        pre-validation or is refused by the server is logged and skipped so the
        rest still apply. Raises :class:`GameruleUnavailableError` if the server
        is not running."""
        for name, value in values.items():
            rule = lookup(name)
            try:
                canonical, submit_value = _coerce_submit_value(rule, name.strip(), value)
            except GameruleRefusedError as exc:
                log.warning("reconcile: skipping %s=%r — %s", name, value, exc)
                continue
            try:
                reply = await self._console.query(
                    f"gamerule {canonical} {submit_value}",
                    _write_reply_shape,
                    reply_timeout=_WRITE_REPLY_TIMEOUT,
                )
            except NotRunningError as exc:
                raise GameruleUnavailableError("the server is not running") from exc
            except InternalQueryError:
                reply = None  # no acknowledgement (feedback off) — fine
            if reply is not None and _WRITE_ERROR_RE.search(reply):
                log.warning(
                    "reconcile: server refused %s=%r — %s",
                    canonical,
                    submit_value,
                    _strip_prefix(reply),
                )
        return await self.read_live()
