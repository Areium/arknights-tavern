"""
Card system — Card dataclass, CardPool (draw/shuffle/discard/recycle).

Card is the fundamental action in combat. Each card has:
  - Damage range (min → max): rolled independently per use
  - ATK scale: attacker's ATK × scale added to base damage
  - Target pattern: which grid cells are affected
  - Range: max Chebyshev distance to target
  - AP cost: energy points consumed
  - Tier: "basic" (recycled) or "elite" (exhausted after use)
"""

import random
from dataclasses import dataclass, field, fields

# ══════════════════════════════════════════════════════════════════════════════
#  Card
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Card:
    card_id: str
    name: str              # Chinese display name
    description: str       # Flavor / effect description
    damage_type: str       # "physical" | "arts" | "healing" | "mixed"
    min_damage: int        # Base damage range (before dice)
    max_damage: int
    atk_scale: float       # ATK multiplier (0.0—1.5)
    target: str            # Target pattern key (SINGLE, ADJACENT, etc.)
    range: int             # Max Chebyshev range; -1 = global
    cost: int              # AP cost (1-3)
    tier: str              # "basic" | "elite"
    class_required: str = "any"  # Class restriction or "any"
    owner: str | None = None  # Character name for exclusive cards
    effects: list = field(default_factory=list)  # 状态效果：[{"type":"shield","value":8}] / [{"type":"slow","duration":2}]
    ignore_def: float = 0.0  # 破甲：物理攻击无视防御的比例 (0.0—1.0)
    cleanse: bool = False    # 净化：命中后驱散目标的负面状态

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "name": self.name,
            "description": self.description,
            "damage_type": self.damage_type,
            "min_damage": self.min_damage,
            "max_damage": self.max_damage,
            "atk_scale": self.atk_scale,
            "target": self.target,
            "range": self.range,
            "cost": self.cost,
            "tier": self.tier,
            "class_required": self.class_required,
            "owner": self.owner,
            "effects": list(self.effects),
            "ignore_def": self.ignore_def,
            "cleanse": self.cleanse,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        """从字典重建卡牌，忽略未知字段（容忍 schema 演进/前端多余字段）。"""
        return cls(**{k: v for k, v in d.items() if k in _CARD_FIELDS})


# 卡牌合法字段集合（from_dict 白名单，用于忽略未知键）
_CARD_FIELDS = {f.name for f in fields(Card)}


# ══════════════════════════════════════════════════════════════════════════════
#  CardPool
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CardPool:
    """Per-unit card management: deck, hand, discard, exhaust.

    Lifecycle:
      1. Start of battle: deck = initial_deck (shuffled)
      2. Start of turn:  draw up to hand_size from deck (reshuffle discard if needed)
      3. Play card:       move from hand to discard (or exhaust if elite)
      4. End of turn:     hand → discard (optional, like Slay the Spire)
    """

    deck: list[Card] = field(default_factory=list)
    hand: list[Card] = field(default_factory=list)
    discard: list[Card] = field(default_factory=list)
    exhaust: list[Card] = field(default_factory=list)
    hand_size: int = 7

    def init_deck(self, cards: list[Card]):
        """Set the initial deck and shuffle."""
        self.deck = list(cards)
        random.shuffle(self.deck)
        self.hand = []
        self.discard = []
        self.exhaust = []

    def play_card(self, card: Card):
        """Remove card from hand. Elite → exhaust; basic → discard."""
        if card not in self.hand:
            return
        self.hand.remove(card)
        if card.tier == "elite":
            self.exhaust.append(card)
        else:
            self.discard.append(card)

    def discard_hand(self):
        """Move all cards from hand to discard pile."""
        self.discard.extend(self.hand)
        self.hand.clear()

    def _reshuffle_discard(self):
        """Shuffle discard pile back into deck."""
        self.deck = list(self.discard)
        random.shuffle(self.deck)
        self.discard = []

    def to_dict(self) -> dict:
        return {
            "deck": [c.to_dict() for c in self.deck],
            "hand": [c.to_dict() for c in self.hand],
            "discard": [c.to_dict() for c in self.discard],
            "exhaust": [c.to_dict() for c in self.exhaust],
        }
