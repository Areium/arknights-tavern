"""
Combat engine — state machine, turn management, enemy AI.

States: INIT → ROUND_START → PLAYER_TURN → ENEMY_TURN (loop) → ROUND_END → (repeat or END)
"""

import copy
import logging
import random
from dataclasses import dataclass, field
from typing import Optional, Callable

from combat_map import BattleMap, default_map
from combat_engine.entity import CombatUnit
from combat_engine.grid import (
    CHEBYSHEV, MANHATTAN, Grid, metric_distance, resolve_targets,
)
from combat_engine.card import Card, CardPool
from combat_engine.dice import check_hit, compute_damage, HitResult, DamageResult


logger = logging.getLogger(__name__)


# ── Enemy intent labels ──
INTENT_LABELS = {
    "attack": "攻击",
    "heavy": "重击",
    "aoe": "范围攻击",
    "move": "移动",
    "defend": "坚守",
    "heal": "治疗",
}


# ── 敌人卡牌目录（ai_skills 数据驱动）──
# 敌人 frontmatter 的 `ai_skills` 引用这里的 card_id；每个敌人实例深拷贝，避免共享可变状态。
ENEMY_CARD_CATALOG: dict[str, Card] = {
    "enemy_atk": Card("enemy_atk", "攻击", "基础攻击",
                      "physical", 5, 10, 0.5, "SINGLE", 1, 1, "basic", "any"),
    "enemy_heavy": Card("enemy_heavy", "重击", "强力攻击",
                        "physical", 8, 16, 0.8, "SINGLE", 1, 2, "basic", "any"),
    "enemy_aoe": Card("enemy_aoe", "横扫", "范围攻击",
                      "physical", 3, 6, 0.3, "ADJACENT", 1, 2, "basic", "any"),
    "enemy_shot": Card("enemy_shot", "射击", "精准射击",
                       "physical", 6, 12, 0.6, "SINGLE", 3, 1, "basic", "any"),
    "enemy_barrage": Card("enemy_barrage", "连射", "快速连射",
                          "physical", 4, 8, 0.4, "SINGLE", 3, 2, "basic", "any"),
    "enemy_bolt": Card("enemy_bolt", "能量弹", "发射源石能量弹",
                       "arts", 5, 10, 0.5, "SINGLE", 3, 1, "basic", "any"),
    "enemy_storm": Card("enemy_storm", "法术风暴", "范围法术攻击",
                        "arts", 4, 8, 0.4, "ADJACENT", 2, 2, "basic", "any"),
    "enemy_blast": Card("enemy_blast", "法术冲击", "高密度源石能量",
                        "arts", 8, 16, 0.8, "SINGLE", 2, 2, "basic", "any"),
}

