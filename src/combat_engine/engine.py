"""
Combat engine — state machine, turn management, enemy AI.

States: INIT → ROUND_START → PLAYER_TURN → ENEMY_TURN (loop) → ROUND_END → (repeat or END)
"""

import random
from dataclasses import dataclass, field
from typing import Optional, Callable

from combat_engine.entity import CombatUnit
from combat_engine.grid import (Grid, PLAYER_COL_START, PLAYER_COL_END, ENEMY_COL_START,
                   ENEMY_COL_END, TOTAL_ROWS, TOTAL_COLS, range_between,
                   resolve_targets, is_player_zone, is_enemy_zone)
from combat_engine.card import Card, CardPool
from combat_engine.card_data import get_starting_deck
from combat_engine.dice import check_hit, compute_damage, HitResult, DamageResult


# ══════════════════════════════════════════════════════════════════════════════
#  Events
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CombatEvent:
    """Emitted by engine for logging / renderer / future frontend."""
    type: str  # "damage", "heal", "move", "death", "round_start", "battle_end", ...
    data: dict = field(default_factory=dict)

    def __repr__(self):
        return f"[{self.type}] {self.data}"


# ══════════════════════════════════════════════════════════════════════════════
#  CombatState
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CombatState:
    """Snapshot of the entire battle at a point in time."""
    round_num: int = 0
    turn_order: list[str] = field(default_factory=list)  # unit_ids in initiative order
    current_idx: int = 0  # index into turn_order
    phase: str = "INIT"  # INIT | ROUND_START | PLAYER_TURN | ENEMY_TURN | ROUND_END | END
    events: list[CombatEvent] = field(default_factory=list)
    winner: str = ""  # "player" | "enemy" | ""


# ══════════════════════════════════════════════════════════════════════════════
#  CombatEngine
# ══════════════════════════════════════════════════════════════════════════════

