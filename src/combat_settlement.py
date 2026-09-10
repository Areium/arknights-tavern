"""
combat_settlement — 战斗结算：数值计算 / 结算数据组装 / 写回会话存档。

设计要点（详见 docs/combat-design.md §10）：

- **单一数据源**：结算读写的是剧情系统的会话覆盖层 `session.overlay`
  （`data/memory/sessions/{mode}/{session_id}/overrides.json` 的
  `characters[<名>].progress` 与 `characters[<名>].metadata.attributes`）。
  本模块不新建任何独立战斗数值副本；写回后剧情侧
  （`SceneManager` / `CharacterAgent` / 场景面板）读到即为更新后的数值。
- **经验公式（沿用现有规则）**：
  `XP = (遭遇 rewards.xp + Σ 敌人 xp_reward) × approach.reward_mult`，
  升级阈值 `level × 100`（升级时扣除阈值，故经验溢出可连续升级），
  每次升级 `+1` 当前最低且未满值的战斗属性（属性上限 10）。
- **计算与展示分离**：`compute_*` / `build_settlement` 为纯计算，返回可直接渲染的 DTO；
  `apply_settlement` 负责调用剧情侧存档接口写回，二者独立可测。
- **写回幂等**：待结算记录持久化在 `overrides.json.pending_settlement`，
  逐角色 / 逐奖励标记 `applied`，写入失败后重试不会重复发放。
"""

from __future__ import annotations

import logging
import time
import uuid
import random

logger = logging.getLogger(__name__)

# ── 成长规则常量（沿用项目现有规则） ──

# 参与战斗数值派生的 7 维属性（「魅力」为叙事属性，仅当其余全满时才提升）
BATTLE_ATTRS = ["物理强度", "战场机动", "生理耐受", "战术规划",
                "战斗技巧", "源石技艺适应性", "情绪稳定性"]

# 叙事属性：7 维全满后的溢出提升目标
CHARISMA_ATTR = "魅力"

# 属性满值上限（与 combat_engine.entity / wiki_manager 的 1-10 标度一致）
ATTR_CAP = 10

# 升级阈值系数：升到下一级所需经验 = level × XP_PER_LEVEL
XP_PER_LEVEL = 100

# 属性缺省值（与 combat_engine.entity._DEFAULT_ATTR 一致）
DEFAULT_ATTR = 5

# 硬等级上限：项目未定义 → 默认 None，成长上限由「7 维 + 魅力全部满值」决定。
# 若需要硬性等级上限，把这里改成整数即可（例如 30）。
MAX_LEVEL: int | None = None

# 阵亡角色是否获得经验：项目现有行为是「出阵即获得」（_apply_progression 不区分存活），
# 这里保持同一规则并显式化，便于后续调整。
XP_FOR_DEAD_CHARACTERS = True

# 战斗历史保留条数（与既有实现一致）
MAX_HISTORY = 20

# 未接入的奖励字段（遭遇 frontmatter 已声明但引擎未消费）——结算面板会提示
UNWIRED_REWARD_KEYS = ("unlock",)


# ── 纯计算：等级 / 经验 / 属性 ──

def xp_needed(level: int) -> int:
    """升到下一级所需经验：level × 100（现有规则）。"""
    return max(1, int(level or 1)) * XP_PER_LEVEL


def pick_growth_attribute(attrs: dict) -> str | None:
    """选本次升级提升的属性：最低且未满值的战斗属性；全满时尝试「魅力」。

    返回 None 表示所有属性均已满值（成长封顶）。
    """
    candidates = [(k, int(attrs.get(k, DEFAULT_ATTR) or DEFAULT_ATTR))
                  for k in BATTLE_ATTRS
                  if int(attrs.get(k, DEFAULT_ATTR) or DEFAULT_ATTR) < ATTR_CAP]
    if not candidates:
        charisma = int(attrs.get(CHARISMA_ATTR, DEFAULT_ATTR) or DEFAULT_ATTR)
        return CHARISMA_ATTR if charisma < ATTR_CAP else None
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


