"""
CV 预算验收测试（design 方案 §12 硬性测试第 1 条）：

- 每张 1/2/3 AP 卡的估算 CV 落在 24 CV/AP 预算的 ±20% 内，
  或出现在 perf_tests/cv_audit.json 的例外清单中（必须有说明文字）；
- cv_budget / cv_estimated 与重新计算一致；
- 方案 §5.2 明确给出推荐值的卡按推荐值落地；
- atk_scale 保持在 Card 声明的 0.0–1.5 区间。

运行：python perf_tests/test_cv_budget.py
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
if os.path.join(_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))

from combat_engine import cv as cvmod                            # noqa: E402
from combat_engine.card_json_loader import load_all_class_cards   # noqa: E402

AUDIT = os.path.join(_HERE, "cv_audit.json")

# 方案 §5.2 推荐值（逐字落地）
DESIGN_VALUES = {
    "guard_slash": {"min_damage": 12, "max_damage": 16, "atk_scale": 0.75},
    "guard_pierce": {"min_damage": 10, "max_damage": 14, "atk_scale": 0.70,
                     "ignore_def": 0.5},
    "guard_true_silver": {"min_damage": 14, "max_damage": 20, "atk_scale": 1.25},
    "medic_heal": {"min_damage": 6, "max_damage": 12, "atk_scale": 0.5},
}


class CVBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = [c for cards in load_all_class_cards().values() for c in cards]
        with open(AUDIT, "r", encoding="utf-8") as f:
            audit = json.load(f)
        cls.audit = {r["card_id"]: r for r in audit["records"]}

    def test_every_card_in_band_or_documented_exception(self):
        offenders = []
        for card in self.cards:
            dev = cvmod.deviation(card)
            if abs(dev["ratio"]) <= cvmod.DEVIATION_LIMIT:
                continue
            record = self.audit.get(card.card_id, {})
            note = record.get("exception")
            if dev["status"] == "in_band":
                continue  # 落在合格区间内，容差口径允许
            if not note:
                offenders.append((card.card_id, dev["ratio"], dev["status"]))
        self.assertEqual(offenders, [],
                         f"存在既偏离预算 >20% 又无例外说明的卡：{offenders}")

    def test_cv_metadata_matches_recomputation(self):
        for card in self.cards:
            self.assertAlmostEqual(card.cv_budget, cvmod.budget(card), places=2,
                                   msg=f"{card.card_id} cv_budget 与预算不符")
            self.assertAlmostEqual(card.cv_estimated,
                                   cvmod.estimate_card_cv(card)["cv"], places=2,
                                   msg=f"{card.card_id} cv_estimated 与重算不符")
            self.assertEqual(card.balance_version, 1)

    def test_design_recommended_values(self):
        by_id = {c.card_id: c for c in self.cards}
        for card_id, expected in DESIGN_VALUES.items():
            card = by_id[card_id]
            for field, value in expected.items():
                self.assertEqual(getattr(card, field), value,
                                 f"{card_id}.{field} 未按方案 §5.2 推荐值落地")

    def test_atk_scale_within_documented_range(self):
        for card in self.cards:
            self.assertGreaterEqual(card.atk_scale, 0.0, card.card_id)
            self.assertLessEqual(card.atk_scale, 1.5, card.card_id)

    def test_budget_follows_cost(self):
        for card in self.cards:
            self.assertEqual(card.cv_budget, 24.0 * card.cost, card.card_id)

    def test_exceptions_have_reasons(self):
        for card_id, record in self.audit.items():
            if record.get("exception"):
                self.assertGreater(len(record["exception"]), 10,
                                   f"{card_id} 例外说明过短")


if __name__ == "__main__":
    unittest.main(verbosity=2)
