"""The static gamerule catalogue (server-gamerules spec; design.md D9).

The set of rules cobble shows is whatever the running server's ``gamerule`` dump
reports — this table is only an aid to presentation and pre-validation, never
authoritative over what the server says. A rule the server reports that is absent
here is carried through with its raw value and marked unrecognised
(:mod:`cobble.gamerules.parser`).

Names, defaults and shapes are those observed on **BDS 1.26.45.1** (design.md
Context): 33 booleans, 5 bounded integers, 1 enum. Integer bounds are recorded
where the server states them (``randomTickSpeed`` ≤ 4096, the number-too-big
error) and otherwise pinned at a non-negative floor, which every integer rule
shares.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class RuleType(enum.StrEnum):
    BOOL = "bool"
    INT = "int"
    ENUM = "enum"


@dataclass(frozen=True)
class GameRule:
    name: str  # canonical camelCase name, exactly as BDS reports it in the dump
    type: RuleType
    default: bool | int | str
    description: str
    minimum: int | None = None
    maximum: int | None = None
    members: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "default": self.default,
            "description": self.description,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "members": list(self.members),
        }


def _b(name: str, default: bool, description: str) -> GameRule:
    return GameRule(name=name, type=RuleType.BOOL, default=default, description=description)


def _i(
    name: str,
    default: int,
    description: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> GameRule:
    return GameRule(
        name=name,
        type=RuleType.INT,
        default=default,
        description=description,
        minimum=minimum,
        maximum=maximum,
    )


# Ordered as the BDS 1.26.45.1 dump reports them, so the section reads in the
# server's own order when the catalogue drives presentation.
CATALOGUE: tuple[GameRule, ...] = (
    _b("commandBlockOutput", True, "Command blocks echo their output to operators."),
    _b("doDayLightCycle", True, "Time of day advances."),
    _b("doEntityDrops", True, "Non-mob entities (minecarts, item frames) drop as items."),
    _b("doFireTick", True, "Fire spreads and burns out."),
    _b("recipesUnlock", True, "Recipes unlock as their ingredients are obtained."),
    _b("doLimitedCrafting", False, "Only unlocked recipes can be crafted."),
    _b("doMobLoot", True, "Mobs drop loot and experience when killed."),
    _b("doMobSpawning", True, "Mobs spawn naturally."),
    _b("doTileDrops", True, "Broken blocks drop as items."),
    _b("doWeatherCycle", True, "Weather changes over time."),
    _b("drowningDamage", True, "Players take drowning damage."),
    _b("fallDamage", True, "Players take fall damage."),
    _b("fireDamage", True, "Players take fire damage."),
    _b("keepInventory", False, "Players keep their inventory on death."),
    _b("mobGriefing", True, "Mobs can change blocks (creepers, endermen, etc.)."),
    _b("pvp", True, "Players can damage each other."),
    _b("showCoordinates", False, "The player's coordinates are shown on the HUD."),
    GameRule(
        name="playerWaypoints",
        type=RuleType.ENUM,
        default="everyone",
        description="Who appears as a waypoint on the locator bar.",
        members=("everyone", "disabled"),
    ),
    _b("locatorbar", True, "The locator bar is shown."),
    _b("showDaysPlayed", False, "The days-played counter is shown."),
    _b("naturalRegeneration", True, "Players regenerate health from a full hunger bar."),
    _b("tntExplodes", True, "TNT can be primed and explodes."),
    _b(
        "sendCommandFeedback",
        True,
        "Commands report their result to the console. Turning this off suppresses "
        "the acknowledgement line for a gamerule change; cobble confirms writes by "
        "re-reading and is unaffected.",
    ),
    _i(
        "maxCommandChainLength",
        65535,
        "Maximum number of commands a chain of command blocks may run.",
    ),
    _b("doInsomnia", True, "Phantoms spawn around players who have not slept."),
    _b("commandBlocksEnabled", True, "Command blocks function."),
    _i(
        "randomTickSpeed",
        1,
        "How many random block ticks occur per chunk per game tick (crop growth, "
        "fire spread, leaf decay).",
        maximum=4096,
    ),
    _b("doImmediateRespawn", False, "Players respawn instantly without the death screen."),
    _b("showDeathMessages", True, "Death messages are broadcast in chat."),
    _i(
        "functionCommandLimit",
        10000,
        "Maximum number of commands a single function file may run.",
    ),
    _i("spawnRadius", 10, "Radius, in blocks, around the world spawn in which players appear."),
    _b("showTags", True, "Block and entity tags are shown in advanced tooltips."),
    _b("freezeDamage", True, "Players take damage from powder snow freezing."),
    _b("respawnBlocksExplode", True, "Beds and respawn anchors explode in the wrong dimension."),
    _b("showBorderEffect", True, "The world border warning effect is shown."),
    _b("showRecipeMessages", True, "A message is shown in chat when a recipe is unlocked."),
    _i(
        "playersSleepingPercentage",
        100,
        "Percentage of players that must sleep to skip the night.",
        maximum=100,
    ),
    _b("projectilesCanBreakBlocks", True, "Projectiles can break blocks (e.g. chorus flowers)."),
    _b("tntExplosionDropDecay", False, "Some blocks destroyed by TNT do not drop as items."),
)

_BY_LOWER: dict[str, GameRule] = {rule.name.lower(): rule for rule in CATALOGUE}


def lookup(name: str) -> GameRule | None:
    """The catalogue entry for ``name`` (case-insensitive on the rule name, as
    BDS input is), or ``None`` if the rule is not catalogued."""
    return _BY_LOWER.get(name.strip().lower())


def catalogue_defaults() -> dict[str, bool | int | str]:
    """Canonical name -> vendor default value for every catalogued rule."""
    return {rule.name: rule.default for rule in CATALOGUE}
