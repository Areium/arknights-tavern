"""
CombatUnit — wraps character data with combat-specific stats (HP, ATK, DEF, etc.).

Stat conversion: 1-10 roleplay attributes → combat numbers.

    HP   = endurance × 12  +  strength × 3
    PATK = (strength + combat_skill) × 2
    MATK = (originium_arts + intelligence) × 2
    HEAL = (originium_arts + intelligence) × 2
    DEF  = round(endurance × 1.5  +  strength × 0.5)
    RES  = round(emotional_stability × 1.5  +  originium_arts × 0.5)
    SPD  = agility × 2  +  intelligence × 0.5
    HIT  = combat_skill + agility
    EVA  = agility × 1.5
"""

from dataclasses import dataclass, field
from typing import Optional
import random


@dataclass
class CombatUnit:
    """A unit in combat — player character or enemy."""

    # Identity
    unit_id: str
    name: str
    team: str            # "player" | "enemy"
    char_class: str = ""  # Chinese class name

    # Core combat stats (derived from attributes)
    max_hp: int = 100
    hp: int = 100
    PATK: float = 10     # Physical ATK
    MATK: float = 10     # Magic (Arts) ATK
    HEAL: float = 10     # Healing power
    DEF: int = 5         # Physical defense
    RES: int = 5         # Arts resistance
    SPD: float = 10      # Speed (initiative order)
    HIT: int = 5         # Accuracy bonus
    EVA: int = 5         # Evasion threshold
    AP: int = 3          # Action points (current, refilled each round)
    MAX_AP: int = 3      # Max AP per round

    # Optional: original attributes for reference
    attributes: dict = field(default_factory=dict)

    # Position on grid
    pos: tuple[int, int] = (-1, -1)  # (row, col)

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    @property
    def is_player(self) -> bool:
        return self.team == "player"

    def take_damage(self, amount: int) -> int:
        """Apply damage, return actual HP lost (capped at current HP)."""
        actual = min(amount, self.hp)
        self.hp -= actual
        return actual

    def heal(self, amount: int) -> int:
        """Restore HP, return actual HP gained."""
        old = self.hp
        self.hp = min(self.hp + amount, self.max_hp)
        return self.hp - old

    def reset_ap(self):
        self.AP = self.MAX_AP

    # ── Factory ──

    @classmethod
    def from_character_metadata(cls, meta: dict, unit_id: str = "",
                                 team: str = "player") -> "CombatUnit":
        """Create a CombatUnit from existing character YAML frontmatter metadata.

        Handles partial attribute sets by defaulting missing stats to 5.
        """
        name = meta.get("name", unit_id or "未知")
        char_class = meta.get("class", "")
        attrs = meta.get("attributes", {}) or {}

        def a(key: str) -> int:
            """Get attribute value, default 5."""
            v = attrs.get(key, 5)
            return int(v) if v is not None else 5

        STR = a("strength")
        INT = a("intelligence")
        EMO = a("emotional_stability")
        CBT = a("combat_skill")
        ORG = a("originium_arts")
        # CHA = a("charisma")  # not used in combat formulas (yet)
        END = a("endurance")
        AGI = a("agility")

        max_hp = END * 12 + STR * 3
        patk = (STR + CBT) * 2
        matk = (ORG + INT) * 2
        heal = (ORG + INT) * 2
        defense = round(END * 1.5 + STR * 0.5)
        resist = round(EMO * 1.5 + ORG * 0.5)
        spd = AGI * 2 + INT * 0.5
        hit = CBT + AGI
        eva = round(AGI * 1.5)

        # Determine MAX_AP from agility
        if AGI >= 8:
            max_ap = 4
        elif AGI <= 3:
            max_ap = 2
        else:
            max_ap = 3

        return cls(
            unit_id=unit_id or name,
            name=name,
            team=team,
            char_class=char_class,
            max_hp=max_hp,
            hp=max_hp,
            PATK=patk,
            MATK=matk,
            HEAL=heal,
            DEF=defense,
            RES=resist,
            SPD=spd,
            HIT=hit,
            EVA=eva,
            AP=max_ap,
            MAX_AP=max_ap,
            attributes=attrs,
        )

    @classmethod
    def create_enemy(cls, name: str, char_class: str = "",
                     hp: int = 80, patk: float = 8, matk: float = 8,
                     defense: int = 4, resist: int = 4,
                     spd: float = 8, hit: int = 4, eva: int = 4,
                     max_ap: int = 3) -> "CombatUnit":
        """Quick enemy creation with explicit stats."""
        return cls(
            unit_id=name,
            name=name,
            team="enemy",
            char_class=char_class,
            max_hp=hp, hp=hp,
            PATK=patk, MATK=matk,
            DEF=defense, RES=resist,
            SPD=spd, HIT=hit, EVA=eva,
            AP=max_ap, MAX_AP=max_ap,
        )

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "name": self.name,
            "team": self.team,
            "char_class": self.char_class,
            "hp": self.hp, "max_hp": self.max_hp,
            "PATK": self.PATK, "MATK": self.MATK,
            "DEF": self.DEF, "RES": self.RES,
            "SPD": self.SPD, "HIT": self.HIT, "EVA": self.EVA,
            "AP": self.AP, "MAX_AP": self.MAX_AP,
            "pos": list(self.pos),
        }
