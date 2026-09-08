"""The verbatim ``gamerule`` bulk reply from BDS 1.26.45.1 on the live host
(design.md Context), used as the parser fixture across the gamerule tests."""

from __future__ import annotations

# Captured 2026-09-08 from the running server via /api/console (four identical
# samples). 39 rules: 33 boolean, 5 integer, 1 enum (playerWaypoints).
DUMP_BODY = (
    "commandBlockOutput = true, doDayLightCycle = true, doEntityDrops = true, "
    "doFireTick = true, recipesUnlock = true, doLimitedCrafting = false, "
    "doMobLoot = true, doMobSpawning = true, doTileDrops = true, "
    "doWeatherCycle = true, drowningDamage = true, fallDamage = true, "
    "fireDamage = true, keepInventory = false, mobGriefing = true, pvp = true, "
    "showCoordinates = false, playerWaypoints = everyone, locatorbar = true, "
    "showDaysPlayed = false, naturalRegeneration = true, tntExplodes = true, "
    "sendCommandFeedback = true, maxCommandChainLength = 65535, doInsomnia = true, "
    "commandBlocksEnabled = true, randomTickSpeed = 1, doImmediateRespawn = false, "
    "showDeathMessages = true, functionCommandLimit = 10000, spawnRadius = 10, "
    "showTags = true, freezeDamage = true, respawnBlocksExplode = true, "
    "showBorderEffect = true, showRecipeMessages = true, "
    "playersSleepingPercentage = 100, projectilesCanBreakBlocks = true, "
    "tntExplosionDropDecay = false"
)

DUMP_LINE = f"[2026-09-08 08:47:58:737 INFO] {DUMP_BODY}"

# 39 (name, raw value) pairs in reported order.
EXPECTED_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (chunk.split(" = ", 1)[0], chunk.split(" = ", 1)[1]) for chunk in DUMP_BODY.split(", ")
)
