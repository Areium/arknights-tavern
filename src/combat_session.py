"""
CombatSession — server-side wrapper around CombatEngine.

Manages a single battle's lifecycle: setup → player actions → enemy AI → events.
Integrates with the project's Session system and SSE event streaming.
"""

import queue
import logging
import os
import sys
import time
import random

# Ensure project root and src/ are importable
_src_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_src_dir)
for _p in (_src_dir, _project_root):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from combat_engine.entity import CombatUnit
from combat_engine.card import Card
from combat_engine.card_data import get_starting_deck
from combat_engine.engine import CombatEngine, CombatEvent
from combat_data_loader import CombatDataLoader

logger = logging.getLogger(__name__)


def _tile_used(battle_map, tile_id: str) -> bool:
    """只导出实际出现在地图上的格子定义（减少 DTO 体积）。"""
    return any(tile_id in row for row in battle_map.tiles)


class CombatSession:
    """Server-side combat session wrapping a CombatEngine instance."""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.engine: CombatEngine | None = None
        self.loader = CombatDataLoader()
        self.event_queue: queue.Queue[CombatEvent] = queue.Queue()
        self._character_metas: list[dict] = []
        self._encounter_id: str = ""
        self._background_url: str | None = None
        self._session_dir: str = ""
        self._inventory: list[dict] = []
        self._reward_mult: float = 1.0
        self._enemy_scale: float = 1.0
        self._map = None                     # BattleMap（节点 JSON 的地图段）
        self._custom_enemies: dict = {}      # 会话自定义敌人定义
        self.last_activity_at: float = time.time()

    # ── Setup ──

    def start(self, encounter_id: str,
              character_names: list[str] = None,
              character_metas: list[dict] = None,
              enemies_override: list[dict] = None,
              combat_params: dict = None,
              location: str = "",
              session_dir: str = "",
              inventory: list[dict] = None,
              reward_mult: float = 1.0,
              bonus_cards: list[dict] = None,
              custom_enemies: dict | None = None) -> dict:
        """Initialize a battle from a battle node definition and character list.

        Args:
            encounter_id: 战斗节点 id（`data/combat/nodes/<id>.json`，也接受中文名）
            character_names: List of character names to load from data/characters/
            character_metas: List of character metadata dicts (takes precedence over names)
            enemies_override: Optional list of {name, count, positions, stats} dicts.
                              When provided, replaces node waves（单波）。
            custom_enemies: 会话内自定义敌人定义（name → meta），优先于全局敌人库
            combat_params: Optional dict with narrative-driven combat modifiers.
            location: Current narrative location name, used to resolve the
                      combat background when the node doesn't specify one.
            session_dir: Owning session's data directory; its backgrounds/
                      subfolder can override global background images.

        Returns:
            dict: Initial combat state snapshot.
        """
        node = self.loader.load_node(encounter_id)
        if not node:
            raise ValueError(f"战斗节点不存在: {encounter_id}")

        self._encounter_id = encounter_id
        self._session_dir = session_dir
        self._inventory = inventory or []
        self._reward_mult = reward_mult
        self._enemy_scale = float((combat_params or {}).get("enemy_scale", 1.0) or 1.0)
        self._custom_enemies = dict(custom_enemies or {})
        self._background_url = self.loader.resolve_background(
            node, location, session_dir=session_dir, session_id=self.session_id)

        # ── 战场：节点 JSON 的地图段（尺寸/地形/部署区）──
        self._map = self.loader.load_map(node)          # 校验失败抛 MapError
        self.engine = CombatEngine(battle_map=self._map,
                                   rules=self.loader.rules_of(node))

        # 节点 conditions：回合上限 + 是否允许撤退（难度曲线 / fail-forward）
        conditions = node.get("conditions", {}) or {}
        self.engine.max_rounds = int(conditions.get("max_rounds", 0) or 0)
        self.engine.escape_enabled = bool(conditions.get("escape_enabled", False))

        # Events flow through _flush_engine_events() only — no on_event callback
        # to avoid double-queuing when both the callback and flush fire.

        # ── Load player characters ──
        if character_metas:
            self._character_metas = character_metas
        elif character_names:
            self._character_metas = []
            for name in character_names:
                meta = self._load_character_meta(name)
                if meta:
                    self._character_metas.append(meta)

        player_slots = self._player_slots(len(self._character_metas))

        for i, meta in enumerate(self._character_metas):
            unit = CombatUnit.from_character_metadata(meta, team="player")
            char_class = unit.char_class

            # Apply narrative-driven status effects
            if combat_params:
                self._apply_status_effects(unit, combat_params)

            # Load cards: use the class engine pool. Character-specific cards in
            # combat.json are narrative cards (0 damage / narrative SP cost), not
            # combat-engine cards — they belong to the story layer, not the engine.
            cards = get_starting_deck(char_class, count=7)
            if not cards:
                cards = get_starting_deck("辅助", count=7)
                logger.warning("No card pool for class '%s', using 辅助 fallback", char_class)

            self.engine.add_player_unit(unit, cards, player_slots[i])

        # ── 持久化卡组奖励卡（战后 1 选 1 获得）──
        if bonus_cards and self.engine.shared_pool:
            player_units = [u for u in self.engine.units.values()
                            if u.team == "player"]
            for bcard in bonus_cards:
                try:
                    card = Card.from_dict(bcard)
                except Exception:
                    logger.warning("奖励卡解析失败，跳过: %s", bcard)
                    continue
                # 按 class_required 匹配小队角色作为 owner；无匹配则用第一个角色
                owner = next((u.name for u in player_units
                              if u.char_class == card.class_required), None)
                if owner is None and player_units:
                    owner = player_units[0].name
                card.owner = owner
                self.engine.shared_pool.deck.append(card)

        # ── Load enemies（按波次预构建，wave 0 立即入场，其余按波触发）──
        if enemies_override:
            wave_defs_list = [enemies_override]
        else:
            wave_defs_list = [w.get("enemies", []) for w in node.get("waves", [])]
            if not wave_defs_list:
                wave_defs_list = [[]]

        all_waves: list[list[tuple[CombatUnit, tuple[int, int]]]] = []
        enemy_seq = 0
        reserved: set[tuple[int, int]] = set()
        for wave_defs in wave_defs_list:
            wave_units: list[tuple[CombatUnit, tuple[int, int]]] = []
            for enemy_def in wave_defs:
                enemy_name = enemy_def.get("enemy", enemy_def.get("name", ""))
                count = int(enemy_def.get("count", 1) or 1)
                if not enemies_override:
                    count = max(1, round(count * self._enemy_scale))
                positions = list(enemy_def.get("positions") or [])
                stats = enemy_def.get("stats") or enemy_def.get("combat_stats")

                for j in range(count):
                    enemy_unit = self._load_enemy(enemy_name, stats)
                    if not enemy_unit:
                        logger.warning("Enemy '%s' not found, skipping", enemy_name)
                        continue

                    # 唯一 unit_id（同名 count>1 或跨波次重复都不冲突）
                    enemy_seq += 1
                    if count > 1 or len(wave_defs_list) > 1:
                        enemy_unit.unit_id = f"{enemy_name}#{enemy_seq}"

                    pos = self._enemy_slot(positions, j, reserved)
                    if pos is None:
                        logger.warning("敌人 %s 无可落脚点，跳过", enemy_unit.name)
                        continue
                    reserved.add(pos)
                    wave_units.append((enemy_unit, pos))
            all_waves.append(wave_units)

        if not any(all_waves):
            from combat_nodes import NodeError
            raise NodeError(
                f"战斗节点「{node.get('name', encounter_id)}」没有可出场的敌人："
                "请先在编辑器中配置波次")

        # 波次交给引擎管理：wave 0 立即入场，其余进 pending_waves
        self.engine.load_waves(all_waves)

        # Start the state machine
        self.engine.start_battle()

        # 首回合先手：打法 first_strike → 共享 AP +1（仅第 1 回合）
        if combat_params and combat_params.get("first_strike"):
            self.engine.shared_ap += 1

        # Flush initial events into the queue
        self._flush_engine_events()

        return self.get_state()

    # ── 落点选择（部署区优先，容错兜底）──

    def _player_slots(self, count: int) -> list[tuple[int, int]]:
        """玩家落点：优先玩家部署区（按行列顺序），不够时扩展到全图空格。"""
        grid = self.engine.grid
        slots = grid.free_deploy_cells("player")
        if len(slots) < count:
            taken = set(slots)
            for r in range(grid.rows):
                for c in range(grid.cols):
                    pos = (r, c)
                    if pos in taken or not grid.can_place(pos):
                        continue
                    slots.append(pos)
                    taken.add(pos)
                    if len(slots) >= count:
                        break
                if len(slots) >= count:
                    break
        if len(slots) < count:
            raise ValueError(f"战场容不下 {count} 名玩家单位（可落脚格不足）")
        return slots[:count]

    def _enemy_slot(self, positions: list, index: int,
                    reserved: set[tuple[int, int]]) -> tuple[int, int] | None:
        """敌人落点：节点声明优先（需可落脚），否则在敌人部署区取空格。"""
        grid = self.engine.grid
        if index < len(positions):
            try:
                pos = tuple(int(v) for v in positions[index])
            except (TypeError, ValueError):
                pos = None
            if pos and pos not in reserved and grid.can_place(pos):
                return pos
        cells = [p for p in grid.free_deploy_cells("enemy") if p not in reserved]
        if not cells:
            cells = [(r, c) for r in range(grid.rows) for c in range(grid.cols)
                     if grid.can_place((r, c)) and (r, c) not in reserved]
        if not cells:
            return None
        return random.choice(cells) if self._map and self._map.enemy_random_shift else cells[0]

    def _load_enemy(self, name: str, stats: dict | None) -> CombatUnit | None:
        """加载敌人：会话自定义定义优先，其次全局敌人库；stats 为逐实例覆盖。"""
        custom = self._custom_enemies.get(name)
        if custom:
            unit = CombatDataLoader.load_enemy_from_meta(custom, stat_overrides=stats)
            if unit:
                unit.name = name
                return unit
        return self.loader.load_enemy(name, stat_overrides=stats)

    def _load_character_meta(self, name: str) -> dict | None:
        """Load a character's YAML frontmatter from data/characters/<name>/index.md."""
        import frontmatter
        from pathlib import Path
        project_root = Path(__file__).resolve().parent.parent
        path = project_root / "data" / "characters" / name / "index.md"
        if not path.exists():
            logger.warning("Character file not found: %s", path)
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return frontmatter.load(f).metadata
        except Exception as e:
            logger.error("Failed to load character %s: %s", name, e)
            return None

    @staticmethod
    def _clamp_penalty(value: float) -> float:
        """Clamp a penalty value to [0, 1). Values > 1 are treated as percentages."""
        if value >= 1:
            value = value / 100.0
        return max(0.0, min(value, 0.99))

    @staticmethod
    def _clamp_bonus(value: float) -> float:
        """Clamp a bonus value to [-1, 5]."""
        return max(-1.0, min(value, 5.0))

    def _apply_status_effects(self, unit, combat_params: dict) -> None:
        """Apply narrative-driven status effects to a combat unit."""
        status_effects = combat_params.get("status_effects", {})
        if not status_effects:
            return

        unit_name = unit.name
        if unit_name not in status_effects:
            return

        effects = status_effects[unit_name]
        if not isinstance(effects, dict):
            return

        hp_penalty = effects.get("hp_penalty")
        if hp_penalty is not None:
            penalty = self._clamp_penalty(float(hp_penalty))
            new_hp = max(1, int(unit.hp * (1 - penalty)))
            logger.info("Combat status: %s hp_penalty=%.2f, HP %d → %d",
                        unit_name, penalty, unit.hp, new_hp)
            unit.max_hp = max(1, int(unit.max_hp * (1 - penalty)))
            unit.hp = new_hp

        atk_bonus = effects.get("atk_bonus")
        if atk_bonus is not None:
            bonus = self._clamp_bonus(float(atk_bonus))
            unit.PATK = max(0, int(unit.PATK * (1 + bonus)))
            unit.MATK = max(0, int(unit.MATK * (1 + bonus)))
            logger.info("Combat status: %s atk_bonus=%.2f, PATK=%.0f MATK=%.0f",
                        unit_name, bonus, unit.PATK, unit.MATK)

        def_penalty = effects.get("def_penalty")
        if def_penalty is not None:
            penalty = self._clamp_penalty(float(def_penalty))
            unit.DEF = max(0, int(unit.DEF * (1 - penalty)))
            logger.info("Combat status: %s def_penalty=%.2f, DEF=%d",
                        unit_name, penalty, unit.DEF)

    # ── Event handling ──

    def _enqueue_event(self, ev: CombatEvent) -> None:
        """Forward engine events into the SSE queue."""
        self.event_queue.put(ev)

    def _flush_engine_events(self) -> None:
        """Move events from engine state into the SSE queue (for init events)."""
        if self.engine:
            for ev in self.engine.state.events:
                self.event_queue.put(ev)
            self.engine.state.events.clear()

    # ── Player actions ──

    def handle_action(self, action: dict) -> dict:
        """Execute a player action and return updated state.

        Args:
            action: {
                "action": "play_card" | "move",
                "card_index": int (for play_card),
                "unit_id": str (for move),
                "target": [row, col]
            }

        Returns:
            dict with keys: "ok", "events" (list), "state" (full snapshot)
        """
        if not self.engine:
            return {"ok": False, "error": "No active battle"}

        if self.engine.is_battle_over():
            return {"ok": False, "error": "Battle is over"}

        if self.engine.state.phase != "PLAYER_TURN":
            return {"ok": False, "error": "Not player turn"}

        action_type = action.get("action", "")
        target = tuple(action.get("target", [0, 0]))

        try:
            if action_type == "play_card":
                card_index = action.get("card_index", 0)
                hand = self.engine.shared_pool.hand if self.engine.shared_pool else []
                if card_index < 0 or card_index >= len(hand):
                    return {"ok": False, "error": f"Invalid card index: {card_index}"}

                card = hand[card_index]

                # Find the unit that owns this card
                owner_unit = None
                for u in self.engine.units.values():
                    if u.team == "player" and u.is_alive and u.name == card.owner:
                        owner_unit = u
                        break
                if not owner_unit:
                    return {"ok": False, "error": f"Card owner '{card.owner}' not found or not alive"}

                # 职业限制校验（卡牌 class_required 与 owner 职业不符时拒绝）
                if card.class_required not in ("any", "", None) and \
                        card.class_required != owner_unit.char_class:
                    return {"ok": False,
                            "error": f"{owner_unit.name} 的职业无法使用 '{card.name}'"}

                # AP 校验：出牌先耗 owner 个人 AP，不足部分以共享 AP 补足（与引擎一致）
                total_available = owner_unit.AP + self.engine.shared_ap
                if card.cost > total_available:
                    return {"ok": False,
                            "error": f"AP 不足 (个人 {owner_unit.AP} + 共享 {self.engine.shared_ap} < {card.cost})"}

                # For auto-target cards, use caster position
                if card.target in ("SELF", "ALL_ALLIES", "GLOBAL"):
                    target = owner_unit.pos

                self.engine.play_card(owner_unit.unit_id, card, target)
                self.engine._check_battle_end()
                self._flush_engine_events()

            elif action_type == "move":
                unit_id = action.get("unit_id", "")
                unit = self.engine.units.get(unit_id)
                if not unit or unit.team != "player" or not unit.is_alive:
                    return {"ok": False, "error": "Invalid unit for move"}

                if self.engine.move_unit(unit_id, target):
                    self._flush_engine_events()
                else:
                    return {"ok": False, "error": "Invalid move target"}

            elif action_type == "escape":
                if not self.engine.escape():
                    return {"ok": False, "error": "本场战斗无法撤退"}
                self._flush_engine_events()

            else:
                return {"ok": False, "error": f"Unknown action: {action_type}"}

        except Exception as e:
            logger.exception("Error executing action")
            return {"ok": False, "error": str(e)}

        self.last_activity_at = time.time()
        return {"ok": True, "state": self.get_state()}

    def end_turn(self) -> dict:
        """End the player's round: execute enemy phase, draw new hand."""
        if not self.engine:
            return {"ok": False, "error": "No active battle"}

        if self.engine.is_battle_over():
            return {"ok": False, "error": "Battle is over"}

        self.engine.end_player_round()
        self._flush_engine_events()
        self.last_activity_at = time.time()

        return {"ok": True, "state": self.get_state()}

    def use_item(self, item_name: str, target_id: str) -> dict:
        """Use a consumable item on a target unit (heal/buff)."""
        if not self.engine:
            return {"ok": False, "error": "No active battle"}
        if self.engine.is_battle_over():
            return {"ok": False, "error": "Battle is over"}
        if self.engine.state.phase != "PLAYER_TURN":
            return {"ok": False, "error": "Not player turn"}

        meta = self.loader.load_item_meta(item_name)
        if not meta:
            return {"ok": False, "error": f"物品 '{item_name}' 不存在"}
        effect = meta.get("combat_effect") or {}
        if not effect:
            return {"ok": False, "error": f"物品 '{item_name}' 无法在战斗中使用"}

        target = self.engine.units.get(target_id)
        if not target or not target.is_alive:
            return {"ok": False, "error": "目标无效"}
        # 消耗品只能作用于我方干员（不能给敌方回血/加护盾）
        if target.team != "player":
            return {"ok": False, "error": "物品只能对我方干员使用"}

        # 使用物品消耗 1 点共享 AP
        if self.engine.shared_ap < 1:
            return {"ok": False, "error": "共享 AP 不足，无法使用物品"}

        effect_type = effect.get("type")
        if effect_type == "heal":
            amount = int(effect.get("amount", 0))
            healed = target.heal(amount)
            self.engine.shared_ap -= 1
            self._enqueue_event(CombatEvent(
                "heal", data={"unit_id": target_id, "caster": "物品", "target_id": target_id,
                              "target": target.name, "amount": healed, "card": item_name,
                              "target_pos": list(target.pos)}))
        elif effect_type == "buff":
            # 增益效果暂未实装（buff/debuff 运行时后置）
            return {"ok": False, "error": "增益类物品暂未实装"}
        else:
            return {"ok": False, "error": f"未知效果类型 '{effect_type}'"}

        # 消耗战斗内 inventory 快照
        for entry in self._inventory:
            if entry.get("name") == item_name:
                entry["count"] = int(entry.get("count", 1)) - 1
                if entry["count"] <= 0:
                    self._inventory.remove(entry)
                break

        self.last_activity_at = time.time()
        return {"ok": True, "state": self.get_state()}

    # ── State queries ──

    @staticmethod
    def _refresh_skin_crop(u) -> dict | None:
        """Re-read skin crop from disk for player units so asset edits take effect."""
        if u.team != "player":
            return u.skin_crop
        try:
            from avatar_color import get_card_face_crop
            fresh = get_card_face_crop(u.name)
            if fresh is not None:
                u.skin_crop = fresh
                return fresh
        except Exception:
            pass
        return u.skin_crop

    def get_state(self, selected_unit_id: str = "") -> dict:
        """Return a full state snapshot for the frontend.

        `selected_unit_id` 非空时，`valid_moves` 为该单位的可达格（曼哈顿代价）。
        """
        if not self.engine:
            return {"phase": "NONE", "error": "No active battle"}

        e = self.engine

        units = []
        for u in e.units.values():
            units.append({
                "unit_id": u.unit_id,
                "name": u.name,
                "team": u.team,
                "char_class": u.char_class,
                "hp": u.hp,
                "max_hp": u.max_hp,
                "personal_ap": u.AP,
                "max_personal_ap": u.MAX_AP,
                "patk": u.PATK,
                "matk": u.MATK,
                "def": u.DEF,
                "res": u.RES,
                "spd": u.SPD,
                "hit": u.HIT,
                "eva": u.EVA,
                "mobility": u.mobility,
                "pos": list(u.pos),
                "is_alive": u.is_alive,
                "attributes": dict(u.attributes) if u.attributes else {},
                "status": dict(u.status),
                "skin_url": u.skin_url,
                "skin_crop": self._refresh_skin_crop(u),
                "action_slots": u.action_slots,
                "power_tier": u.power_tier,
                "role": u.role,
                "threat_points": u.threat_points,
            })

        # Shared hand — always available from shared pool
        shared_hand = []
        if e.shared_pool:
            for card in e.shared_pool.hand:
                shared_hand.append(card.to_dict())

        # Shared card pool data (deck, discard, exhaust)
        shared_pool_data = e.shared_pool.to_dict() if e.shared_pool else {}

        # Per-player hand breakdown for character selection UI
        player_hands: dict[str, list[dict]] = {}
        if e.shared_pool:
            for u in e.units.values():
                if u.team == "player" and u.is_alive:
                    player_hands[u.unit_id] = [
                        c.to_dict() for c in e.shared_pool.hand
                        if c.owner == u.name
                    ]

        # Valid targets for targeting mode
        valid_targets = self._compute_valid_targets()

        # 选中单位的可达格（曼哈顿代价 + 地形 + 占位，服务端权威计算）
        active_player_id = next((u.unit_id for u in e.units.values()
                                 if u.team == "player" and u.is_alive), None)
        move_for = selected_unit_id or active_player_id or ""
        valid_moves = self._compute_valid_moves(move_for)

        # Grid (positions only)
        grid_cells = {}
        for pos_key, unit in e.grid._cells.items():
            grid_cells[f"{pos_key[0]},{pos_key[1]}"] = unit.unit_id

        battle_map = self._map or e.map

        return {
            "round_num": e.state.round_num,
            "phase": e.state.phase,
            "winner": e.state.winner or None,
            "rows": battle_map.rows,
            "cols": battle_map.cols,
            "tiles": [list(row) for row in battle_map.tiles],
            "tile_defs": {tid: tt.to_dict() for tid, tt in battle_map.tile_types.items()
                          if _tile_used(battle_map, tid)},
            "deploy": {
                "player": [list(p) for p in battle_map.deploy_player],
                "enemy": [list(p) for p in battle_map.deploy_enemy],
            },
            "map_warnings": list(battle_map.warnings),
            "range_metric": e.range_metric,
            "background_url": self._background_url,
            "shared_ap": e.shared_ap,
            "shared_ap_max": e.SHARED_AP_MAX,
            "balance_version": getattr(e, "balance_version", 0),
            "max_rounds": e.max_rounds,
            "escape_enabled": e.escape_enabled,
            "wave_num": e.wave_num,
            "pending_waves": len(e.pending_waves),
            "units": units,
            "shared_hand": shared_hand,
            "player_hands": player_hands,
            "shared_pool": {"deck": shared_pool_data.get("deck", []),
                           "discard": shared_pool_data.get("discard", []),
                           "exhaust": shared_pool_data.get("exhaust", [])},
            "valid_targets": valid_targets,
            "valid_moves": valid_moves,
            "valid_moves_unit": move_for or None,
            "active_unit_id": active_player_id,
            "grid": grid_cells,
            "enemy_intents": dict(getattr(e.state, "enemy_intents", {}) or {}),
            "battle_over": e.is_battle_over(),
            "inventory": self._inventory,
        }

    def _compute_valid_moves(self, unit_id: str) -> list[list[int]]:
        """选中单位的可达格（Dijkstra，曼哈顿代价；非玩家回合返回空）。"""
        if not self.engine or self.engine.state.phase != "PLAYER_TURN":
            return []
        unit = self.engine.units.get(unit_id) if unit_id else None
        if not unit or unit.team != "player" or not unit.is_alive:
            return []
        if unit.AP < 1 or unit.status_amount("bind") > 0:
            return []
        reachable = self.engine.grid.reachable(unit.pos,
                                              self.engine.move_budget(unit),
                                              mover_id=unit.unit_id)
        return [list(pos) for pos in sorted(reachable)]

    def _compute_valid_targets(self) -> list[list[int]]:
        """Compute valid target positions (all alive enemies) during player phase."""
        if not self.engine:
            return []
        if self.engine.state.phase != "PLAYER_TURN":
            return []

        targets = []
        enemies = [u for u in self.engine.units.values()
                    if u.team == "enemy" and u.is_alive]
        for enemy in enemies:
            targets.append(list(enemy.pos))
        return targets

    # ── 结算快照 ──

    def snapshot(self) -> dict:
        """结算与历史记录所需的战斗快照。

        战斗态只存在于内存（`session.combat`），不跨进程保存，因此这里只导出
        结算要用的字段，不再提供状态重建入口。若将来需要"战斗中恢复"，
        应以「节点 spec + 命令流重放」实现，而不是回填状态序列化。
        """
        if not self.engine:
            return {"active": False}

        return {
            "active": True,
            "encounter_id": self._encounter_id,
            "session_id": self.session_id,
            "reward_mult": self._reward_mult,
            "enemy_scale": self._enemy_scale,
            "max_rounds": self.engine.max_rounds,
            "escape_enabled": self.engine.escape_enabled,
            "engine_state": {
                "round_num": self.engine.state.round_num,
                "phase": self.engine.state.phase,
                "winner": self.engine.state.winner,
                "turn_order": self.engine.state.turn_order,
                "current_idx": self.engine.state.current_idx,
                "enemy_intents": getattr(self.engine.state, "enemy_intents", {}) or {},
            },
            "units": {uid: u.to_dict() for uid, u in self.engine.units.items()},
            "character_metas": self._character_metas,
        }


class CombatTestSessionManager:
    """管理无会话战斗测试的生命周期，替代 app.py 中的 _test_combats 全局 dict。"""

    def __init__(self):
        self._sessions: dict[str, CombatSession] = {}

    def create(self, test_id: str, combat: CombatSession) -> None:
        self._sessions[test_id] = combat

    def get(self, test_id: str) -> CombatSession | None:
        return self._sessions.get(test_id)

    def remove(self, test_id: str) -> None:
        self._sessions.pop(test_id, None)

    @property
    def count(self) -> int:
        return len(self._sessions)