def compute_character_growth(name: str, attrs: dict, progress: dict, xp_gain: int,
                             *, in_battle: bool = True, alive: bool = True) -> dict:
    """纯函数：计算单个角色的结算结果（不写任何存档）。

    Args:
        name: 角色名
        attrs: 角色当前属性（模板 + 会话覆盖合并后的结果）
        progress: 角色当前成长进度 {"level": int, "xp": int}
        xp_gain: 本次获得的经验
        in_battle: 是否出阵
        alive: 战斗结束时是否存活

    Returns:
        结算条目 DTO（见模块 docstring），含 level_before/after、属性变化、封顶标记。
    """
    level_before = max(1, int(progress.get("level", 1) or 1))
    xp_before = max(0, int(progress.get("xp", 0) or 0))
    gain = int(xp_gain or 0)

    current = {k: int(v or 0) for k, v in (attrs or {}).items()}
    level_after = level_before
    xp_after = xp_before + gain

    level_ups: list[dict] = []
    raised: dict[str, int] = {}
    capped = False
    cap_reason = ""

    while True:
        need = xp_needed(level_after)
        if xp_after < need:
            break
        if MAX_LEVEL is not None and level_after >= MAX_LEVEL:
            capped = True
            cap_reason = f"已达等级上限 Lv.{MAX_LEVEL}"
            break
        attr_name = pick_growth_attribute(current)
        if attr_name is None:
            capped = True
            cap_reason = "所有属性均已满值（10），无法继续成长"
            break
        xp_after -= need
        level_after += 1
        current[attr_name] = min(ATTR_CAP, int(current.get(attr_name, DEFAULT_ATTR) or DEFAULT_ATTR) + 1)
        raised[attr_name] = current[attr_name]
        level_ups.append({
            "level": level_after,
            "attribute": attr_name,
            "value": current[attr_name],
            "delta": 1,
        })

    # 封顶时经验不再无意义累积：停在当前等级的满条位置
    if capped:
        xp_after = min(xp_after, xp_needed(level_after))

    attribute_changes = [
        {
            "name": attr,
            "before": int((attrs or {}).get(attr, DEFAULT_ATTR) or DEFAULT_ATTR),
            "after": value,
            "delta": value - int((attrs or {}).get(attr, DEFAULT_ATTR) or DEFAULT_ATTR),
        }
        for attr, value in raised.items()
    ]

    return {
        "name": name,
        "in_battle": bool(in_battle),
        "alive": bool(alive),
        "xp_gained": gain,
        "level_before": level_before,
        "level_after": level_after,
        "level_delta": level_after - level_before,
        "xp_before": xp_before,
        "xp_after": xp_after,
        "xp_needed_before": xp_needed(level_before),
        "xp_needed": xp_needed(level_after),
        "level_ups": level_ups,
        "attribute_changes": attribute_changes,
        "capped": capped,
        "cap_reason": cap_reason,
    }


def build_writeback_payload(character: dict) -> dict:
    """由结算条目推导写回存档的 payload（仅包含发生变化的字段）。"""
    payload: dict = {
        "progress": {
            "level": int(character.get("level_after", 1)),
            "xp": int(character.get("xp_after", 0)),
        }
    }
    changes = character.get("attribute_changes") or []
    if changes:
        payload["metadata"] = {
            "attributes": {c["name"]: int(c["after"]) for c in changes}
        }
    return payload


# ── 纯计算：奖励 roll ──

def roll_rewards(encounter: dict, enemy_units: list[dict], reward_mult: float = 1.0,
                 loader=None) -> dict:
    """计算遭遇战奖励：XP + 掉落物品（现有规则，随机 roll 只在此处发生一次）。

    Args:
        encounter: 遭遇数据（含 rewards.xp / rewards.items）
        enemy_units: 敌方单位列表，元素需含 "name"
        reward_mult: 打法奖励倍率
        loader: CombatDataLoader 实例（便于测试注入）
    """
    if loader is None:
        from combat_data_loader import CombatDataLoader
        loader = CombatDataLoader()

    rewards_cfg = (encounter or {}).get("rewards", {}) or {}
    xp = int(rewards_cfg.get("xp", 0) or 0)
    items = list(rewards_cfg.get("items", []) or [])
    enemy_xp = 0

    for unit in enemy_units or []:
        meta = loader.load_enemy_meta(unit.get("name", ""))
        if not meta:
            continue
        enemy_xp += int(meta.get("xp_reward", 0) or 0)
        if random.random() < float(meta.get("drop_rate", 0) or 0):
            items.extend(meta.get("drop_items", []) or [])

    xp = int((xp + enemy_xp) * float(reward_mult or 0.0))
    return {"xp": xp, "items": items, "enemy_xp": enemy_xp}


def aggregate_items(items: list[str]) -> list[dict]:
    """把掉落物品列表聚合为 [{name, count}]（保持首次出现顺序）。"""
    counts: dict[str, int] = {}
    order: list[str] = []
    for name in items or []:
        if name not in counts:
            counts[name] = 0
            order.append(name)
        counts[name] += 1
    return [{"name": n, "count": counts[n]} for n in order]


# ── 战后卡牌奖励（1 选 1） ──