# 职业 → 默认 ai_skills（ai_skills 未定义或全部未知时回退）
_ENEMY_CLASS_DEFAULT_SKILLS: dict[str, list[str]] = {
    "术师": ["enemy_bolt", "enemy_storm", "enemy_blast"],
    "caster": ["enemy_bolt", "enemy_storm", "enemy_blast"],
    "caster_elite": ["enemy_bolt", "enemy_storm", "enemy_blast"],
    "狙击": ["enemy_shot", "enemy_barrage"],
    "sniper": ["enemy_shot", "enemy_barrage"],
    "sniper_elite": ["enemy_shot", "enemy_barrage"],
}
_ENEMY_MELEE_SKILLS = ["enemy_atk", "enemy_heavy", "enemy_aoe"]


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
    BALANCE_VERSION = 1

    def __init__(self, battle_map: BattleMap | None = None,
                 rules: dict | None = None):
        rules = dict(rules or {})
        self.map: BattleMap = battle_map or default_map()
        self.corner_cut = bool(rules.get("allow_corner_cut", False))
        # 距离度量：移动与攻击统一曼哈顿（8 向、斜向步代价 ×2），可逐节点覆盖
        self.range_metric = str(rules.get("range_metric") or MANHATTAN)
        self.grid = Grid(self.map, corner_cut=self.corner_cut)
        self.units: dict[str, CombatUnit] = {}     # unit_id → CombatUnit
        self.shared_pool: CardPool | None = None    # single shared pool for all player cards
        self.enemy_pools: dict[str, CardPool] = {}  # per-enemy pools for AI
        self.state = CombatState()
        self.shared_ap = 0
        self.SHARED_AP_MAX = 4
        self.balance_version = self.BALANCE_VERSION
        self.telemetry = {"rounds": {}, "totals": self._empty_metrics()}
        self.initial_hp: dict[str, int] = {}
        self.enemy_actions_taken: dict[str, int] = {}
        self.max_rounds = 0          # 回合上限（0 = 无限制）
        self.escape_enabled = False  # 是否允许撤退
        self.pending_waves: list[list[tuple[CombatUnit, tuple[int, int]]]] = []  # 待入场波次
        self.wave_num = 0            # 当前波次编号（1 起）

        # Callbacks for external input
        self.on_event: Optional[Callable[[CombatEvent], None]] = None

    # ── Setup ──

    def distance(self, a: tuple[int, int], b: tuple[int, int]) -> int:
        """按本场度量取距离（默认曼哈顿；移动与攻击共用同一度量）。"""
        return metric_distance(a, b, self.range_metric)

    def _terrain_mods(self, attacker_pos: tuple[int, int],
                      defender_pos: tuple[int, int]) -> dict:
        """攻守双方所在地形修正：攻方加伤、守方加防/加闪避。"""
        atk = self.grid.terrain_at(attacker_pos)
        dfn = self.grid.terrain_at(defender_pos)
        return {
            "damage_bonus": atk.get("damage_bonus", 0),
            "defense_bonus": dfn.get("defense_bonus", 0),
            "evasion_bonus": dfn.get("evasion_bonus", 0),
        }

    def move_budget(self, unit: CombatUnit) -> int:
        """单位一次移动的预算（曼哈顿格）：mobility // 2，减速减半。"""
        budget = unit.mobility // 2
        if unit.status_amount("slow") > 0:
            budget = max(1, budget // 2)
        return max(1, budget)

    def _place_validated(self, unit: CombatUnit, pos) -> None:
        """坐标校验后落位（越界/地形阻挡/占用一律拒绝，避免静默错位）。"""
        pos = tuple(pos)
        if not self.grid.can_place(pos, ignore_unit_id=unit.unit_id):
            raise ValueError(
                f"{unit.name} 无法部署到 {pos}：越界、地形阻挡或该格已有单位")

    def add_player_unit(self, unit: CombatUnit, cards: list[Card] = None,
                        pos: tuple[int, int] = None):
        """Add a player unit. Player cards go into the shared pool."""
        self.units[unit.unit_id] = unit
        self.initial_hp.setdefault(unit.unit_id, unit.hp)

        # Set card owners and collect into shared pool
        if not self.shared_pool:
            self.shared_pool = CardPool(hand_size=self.SHARED_HAND_SIZE)
        if cards:
            for c in cards:
                c.owner = unit.name
                self.shared_pool.deck.append(c)

        # Auto-place if position given
        if pos:
            self._place_validated(unit, pos)
            self.grid.place_unit(unit, tuple(pos))

    def add_enemy_unit(self, unit: CombatUnit, pos: tuple[int, int] = None):
        """Add an enemy unit with its own simple card pool."""
        self.units[unit.unit_id] = unit
        self.initial_hp.setdefault(unit.unit_id, unit.hp)
        pool = CardPool(hand_size=5)
        pool.init_deck(self._enemy_cards(unit))
        self.enemy_pools[unit.unit_id] = pool

        if pos:
            self._place_validated(unit, pos)
            self.grid.place_unit(unit, tuple(pos))

    @staticmethod
    def _enemy_cards(unit: CombatUnit) -> list[Card]:
        """敌人卡组由 frontmatter `ai_skills` 数据驱动；未声明/全部未知时回退职业默认。"""
        ids = [i for i in (getattr(unit, "ai_skills", None) or [])
               if i in ENEMY_CARD_CATALOG]
        if not ids:
            cls = getattr(unit, "char_class", "")
            ids = _ENEMY_CLASS_DEFAULT_SKILLS.get(cls, _ENEMY_MELEE_SKILLS)
        return [copy.deepcopy(ENEMY_CARD_CATALOG[i]) for i in ids]

    def load_waves(self, waves: list[list[tuple[CombatUnit, tuple[int, int]]]]):
        """接收预构建波次（wave 0 立即入场，其余进入 pending_waves 按波触发）。"""
        self.pending_waves = [list(w) for w in waves]
        self.wave_num = 0
        self._spawn_next_wave()

    def _spawn_next_wave(self) -> bool:
        """将 pending_waves 队首波次入场；无更多波次返回 False。"""
        if not self.pending_waves:
            return False
        wave = self.pending_waves.pop(0)
        self.wave_num += 1
        for unit, pos in wave:
            spawn = self._resolve_spawn_pos(pos)
            if spawn is None:
                logger.warning("波次 %d：%s 无可用落脚点，跳过入场", self.wave_num, unit.name)
                continue
            self.add_enemy_unit(unit, spawn)
        self._emit("wave_start", wave=self.wave_num)
        return True

    def _resolve_spawn_pos(self, pos, max_radius: int = 6):
        """波次入场落点：声明格不可用时顺延到最近空位；全图无空位返回 None。

        多波次节点常复用同一批坐标，第二波入场时原格已被占——此时顺延而不是
        报错（此前旧实现会静默覆盖占位，导致先入场的单位被从网格上抹掉）。
        """
        pos = tuple(pos)
        if self.grid.can_place(pos):
            return pos
        for radius in range(1, max_radius + 1):
            ring = [(pos[0] + dr, pos[1] + dc)
                    for dr in range(-radius, radius + 1)
                    for dc in range(-radius, radius + 1)]
            for cand in ring:
                if self.grid.can_place(cand):
                    return cand
        for row in range(self.grid.rows):
            for col in range(self.grid.cols):
                if self.grid.can_place((row, col)):
                    return (row, col)
        return None

    # ── State Machine ──

    @staticmethod
    def _empty_metrics() -> dict:
        return {"player_card_ap": 0, "player_move_ap": 0,
                "player_cards_played": 0, "player_moves": 0,
                "enemy_actions": 0, "enemy_card_ap": 0,
                "damage_by_source": {}, "healing_effective": 0,
                "healing_overflow": 0, "healing_overflow_pure": 0,
                "cards_drawn": {}, "cards_used": {}}

    def _record_telemetry(self, event_type: str, data: dict) -> None:
        if event_type not in ("damage", "heal", "move", "card_drawn", "card_played"):
            return
        metrics = self.telemetry["rounds"].setdefault(
            str(self.state.round_num), self._empty_metrics())
        for bucket in (metrics, self.telemetry["totals"]):
            if event_type == "damage":
                source = data["unit_id"]
                amounts = bucket["damage_by_source"]
                amounts[source] = amounts.get(source, 0) + data["damage"]
            elif event_type == "heal":
                bucket["healing_effective"] += data["amount"]
                bucket["healing_overflow"] += data.get("overflow", 0)
                # 纯治疗卡（无附带效果）的溢出单独记账：护盾/辅助类「治疗型」卡
                # 在满血目标上的治疗量属于设计内的附带效果，不应计入治疗效率指标。
                if not data.get("support"):
                    bucket["healing_overflow_pure"] += data.get("overflow", 0)
            elif event_type == "move":
                if data.get("team") == "player":
                    bucket["player_move_ap"] += data["cost"]
                    bucket["player_moves"] += 1
                else:
                    bucket["enemy_actions"] += 1
            elif event_type in ("card_drawn", "card_played"):
                key = "cards_drawn" if event_type == "card_drawn" else "cards_used"
                counts = bucket[key]
                card_id = data["card_id"]
                counts[card_id] = counts.get(card_id, 0) + 1
                if event_type == "card_played":
                    if data.get("team") == "player":
                        bucket["player_card_ap"] += data["cost"]
                        bucket["player_cards_played"] += 1
                    else:
                        bucket["enemy_actions"] += 1
                        bucket["enemy_card_ap"] += data["cost"]

    def _emit(self, event_type: str, **data):
        data.setdefault("round", self.state.round_num)
        source = self.units.get(data.get("unit_id"))
        if source:
            data.setdefault("team", source.team)
        self._record_telemetry(event_type, data)
        ev = CombatEvent(event_type, data)
        self.state.events.append(ev)
        if self.on_event:
            self.on_event(ev)

    def _record_draw(self, card: Card, reason: str = "draw") -> None:
        owner = next((u for u in self.units.values()
                      if u.team == "player" and u.name == card.owner), None)
        self._emit("card_drawn", unit_id=owner.unit_id if owner else "",
                   team="player", card_id=card.card_id, card=card.name,
                   owner=card.owner, cost=card.cost, reason=reason)

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
        self.enemy_actions_taken = {}
        self.telemetry["rounds"].setdefault(str(self.state.round_num), self._empty_metrics())

        # Resolve deaths before guaranteeing cards for surviving characters.
        for unit in list(self.units.values()):
            if unit.is_alive:
                unit.reset_ap()
                self._apply_burn(unit)
                unit.tick_status()
                if unit.is_alive:
                    self._apply_tile_effects(unit, [unit.pos], hook="round_start")
        if self._check_battle_end():
            return

        # Move all remaining hand cards to discard (shared pool)
        if self.shared_pool:
            self.shared_pool.discard_hand()
            self._draw_shared_hand()
            self._character_guarantee()

        # Reset shared AP
        self._recalc_shared_ap_max()
        self.shared_ap = self.SHARED_AP_MAX

        self.state.turn_order = [u.unit_id for u in sorted(
            (u for u in self.units.values() if u.team == "enemy" and u.is_alive),
            key=lambda u: u.SPD, reverse=True)]
        self.state.current_idx = 0

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
        shield_before = unit.status_amount("shield")
        actual = unit.take_damage(dmg)
        source = unit.status.get("burn_source", {})
        self._emit("damage", unit_id=source.get("unit_id", "burn"), caster="Burn",
                   team=source.get("team", ""), card_id=source.get("card_id", "burn"),
                   cost=0, source_type="burn", target_team=unit.team,
                   target_id=unit.unit_id, target=unit.name,
                   damage=actual, hit_result="HIT", card="Burn",
                   shielded=shield_before - unit.status_amount("shield"),
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
                card = self.shared_pool.deck.pop()
                self.shared_pool.hand.append(card)
                self._record_draw(card)

    def _character_guarantee(self):
        """Draw missing owners from recyclable piles without removing a sole card."""
        pool = self.shared_pool
        if not pool:
            return
        owners = [u.name for u in self.units.values() if u.team == "player" and u.is_alive]
        for owner in owners:
            if any(c.owner == owner for c in pool.hand):
                continue
            source = next((pile for pile in (pool.deck, pool.discard)
                           if any(c.owner == owner for c in pile)), None)
            if source is None:
                continue
            replacement = next(c for c in source if c.owner == owner)
            index = None
            if len(pool.hand) >= self.SHARED_HAND_SIZE:
                candidates = [i for i, c in enumerate(pool.hand)
                              if c.owner not in owners or
                              sum(h.owner == c.owner for h in pool.hand) > 1]
                if not candidates:
                    continue
                index = random.choice(candidates)
            source.remove(replacement)
            if index is None:
                pool.hand.append(replacement)
            else:
                pool.deck.insert(0, pool.hand[index])
                pool.hand[index] = replacement
            self._record_draw(replacement, "guarantee")

    def _recalc_shared_ap_max(self):
        highest = max((u.attributes.get("tactical_planning", 5)
                       for u in self.units.values() if u.team == "player" and u.is_alive),
                      default=5)
        self.SHARED_AP_MAX = 5 if highest >= 8 else 4

    def end_player_round(self):
        """End the player's round: execute all enemy turns, then advance round."""
        if self._check_battle_end():
            return

        self.state.phase = "ENEMY_TURN"

        for uid in self.state.turn_order[self.state.current_idx:]:
            if self.is_battle_over():
                break
            enemy = self.units.get(uid)
            if enemy and enemy.is_alive:
                self._execute_enemy_turn(uid)
            self.state.current_idx += 1
            self._check_battle_end()

        if not self.is_battle_over():
            self._emit("turn_end", round=self.state.round_num)
            self.state.round_num += 1
            if self.max_rounds > 0 and self.state.round_num > self.max_rounds:
                self._force_end("enemy", f"回合超时（{self.max_rounds} 回合）")
                return
            self._start_round()

    # ── Actions ──

    @staticmethod
    def _valid_position(pos) -> bool:
        return (isinstance(pos, (tuple, list)) and len(pos) == 2
                and all(type(v) is int for v in pos))

    def _card_targets(self, unit: CombatUnit, card: Card, target_pos) -> list[CombatUnit]:
        """The single target-resolution contract used by validation, AI, and execution."""
        if card.target in ("SELF", "ALL_ALLIES", "GLOBAL"):
            target_pos = unit.pos
        if not self._valid_position(target_pos):
            return []
        target_pos = tuple(target_pos)
        if not self.grid.is_valid_position(target_pos):
            return []
        if card.target not in ("ALL_ALLIES", "GLOBAL") and card.range >= 0:
            if self.distance(unit.pos, target_pos) > card.range:
                return []
            if card.range > 1 and not self.grid.has_line_of_sight(unit.pos, target_pos):
                return []
        if card.target == "SELF":
            positions = [unit.pos]
        elif card.target == "ALL_ALLIES":
            positions = [u.pos for u in self.units.values() if u.team == unit.team]
        elif card.target == "GLOBAL":
            positions = [u.pos for u in self.units.values() if u.team != unit.team]
        elif card.target == "LINE_3":
            dr = (target_pos[0] > unit.pos[0]) - (target_pos[0] < unit.pos[0])
            dc = (target_pos[1] > unit.pos[1]) - (target_pos[1] < unit.pos[1])
            positions = resolve_targets(card.target, target_pos,
                                       direction=(dr, dc) if dr or dc else (0, 1),
                                       rows=self.grid.rows, cols=self.grid.cols)
        else:
            positions = resolve_targets(card.target, target_pos,
                                        rows=self.grid.rows, cols=self.grid.cols)
        targets = []
        for pos in positions:
            target = self.grid.get_unit_at(pos)
            if not target or not target.is_alive:
                continue
            if card.range >= 0 and self.distance(unit.pos, pos) > card.range:
                continue
            if card.range > 1 and not self.grid.has_line_of_sight(unit.pos, pos):
                continue
            if (target.team == unit.team) != (card.damage_type == "healing"):
                continue
            targets.append(target)
        return targets

    def validate_card_play(self, unit_id: str, card: Card, target_pos,
                           require_hand: bool = True) -> str | None:
        """Return a rejection reason without spending AP or changing piles."""
        unit = self.units.get(unit_id)
        if not unit or not unit.is_alive:
            return "Invalid or defeated card owner"
        if self.is_battle_over():
            return "Battle is over"
        if unit.team == "player":
            if self.state.phase != "PLAYER_TURN":
                return "Not player turn"
            if card.owner not in (None, "", unit.name):
                return "Card belongs to another character"
        else:
            if self.enemy_actions_taken.get(unit_id, 0) >= unit.action_slots:
                return "No action slots remaining"
        if card.class_required not in ("any", "", None, unit.char_class):
            return "Card class requirement not met"
        pool = self.shared_pool if unit.team == "player" else self.enemy_pools.get(unit_id)
        available = pool.hand if pool and require_hand else self._enemy_card_pool(unit)
        if not pool or not any(c is card for c in available):
            return "Card is not available"
        if type(card.cost) is not int or card.cost < 0:
            return "Invalid card cost"
        if unit.status_amount("silence") > 0 and card.damage_type == "arts":
            return "Silenced units cannot play arts cards"
        ap = self.shared_ap if unit.team == "player" else unit.AP
        if ap < card.cost:
            return "Insufficient shared AP" if unit.team == "player" else "Insufficient personal AP"
        if not self._card_targets(unit, card, target_pos):
            if card.range > 1 and self._valid_position(target_pos) and \
                    not self.grid.has_line_of_sight(unit.pos, tuple(target_pos)):
                return "Target is blocked by terrain"
            return "No legal targets in range"
        return None

    def play_card(self, unit_id: str, card: Card, target_pos: tuple[int, int]) -> list[DamageResult]:
        error = self.validate_card_play(unit_id, card, target_pos)
        if error:
            self._emit("error", unit_id=unit_id, card_id=card.card_id, cost=card.cost, msg=error)
            return []
        unit = self.units[unit_id]
        pool = self.shared_pool if unit.team == "player" else self.enemy_pools[unit_id]
        if card.target in ("SELF", "ALL_ALLIES", "GLOBAL"):
            target_pos = unit.pos
        targets = self._card_targets(unit, card, target_pos)
        if unit.team == "player":
            self.shared_ap -= card.cost
        else:
            unit.AP -= card.cost
        results: list[DamageResult] = []
        self_effects_applied = set()
        for target in targets:
            if card.damage_type == "healing":
                # Healing always hits
                hr = HitResult(0, True, False, False)
                dr = compute_damage(unit, target, card, hr)
                healed = target.heal(dr.final)
                self._emit("heal", unit_id=unit.unit_id, caster=unit.name,
                           card_id=card.card_id, cost=card.cost, target_team=target.team,
                           target_id=target.unit_id, target=target.name,
                           amount=healed, overflow=dr.final - healed, requested=dr.final,
                           support=bool(card.effects),
                           card=card.name, target_pos=list(target.pos))
            else:
                terrain_mods = self._terrain_mods(unit.pos, target.pos)
                hr = check_hit(unit, target, terrain_mods)
                dr = compute_damage(unit, target, card, hr, terrain_mods)
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
                           card_id=card.card_id, cost=card.cost, damage_type=card.damage_type,
                           target_team=target.team, source_type="card",
                           target_id=target.unit_id, target=target.name,
                           damage=actual, hit_result=str(hr), card=card.name,
                           shielded=shielded, target_pos=list(target.pos))

                if not target.is_alive:
                    self._emit("death", unit_id=target.unit_id,
                               name=target.name, team=target.team,
                               pos=list(target.pos))
                    self.grid.remove_unit(target)

            results.append(dr)

            # 净化：驱散目标的负面状态
            if card.cleanse and hr.hit:
                target.clear_debuffs()
                self._emit("cleanse", unit_id=unit.unit_id, target_id=target.unit_id,
                           target=target.name, target_pos=list(target.pos))

            # 施加卡牌声明的状态效果（护盾/减速/束缚/虚弱/增幅/沉默/嘲讽/闪避/致盲）——命中才生效
            if hr.hit and card.effects:
                for index, eff in enumerate(card.effects):
                    etype = eff.get("type", "")
                    effect_target = unit if eff.get("self") else target
                    if not effect_target.is_alive or (eff.get("self") and index in self_effects_applied):
                        continue
                    if eff.get("self"):
                        self_effects_applied.add(index)
                    if etype == "shield":
                        val = max(0, round(eff.get("value", 0) + unit.DEF * eff.get("def_scale", 0)))
                        effect_target.apply_status("shield", val, duration=eff.get("duration"))
                    elif etype == "burn":
                        effect_target.apply_burn(eff.get("value", 4), eff.get("duration", 2))
                        effect_target.status["burn_source"] = {
                            "unit_id": unit.unit_id, "team": unit.team, "card_id": card.card_id}
                        val = eff.get("value", 4)
                    elif etype in ("slow", "bind", "weaken", "strengthen", "silence", "taunt", "evade", "blind"):
                        effect_target.apply_status(etype, eff.get("duration", 1))
                        val = eff.get("duration", 1)
                    else:
                        continue
                    self._emit("status", unit_id=unit.unit_id,
                               card_id=card.card_id, cost=card.cost, duration=eff.get("duration"),
                               target_id=effect_target.unit_id, target=effect_target.name,
                               type=etype, value=val,
                               target_pos=list(effect_target.pos))

        pool.play_card(card)
        if unit.team == "enemy":
            self.enemy_actions_taken[unit_id] = self.enemy_actions_taken.get(unit_id, 0) + 1
        self._emit("card_played", unit_id=unit.unit_id, caster=unit.name,
                   card_id=card.card_id, cost=card.cost, card=card.name,
                   target=list(target_pos), results=[r.final for r in results])
        self._check_battle_end()
        return results

    def validate_move(self, unit_id: str, new_pos, ap_cost: int = 1) -> str | None:
        """Validate movement without borrowing shared AP or changing the grid."""
        unit = self.units.get(unit_id)
        if not unit or not unit.is_alive:
            return "Invalid or defeated unit"
        if self.is_battle_over():
            return "Battle is over"
        if unit.team == "player" and self.state.phase != "PLAYER_TURN":
            return "Not player turn"
        if unit.team == "enemy" and self.enemy_actions_taken.get(unit_id, 0) >= unit.action_slots:
            return "No action slots remaining"
        if type(ap_cost) is not int or ap_cost != 1:
            return "Movement costs exactly one personal AP"
        if unit.AP < ap_cost:
            return "Insufficient personal AP"
        if unit.status_amount("bind") > 0:
            return "Bound units cannot move"
        if not self._valid_position(new_pos):
            return "Invalid move target"
        new_pos = tuple(new_pos)
        if not self.grid.can_place(new_pos, ignore_unit_id=unit_id):
            return "Invalid or occupied move target"
        if self.grid.path_to(unit.pos, new_pos, budget=self.move_budget(unit),
                             mover_id=unit_id) is None:
            return "Move target is out of range or unreachable"
        return None

    def move_unit(self, unit_id: str, new_pos: tuple[int, int],
                  ap_cost: int = 1) -> bool:
        """Move for one personal AP; shared AP is reserved for cards/items.

        路径按曼哈顿代价计算（斜向 ×2、地形 move_cost），逐格触发 `on_enter` 效果。
        """
        error = self.validate_move(unit_id, new_pos, ap_cost)
        if error:
            self._emit("error", unit_id=unit_id, msg=error)
            return False
        unit = self.units[unit_id]
        from_pos = unit.pos
        path = self.grid.path_to(from_pos, tuple(new_pos),
                                 budget=self.move_budget(unit), mover_id=unit_id) or []
        if not self.grid.move_unit(unit, tuple(new_pos)):
            return False
        unit.AP -= ap_cost
        if unit.team == "enemy":
            self.enemy_actions_taken[unit_id] = self.enemy_actions_taken.get(unit_id, 0) + 1
        self._emit("move", unit_id=unit_id, name=unit.name, cost=ap_cost,
                   from_pos=list(from_pos), to_pos=list(unit.pos),
                   path=[list(p) for p in path])
        self._apply_tile_effects(unit, path[1:] or [unit.pos], hook="enter")
        return True

    # ── 格子效果 ──

    def _apply_tile_effects(self, unit: CombatUnit, cells, hook: str) -> None:
        """触发格子效果：`enter`（移动途经/落脚）或 `round_start`（回合开始所在格）。

        效果字段：damage（立即伤害，护盾先吸收）/ heal（立即治疗）/
        status + stacks（burn=每回合 stacks 点伤害持续 2 回合；shield=层数持续 2 回合；
        其余状态视为持续回合数）。
        """
        for pos in cells:
            if not unit.is_alive:
                return
            pos = tuple(pos)
            if not self.grid.in_bounds(pos):
                continue
            tile = self.grid.tile(pos)
            effect = tile.effect(hook)
            if not effect:
                continue
            tile_card = f"tile_{tile.tile_id}"
            damage = int(effect.get("damage") or 0)
            if damage > 0:
                shield_before = unit.status_amount("shield")
                actual = unit.take_damage(damage)
                self._emit("damage", unit_id=f"terrain:{pos}", caster=tile.name or "地形",
                           team="", card_id=tile_card, cost=0, source_type="terrain",
                           target_team=unit.team, target_id=unit.unit_id, target=unit.name,
                           damage=actual, hit_result="HIT", card=tile.name,
                           shielded=shield_before - unit.status_amount("shield"),
                           damage_type="arts", target_pos=list(unit.pos))
            heal = int(effect.get("heal") or 0)
            if heal > 0 and unit.is_alive:
                healed = unit.heal(heal)
                if healed:
                    self._emit("heal", unit_id=f"terrain:{pos}", caster=tile.name or "地形",
                               card_id=tile_card, cost=0, target_team=unit.team,
                               target_id=unit.unit_id, target=unit.name, amount=healed,
                               overflow=heal - healed, requested=heal, support=False,
                               card=tile.name, target_pos=list(unit.pos))
            status = str(effect.get("status") or "")
            stacks = int(effect.get("stacks") or 0)
            if status and stacks and unit.is_alive:
                if status == "burn":
                    unit.apply_burn(stacks, 2)
                elif status == "shield":
                    unit.apply_status("shield", stacks, duration=2)
                else:
                    unit.apply_status(status, stacks)
                self._emit("status", unit_id=f"terrain:{pos}", card_id=tile_card, cost=0,
                           duration=2, target_id=unit.unit_id, target=unit.name,
                           type=status, value=stacks, target_pos=list(unit.pos))
            if not unit.is_alive:
                self._emit("death", unit_id=unit.unit_id, name=unit.name,
                           team=unit.team, pos=list(unit.pos))
                self.grid.remove_unit(unit)
        self._check_battle_end()

    # ── Enemy intent ──

    def _enemy_card_pool(self, unit: CombatUnit) -> list[Card]:
        """Return all cards available to an enemy (deck + hand + discard).

        exhaust 堆排除：elite 卡被消耗后本场战斗不可再用（Slay the Spire 语义）。
        """
        pool = self.enemy_pools.get(unit.unit_id)
        if not pool:
            return []
        return pool.deck + pool.hand + pool.discard

    @staticmethod
    def _classify_enemy_intent(card: Card) -> str:
        """Map an enemy card to a coarse intent type for display + planning."""
        if card.target in ("ADJACENT", "AREA_2X2", "CROSS", "LINE_3", "ROW"):
            return "aoe"
        if card.damage_type == "healing":
            return "heal"
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

    def _pick_enemy_card(self, unit: CombatUnit, target: CombatUnit,
                         from_pos: tuple[int, int] | None = None) -> Card | None:
        """Choose the strongest affordable card that reaches `target`.

        Cards that can hit multiple players score higher (favours AOE when
        players clump together), keeping intents faithful to execution.
        `from_pos` allows planning from a simulated position.
        """
        players = [u for u in self.units.values()
                   if u.team == "player" and u.is_alive]
        if not players:
            return None
        pos = from_pos or unit.pos

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
                    if self.distance(pos, p.pos) <= card.range)

            if affected == 0:
                continue

            avg_damage = (card.min_damage + card.max_damage) / 2 + card.atk_scale * 10
            score = avg_damage * affected
            if score > best_score:
                best = card
                best_score = score
        return best

    def _enemy_target(self, unit: CombatUnit, players: list[CombatUnit]) -> CombatUnit:
        """敌人目标选择：优先攻击嘲讽（taunt）中的玩家，否则攻击最近的。"""
        taunted = [p for p in players if p.status_amount("taunt") > 0]
        pool = taunted if taunted else players
        return min(pool, key=lambda p: self.distance(unit.pos, p.pos))

    def step_toward(self, pos: tuple[int, int], target: tuple[int, int],
                     mover_id: str = "") -> tuple[int, int]:
        """朝 target 前进一格：走寻路结果的第一步（曼哈顿代价，绕开地形）。

        目标格可能被目标单位占着，这里只把目标当作方向指引，取第一个**可落脚**的
        中间步；无路可走或下一步不可落脚时返回原位，调用方据此结束该动作
        （不阻塞回合），这样被墙围死的敌人不会卡死整场战斗。
        """
        path = self.grid.path_to(pos, target, budget=None, mover_id=mover_id,
                                 goal_may_be_occupied=True)
        if path and len(path) > 1:
            step = path[1]
            if self.grid.can_place(step, ignore_unit_id=mover_id):
                return step
        return pos

    def _plan_enemy_actions(self, unit: CombatUnit,
                            players: list[CombatUnit]) -> list[dict]:
        """共享决策：预告与执行使用同一规则生成敌人行动计划。

        规则（design §4.2）：
        - 每轮最多 action_slots 个动作；每动作消耗卡牌 cost 或移动 1 AP；
        - 能命中玩家时优先出分最高的可负担卡；否则 aggressive 前进、defensive 坚守；
        - 计划顺序执行，移动后的位置用于后续选卡（不虚报可行动数）。
        """
        plan: list[dict] = []
        ap = unit.AP
        pos = unit.pos
        for _ in range(max(0, int(unit.action_slots))):
            if ap <= 0 or not players:
                break
            target = min(players, key=lambda p: self.distance(pos, p.pos))
            card = self._pick_enemy_card(unit, target, from_pos=pos)
            if card and card.cost <= ap:
                itype = self._classify_enemy_intent(card)
                lo, hi = self._estimate_card_damage(unit, card, target)
                plan.append({"type": itype, "label": INTENT_LABELS[itype],
                             "card_id": card.card_id, "card_name": card.name,
                             "target_id": target.unit_id, "target_name": target.name,
                             "damage_min": lo, "damage_max": hi})
                ap -= card.cost
                continue
            if unit.ai_behavior != "defensive" and ap >= 1:
                step = self.step_toward(pos, target.pos, mover_id=unit.unit_id)
                if step == pos:
                    break
                plan.append({"type": "move", "label": INTENT_LABELS["move"],
                             "card_id": "", "card_name": "",
                             "target_id": target.unit_id, "target_name": target.name,
                             "damage_min": None, "damage_max": None})
                pos = step
                ap -= 1
                continue
            break
        return plan

    def _compute_enemy_intents(self) -> dict:
        """Compute each alive enemy's planned action sequence for the upcoming turn.

        Exposed to the frontend (state.enemy_intents + round_start event) so
        players can read enemy plans and react. 每个意图包含 `action_slots` 与
        `actions` 列表；执行阶段按同一计划执行，局势变化时才重规划。
        """
        players = [u for u in self.units.values()
                   if u.team == "player" and u.is_alive]
        intents: dict[str, dict] = {}

        for enemy in self.units.values():
            if enemy.team != "enemy" or not enemy.is_alive:
                continue

            plan = self._plan_enemy_actions(enemy, players)
            if plan:
                first = plan[0]
                intent = {
                    "type": first["type"], "label": first["label"],
                    "target_id": first["target_id"], "target_name": first["target_name"],
                    "card_id": first["card_id"], "card_name": first["card_name"],
                    "damage_min": first["damage_min"], "damage_max": first["damage_max"],
                    "action_slots": enemy.action_slots, "ap": enemy.AP,
                    "actions": plan,
                }
            else:
                intent = {
                    "type": "defend", "label": INTENT_LABELS["defend"],
                    "target_id": "", "target_name": "",
                    "card_id": "", "card_name": "",
                    "damage_min": None, "damage_max": None,
                    "action_slots": enemy.action_slots, "ap": enemy.AP,
                    "actions": [],
                }
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

    def _find_enemy_card(self, unit: CombatUnit, card_id: str) -> Card | None:
        """Locate the precomputed intent card in the enemy's available piles."""
        if not card_id:
            return None
        pool = self.enemy_pools.get(unit.unit_id)
        if not pool:
            return None
        for pile in (pool.hand, pool.deck, pool.discard):
            for c in pile:
                if c.card_id == card_id:
                    return c
        return None

    def _execute_enemy_turn(self, unit_id: str) -> list[DamageResult]:
        """按行动槽循环执行敌人回合：计划内动作逐个执行，局势变化时重规划。

        - 每个动作消耗卡牌 cost（出牌）或 1 AP（移动）；
        - 循环直到 action_slots 用尽、AP 耗尽或战斗结束；
        - 预告（_compute_enemy_intents）与本函数共用同一计划与同一决策规则，
          仅当控制/目标失效导致动作无法执行时才重规划。
        """
        unit = self.units[unit_id]
        intent = self.state.enemy_intents.get(unit_id, {})
        plan = list(intent.get("actions") or [])
        plan_idx = 0
        results: list[DamageResult] = []

        guard = 0
        while (unit.is_alive and not self.is_battle_over()
               and self.enemy_actions_taken.get(unit_id, 0) < unit.action_slots
               and unit.AP > 0):
            guard += 1
            if guard > 8:  # 防呆：每轮每敌人最多 8 次动作尝试
                break
            players = [u for u in self.units.values()
                       if u.team == "player" and u.is_alive]
            if not players:
                break

            ok = False
            if plan_idx < len(plan):
                ok, res = self._execute_planned_enemy_action(unit, plan[plan_idx], players)
                results.extend(res)
                plan_idx += 1
            if not ok:
                ok = self._fallback_enemy_action(unit, players)
            if not ok:
                break
            self._check_battle_end()

        return results

    def _execute_planned_enemy_action(self, unit: CombatUnit, action: dict,
                                      players: list[CombatUnit]) -> tuple[bool, list[DamageResult]]:
        """执行计划内的单个动作；成功返回 (True, 结果)，失败返回 (False, [])。"""
        if action.get("type") == "move":
            target = self._resolve_intent_target(unit, action, players)
            if target is None:
                return False, []
            step = self.step_toward(unit.pos, target.pos, mover_id=unit.unit_id)
            if self.validate_move(unit.unit_id, step):
                return False, []
            return (True, []) if self.move_unit(unit.unit_id, step) else (False, [])

        card = self._find_enemy_card(unit, action.get("card_id", ""))
        if card is None or card.cost > unit.AP:
            return False, []
        target = self._resolve_intent_target(unit, action, players)
        if target is None:
            return False, []
        self._ensure_card_in_hand(unit, card)
        results = self.play_card(unit.unit_id, card, target.pos)
        return (True, results) if results else (False, results)

    def _resolve_intent_target(self, unit: CombatUnit, action: dict,
                               players: list[CombatUnit]) -> CombatUnit | None:
        """解析计划中的目标；目标已失效时回退到距离 unit 最近的存活玩家。"""
        target_id = action.get("target_id", "")
        if target_id and target_id in self.units:
            candidate = self.units[target_id]
            if candidate.team == "player" and candidate.is_alive:
                return candidate
        if not players:
            return None
        return min(players, key=lambda p: self.distance(unit.pos, p.pos))

    def _fallback_enemy_action(self, unit: CombatUnit,
                               players: list[CombatUnit]) -> bool:
        """计划动作失效时的重规划：重新选卡，否则 aggressive 前进一格子。"""
        target = self._enemy_target(unit, players)
        card = self._pick_enemy_card(unit, target)
        if card and card.cost <= unit.AP:
            self._ensure_card_in_hand(unit, card)
            results = self.play_card(unit.unit_id, card, target.pos)
            return bool(results)
        if unit.ai_behavior != "defensive" and unit.AP >= 1:
            step = self.step_toward(unit.pos, target.pos, mover_id=unit.unit_id)
            if step != unit.pos and not self.validate_move(unit.unit_id, step):
                return self.move_unit(unit.unit_id, step)
        return False

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
        if self.state.phase == "END":
            return True

        players_alive = any(u.team == "player" and u.is_alive for u in self.units.values())
        enemies_alive = any(u.team == "enemy" and u.is_alive for u in self.units.values())

        if not enemies_alive:
            # 波次：清空当前波后还有待入场波次则继续战斗，否则胜利
            if self._spawn_next_wave():
                return False
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

    # ══════════════════════════════════════════════════════════════════════════
    #  挂起 / 恢复（战斗中途保存整局态势）
    # ══════════════════════════════════════════════════════════════════════════

    def snapshot(self) -> dict:
        """完整战斗态快照：单位、手牌、牌堆、波次、回合与敌方意图。

        与 `CombatSession.snapshot()`（结算用，只导出结算字段）区分：
        本方法导出的数据可**原样重建**引擎，用于「临时返回后继续打」。
        随机数状态（shuffle 用）不导出——恢复后重新洗牌只会影响后续抽牌顺序，
        不会改变已发到手上的牌与场上态势。
        """
        return {
            "balance_version": self.balance_version,
            "range_metric": self.range_metric,
            "corner_cut": self.corner_cut,
            "shared_ap": self.shared_ap,
            "shared_ap_max": self.SHARED_AP_MAX,
            "max_rounds": self.max_rounds,
            "escape_enabled": self.escape_enabled,
            "wave_num": self.wave_num,
            "state": {
                "round_num": self.state.round_num,
                "turn_order": list(self.state.turn_order),
                "current_idx": self.state.current_idx,
                "phase": self.state.phase,
                "winner": self.state.winner,
                "enemy_intents": copy.deepcopy(self.state.enemy_intents),
            },
            "units": {uid: u.to_dict() for uid, u in self.units.items()},
            "shared_pool": self.shared_pool.to_dict() if self.shared_pool else None,
            "enemy_pools": {uid: p.to_dict() for uid, p in self.enemy_pools.items()},
            "pending_waves": [
                [{"unit": unit.to_dict(), "pos": list(pos)} for unit, pos in wave]
                for wave in self.pending_waves
            ],
            "initial_hp": dict(self.initial_hp),
            "enemy_actions_taken": dict(self.enemy_actions_taken),
            "telemetry": copy.deepcopy(self.telemetry),
        }

    @classmethod
    def from_snapshot(cls, data: dict, battle_map: BattleMap | None = None,
                      rules: dict | None = None) -> "CombatEngine":
        """从 `snapshot()` 重建引擎（战斗挂起恢复）。

        `battle_map` / `rules` 来自节点 JSON（不随快照序列化地图，避免存档与节点
        配置双份真相）；缺省时退回默认地图。
        """
        engine = cls(battle_map=battle_map, rules=rules)
        engine.range_metric = str(data.get("range_metric") or engine.range_metric)
        engine.corner_cut = bool(data.get("corner_cut", engine.corner_cut))
        engine.balance_version = int(data.get("balance_version", cls.BALANCE_VERSION) or 1)
        engine.SHARED_AP_MAX = int(data.get("shared_ap_max", engine.SHARED_AP_MAX) or 0)
        engine.shared_ap = int(data.get("shared_ap", 0) or 0)
        engine.max_rounds = int(data.get("max_rounds", 0) or 0)
        engine.escape_enabled = bool(data.get("escape_enabled", False))
        engine.wave_num = int(data.get("wave_num", 0) or 0)

        st = data.get("state") or {}
        engine.state.round_num = int(st.get("round_num", 0) or 0)
        engine.state.turn_order = list(st.get("turn_order") or [])
        engine.state.current_idx = int(st.get("current_idx", 0) or 0)
        engine.state.phase = st.get("phase") or "INIT"
        engine.state.winner = st.get("winner") or ""
        engine.state.enemy_intents = copy.deepcopy(st.get("enemy_intents") or {})

        # 单位 + 网格占位：占位由 unit.pos 重建（阵亡单位已从网格移除，不再放回）
        for _uid, ud in (data.get("units") or {}).items():
            unit = CombatUnit.from_dict(ud)
            if not unit.unit_id:
                continue
            engine.units[unit.unit_id] = unit
            if unit.is_alive and tuple(unit.pos) != (-1, -1):
                engine.grid.place_unit(unit, tuple(unit.pos))

        if data.get("shared_pool"):
            engine.shared_pool = CardPool.from_dict(data["shared_pool"])
        engine.enemy_pools = {
            uid: CardPool.from_dict(pd) for uid, pd in (data.get("enemy_pools") or {}).items()
        }
        engine.pending_waves = [
            [(CombatUnit.from_dict(item["unit"]), tuple(item["pos"])) for item in wave]
            for wave in (data.get("pending_waves") or [])
        ]
        engine.initial_hp = {k: int(v) for k, v in (data.get("initial_hp") or {}).items()}
        engine.enemy_actions_taken = {
            k: int(v) for k, v in (data.get("enemy_actions_taken") or {}).items()
        }
        telemetry = data.get("telemetry")
        if isinstance(telemetry, dict):
            engine.telemetry = {
                "rounds": telemetry.get("rounds") or {},
                "totals": telemetry.get("totals") or cls._empty_metrics(),
            }
        return engine
