"""Parse a BDS ``gamerule`` bulk reply into a typed set (server-gamerules spec;
design.md D1, D9).

The only reply shape cobble parses is the bulk dump produced by ``gamerule`` with
no argument: a single line of ``name = value`` pairs separated by ``, ``, behind
an optional ``[timestamp INFO]`` log prefix. Values are coerced by the catalogue
(:mod:`cobble.gamerules.catalogue`); a rule absent from the catalogue is carried
through with its raw text and marked unrecognised.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cobble.gamerules.catalogue import GameRule, RuleType, lookup

_PREFIX_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?")
_PAIR_SEP = ", "
_KV_SEP = " = "

# The shape a line must have to be accepted as a bulk dump: several ``name =
# value`` pairs. Content logging to console is off by default on BDS, so no
# player-authored line can reach stdout and imitate this (design.md D3).
_MIN_PAIRS_FOR_DUMP = 5


@dataclass(frozen=True)
class ParsedRule:
    name: str  # canonical name from the catalogue when recognised, else as reported
    raw: str  # the value exactly as the server printed it
    value: bool | int | str  # coerced by type; equal to ``raw`` when unrecognised
    type: RuleType | None  # None for an unrecognised rule
    recognised: bool

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "raw": self.raw,
            "value": self.value,
            "type": None if self.type is None else self.type.value,
            "recognised": self.recognised,
        }


@dataclass(frozen=True)
class GameruleSet:
    """An ordered, typed snapshot of the live gamerule set."""

    rules: tuple[ParsedRule, ...]

    def __len__(self) -> int:
        return len(self.rules)

    def __iter__(self):
        return iter(self.rules)

    def get(self, name: str) -> ParsedRule | None:
        low = name.strip().lower()
        for rule in self.rules:
            if rule.name.lower() == low:
                return rule
        return None

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def value_map(self) -> dict[str, bool | int | str]:
        """Canonical name -> coerced value, for records and comparison."""
        return {rule.name: rule.value for rule in self.rules}

    def to_dict(self) -> dict:
        return {"rules": [r.to_dict() for r in self.rules]}


def looks_like_bulk_dump(text: str) -> bool:
    """Whether ``text`` has the bulk-dump shape (design.md D3): several ``name =
    value`` pairs separated by ``, ``."""
    body = _PREFIX_RE.sub("", text)
    return body.count(_KV_SEP) >= _MIN_PAIRS_FOR_DUMP and _PAIR_SEP in body


def parse_pairs(line: str) -> dict[str, str]:
    """Split a bulk reply into ``name -> raw value`` strings, in reported order.
    An optional ``[... INFO]`` prefix is stripped. Chunks without ``' = '`` are
    ignored."""
    body = _PREFIX_RE.sub("", line).strip()
    pairs: dict[str, str] = {}
    for chunk in body.split(_PAIR_SEP):
        if _KV_SEP not in chunk:
            continue
        name, _, value = chunk.partition(_KV_SEP)
        name = name.strip()
        if name:
            pairs[name] = value.strip()
    return pairs


def _coerce(rule: GameRule | None, name: str, raw: str) -> ParsedRule:
    if rule is None:
        return ParsedRule(name=name, raw=raw, value=raw, type=None, recognised=False)
    if rule.type is RuleType.BOOL:
        low = raw.strip().lower()
        coerced: bool | int | str = low == "true" if low in ("true", "false") else raw
        return ParsedRule(name=rule.name, raw=raw, value=coerced, type=rule.type, recognised=True)
    if rule.type is RuleType.INT:
        try:
            coerced = int(raw.strip())
        except ValueError:
            coerced = raw
        return ParsedRule(name=rule.name, raw=raw, value=coerced, type=rule.type, recognised=True)
    # ENUM: the value is already a member name.
    return ParsedRule(name=rule.name, raw=raw, value=raw.strip(), type=rule.type, recognised=True)


def parse_bulk_dump(line: str) -> GameruleSet:
    """Parse a full ``gamerule`` bulk reply into a :class:`GameruleSet`, coercing
    each value by the catalogue and marking uncatalogued rules unrecognised."""
    return GameruleSet(
        rules=tuple(_coerce(lookup(name), name, raw) for name, raw in parse_pairs(line).items())
    )


def _raw_of(value: bool | int | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def set_from_values(values: dict[str, bool | int | str]) -> GameruleSet:
    """Build a typed :class:`GameruleSet` from a stored ``name -> value`` record
    (already coerced), so a recorded set is presented exactly like a live one."""
    rules: list[ParsedRule] = []
    for name, value in values.items():
        rule = lookup(name)
        rules.append(
            ParsedRule(
                name=name if rule is None else rule.name,
                raw=_raw_of(value),
                value=value,
                type=None if rule is None else rule.type,
                recognised=rule is not None,
            )
        )
    return GameruleSet(rules=tuple(rules))
