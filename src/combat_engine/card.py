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
from dataclasses import dataclass, field
from typing import Optional

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
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        return cls(**d)


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

    def add_card_to_deck(self, card: Card):
        """Add a new card to the deck (from level-up or acquisition)."""
        self.deck.append(card)

    def draw_to_hand(self):
        """Draw cards until hand is full or deck+discard exhausted."""
        while len(self.hand) < self.hand_size:
            if not self.deck:
                if not self.discard:
                    break
                self._reshuffle_discard()
            self.hand.append(self.deck.pop())

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
