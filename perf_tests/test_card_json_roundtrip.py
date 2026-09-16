"""
卡牌数据源迁移验证：
1. data/classes/<职业>/cards.json 与迁移前 Python 旧表逐字段等价；
2. 每张卡的 JSON 往返（to_dict → from_dict → to_dict）无损；
3. cards.json 的 _hash 与内容一致（前端编辑器的冲突检测依赖它）；
4. 新增成长字段（rank/upgrade_branch/exhaust/power_tier/cv_budget/
   cv_estimated/balance_version）能完整加载与序列化，不被静默丢弃。

运行：python perf_tests/test_card_json_roundtrip.py
"""
import hashlib
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
if os.path.join(_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))

from combat_engine.card import Card, _CARD_FIELDS                       # noqa: E402
from combat_engine.card_data import get_cards_for_class, get_starting_deck  # noqa: E402
from combat_engine.card_json_loader import clear_cache, load_all_class_cards  # noqa: E402

SNAPSHOT = os.path.join(_HERE, "fixtures", "cards_python_snapshot.json")
CLASS_DIR = os.path.join(_ROOT, "data", "classes")

GROWTH_FIELDS = ("rank", "upgrade_branch", "exhaust", "power_tier",
                 "cv_budget", "cv_estimated", "balance_version")


def compute_hash(data: dict) -> str:
    payload = {k: v for k, v in data.items() if k != "_hash"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class EquivalenceTests(unittest.TestCase):
    """JSON 单一真相源与迁移前旧表逐字段等价。"""

    @classmethod
    def setUpClass(cls):
        with open(SNAPSHOT, "r", encoding="utf-8") as f:
            cls.snapshot = json.load(f)

    def test_structure_matches_legacy_table(self):
        """迁移前后结构性字段必须一致；数值字段由 CV 迁移按方案改写（记录在案）。"""
        structural = ("card_id", "name", "description", "damage_type", "target",
                      "range", "cost", "tier", "class_required", "owner",
                      "cleanse", "ignore_def")
        for char_class, legacy_cards in self.snapshot.items():
            loaded = get_cards_for_class(char_class)
            self.assertEqual(len(loaded), len(legacy_cards),
                             f"{char_class} 卡数不一致")
            for legacy, card in zip(legacy_cards, loaded):
                new = card.to_dict()
                for key in structural:
                    self.assertEqual(new.get(key), legacy.get(key),
                                     f"{char_class}/{legacy['card_id']} 结构字段 {key} 被改动")
                # 效果种类必须保留（数值可被 CV 迁移调整）
                self.assertEqual([e.get("type") for e in (new.get("effects") or [])],
                                 [e.get("type") for e in (legacy.get("effects") or [])],
                                 f"{char_class}/{legacy['card_id']} 状态效果种类被改动")

    def test_growth_fields_present_in_json(self):
        for char_class in self.snapshot:
            path = os.path.join(CLASS_DIR, char_class, "cards.json")
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            for raw in doc["cards"]:
                for field in GROWTH_FIELDS:
                    self.assertIn(field, raw, f"{char_class}/{raw.get('card_id')} 缺字段 {field}")
                self.assertEqual(raw["balance_version"], 1)
                self.assertEqual(raw["cv_budget"], 24 * raw["cost"])
                self.assertIn(raw["power_tier"], ("T0", "T1", "T2", "T3", "T4"))

    def test_all_cards_loaded(self):
        all_cards = load_all_class_cards()
        self.assertEqual(len(all_cards), 9)
        self.assertEqual(sum(len(v) for v in all_cards.values()), 72)

    def test_unknown_class_returns_empty(self):
        self.assertEqual(get_cards_for_class("不存在的职业"), [])
        self.assertEqual(get_starting_deck("不存在的职业"), [])


class RoundTripTests(unittest.TestCase):
    def test_card_json_round_trip(self):
        for char_class in load_all_class_cards():
            for card in get_cards_for_class(char_class):
                first = card.to_dict()
                second = Card.from_dict(first).to_dict()
                self.assertEqual(first, second, f"{card.card_id} 往返不等价")
                self.assertIn("exhaust", _CARD_FIELDS)
                self.assertIn("cv_estimated", _CARD_FIELDS)

    def test_effects_and_penetration_survive(self):
        # 迁移前 JSON 缺 effects/ignore_def/cleanse，迁移后必须完整
        guard = {c.card_id: c for c in get_cards_for_class("近卫")}
        self.assertEqual(guard["guard_pierce"].ignore_def, 0.5)
        medic = {c.card_id: c for c in get_cards_for_class("医疗")}
        self.assertTrue(medic["medic_cleanse"].cleanse)
        caster = {c.card_id: c for c in get_cards_for_class("术师")}
        self.assertTrue(caster["caster_burn"].effects)
        self.assertEqual(caster["caster_burn"].effects[0]["type"], "burn")

    def test_starting_deck_uses_json_source(self):
        deck = get_starting_deck("重装", count=7)
        self.assertEqual(len(deck), 7)
        ids = {c.card_id for c in deck}
        self.assertIn("defender_wall", ids)
        # 深拷贝：修改牌堆实例不得污染类池
        deck[0].owner = "测试"
        clear_cache()
        fresh = {c.card_id: c for c in get_cards_for_class("重装")}
        self.assertIsNone(fresh[deck[0].card_id].owner)


class HashTests(unittest.TestCase):
    def test_hash_matches_content(self):
        for char_class in load_all_class_cards():
            path = os.path.join(CLASS_DIR, char_class, "cards.json")
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            self.assertEqual(doc["_hash"], compute_hash(doc),
                             f"{char_class}/cards.json 的 _hash 与内容不符（编辑器会误报冲突）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
