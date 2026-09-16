"""
CV 审计与数值迁移（design 方案 §3 / §11 P1-1）。

用法：
    python scripts/cv_audit.py              # 只出报告，不改数据
    python scripts/cv_audit.py --apply      # 按报告把调整写回 cards.json

规则：
1. 逐卡估算 CV（combat_engine.cv），与 24 CV/AP 预算比较；
2. 方案 §5.2 明确给出推荐值的卡，直接采用推荐值；
3. 其余偏离预算的卡，按「等比缩放基础伤害 / 攻击缩放 / 护盾数值」迭代逼近
   预算带（单轮缩放限幅 0.55–2.20，最多 6 轮）；atk_scale 保持 0.0–1.5 区间，
   触顶后溢出交由基础伤害承接；
4. 可缩放价值（伤害/治疗/护盾）占比低于 25% 的卡不做向下缩放：砍伤害既救不回
   CV 又会破坏卡牌形态，保留数值并记为 effect_dominated 例外；
5. 纯治疗卡允许低于预算至多 35%（support_discount，方案 §5.2 治疗术示例认可）；
6. 结果写回 data/classes/<职业>/cards.json（含 cv_budget / cv_estimated），
   并输出 perf_tests/fixtures/cv_audit.json 与 perf_tests/cv_audit_report.md。
"""
import argparse
import copy
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from combat_engine import cv as cvmod                       # noqa: E402
from combat_engine.card import Card                          # noqa: E402
from combat_engine.card_json_loader import load_all_class_cards  # noqa: E402  (测试/外部用)

CLASS_DIR = os.path.join(_ROOT, "data", "classes")
REPORT_JSON = os.path.join(_ROOT, "perf_tests", "fixtures", "cv_audit.json")
REPORT_MD = os.path.join(_ROOT, "perf_tests", "cv_audit_report.md")
# 迁移基线：迁移前 Python 旧表快照（作为固定审计夹具纳入版本库）。
# 以基线为起点做迁移，保证重复执行 --apply 结果一致（幂等、可复现）。
BASELINE = os.path.join(_ROOT, "perf_tests", "fixtures", "cards_python_snapshot.json")

SUPPORT_ALLOWANCE = 0.35
SCALE_MIN, SCALE_MAX = 0.55, 2.20
MAX_ITER = 6

# ── 方案 §5.2 明确给出推荐值的卡（逐字采用）──
EXPLICIT_RECOMMENDATIONS = {
    "guard_slash": {"min_damage": 12, "max_damage": 16, "atk_scale": 0.75},
    "guard_pierce": {"min_damage": 10, "max_damage": 14, "atk_scale": 0.70,
                     "ignore_def": 0.5},
    "guard_true_silver": {"min_damage": 14, "max_damage": 20, "atk_scale": 1.25},
    "medic_heal": {},  # 方案明确保留 6–12 + 0.5 HEAL（support_discount 例外）
    "defender_wall": {"effects": [{"type": "shield", "value": 12,
                                   "def_scale": 0.25, "duration": 1}]},
}


def _is_support(card: Card) -> bool:
    """治疗向卡（价值来自治疗/护盾而非伤害）：允许稳定性折扣。"""
    return card.damage_type == "healing"


def _is_pure_effect(card: Card) -> bool:
    """无伤害也无治疗、价值全部来自状态效果的卡（数值缩放不可调）。"""
    return card.max_damage <= 0


def _scalable_share(card: Card) -> float:
    """可被数值缩放的部分（伤害/治疗/护盾）在整卡价值中的占比。"""
    est = cvmod.estimate_card_cv(card)
    total = (est["damage_exp"] + est["heal_value"] + est["control_value"] +
             est["group_value"] + est["shield_value"] + est["burn_value"])
    if not total:
        return 0.0
    return (est["damage_exp"] + est["heal_value"] + est["shield_value"]) / total


def _scale_card(card: Card, factor: float) -> None:
    """等比缩放卡牌数值（基础伤害区间 / 攻击缩放 / 效果数值）。"""
    f = max(SCALE_MIN, min(SCALE_MAX, factor))
    if card.max_damage > 0:
        card.min_damage = max(1, int(round(card.min_damage * f)))
        card.max_damage = max(card.min_damage, int(round(card.max_damage * f)))
        if card.atk_scale:
            card.atk_scale = round(min(1.5, max(0.10, card.atk_scale * f)), 2)
    for eff in card.effects or []:
        if eff.get("type") in ("shield", "burn") and eff.get("value"):
            eff["value"] = max(1, int(round(float(eff["value"]) * f)))


