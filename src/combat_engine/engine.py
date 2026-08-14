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
from combat_engine.dice import check_hit, compute_damage, HitResult, DamageResult


# ── Enemy intent labels ──
INTENT_LABELS = {
    "attack": "攻击",
    "heavy": "重击",
    "aoe": "范围攻击",
    "move": "移动",
    "defend": "坚守",
}


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
    enemy_intents: dict = field(default_factory=dict)  # unit_id → intent dict


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
        self.max_rounds = 0          # 回合上限（0 = 无限制）
        self.escape_enabled = False  # 是否允许撤退

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
        """Generate enemy attack cards based on class/archetype."""
        # Caster-type enemies use arts damage
        if unit.char_class in ("术师", "caster", "caster_elite"):
            return [
                Card("enemy_bolt", "能量弹", "发射源石能量弹",
                     "arts", 5, 10, 0.5, "SINGLE", 3, 1, "basic", "any"),
                Card("enemy_storm", "法术风暴", "范围法术攻击",
                     "arts", 4, 8, 0.4, "ADJACENT", 2, 2, "basic", "any"),
                Card("enemy_blast", "法术冲击", "高密度源石能量",
                     "arts", 8, 16, 0.8, "SINGLE", 2, 2, "basic", "any"),
            ]
        # Sniper-type enemies use physical ranged attacks
        if unit.char_class in ("狙击", "sniper", "sniper_elite"):
            return [
                Card("enemy_shot", "射击", "精准射击",
                     "physical", 6, 12, 0.6, "SINGLE", 3, 1, "basic", "any"),
                Card("enemy_barrage", "连射", "快速连射",
                     "physical", 4, 8, 0.4, "SINGLE", 3, 2, "basic", "any"),
            ]
        # Default melee enemies (guard, defender, soldier)
        return [
            Card("enemy_atk", "攻击", "基础攻击",
                 "physical", 5, 10, 0.5, "SINGLE", 1, 1, "basic", "any"),
            Card("enemy_heavy", "重击", "强力攻击",
                 "physical", 8, 16, 0.8, "SINGLE", 1, 2, "basic", "any"),
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
        """Begin a new round: discard hand, draw 6, reset AP, compute enemy intents."""
        self.state.phase = "ROUND_START"

        # Move all remaining hand cards to discard (shared pool)
        if self.shared_pool:
            self.shared_pool.discard_hand()
            self._draw_shared_hand()
            self._character_guarantee()

        # Reset shared AP
        self._recalc_shared_ap_max()
        self.shared_ap = self.SHARED_AP_MAX

        # Reset personal AP + 燃烧 DoT + tick down status effects
        for unit in list(self.units.values()):
            unit.reset_ap()
            self._apply_burn(unit)
            unit.tick_status()

        # Compute enemy intents so the player can read enemy plans before acting.
        self.state.enemy_intents = self._compute_enemy_intents()
        self._emit("round_start", round=self.state.round_num,
                   intents=self.state.enemy_intents)

        # All players share the same round — begin player phase
        self.state.phase = "PLAYER_TURN"

    def _apply_burn(self, unit: CombatUnit) -> None:
        """燃烧 DoT：每回合开始造成 burn_damage 点伤害（护盾先吸收）。"""
        if unit.status_amount("burn") <= 0:
            return
        dmg = int(unit.status.get("burn_damage", 0) or 0)
        if dmg <= 0:
            return
        actual = unit.take_damage(dmg)
        self._emit("damage", unit_id="burn", caster="燃烧",
                   target_id=unit.unit_id, target=unit.name,
                   damage=actual, hit_result="HIT", card="燃烧",
                   damage_type="arts", target_pos=list(unit.pos))
        if not unit.is_alive:
            self._emit("death", unit_id=unit.unit_id, name=unit.name,
                       team=unit.team, pos=list(unit.pos))
            self.grid.remove_unit(unit)

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
                    self.shared_pool.deck.insert(0, old)
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
        if self._check_battle_end():
            return

        self.state.phase = "ENEMY_TURN"

        enemy_units = [u for u in self.units.values()
                       if u.team == "enemy" and u.is_alive]
        # 敌人按 SPD 降序行动（先手权决定行动顺序）
        enemy_units.sort(key=lambda u: u.SPD, reverse=True)
        for enemy in enemy_units:
            if self.is_battle_over():
                break
            self._execute_enemy_turn(enemy.unit_id)
            self._check_battle_end()

        if not self.is_battle_over():
            self._emit("turn_end", round=self.state.round_num)
            self.state.round_num += 1
            if self.max_rounds > 0 and self.state.round_num > self.max_rounds:
                self._force_end("enemy", f"回合超时（{self.max_rounds} 回合）")
                return
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

        # 沉默：无法使用源石技艺（arts）卡牌
        if card.damage_type == "arts" and unit.status_amount("silence") > 0:
            self._emit("error", unit_id=unit_id,
                       msg=f"{unit.name} 被沉默，无法施放 '{card.name}'")
            return []

        # AP check: player units use personal AP first, shared AP as fallback
        from_personal = 0
        from_shared = 0
        if unit.team == "player":
            total_available = unit.AP + self.shared_ap
            if total_available < card.cost:
                self._emit("error", unit_id=unit_id,
                           msg=f"AP 不足 (个人 {unit.AP} + 共享 {self.shared_ap} < {card.cost})")
                return []
            from_personal = min(unit.AP, card.cost)
            from_shared = card.cost - from_personal
            unit.AP -= from_personal
            self.shared_ap -= from_shared
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
                           amount=dr.final, card=card.name,
                           target_pos=list(target.pos))
            else:
                hr = check_hit(unit, target)
                dr = compute_damage(unit, target, card, hr)
                actual = 0
                shielded = 0
                if hr.hit and dr.final > 0:
                    # 状态效果修正：虚弱目标多受 25% / 增幅来源多造成 25%
                    final_dmg = dr.final
                    if target.status_amount("weaken") > 0:
                        final_dmg = int(final_dmg * 1.25)
                    if unit.status_amount("strengthen") > 0:
                        final_dmg = int(final_dmg * 1.25)
                    shield_before = target.status_amount("shield")
                    actual = target.take_damage(max(1, final_dmg))
                    shielded = shield_before - target.status_amount("shield")
                self._emit("damage", unit_id=unit.unit_id, caster=unit.name,
                           target_id=target.unit_id, target=target.name,
                           damage=actual, hit_result=str(hr), card=card.name,
                           shielded=shielded, target_pos=list(target.pos))

                if not target.is_alive:
                    self._emit("death", unit_id=target.unit_id,
                               name=target.name, team=target.team,
                               pos=list(target.pos))
                    self.grid.remove_unit(target)

            results.append(dr)

            # 施加卡牌声明的状态效果（护盾/减速/束缚/虚弱/增幅）——命中才生效
            if hr.hit and card.effects:
                for eff in card.effects:
                    etype = eff.get("type", "")
                    if etype == "shield":
                        target.apply_status("shield", eff.get("value", 0))
                        val = eff.get("value", 0)
                    elif etype == "burn":
                        target.apply_burn(eff.get("value", 4), eff.get("duration", 2))
                        val = eff.get("value", 4)
                    elif etype in ("slow", "bind", "weaken", "strengthen", "silence"):
                        target.apply_status(etype, eff.get("duration", 1))
                        val = eff.get("duration", 1)
                    else:
                        continue
                    self._emit("status", unit_id=unit.unit_id,
                               target_id=target.unit_id, target=target.name,
                               type=etype, value=val,
                               target_pos=list(target.pos))

        if not results:
            # No valid targets in range — refund AP, don't consume card
            if unit.team == "player":
                unit.AP += from_personal
                self.shared_ap += from_shared
            else:
                unit.AP += card.cost
            self._emit("error", unit_id=unit.unit_id,
                       msg=f"目标不在 '{card.name}' 的范围 ({card.range}) 内")
            return results

        pool.play_card(card)
        self._emit("card_played", unit_id=unit.unit_id, caster=unit.name,
                   card=card.name, target=list(target_pos),
                   results=[r.final for r in results])
        self._check_battle_end()
        return results

    def move_unit(self, unit_id: str, new_pos: tuple[int, int],
                  ap_cost: int = 1) -> bool:
        """Move a unit on the grid (costs AP: personal first for players)."""
        unit = self.units[unit_id]
        from_pos = unit.pos

        # 束缚：无法移动
        if unit.status_amount("bind") > 0:
            self._emit("error", unit_id=unit_id, msg="被束缚，无法移动")
            return False

        # Distance validation (Chebyshev, mobility // 2；减速时移动距离减半)
        dist = max(abs(unit.pos[0] - new_pos[0]), abs(unit.pos[1] - new_pos[1]))
        max_move = unit.mobility // 2
        if unit.status_amount("slow") > 0:
            max_move = max(1, max_move // 2)
        if dist > max_move:
            self._emit("error", unit_id=unit_id,
                       msg=f"移动距离超限 ({dist} > {max_move})")
            return False

        if unit.team == "player":
            total_available = unit.AP + self.shared_ap
            if total_available < ap_cost:
                return False
            from_personal = min(unit.AP, ap_cost)
            from_shared = ap_cost - from_personal
            if self.grid.move_unit(unit, new_pos):
                unit.AP -= from_personal
                self.shared_ap -= from_shared
                self._emit("move", unit_id=unit_id, name=unit.name,
                          from_pos=list(from_pos), to_pos=list(new_pos))
                return True
            return False
        else:
            if unit.AP < ap_cost:
                return False
            if self.grid.move_unit(unit, new_pos):
                unit.AP -= ap_cost
                self._emit("move", unit_id=unit_id, name=unit.name,
                          from_pos=list(from_pos), to_pos=list(new_pos))
                return True
            return False

    # ── Enemy intent ──

    def _enemy_card_pool(self, unit: CombatUnit) -> list[Card]:
        """Return all cards available to an enemy (deck + hand + discard + exhaust)."""
        pool = self.enemy_pools.get(unit.unit_id)
        if not pool:
            return []
        return pool.deck + pool.hand + pool.discard + pool.exhaust

    @staticmethod
    def _classify_enemy_intent(card: Card) -> str:
        """Map an enemy card to a coarse intent type for display + planning."""
        if card.target in ("ADJACENT", "AREA_2X2", "CROSS", "LINE_3", "ROW"):
            return "aoe"
        if card.damage_type == "healing":
            return "attack"
        if card.cost >= 2 or card.max_damage >= 12:
            return "heavy"
        return "attack"

    def _estimate_card_damage(self, enemy: CombatUnit, card: Card,
                              target: CombatUnit) -> tuple[int, int]:
        """Estimate a card's post-resistance damage range vs `target` (no hit roll)."""
        if card.damage_type == "physical":
            atk = enemy.PATK
            resist = target.DEF
        elif card.damage_type == "arts":
            atk = enemy.MATK
            resist = target.RES
        elif card.damage_type == "healing":
            return (card.min_damage, card.max_damage)
        else:  # mixed
            atk = (enemy.PATK + enemy.MATK) / 2
            resist = min(target.DEF, target.RES)

        lo = max(1, round(card.min_damage + atk * card.atk_scale - resist))
        hi = max(lo, round(card.max_damage + atk * card.atk_scale - resist))
        return (lo, hi)

    def _pick_enemy_card(self, unit: CombatUnit, target: CombatUnit) -> Card | None:
        """Choose the strongest affordable card that reaches `target`.

        Cards that can hit multiple players score higher (favours AOE when
        players clump together), keeping intents faithful to execution.
        """
        players = [u for u in self.units.values()
                   if u.team == "player" and u.is_alive]
        if not players:
            return None

        best: Card | None = None
        best_score = -1.0
        for card in self._enemy_card_pool(unit):
            if card.cost > unit.AP:
                continue
            if card.target in ("SELF", "ALL_ALLIES"):
                continue
            # 被沉默的敌人无法施放源石技艺（arts）卡牌
            if card.damage_type == "arts" and unit.status_amount("silence") > 0:
                continue

            # How many players this card can reach (global hits everyone).
            if card.range < 0:
                affected = len(players)
            else:
                affected = sum(
                    1 for p in players
                    if range_between(unit.pos, p.pos) <= card.range)

            if affected == 0:
                continue

            avg_damage = (card.min_damage + card.max_damage) / 2 + card.atk_scale * 10
            score = avg_damage * affected
            if score > best_score:
                best = card
                best_score = score
        return best

    def _compute_enemy_intents(self) -> dict:
        """Compute each alive enemy's planned action for the upcoming turn.

        Exposed to the frontend (state.enemy_intents + round_start event) so
        players can read enemy plans and react. `ai_behavior == "defensive"`
        enemies hold position when out of range; aggressive ones close in.
        """
        players = [u for u in self.units.values()
                   if u.team == "player" and u.is_alive]
        intents: dict[str, dict] = {}

        for enemy in self.units.values():
            if enemy.team != "enemy" or not enemy.is_alive:
                continue

            intent = {"type": "defend", "label": INTENT_LABELS["defend"],
                      "target_id": "", "target_name": "",
                      "card_id": "", "card_name": "",
                      "damage_min": None, "damage_max": None}

            if players:
                nearest = min(players, key=lambda p: range_between(enemy.pos, p.pos))
                card = self._pick_enemy_card(enemy, nearest)
                if card:
                    itype = self._classify_enemy_intent(card)
                    lo, hi = self._estimate_card_damage(enemy, card, nearest)
                    intent = {"type": itype, "label": INTENT_LABELS[itype],
                              "target_id": nearest.unit_id,
                              "target_name": nearest.name,
                              "card_id": card.card_id,
                              "card_name": card.name,
                              "damage_min": lo, "damage_max": hi}
                elif enemy.ai_behavior != "defensive" and enemy.AP >= 1:
                    intent = {"type": "move", "label": INTENT_LABELS["move"],
                              "target_id": nearest.unit_id,
                              "target_name": nearest.name,
                              "card_id": "", "card_name": "",
                              "damage_min": None, "damage_max": None}

            intents[enemy.unit_id] = intent

        return intents

    def _ensure_card_in_hand(self, unit: CombatUnit, card: Card) -> None:
        """Move `card` into the enemy's hand so `play_card` validates it."""
        pool = self.enemy_pools.get(unit.unit_id)
        if not pool or card in pool.hand:
            return
        for pile in (pool.deck, pool.discard, pool.exhaust):
            if card in pile:
                pile.remove(card)
                break
        pool.hand.append(card)

    # ── Enemy AI ──

    def _execute_enemy_turn(self, unit_id: str) -> list[DamageResult]:
        """Execute an enemy's planned action, following its precomputed intent."""
        unit = self.units[unit_id]
        intent = self.state.enemy_intents.get(unit_id, {})
        intent_type = intent.get("type", "attack")

        players = [u for u in self.units.values()
                   if u.team == "player" and u.is_alive]
        if not players:
            return []

        # 坚守：固守位置，本回合不行动。
        if intent_type == "defend":
            return []

        # Resolve intended target; fall back to nearest alive player.
        target = None
        target_id = intent.get("target_id", "")
        if target_id and target_id in self.units:
            candidate = self.units[target_id]
            if candidate.team == "player" and candidate.is_alive:
                target = candidate
        if target is None:
            target = min(players, key=lambda p: range_between(unit.pos, p.pos))

        card = self._pick_enemy_card(unit, target)
        if card:
            self._ensure_card_in_hand(unit, card)
            return self.play_card(unit_id, card, target.pos)

        # Can't attack — move toward the target if AP remains.
        if unit.AP >= 1:
            r, c = unit.pos
            tr, tc = target.pos
            dr = 0 if r == tr else (1 if tr > r else -1)
            dc = 0 if c == tc else (1 if tc > c else -1)
            new_pos = (r + dr, c + dc)
            if self.grid.is_valid_position(new_pos, unit.team):
                if self.grid.move_unit(unit, new_pos):
                    unit.AP -= 1

        return []

    # ── Query ──

    def _force_end(self, winner: str, reason: str) -> None:
        """强制结束战斗并指定胜负方与原因（回合超时 / 玩家撤退）。"""
        self.state.phase = "END"
        self.state.winner = winner
        self._emit("battle_end", winner=winner, reason=reason)

    def escape(self) -> bool:
        """玩家撤退（fail-forward，不判负死亡）。返回是否成功结束战斗。"""
        if not self.escape_enabled or self.is_battle_over():
            return False
        self._force_end("escaped", "玩家撤退")
        return True

    def _check_battle_end(self) -> bool:
        """Check if the battle has ended (all players or all enemies dead).
        Returns True if the battle ended."""
        players_alive = any(u.team == "player" and u.is_alive for u in self.units.values())
        enemies_alive = any(u.team == "enemy" and u.is_alive for u in self.units.values())

        if not enemies_alive:
            self.state.phase = "END"
            self.state.winner = "player"
            self._emit("battle_end", winner="player", reason="所有敌人已消灭")
            return True
        if not players_alive:
            self.state.phase = "END"
            self.state.winner = "enemy"
            self._emit("battle_end", winner="enemy", reason="所有干员已撤退")
            return True
        return False

    def is_battle_over(self) -> bool:
        return self.state.phase == "END"