def squad_card_pool(character_metas: list[dict]) -> list[dict]:
    """聚合小队各职业的卡池（去重）。"""
    from combat_engine.card_data import get_cards_for_class
    seen: set[str] = set()
    cards: list[dict] = []
    for meta in character_metas or []:
        for card in get_cards_for_class(meta.get("class", "")):
            if card.card_id not in seen:
                seen.add(card.card_id)
                cards.append(card.to_dict())
    return cards


def generate_card_choices(session, character_metas: list[dict], count: int = 3) -> list[dict]:
    """战后 1 选 1：从小队卡池随机抽 count 张（排除已拥有的卡）。"""
    owned = {c.get("card_id") for c in session.overlay._data.get("combat_deck", [])}
    pool = [c for c in squad_card_pool(character_metas) if c.get("card_id") not in owned]
    if not pool:
        return []
    random.shuffle(pool)
    return pool[:count]


# ── 结算数据组装 ──

def build_settlement(session, combat_data: dict, reward_mult: float = 1.0,
                     loader=None) -> dict:
    """组装完整结算 DTO（含每个参战角色的经验/升级/属性变化/进度）。

    该函数是**纯读取**：只读 overlay 与战斗快照，不写任何存档。
    """
    if loader is None:
        from combat_data_loader import CombatDataLoader
        loader = CombatDataLoader()

    encounter_id = combat_data.get("encounter_id", "") or ""
    encounter = loader.load_encounter(encounter_id) or {}
    engine_state = combat_data.get("engine_state", {}) or {}
    winner = engine_state.get("winner", "") or combat_data.get("winner", "") or ""
    rounds = int(engine_state.get("round_num", 0) or 0)

    units = combat_data.get("units", {}) or {}
    enemy_units = [u for u in units.values() if u.get("team") == "enemy"]
    player_alive: dict[str, bool] = {}
    for u in units.values():
        if u.get("team") == "player":
            player_alive[u.get("name", "")] = bool(u.get("is_alive", True))

    victory = winner == "player"
    rolled = roll_rewards(encounter, enemy_units, reward_mult, loader=loader) if victory \
        else {"xp": 0, "items": [], "enemy_xp": 0}
    items = rolled["items"]
    xp_total = rolled["xp"]

    character_metas = combat_data.get("character_metas", []) or []
    characters: list[dict] = []
    for meta in character_metas:
        name = meta.get("name", "")
        if not name:
            continue
        overrides = session.overlay.get_character_overrides(name) or {}
        progress = overrides.get("progress", {}) or {}

        # 当前属性 = 模板 attributes + 已存档覆盖（与 build_character_metas 同源）
        attrs = dict(meta.get("attributes", {}) or {})
        ov_attrs = ((overrides.get("metadata", {}) or {}).get("attributes", {})) or {}
        for k, v in ov_attrs.items():
            attrs[k] = v

        alive = player_alive.get(name, True)
        xp_gain = xp_total
        if not XP_FOR_DEAD_CHARACTERS and not alive:
            xp_gain = 0

        characters.append(compute_character_growth(
            name, attrs, progress, xp_gain, in_battle=True, alive=alive))

    cards = generate_card_choices(session, character_metas) if victory else []

    has_reward = bool(
        xp_total > 0 or items
        or any(c["level_delta"] > 0 for c in characters)
        or cards
    )
    empty_message = None
    if not has_reward:
        empty_message = ("本次战斗未获得经验与奖励"
                         if victory else "战斗未获胜，没有经验与奖励")

    return {
        "settlement_id": uuid.uuid4().hex[:12],
        "encounter_id": encounter_id,
        "encounter_name": encounter.get("name", encounter_id),
        "winner": winner,
        "rounds": rounds,
        "reward_mult": float(reward_mult or 0.0),
        "victory": victory,
        "characters": characters,
        "rewards": {
            "xp_total": xp_total,
            "enemy_xp": rolled.get("enemy_xp", 0),
            "items": aggregate_items(items),
            "cards": cards,
            "unwired": [k for k in UNWIRED_REWARD_KEYS if (encounter.get("rewards", {}) or {}).get(k)],
            "xp_formula": (f"XP = (遭遇 {int((encounter.get('rewards', {}) or {}).get('xp', 0) or 0)}"
                           f" + 敌人 {int(rolled.get('enemy_xp', 0) or 0)})"
                           f" × 打法倍率 {float(reward_mult or 0.0):g}"
                           f" = {xp_total}；升级阈值 = 等级 × {XP_PER_LEVEL}"),
        },
        "has_reward": has_reward,
        "empty_message": empty_message,
        "created_at": time.time(),
    }


# ── 写回存档（幂等） ──