def _target_cv(card: Card) -> float:
    """调整目标：预算带中点（避免贴着区间边缘）。"""
    lo, hi = cvmod.budget_band(int(card.cost))
    return (lo + hi) / 2.0


def tune_card(card: Card, allow_support_discount: bool = True) -> dict:
    """迭代把卡片 CV 逼近期望值，返回调整记录。"""
    original = card.to_dict()
    history = []

    if card.card_id in EXPLICIT_RECOMMENDATIONS:
        for key, value in EXPLICIT_RECOMMENDATIONS[card.card_id].items():
            setattr(card, key, value)
        history.append({"step": "explicit_recommendation",
                        "fields": list(EXPLICIT_RECOMMENDATIONS[card.card_id])})

    dev = cvmod.deviation(card)
    pure_effect = _is_pure_effect(card)
    # 容差口径与方案一致：只处理偏离预算超过 20% 的卡（±20% 内不动）
    tolerance_floor = dev["budget"] * (1.0 - cvmod.DEVIATION_LIMIT)
    floor = dev["budget"] * (1.0 - SUPPORT_ALLOWANCE) if (
        allow_support_discount and _is_support(card)) else tolerance_floor

    if not pure_effect:
        iterations = 0
        while iterations < MAX_ITER and dev["cv"] < floor:
            factor = _target_cv(card) / max(1e-6, dev["cv"])
            _scale_card(card, factor)
            history.append({"step": "scale_up", "factor": round(factor, 3)})
            dev = cvmod.deviation(card)
            iterations += 1

        iterations = 0
        while (iterations < MAX_ITER and dev["cv"] > dev["band"][1]
               and dev["ratio"] > cvmod.DEVIATION_LIMIT
               and _scalable_share(card) >= 0.25):
            factor = _target_cv(card) / max(1e-6, dev["cv"])
            _scale_card(card, factor)
            history.append({"step": "scale_down", "factor": round(factor, 3)})
            dev = cvmod.deviation(card)
            iterations += 1

    # 例外说明：数值缩放无法解决的类型，明确记录而非静默放过
    # 判定与统计口径一致：只有偏离预算 >20% 且落在区间外才需要例外说明。
    est = cvmod.estimate_card_cv(card)
    needs_note = (abs(dev["ratio"]) > cvmod.DEVIATION_LIMIT
                  and dev["status"] != "in_band")
    scalable_share = _scalable_share(card)
    exception = None
    if needs_note:
        if pure_effect:
            exception = ("effect_only（纯效果卡无法用数值缩放调整，"
                         "建议按方案 §5.2 增加机制补足剩余预算——P2 内容）")
        elif scalable_share < 0.25:
            exception = ("effect_dominated（价值主要来自状态效果，数值缩放无效；"
                         "方案 §3.4 的 SELF 目标系数低估自保型技能，"
                         "建议 P2 以机制补足而非堆数值）")
        elif _is_support(card) and dev["status"] == "under":
            exception = "support_discount（纯治疗卡按稳定性溢价允许低于预算 ≤35%）"
        elif (card.target == "SINGLE" and card.range == 2 and card.cost == 1
              and abs(dev["ratio"]) <= 0.35):
            # 批次 1：统一曼哈顿度量后，单一目标近战卡射程 1 → 2（补回斜角邻格），
            # 覆盖由 4 格增至 13 格使 CV 略超带宽；属有意的手感补偿，见
            # perf_tests/metric_migration_report.md
            exception = ("melee_range_manhattan（曼哈顿射程补偿：单体近战 1→2 使 CV "
                         "超出带宽 ≤35%，见 metric_migration_report.md）")
    if card.card_id == "medic_heal":
        exception = "support_discount（方案 §5.2 明确保留治疗术数值）"

    return {
        "card_id": card.card_id,
        "class": card.class_required,
        "cost": card.cost,
        "tier": card.tier,
        "pure_effect": pure_effect,
        "before": {"min_damage": original["min_damage"],
                   "max_damage": original["max_damage"],
                   "atk_scale": original["atk_scale"],
                   "effects": original["effects"],
                   "cv": cvmod.estimate_card_cv(Card.from_dict(original))["cv"]},
        "after": {"min_damage": card.min_damage, "max_damage": card.max_damage,
                  "atk_scale": card.atk_scale, "effects": copy.deepcopy(card.effects),
                  "cv": dev["cv"]},
        "budget": dev["budget"],
        "band": dev["band"],
        "ratio": dev["ratio"],
        "status": dev["status"],
        "exception": exception,
        "history": history,
    }


