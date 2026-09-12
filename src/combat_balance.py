"""战斗数值模型：威胁点、期望输出/有效生命与阶段带判定。

从 `scripts/migrate_balance_v1.py` 抽出（design §8.1 / §9.2），供三处共用：

1. **校验器**（`combat_nodes.validate_node`）—— 节点实际威胁 vs 声明 `threat_budget`
2. **编辑器** —— 实时显示"小队战力 vs 节点威胁"
3. **生成器/试跑器**（`tools/generate_battle_spec.py` / `simulate_battle.py`）——
   按目标威胁预算生成与验证编排

模型保持与 v1 数值方案一致：五类模板（相对生命 / 相对输出 → 威胁点 / 行动槽），
以 `STD_HP=100`、`STD_OUTPUT=20` 为基准。
"""

from __future__ import annotations

import logging

from combat_rules import difficulty_rules

logger = logging.getLogger(__name__)

# §8.1 五类模板：(相对生命中值, 相对输出中值, 威胁点, 行动槽)
TEMPLATES: dict[str, tuple[float, float, float, int]] = {
    "minion": (0.675, 0.725, 1.0, 1),
    "standard": (1.000, 1.000, 1.6, 1),
    "strong": (1.375, 1.175, 2.2, 1),
    "elite": (1.800, 1.250, 3.2, 2),
    "boss": (4.250, 1.350, 7.0, 2),
}
STD_HP = 100.0
STD_OUTPUT = 20.0

# difficulty（1–5 整数）→ 建议阶段带
DIFFICULTY_TIER = {1: "T0", 2: "T1", 3: "T1", 4: "T2", 5: "T3"}
BANDS = ("T0", "T1", "T2", "T3", "T4")


def classify_enemy(stats: dict, level: int = 1, *, declared_role: str = "",
                   declared_tier: str = "") -> dict:
    """按相对生命 / 相对输出最近邻分类敌人（返回 role/tier/威胁点等）。

    `stats` 使用敌人 frontmatter 的 `combat_stats` 字段名（hp/patk/defense/...）。
    声明了 `role`/`power_tier` 时以声明为准（设计者的意图优先于自动分类）。
    """
    stats = stats or {}
    hp = float(stats.get("hp", 100) or 100)
    patk = float(stats.get("patk", 20) or 20)
    defense = float(stats.get("defense", 5) or 5)
    dpr = 0.5 * patk + 7.5                # enemy_atk 期望伤害
    ehp = hp * (1 + defense / 20.0)       # 含防御的有效生命
    hp_rel = hp / STD_HP
    out_rel = dpr / STD_OUTPUT

    best_role, best_dist = "standard", 1e9
    for role, (hp_mid, out_mid, _threat, _slots) in TEMPLATES.items():
        dist = abs(hp_rel - hp_mid) / hp_mid + abs(out_rel - out_mid) / out_mid
        if dist < best_dist:
            best_role, best_dist = role, dist

    role = str(declared_role or "").strip() or best_role
    if role not in TEMPLATES:
        role = best_role
    threat = TEMPLATES[role][2]
    tier = str(declared_tier or "").strip().upper() or DIFFICULTY_TIER.get(
        int(level or 1), "T1")

    return {
        "role": role,
        "power_tier": tier,
        "action_slots": TEMPLATES[role][3],
        "threat_points": threat,
        "relative_hp": round(hp_rel, 2),
        "relative_output": round(out_rel, 2),
        "expected_dpr": round(dpr, 1),
        "expected_effective_hp": round(ehp, 1),
        "distance": round(best_dist, 3),
    }


def enemy_threat(unit, *, declared_role: str = "", declared_tier: str = "") -> float:
    """由已构建的 `CombatUnit` 估威胁点（战斗中/试跑时用）。"""
    return float(classify_enemy(
        {"hp": unit.max_hp, "patk": unit.PATK, "defense": unit.DEF},
        level=getattr(unit, "level", 1) if hasattr(unit, "level") else 1,
        declared_role=declared_role or getattr(unit, "role", ""),
        declared_tier=declared_tier or getattr(unit, "power_tier", ""),
    )["threat_points"])


def node_threat(node: dict, *, loader=None) -> dict:
    """节点实际威胁：敌人条目威胁点 × 数量（含数值覆盖的重新估算）。

    返回 `{"total": float, "by_wave": [...], "units": int, "band_hint": "T2"}`。
    """
    node = node or {}
    if loader is None:
        try:
            from combat_data_loader import CombatDataLoader
            loader = CombatDataLoader()
        except Exception:  # 测试/离线场景下允许无 loader（按内置默认数值估）
            loader = None
    waves = node.get("waves") or []
    inline = node.get("enemies_def") or {}
    band = str(((node.get("difficulty") or {}).get("band")) or "").upper()

    total = 0.0
    units = 0
    by_wave: list[dict] = []
    for wi, wave in enumerate(waves):
        wave_threat = 0.0
        wave_units = 0
        for entry in (wave or {}).get("enemies") or []:
            name = str(entry.get("enemy") or entry.get("name") or "")
            count = max(1, int(entry.get("count", 1) or 1))
            stats, role, tier = _enemy_profile(name, inline, loader)
            overrides = entry.get("stats") or entry.get("combat_stats") or {}
            if overrides:
                stats = ({**stats, **{k: v for k, v in overrides.items() if k in stats}}
                         if stats else dict(overrides))
                # 逐单位数值覆盖后已不是原条目那回事（例如 hp 150 的"士兵"），
                # 因此不再沿用声明的 role/tier，改由模型按新数值分类
                role, tier = "", ""
            info = classify_enemy(stats, declared_role=role, declared_tier=tier)
            wave_threat += float(info["threat_points"]) * count
            wave_units += count
        total += wave_threat
        units += wave_units
        by_wave.append({"wave": wi + 1, "threat": round(wave_threat, 2), "units": wave_units})

    return {
        "total": round(total, 2),
        "by_wave": by_wave,
        "units": units,
        "band": band,
        "band_hint": recommend_band(total),
    }


