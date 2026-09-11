"""
cv.py — 战斗价值单位 CV（Combat Value）估算（design 方案 §3）。

单一预算口径：`卡牌预算 B = 24 × AP费用 × 品质系数`（初版品质系数取 1.00）。

    V单体 = 伤害期望 + 0.85×有效治疗 + 0.75×有效护盾 + 控制CV + 功能CV
    CV    = V单体 × 目标系数 × 射程系数 × 可靠性系数 × 持续系数 × 重复系数

伤害期望使用参考功率带内的命中后期望值：
    伤害期望 = 命中率 × max(1, 平均基础伤害 + 攻击×缩放 - 有效抗性)

本模块只做估算，不参与运行时结算；供审计脚本、验收测试与模拟器共用。
"""
from __future__ import annotations

from combat_engine.card import Card

# ── 参考功率带（design §6.1 各阶段中值；命中率取 §3.2 建议的正常命中 80%）──
# T1 为主参考带（与方案示例一致：PATK/MATK/HEAL=24、DEF/RES=6、命中 80%）。
REFERENCE_BANDS: dict[str, dict] = {
    "T0": {"atk": 21.0, "resist": 5.0, "hit": 0.80},
    "T1": {"atk": 24.0, "resist": 6.0, "hit": 0.80},
    "T2": {"atk": 32.0, "resist": 8.5, "hit": 0.80},
    "T3": {"atk": 39.0, "resist": 11.0, "hit": 0.80},
    "T4": {"atk": 46.0, "resist": 13.5, "hit": 0.80},
}
DEFAULT_TIER = "T1"

CV_PER_AP = 24.0
QUALITY_COEF = 1.00

# 预算合格区间（design §3.1）：|CV − B| / B > DEVIATION_LIMIT 视为需处理
DEVIATION_LIMIT = 0.20
BUDGET_BANDS = {
    1: (20.0, 26.0),
    2: (42.0, 52.0),
    3: (64.0, 78.0),
}

TARGET_COEF = {
    "SELF": 1.00, "SINGLE": 1.00,
    "ADJACENT": 1.45, "LINE_3": 1.65, "CROSS": 1.65,
    "ROW": 1.65, "AREA_2X2": 1.80,
    "GLOBAL": 2.20, "ALL_ALLIES": 2.40,
}

# 目标系数回退值（未知 pattern 视为单体）
DEFAULT_TARGET_COEF = 1.00


def range_coef(card_range: int) -> float:
    """射程系数（design §3.3）：近战 1 格 1.00 / 2–3 格 1.05 / 4 格以上 1.10。

    全图（range = -1）与全体友方已由目标系数承担跨距离收益，不再叠加射程系数
    ——与方案 §5.2 真银斩示例的算式一致（61.3 = 32.8 × 2.20 × 0.85）。
    """
    if card_range < 0:
        return 1.00
    if card_range >= 4:
        return 1.10
    if card_range >= 2:
        return 1.05
    return 1.00


def reliability_coef(card: Card, tier: str = DEFAULT_TIER) -> float:
    """可靠性系数：需要命中的卡直接使用阶段命中率；治疗/纯辅助按 1.00。

    方案 §5.2 的示例统一以 T1 参考角色/敌人估算，故默认按 T1 命中率（80%）。
    分阶段复算时显式传入 tier。
    """
    is_attack = card.damage_type in ("physical", "arts", "mixed") and card.max_damage > 0
    if not is_attack:
        return 1.00
    band = REFERENCE_BANDS.get(tier, REFERENCE_BANDS[DEFAULT_TIER])
    return band["hit"]


def duration_coef(rounds: int) -> float:
    """持续系数（design §3.3）：持续 2 回合 1.65（非 2.00）、3 回合 2.10（非 3.00）。"""
    if rounds <= 1:
        return 1.00
    if rounds == 2:
        return 1.65
    return 2.10


def repeat_coef(card: Card) -> float:
    """重复系数：基础卡可循环 1.00；精英卡正确进入耗竭 0.85。"""
    return 0.85 if card.is_exhausted_on_play else 1.00


# 控制/功能价值（design §3.4；未列出的控制类型给出保守假设，见交付说明）
CONTROL_CV = {
    "weaken": 10.0,      # 虚弱 1 回合
    "strengthen": 8.0,   # 强化自身 1 回合
    "silence": 12.0,     # 沉默 1 回合
    "blind": 8.0,        # 致盲 1 回合
    "taunt": 6.0,        # 嘲讽 1 回合
    "cleanse": 8.0,      # 净化 1 个负面
    "slow": 8.0,         # 假设：减速 1 回合 ≈ 致盲量级
    "bind": 10.0,        # 假设：束缚 1 回合 ≈ 虚弱量级（剥夺移动）
    "evade": 8.0,        # 假设：闪避姿态 1 回合 ≈ 致盲量级
}
# 群体强化：design 给出 20–28（取决于本轮剩余可出牌数），取中值 24
GROUP_BUFF_CV = 24.0
# 燃烧：按 DoT 总伤害折算，延迟生效折扣 0.7（假设）
BURN_DELAY_DISCOUNT = 0.7
# 护盾/治疗的价值系数（design §3.2）
HEAL_COEF = 0.85
SHIELD_COEF = 0.75