class CombatEngine:
    """Orchestrates a complete combat encounter."""

    SHARED_HAND_SIZE = 6

    def __init__(self):
        self.grid = Grid()
        self.units: dict[str, CombatUnit] = {}     # unit_id → CombatUnit
        self.shared_pool: CardPool | None = None    # single shared pool for all player cards
        self.enemy_pools: dict[str, CardPool] = {}  # per-enemy pools for AI
        self.state = CombatState()
        self.shared_ap = 0
        self.SHARED_AP_MAX = 2

        # Callbacks for external input
        self.on_event: Optional[Callable[[CombatEvent], None]] = None

    # ── Setup ──

    def add_player_unit(self, unit: CombatUnit, cards: list[Card] = None,
                        pos: tuple[int, int] = None):
        """Add a player unit. Player cards go into the shared pool."""
        self.units[unit.unit_id] = unit

        # Set card owners and collect into shared pool
        if not self.shared_pool:
            self.shared_pool = CardPool(hand_size=self.SHARED_HAND_SIZE)
        if cards:
            for c in cards:
                c.owner = unit.name
                self.shared_pool.deck.append(c)

        # Auto-place if position given
        if pos:
            self.grid.place_unit(unit, pos)

    def add_enemy_unit(self, unit: CombatUnit, pos: tuple[int, int] = None):
        """Add an enemy unit with its own simple card pool."""
        self.units[unit.unit_id] = unit
        pool = CardPool(hand_size=5)
        pool.init_deck(self._enemy_cards(unit))
        self.enemy_pools[unit.unit_id] = pool

        if pos:
            self.grid.place_unit(unit, pos)

    @staticmethod
    def _enemy_cards(unit: CombatUnit) -> list[Card]:
        """Generate simple enemy attack cards."""
        return [
            Card("enemy_atk", "攻击", "基础攻击",
                 "physical", 4, 8, 0.4, "SINGLE", 1, 1, "basic", "any"),
            Card("enemy_heavy", "重击", "强力攻击",
                 "physical", 7, 14, 0.7, "SINGLE", 1, 2, "basic", "any"),
            Card("enemy_aoe", "横扫", "范围攻击",
                 "physical", 3, 6, 0.3, "ADJACENT", 1, 2, "basic", "any"),
        ]

    # ── State Machine ──

    def _emit(self, event_type: str, **data):
        ev = CombatEvent(event_type, data)
        self.state.events.append(ev)
        if self.on_event:
            self.on_event(ev)

    def start_battle(self):
        """Initialize combat: shuffle shared deck, draw 6."""
        self.state.phase = "INIT"
        self.state.round_num = 1

        # Shuffle shared deck
        if self.shared_pool:
            random.shuffle(self.shared_pool.deck)
            self.shared_pool.hand = []
            self.shared_pool.discard = []
            self.shared_pool.exhaust = []

        # Shuffle enemy decks
        for pool in self.enemy_pools.values():
            random.shuffle(pool.deck)

        self._emit("battle_start", round=1)
        self._start_round()

    def _start_round(self):
        """Begin a new round: discard hand, draw 6, reset AP."""
        self.state.phase = "ROUND_START"
        self._emit("round_start", round=self.state.round_num)

        # Move all remaining hand cards to discard (shared pool)
        if self.shared_pool:
            self.shared_pool.discard_hand()
            self._draw_shared_hand()
            self._character_guarantee()

        # Reset shared AP
        self._recalc_shared_ap_max()
        self.shared_ap = self.SHARED_AP_MAX

        # Reset personal AP for all units
        for unit in self.units.values():
            unit.reset_ap()

        # All players share the same round — begin player phase
        self.state.phase = "PLAYER_TURN"

    def _draw_shared_hand(self):
        """Draw cards from shared deck until hand has SHARED_HAND_SIZE cards."""
        if not self.shared_pool:
            return
        while len(self.shared_pool.hand) < self.SHARED_HAND_SIZE:
            if not self.shared_pool.deck:
                # Reshuffle discard into deck
                if not self.shared_pool.discard:
                    break
                self.shared_pool._reshuffle_discard()
            if self.shared_pool.deck:
                self.shared_pool.hand.append(self.shared_pool.deck.pop())

    def _character_guarantee(self):
        """Ensure each alive player character has at least one usable card in hand.
        If not, replace one random hand card with a card from that character's owner pool."""
        if not self.shared_pool:
            return
        player_units = [u for u in self.units.values()
                       if u.team == "player" and u.is_alive]
        for unit in player_units:
            if not any(c.owner == unit.name for c in self.shared_pool.hand):
                # Find a card owned by this character from deck or discard
                replacement = None
                # Check deck first (unlikely at round start, but possible)
                replacement = next((c for c in self.shared_pool.deck
                                   if c.owner == unit.name), None)
                if not replacement:
                    replacement = next((c for c in self.shared_pool.discard
                                       if c.owner == unit.name), None)
                if not replacement:
                    replacement = next((c for c in self.shared_pool.exhaust
                                       if c.owner == unit.name), None)

                if replacement and self.shared_pool.hand:
                    # Replace a random card in hand
                    idx = random.randrange(len(self.shared_pool.hand))
                    old = self.shared_pool.hand[idx]
                    self.shared_pool.discard.append(old)
                    self.shared_pool.hand[idx] = replacement
                    # Remove replacement from its source pile
                    if replacement in self.shared_pool.deck:
                        self.shared_pool.deck.remove(replacement)
                    elif replacement in self.shared_pool.discard:
                        self.shared_pool.discard.remove(replacement)
                    elif replacement in self.shared_pool.exhaust:
                        self.shared_pool.exhaust.remove(replacement)

    def _recalc_shared_ap_max(self):
        """Shared AP derived from highest tactical_planning among alive players."""
        player_int = [u.attributes.get("tactical_planning", 5)
                     for u in self.units.values()
                     if u.team == "player" and u.is_alive]
        if player_int:
            highest = max(player_int)
            self.SHARED_AP_MAX = 2 + max(0, (highest - 5) // 3)
        else:
            self.SHARED_AP_MAX = 2

    def end_player_round(self):
        """End the player's round: execute all enemy turns, then advance round."""
        self.state.phase = "ENEMY_TURN"

        enemy_units = [u for u in self.units.values()
                       if u.team == "enemy" and u.is_alive]
        for enemy in enemy_units:
            if self.is_battle_over():
                break
            self.execute_enemy_turn(enemy.unit_id)

        if not self.is_battle_over():
            self.state.round_num += 1
            self._start_round()

    # ── Actions ──

    def play_card(self, unit_id: str, card: Card, target_pos: tuple[int, int]) -> list[DamageResult]:
        """Unit plays a card targeting a grid position. Returns damage results.

        The card may affect multiple cells (AOE). Each occupied enemy/friendly cell
        in the target pattern takes damage/healing respectively.
        """
        unit = self.units[unit_id]

        # Player cards come from shared pool; enemy cards from per-unit pool
        if unit.team == "player":
            pool = self.shared_pool
        else:
            pool = self.enemy_pools.get(unit_id)

        if not pool or card not in pool.hand:
            self._emit("error", unit_id=unit_id, msg=f"卡牌 '{card.name}' 不在手牌中")
            return []

        # AP check: player units use shared AP, enemies use personal AP
        if unit.team == "player":
            if self.shared_ap < card.cost:
                self._emit("error", unit_id=unit_id, msg=f"共用 AP 不足 ({self.shared_ap} < {card.cost})")
                return []
            self.shared_ap -= card.cost
        else:
            if unit.AP < card.cost:
                self._emit("error", unit_id=unit_id, msg=f"AP 不足 ({unit.AP} < {card.cost})")
                return []
            unit.AP -= card.cost

        # Resolve target pattern
        if card.target == "ALL_ALLIES":
            allies = [u for u in self.units.values()
                     if u.team == unit.team and u.is_alive]
            affected_positions = [u.pos for u in allies]
        elif card.target == "GLOBAL":
            enemies = [u for u in self.units.values()
                      if u.team != unit.team and u.is_alive]
            affected_positions = [u.pos for u in enemies]
        else:
            affected_positions = resolve_targets(card.target, target_pos)

        # Range check (-1 = global, no filtering)
        if card.range >= 0:
            valid = []
            for p in affected_positions:
                if range_between(unit.pos, p) <= card.range:
                    valid.append(p)
            affected_positions = valid

        results: list[DamageResult] = []

        for pos in affected_positions:
            target = self.grid.get_unit_at(pos)
            if not target or not target.is_alive:
                continue

            # Skip self-targeting for non-self/non-heal cards
            if target.unit_id == unit.unit_id and card.target != "SELF":
                if card.damage_type not in ("healing",):
                    continue

            # Skip allies for damage cards
            if target.team == unit.team and card.damage_type not in ("healing",):
                continue

            # Skip enemies for healing cards
            if target.team != unit.team and card.damage_type == "healing":
                continue

            if card.damage_type == "healing":
                # Healing always hits
                hr = HitResult(0, True, False, False)
                dr = compute_damage(unit, target, card, hr)
                target.heal(dr.final)
                self._emit("heal", unit_id=unit.unit_id, caster=unit.name,
                           target_id=target.unit_id, target=target.name,
                           amount=dr.final, card=card.name)
            else:
                hr = check_hit(unit, target)
                dr = compute_damage(unit, target, card, hr)
                if not hr.miss and dr.final > 0:
                    target.take_damage(dr.final)
                self._emit("damage", unit_id=unit.unit_id, caster=unit.name,
                           target_id=target.unit_id, target=target.name,
                           damage=dr.final, hit_result=str(hr), card=card.name)

                if not target.is_alive:
                    self._emit("death", unit_id=target.unit_id,
                               name=target.name, team=target.team)
                    self.grid.remove_unit(target)

            results.append(dr)

        if not results:
            # No valid targets in range — refund AP, don't consume card
            if unit.team == "player":
                self.shared_ap += card.cost
            else:
                unit.AP += card.cost
            self._emit("error", unit_id=unit.unit_id,
                       msg=f"目标不在 '{card.name}' 的范围 ({card.range}) 内")
            return results

        pool.play_card(card)
        return results

    def move_unit(self, unit_id: str, new_pos: tuple[int, int],
                  ap_cost: int = 1) -> bool:
        """Move a unit on the grid (costs 1 AP from shared pool for players)."""
        unit = self.units[unit_id]
        if unit.team == "player":
            if self.shared_ap < ap_cost:
                return False
            if self.grid.move_unit(unit, new_pos):
                self.shared_ap -= ap_cost
                return True
            return False
        else:
            if unit.AP < ap_cost:
                return False
            if self.grid.move_unit(unit, new_pos):
                unit.AP -= ap_cost
                return True
            return False

    # ── Enemy AI ──

    def execute_enemy_turn(self, unit_id: str) -> list[DamageResult]:
        """Simple AI: find nearest player, play best card if in range, else move closer."""
        unit = self.units[unit_id]
        pool = self.enemy_pools.get(unit_id)

        # Draw a card for this enemy
        if pool:
            if not pool.deck and pool.discard:
                pool._reshuffle_discard()
            if pool.deck:
                pool.hand.append(pool.deck.pop())

        # Find nearest player unit
        players = [u for u in self.units.values()
                   if u.team == "player" and u.is_alive]
        if not players:
            return []

        nearest = min(players, key=lambda p: range_between(unit.pos, p.pos))
        dist = range_between(unit.pos, nearest.pos)

        # Try to play a card
        playable = [c for c in pool.hand if c.cost <= unit.AP]
        if playable:
            # Sort by damage potential
            playable.sort(key=lambda c: c.max_damage + c.atk_scale * 10, reverse=True)
            for card in playable:
                if card.target in ("SELF", "ALL_ALLIES"):
                    continue
                in_range = card.range < 0 or dist <= card.range
                if in_range:
                    return self.play_card(unit_id, card, nearest.pos)

        # Can't attack — move toward nearest player
        if unit.AP >= 1:
            r, c = unit.pos
            tr, tc = nearest.pos
            # Move one step closer (Chebyshev)
            dr = 0 if r == tr else (1 if tr > r else -1)
            dc = 0 if c == tc else (1 if tc > c else -1)
            new_pos = (r + dr, c + dc)
            # Check if valid
            if self.grid.is_valid_position(new_pos, unit.team):
                if self.grid.move_unit(unit, new_pos):
                    unit.AP -= 1

        return []

    # ── Query ──

    def get_unit_hand(self, unit_id: str) -> list[Card]:
        """Get the hand for a given unit. Player units use the shared hand;
        enemy units use their per-unit pool."""
        unit = self.units.get(unit_id)
        if unit and unit.team == "player":
            return self.shared_pool.hand if self.shared_pool else []
        return self.enemy_pools[unit_id].hand if unit_id in self.enemy_pools else []

    def get_active_unit(self) -> Optional[CombatUnit]:
        return None

    def is_battle_over(self) -> bool:
        return self.state.phase == "END"

    def to_dict(self) -> dict:
        return {
            "round": self.state.round_num,
            "phase": self.state.phase,
            "winner": self.state.winner,
            "units": [u.to_dict() for u in self.units.values()],
            "shared_pool": self.shared_pool.to_dict() if self.shared_pool else {},
            "enemy_pools": {uid: p.to_dict() for uid, p in self.enemy_pools.items()},
            "events": [{"type": e.type, "data": e.data}
                       for e in self.state.events[-20:]],  # last 20 events
        }