def _enemy_profile(name: str, inline: dict, loader) -> tuple[dict, str, str]:
    """取敌人战斗数值与声明分层（内联 enemies_def 优先 → 全局敌人库）。"""
    meta = inline.get(name)
    if meta is None and loader is not None:
        meta = getattr(loader, "_read_enemy_meta", lambda _n: None)(name) or {}
        meta = {**meta, "combat_stats": meta.get("combat_stats") or {}}
        if not meta.get("combat_stats"):
            # 纯叙事条目：按 attributes 派生
            unit = loader.load_enemy(name)
            if unit is not None:
                return ({"hp": unit.max_hp, "patk": unit.PATK, "defense": unit.DEF},
                        getattr(unit, "role", ""), getattr(unit, "power_tier", ""))
    meta = meta or {}
    stats = dict(meta.get("combat_stats") or {})
    if not stats and meta.get("attributes"):
        stats = _derive_stats_from_attributes(meta["attributes"])
    return stats, str(meta.get("role") or ""), str(meta.get("power_tier") or "")


def _derive_stats_from_attributes(attributes: dict) -> dict:
    """敌人 attributes → combat_stats（与 CombatUnit.from_character_metadata 同口径的近似）。"""
    def attr(key: str, default: int = 5) -> float:
        value = attributes.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    return {
        "hp": attr("生理耐受") * 12 + attr("物理强度") * 3,
        "patk": (attr("物理强度") + attr("战斗技巧")) * 2,
        "defense": round(attr("生理耐受") * 1.5 + attr("物理强度") * 0.5),
    }


def recommend_band(total_threat: float) -> str:
    """按威胁总量推荐阶段带（配置 `threat_range` 的区间中点就近）。"""
    bands = (difficulty_rules().get("bands") or {})
    best, best_dist = "T1", 1e9
    for band in BANDS:
        cfg = bands.get(band) or {}
        rng = cfg.get("threat_range")
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
            continue
        lo, hi = float(rng[0]), float(rng[1])
        mid = (lo + hi) / 2
        if lo <= total_threat <= hi:
            return band
        dist = abs(total_threat - mid)
        if dist < best_dist:
            best, best_dist = band, dist
    return best


def node_budget_report(node: dict, *, loader=None) -> dict:
    """节点威胁 vs 声明预算/阶段带的对照（校验器与编辑器都用它）。"""
    difficulty = (node or {}).get("difficulty") or {}
    rules = difficulty_rules()
    tolerance = float(rules.get("threat_tolerance", 0.25) or 0.25)

    threat = node_threat(node, loader=loader)
    declared = difficulty.get("threat_budget")
    declared_band = str(difficulty.get("band") or "").upper()

    report: dict = {
        **threat,
        "declared_budget": declared,
        "declared_band": declared_band,
        "warnings": [],
    }
    if declared is not None:
        try:
            budget = float(declared)
        except (TypeError, ValueError):
            budget = None
        if budget and budget > 0:
            ratio = abs(threat["total"] - budget) / budget
            report["budget_ratio"] = round(ratio, 3)
            if ratio > tolerance:
                arrow = "超出" if threat["total"] > budget else "低于"
                report["warnings"].append(
                    f"实际威胁 {threat['total']} {arrow}声明预算 {budget:g}"
                    f"（偏差 {ratio:.0%} > 容差 {tolerance:.0%}）")
    if declared_band and declared_band in BANDS:
        # 只在"实际威胁明显落在声明阶段带的参考区间之外"时提醒（留 tolerance 余量），
        # 避免与相邻阶段带擦边就报警；推荐值始终在 metrics 里可见。
        bands = rules.get("bands") or {}
        rng = (bands.get(declared_band) or {}).get("threat_range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            lo, hi = float(rng[0]), float(rng[1])
            slack = tolerance * max(1e-6, hi - lo)
            if not (lo - slack <= threat["total"] <= hi + slack):
                report["warnings"].append(
                    f"实际威胁 {threat['total']} 明显偏离声明阶段带 {declared_band} 的参考区间 "
                    f"{lo:g}–{hi:g}（模型推荐 {threat['band_hint']}）")
        elif declared_band != threat["band_hint"]:
            report["warnings"].append(
                f"声明阶段带 {declared_band} 与按威胁推荐 {threat['band_hint']} 不一致"
                f"（威胁 {threat['total']}）")
    return report