class SettlementApplyError(RuntimeError):
    """结算写回失败（存档层异常），调用方应保留 pending 供重试。"""


def apply_settlement(session, pending: dict) -> dict:
    """把待结算数据写入会话存档层；幂等，失败可安全重试。

    Args:
        session: 会话对象（提供 overlay）
        pending: `session.overlay.get_pending_settlement()` 返回的完整记录

    Returns:
        {"applied_characters": [...], "items_added": [...], "already_done": bool}
    """
    data = (pending or {}).get("data") or {}
    applied = pending.setdefault("applied", {"characters": [], "inventory": False})
    overlay = session.overlay

    done_chars: list[str] = []
    try:
        for ch in data.get("characters", []):
            name = ch.get("name", "")
            if not name or name in applied["characters"]:
                continue
            # 无经验、无升级、无属性变化（战败/撤退）→ 不触碰剧情侧存档
            if not ch.get("xp_gained") and not ch.get("level_delta") \
                    and not ch.get("attribute_changes"):
                continue
            overlay.set_character_overrides(name, build_writeback_payload(ch))
            applied["characters"].append(name)
            done_chars.append(name)
            overlay.set_pending_settlement(pending)  # 记录进度，便于失败重试跳过已写角色
    except Exception as e:  # 存档层写入失败（磁盘/权限/序列化）
        logger.exception("结算写回失败（角色成长）: %s", e)
        raise SettlementApplyError(f"角色成长写入失败: {e}") from e

    item_counts = (data.get("rewards", {}) or {}).get("items", []) or []
    added: list[str] = []
    if item_counts and not applied.get("inventory"):
        try:
            _add_to_inventory(overlay, item_counts)
            applied["inventory"] = True
            overlay.set_pending_settlement(pending)
            added = [i.get("name", "") for i in item_counts]
        except Exception as e:
            logger.exception("结算写回失败（背包掉落）: %s", e)
            raise SettlementApplyError(f"掉落物品写入失败: {e}") from e

    return {
        "applied_characters": done_chars,
        "items_added": added,
        "already_done": not done_chars and not added,
    }


def _add_to_inventory(overlay, item_counts: list[dict]) -> None:
    """把掉落物品累加进会话背包（overlay 的 inventory 字段）。"""
    data = overlay._data
    inventory = data.get("inventory", [])
    for entry in item_counts:
        item_name = entry.get("name", "")
        count = int(entry.get("count", 1) or 1)
        for existing in inventory:
            if existing.get("name") == item_name:
                existing["count"] = int(existing.get("count", 1)) + count
                break
        else:
            inventory.append({"name": item_name, "count": count, "obtained_at": time.time()})
    data["inventory"] = inventory
    overlay._save()


# ── 战斗历史 ──

def append_history(session, *, encounter_id: str, winner: str, rounds: int,
                   reward_mult: float, settlement: dict, extra: dict | None = None) -> list[dict]:
    """把本次战斗写入会话战斗历史（保留最近 MAX_HISTORY 条）。"""
    overlay_data = session.overlay._data
    history = overlay_data.setdefault("combat_history", [])
    entry = {
        "encounter_id": encounter_id,
        "result": winner,
        "rounds": int(rounds or 0),
        "reward_mult": float(reward_mult or 0.0),
        "rewards": {
            "xp": int((settlement.get("rewards", {}) or {}).get("xp_total", 0) or 0),
            "items": [i.get("name", "") for i in (settlement.get("rewards", {}) or {}).get("items", [])],
            "level_ups": [
                {"name": c["name"], "level": lu["level"], "attribute": lu["attribute"]}
                for c in settlement.get("characters", [])
                for lu in c.get("level_ups", [])
            ],
        },
        "timestamp": time.time(),
    }
    for key, value in (extra or {}).items():
        if value is not None:
            entry[key] = value
    history.append(entry)
    if len(history) > MAX_HISTORY:
        overlay_data["combat_history"] = history[-MAX_HISTORY:]
    return overlay_data["combat_history"]


def legacy_rewards_view(settlement: dict) -> dict:
    """把结算 DTO 映射为旧前端字段（xp/items/level_ups/card_choices），保持向后兼容。"""
    rewards = settlement.get("rewards", {}) or {}
    return {
        "xp": int(rewards.get("xp_total", 0) or 0),
        "items": [i.get("name", "") for i in rewards.get("items", [])],
        "level_ups": [
            {"name": c["name"], "level": lu["level"], "attribute": lu["attribute"]}
            for c in settlement.get("characters", [])
            for lu in c.get("level_ups", [])
        ],
        "card_choices": rewards.get("cards", []),
    }
