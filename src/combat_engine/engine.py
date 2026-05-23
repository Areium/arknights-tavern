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

    def __init__(self):
        self.grid = Grid()
        self.units: dict[str, CombatUnit] = {}     # unit_id → CombatUnit
        self.pools: dict[str, CardPool] = {}       # unit_id → CardPool
        self.state = CombatState()
        self._turns_remaining = 0  # Countdown of units yet to act this round
        self.shared_ap = 0
        self.SHARED_AP_MAX = 2

        # Callbacks for external input
        self.on_event: Optional[Callable[[CombatEvent], None]] = None

    # ── Setup ──

    def add_player_unit(self, unit: CombatUnit, cards: list[Card] = None,
                        pos: tuple[int, int] = None):
        """Add a player unit with its starting deck."""
        self.units[unit.unit_id] = unit
        pool = CardPool()
        if cards:
            pool.init_deck(cards)
        self.pools[unit.unit_id] = pool

        # Auto-place if position given
        if pos:
            self.grid.place_unit(unit, pos)

    def add_enemy_unit(self, unit: CombatUnit, pos: tuple[int, int] = None):
        """Add an enemy unit (enemies don't use card pools — they have simple attacks)."""
        self.units[unit.unit_id] = unit
        pool = CardPool()
        pool.init_deck(self._enemy_cards(unit))
        self.pools[unit.unit_id] = pool

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
        """Initialize combat: shuffle decks, draw hands, roll initiative."""
        self.state.phase = "INIT"
        self.state.round_num = 1

        # Shuffle all decks and draw initial hands
        for uid, pool in self.pools.items():
            random.shuffle(pool.deck)
            pool.draw_to_hand()

        # Determine turn order by SPD (highest first)
        alive = [u for u in self.units.values() if u.is_alive]
        alive.sort(key=lambda u: u.SPD, reverse=True)
        self.state.turn_order = [u.unit_id for u in alive]
        self.state.current_idx = 0

        self._emit("battle_start", round=1)
        self._start_round()

    def _start_round(self):
        """Begin a new round: reset AP, draw cards."""
        self.state.phase = "ROUND_START"
        self._emit("round_start", round=self.state.round_num)
        self.state.current_idx = 0

        # Reset shared AP for player team
        self.shared_ap = self.SHARED_AP_MAX

        # Update turn order (dead units removed)
        alive = [u for u in self.units.values() if u.is_alive]
        alive_ids = {u.unit_id for u in alive}
        self.state.turn_order = [uid for uid in self.state.turn_order
                                 if uid in alive_ids]
        self._turns_remaining = len(alive)

        for uid in alive_ids:
            unit = self.units[uid]
            unit.reset_ap()
            self.pools[uid].draw_to_hand()

        # Advance to first unit's turn
        self._next_turn()

    def _next_turn(self):
        """Advance to the next alive unit's turn."""
        # Check win/loss
        player_alive = any(u.is_alive and u.team == "player"
                          for u in self.units.values())
        enemy_alive = any(u.is_alive and u.team == "enemy"
                         for u in self.units.values())

        if not player_alive:
            self.state.phase = "END"
            self.state.winner = "enemy"
            self._emit("battle_end", winner="enemy", reason="all players dead")
            return
        if not enemy_alive:
            self.state.phase = "END"
            self.state.winner = "player"
            self._emit("battle_end", winner="player", reason="all enemies dead")
            return

        # All units have acted this round → advance round
        if self._turns_remaining <= 0:
            self.state.round_num += 1
            self._start_round()
            return

        n = len(self.state.turn_order)
        if n == 0:
            return

        # Find next alive unit in turn order
        for _ in range(n):
            idx = self.state.current_idx
            uid = self.state.turn_order[idx]
            unit = self.units.get(uid)
            self.state.current_idx = (idx + 1) % n
            if unit and unit.is_alive:
                self._turns_remaining -= 1
                if unit.team == "player":
                    self.state.phase = "PLAYER_TURN"
                else:
                    self.state.phase = "ENEMY_TURN"
                self._emit("turn_start", unit_id=uid, name=unit.name,
                           team=unit.team, ap=unit.AP)
                return

        # No alive unit found (remaining units died before their turn)
        self._turns_remaining = 0
        self._next_turn()

    def end_current_turn(self):
        """Called after player/enemy finishes their turn."""
        self._next_turn()

    # ── Actions ──

    def play_card(self, unit_id: str, card: Card, target_pos: tuple[int, int]) -> list[DamageResult]:
        """Unit plays a card targeting a grid position. Returns damage results.

        The card may affect multiple cells (AOE). Each occupied enemy/friendly cell
        in the target pattern takes damage/healing respectively.
        """
        unit = self.units[unit_id]
        pool = self.pools[unit_id]

        if card not in pool.hand:
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
        pool = self.pools[unit_id]
        enemies = [u for u in self.units.values()
                   if u.team == "enemy" and u.is_alive]

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
        return self.pools[unit_id].hand if unit_id in self.pools else []

    def get_active_unit(self) -> Optional[CombatUnit]:
        if self.state.turn_order:
            # The active unit is the one before current_idx in the order
            n = len(self.state.turn_order)
            prev_idx = (self.state.current_idx - 1) % n
            uid = self.state.turn_order[prev_idx]
            return self.units.get(uid)
        return None

    def is_battle_over(self) -> bool:
        return self.state.phase == "END"

    def to_dict(self) -> dict:
        return {
            "round": self.state.round_num,
            "phase": self.state.phase,
            "winner": self.state.winner,
            "units": [u.to_dict() for u in self.units.values()],
            "events": [{"type": e.type, "data": e.data}
                       for e in self.state.events[-20:]],  # last 20 events
        }