def write_cards_back(cards_by_class: dict) -> None:
    """把调整后的数值与 cv_* 元数据写回 cards.json（重算 _hash）。"""
    for char_class, cards in cards_by_class.items():
        path = os.path.join(CLASS_DIR, char_class, "cards.json")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        by_id = {c.card_id: c for c in cards}
        new_cards = []
        for raw in doc.get("cards", []):
            card = by_id.get(raw["card_id"])
            if card is None:
                new_cards.append(raw)
                continue
            updated = card.to_dict()
            updated["power_tier"] = raw.get("power_tier", updated.get("power_tier"))
            updated["cv_budget"] = cvmod.budget(card)
            updated["cv_estimated"] = cvmod.estimate_card_cv(card)["cv"]
            new_cards.append(updated)
        doc["cards"] = new_cards
        payload = {k: v for k, v in doc.items() if k != "_hash"}
        doc["_hash"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")


def baseline_cards() -> dict:
    """从旧表快照构建迁移基线卡组（{职业: [Card]}），保证迁移可复现。"""
    with open(BASELINE, "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    result: dict[str, list[Card]] = {}
    for char_class, raw_cards in snapshot.items():
        cards = []
        for raw in raw_cards:
            card = Card.from_dict(raw)
            card.power_tier = "T2" if card.tier == "elite" else "T1"  # 假设：精英归 T2
            card.cv_budget = cvmod.budget(card)
            cards.append(card)
        result[char_class] = cards
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写回 cards.json")
    args = ap.parse_args()

    if not os.path.isfile(BASELINE):
        raise SystemExit(f"缺少迁移基线 {BASELINE}；请从版本库恢复该审计夹具")
    cards_by_class = baseline_cards()
    records = []
    for cards in cards_by_class.values():
        for card in cards:
            records.append(tune_card(card))
    records.sort(key=lambda r: abs(r["ratio"]), reverse=True)

    in_band = [r for r in records if abs(r["ratio"]) <= cvmod.DEVIATION_LIMIT]
    exceptions = [r for r in records if r["exception"]]
    remaining = [r for r in records
                 if abs(r["ratio"]) > cvmod.DEVIATION_LIMIT and not r["exception"]]

    lines = ["# 战术卡 CV 审计报告（balance_version 1）", "",
             f"- 卡牌总数：{len(records)}",
             f"- 落在预算 ±20%：{len(in_band)}",
             f"- 有明确例外说明：{len(exceptions)}",
             f"- 仍偏离预算且无说明：{len(remaining)}", "",
             "| 卡 | 职业 | AP | 阶 | 调整前 | 调整后 | CV | 预算 | 偏差 | 状态 | 例外 |",
             "|---|---|---:|---|---|---|---:|---:|---:|---|---|"]
    for r in records:
        before = (f"{r['before']['min_damage']}–{r['before']['max_damage']} / "
                  f"{r['before']['atk_scale']}")
        after = (f"{r['after']['min_damage']}–{r['after']['max_damage']} / "
                 f"{r['after']['atk_scale']}")
        lines.append(f"| {r['card_id']} | {r['class']} | {r['cost']} | {r['tier']} | "
                     f"{before} | {after} | {r['after']['cv']} | {r['budget']} | "
                     f"{r['ratio']:+.0%} | {r['status']} | {r['exception'] or '-'} |")
    if remaining:
        lines += ["", "## 仍偏离预算的卡（需人工确认）", ""]
        lines += [f"- {r['card_id']}: CV {r['after']['cv']} vs 预算 {r['budget']} "
                  f"({r['ratio']:+.0%})" for r in remaining]

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump({"records": records,
                   "summary": {"total": len(records), "in_band": len(in_band),
                               "exceptions": len(exceptions),
                               "remaining": len(remaining)}},
                  f, ensure_ascii=False, indent=2)

    print(f"total={len(records)} in_band={len(in_band)} "
          f"exceptions={len(exceptions)} remaining={len(remaining)}")
    print("top deviations:")
    for r in records[:12]:
        print(f"  {r['card_id']:<26} cv={r['after']['cv']:>6} budget={r['budget']:>5} "
              f"{r['ratio']:+.0%} {r['status']}")

    if args.apply:
        write_cards_back(cards_by_class)
        print("applied to cards.json")
    else:
        print("dry-run (add --apply to write back)")


if __name__ == "__main__":
    main()
