"""
Combat dice system — random rolls, hit/miss checks, and damage calculation.

Formulas:
  - Hit:    d20 + attacker.HIT >= 10 + defender.EVA → hit
  - Crit:   natural 20 → double damage
  - Miss:   natural 1 → no damage
  - Damage: random(card.min_dmg, card.max_dmg) + ATK × card.atk_scale - resist
"""

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from combat_engine.entity import CombatUnit  # noqa: F401
    from combat_engine.card import Card  # noqa: F401

# ══════════════════════════════════════════════════════════════════════════════
#  Dice Utilities
# ══════════════════════════════════════════════════════════════════════════════

def roll_d20() -> int:
    return random.randint(1, 20)


def roll_range(lo: int, hi: int) -> int:
    return random.randint(lo, hi)


# ══════════════════════════════════════════════════════════════════════════════
#  Hit / Miss / Crit
# ══════════════════════════════════════════════════════════════════════════════

class HitResult:
    """Outcome of a hit check."""

    def __init__(self, roll: int, hit: bool, crit: bool, miss: bool):
        self.roll = roll
        self.hit = hit
        self.crit = crit
        self.miss = miss

    def __repr__(self):
        tags = []
        if self.crit:
            tags.append("CRIT")
        if self.miss:
            tags.append("MISS")
        if not self.hit and not self.miss:
            tags.append("DODGE")
        if self.hit and not self.crit and not self.miss:
            tags.append("HIT")
        return f"HitResult(roll={self.roll}, {' '.join(tags)})"


def check_hit(attacker: "CombatUnit", defender: "CombatUnit") -> HitResult:
    """Roll d20 + HIT against target DC (10 + EVA)."""
    roll = roll_d20()
    natural_1 = (roll == 1)
    natural_20 = (roll == 20)

    total = roll + attacker.HIT
    dc = 10 + defender.EVA

    if natural_1:
        return HitResult(roll, False, False, True)
    if natural_20:
        return HitResult(roll, True, True, False)

    hit = total >= dc
    return HitResult(roll, hit, False, False)


# ══════════════════════════════════════════════════════════════════════════════
#  Damage Calculation
# ══════════════════════════════════════════════════════════════════════════════

class DamageResult:
    """Result of a damage calculation."""

    def __init__(self, base_damage: int, atk_bonus: float, resist: int,
                 raw: float, final: int, damage_type: str, hit_result: HitResult):
        self.base_damage = base_damage
        self.atk_bonus = atk_bonus
        self.resist = resist
        self.raw = raw
        self.final = final
        self.damage_type = damage_type
        self.hit = hit_result

    def __repr__(self):
        return (f"Damage({self.base_damage} base + {self.atk_bonus:.1f} ATK"
                f" - {self.resist} res = {self.final} {self.damage_type})"
                f" [{self.hit}]")


def compute_damage(attacker: "CombatUnit", defender: "CombatUnit",
                   card: "Card", hit_result: HitResult) -> DamageResult:
    """Calculate damage from a card play.

    Steps:
      1. Check hit (already done, passed in)
      2. Roll base damage from card range
      3. Add ATK × card.atk_scale
      4. Subtract defender's DEF (physical) or RES (arts)
      5. Apply crit multiplier (×2)
    """
    if hit_result.miss:
        return DamageResult(0, 0, 0, 0, 0, card.damage_type, hit_result)

    # Roll base damage
    base_damage = roll_range(card.min_damage, card.max_damage)

    # Determine attacker's ATK based on damage type
    if card.damage_type == "physical":
        atk_stat = attacker.PATK
    elif card.damage_type == "arts":
        atk_stat = attacker.MATK
    elif card.damage_type == "healing":
        atk_stat = attacker.HEAL  # healing uses HEAL stat
    else:  # mixed — average
        atk_stat = (attacker.PATK + attacker.MATK) / 2

    atk_bonus = atk_stat * card.atk_scale

    # Defender resistance
    if card.damage_type == "physical":
        resist = defender.DEF
    elif card.damage_type == "arts":
        resist = defender.RES
    else:  # healing / mixed — use lower of DEF/RES
        resist = min(defender.DEF, defender.RES)

    if card.damage_type == "healing":
        # Healing ignores hit/miss (always lands), no resistance
        raw = base_damage + atk_bonus
        final = max(0, round(raw))
    else:
        raw = base_damage + atk_bonus - resist
        if hit_result.crit:
            raw *= 2
        final = max(1, round(raw))

    return DamageResult(base_damage, atk_bonus, resist, raw, final,
                        card.damage_type, hit_result)