def budget(card: Card) -> float:
    """卡牌设计预算 B = 24 × AP费用 × 品质系数。"""
    return CV_PER_AP * max(0, int(card.cost)) * QUALITY_COEF


def budget_band(cost: int) -> tuple[float, float]:
    """合格区间；未定义费用的退回 ±10%。"""
    if cost in BUDGET_BANDS:
        return BUDGET_BANDS[cost]
    b = CV_PER_AP * max(1, cost)
    return (b * 0.9, b * 1.1)


def _attack_stat(card: Card, band: dict) -> float:
    """参考角色的主攻属性：物理→PATK，源石→MATK，治疗→HEAL，混合→两者均值。"""
    if card.damage_type == "healing":
        return band["atk"]
    if card.damage_type == "arts":
        return band["atk"]
    return band["atk"]  # 参考带内 PATK/MATK/HEAL 同值，mixed 亦取该值


def estimate_card_cv(card: Card, tier: str | None = None) -> dict:
    """估算单卡 CV，返回含明细的字典（便于审计与回归对比）。

    默认按 T1 参考带（方案 §5.2 示例口径）；传 tier 可分阶段复算。
    """
    tier = tier or DEFAULT_TIER
    if tier not in REFERENCE_BANDS:
        tier = DEFAULT_TIER
    band = REFERENCE_BANDS[tier]

    # ── 单目标基础价值 ──
    damage_exp = 0.0
    if card.damage_type != "healing" and card.max_damage > 0:
        base = (card.min_damage + card.max_damage) / 2.0
        atk = _attack_stat(card, band)
        resist = band["resist"] * (1.0 - (card.ignore_def or 0.0))
        raw = max(1.0, base + atk * card.atk_scale - resist)
        damage_exp = raw * reliability_coef(card, tier)

    heal_value = 0.0
    if card.damage_type == "healing" and card.max_damage > 0:
        base = (card.min_damage + card.max_damage) / 2.0
        heal_value = max(0.0, base + band["atk"] * card.atk_scale) * HEAL_COEF

    shield_value = 0.0
    control_value = 0.0
    burn_value = 0.0
    group_value = 0.0
    max_duration = 1
    for eff in card.effects or []:
        etype = eff.get("type", "")
        duration = int(eff.get("duration", 1) or 1)
        max_duration = max(max_duration, duration)
        if etype == "shield":
            shield_value += max(0.0, float(eff.get("value", 0))) * SHIELD_COEF
        elif etype == "burn":
            total = max(0.0, float(eff.get("value", 0))) * duration
            burn_value += total * BURN_DELAY_DISCOUNT
        elif etype in CONTROL_CV:
            value = CONTROL_CV[etype] * duration_coef(duration)
            if etype == "strengthen" and card.target == "ALL_ALLIES":
                # 方案 §3.4：群体强化 1 回合 20–28 CV（不能简单按 4 人相乘），
                # 该数值已含目标数补偿，不再叠加 ALL_ALLIES 目标系数。
                group_value += GROUP_BUFF_CV * duration_coef(duration)
            else:
                control_value += value
    if card.cleanse:
        control_value += CONTROL_CV["cleanse"]

    v_single = damage_exp + heal_value + shield_value + control_value + burn_value

    # ── 整卡系数 ──
    target_coef = TARGET_COEF.get(card.target, DEFAULT_TARGET_COEF)
    rng_coef = range_coef(card.range)
    rep_coef = repeat_coef(card)
    # 持续系数已按效果逐条计入；此处不再重复乘，仅记录展示
    cv = (v_single * target_coef + group_value) * rng_coef * rep_coef

    return {
        "card_id": card.card_id,
        "cost": card.cost,
        "tier": tier,
        "damage_exp": round(damage_exp, 2),
        "heal_value": round(heal_value, 2),
        "shield_value": round(shield_value, 2),
        "control_value": round(control_value, 2),
        "group_value": round(group_value, 2),
        "burn_value": round(burn_value, 2),
        "v_single": round(v_single, 2),
        "target_coef": target_coef,
        "range_coef": rng_coef,
        "reliability": reliability_coef(card),
        "repeat_coef": rep_coef,
        "max_duration": max_duration,
        "cv": round(cv, 2),
        "budget": round(budget(card), 2),
    }


def deviation(card: Card, cv: float | None = None) -> dict:
    """相对预算的偏差评估：ratio>0 表示高于预算。"""
    cv = estimate_card_cv(card)["cv"] if cv is None else cv
    b = budget(card)
    lo, hi = budget_band(int(card.cost))
    ratio = (cv - b) / b if b else 0.0
    if cv < lo:
        status = "under"
    elif cv > hi:
        status = "over"
    else:
        status = "in_band"
    return {"cv": round(cv, 2), "budget": round(b, 2), "band": [lo, hi],
            "ratio": round(ratio, 3), "status": status,
            "needs_fix": abs(ratio) > DEVIATION_LIMIT and status != "in_band"}
