"""
战前打法（Approach）解析 — 遭遇战 approaches → 战斗参数 / 剧情投点 / 撤退。

设计目标（见 docs/combat-core-design.md B5）：
  - 打法由数据侧定义（平衡、可预期），LLM 只负责用简报叙述引出，不决定机制。
  - 选定打法后经 POST /combat/start 启动，映射为机械参数：
    enemy_scale（敌人数倍率）、first_strike（首回合共享 AP+1）、
    player_effects（复用 status_effects）、reward_mult（奖励倍率）。
  - 谈判/抉择类打法走 d20 剧情投点（成功避免战斗 / 失败以 fail_combat 参数开战）。
  - 撤退类打法直接跳过战斗，无奖励。
"""

from __future__ import annotations

import random


# 遭遇战未定义 approaches 时的兜底（保证所有遭遇战都能选择打法）
DEFAULT_APPROACHES: list[dict] = [
    {
        "id": "assault",
        "label": "正面强攻",
        "hint": "以绝对火力正面压制，敌人不会增援，但将全力迎战。",
        "combat": {
            "enemy_scale": 1.0,
            "first_strike": False,
            "player_effects": {},
            "reward_mult": 1.2,
        },
    },
    {
        "id": "retreat",
        "label": "撤退",
        "hint": "保全队伍撤退，放弃本次战利品。",
        "avoid": True,
        "reward_mult": 0.0,
    },
]


def _kind_of(approach: dict) -> str:
    if approach.get("avoid"):
        return "avoid"
    if approach.get("check"):
        return "check"
    return "combat"


def _as_combat_params(cfg: dict) -> dict:
    """把 approach 的 combat 段归一化为 CombatSession.start 的 combat_params。"""
    params: dict = {}
    if cfg.get("enemy_scale") is not None:
        params["enemy_scale"] = float(cfg["enemy_scale"])
    if cfg.get("first_strike") is not None:
        params["first_strike"] = bool(cfg["first_strike"])
    player_effects = cfg.get("player_effects") or {}
    if player_effects:
        params["status_effects"] = player_effects
    return params


def list_approaches(encounter: dict) -> list[dict]:
    """返回遭遇战可用的打法列表（供前端展示/简报用）。"""
    approaches = encounter.get("approaches") or DEFAULT_APPROACHES
    return [
        {
            "id": a.get("id"),
            "label": a.get("label", a.get("id", "战斗")),
            "hint": a.get("hint", ""),
            "kind": _kind_of(a),
        }
        for a in approaches
    ]


def resolve_approach(encounter: dict, approach_id: str | None) -> dict:
    """把选定的打法解析为可执行指令。

    Returns:
        {
          "kind": "combat" | "check" | "avoid",
          "label": str, "hint": str, "reward_mult": float,
          "combat_params": dict,            # kind=combat 时非空
          "check": {"attr": str, "dc": int} | None,   # kind=check 时非空
          "fail_combat_params": dict,       # kind=check 失败时开战参数
        }
    """
    approaches = encounter.get("approaches") or DEFAULT_APPROACHES

    picked = None
    if approach_id:
        for a in approaches:
            if a.get("id") == approach_id:
                picked = a
                break
    if picked is None:
        picked = approaches[0] if approaches else DEFAULT_APPROACHES[0]

    kind = _kind_of(picked)
    result: dict = {
        "kind": kind,
        "label": picked.get("label", picked.get("id", "战斗")),
        "hint": picked.get("hint", ""),
        "reward_mult": 1.0,
        "combat_params": {},
        "check": None,
        "fail_combat_params": {},
    }

    if kind == "combat":
        cfg = picked.get("combat") or {}
        result["combat_params"] = _as_combat_params(cfg)
        result["reward_mult"] = float(cfg.get("reward_mult", picked.get("reward_mult", 1.0)))
    elif kind == "check":
        check = picked.get("check") or {}
        result["check"] = {
            "attr": check.get("attr", "魅力"),
            "dc": int(check.get("dc", 12)),
        }
        fail_cfg = picked.get("fail_combat") or {}
        result["fail_combat_params"] = _as_combat_params(fail_cfg)
        result["reward_mult"] = float(fail_cfg.get("reward_mult", picked.get("reward_mult", 1.0)))
    else:  # avoid
        result["reward_mult"] = float(picked.get("reward_mult", 0.0))

    return result


def roll_check(character_metas: list[dict], check: dict,
               d20: int | None = None) -> dict:
    """对谈判/抉择类打法执行 d20 剧情投点。

    取小队中该属性最高的角色作为检定代表（最佳人选）。自然 20 必成、自然 1 必败。

    Returns:
        {"d20", "modifier", "total", "dc", "success", "attr", "character"}
    """
    from services.attribute_loader import AttributeLoader
    from services.dice import DiceSystem

    attr = check.get("attr", "魅力")
    dc = int(check.get("dc", 12))

    best_name = ""
    best_level = 0
    for meta in character_metas:
        attrs = meta.get("attributes") or {}
        level = int(attrs.get(attr, 0) or 0)
        if level > best_level:
            best_level = level
            best_name = meta.get("name", "")
    if not best_name:
        best_name = "博士"
        best_level = 5

    modifier = AttributeLoader.get_modifier(attr, best_level)

    if d20 is not None:
        roll = max(1, min(20, int(d20)))
        total = roll + modifier
        if roll == 20:
            success = True
        elif roll == 1:
            success = False
        else:
            success = total >= dc
        return {
            "d20": roll, "modifier": modifier, "total": total,
            "dc": dc, "success": success, "attr": attr,
            "character": best_name,
        }

    result = DiceSystem.roll_d20_structured(modifier, dc)
    return {
        "d20": result["roll"], "modifier": modifier,
        "total": result["total"], "dc": dc,
        "success": result["success"], "attr": attr,
        "character": best_name,
    }
