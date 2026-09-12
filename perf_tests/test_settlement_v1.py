"""
结算 v1 规则测试（design §9）：经验公式 / 参与度分配 / 追赶 / 成长解耦 /
奖励倍率钳制 / 敌人 XP 权重。

运行：python perf_tests/test_settlement_v1.py
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
if os.path.join(_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))

import combat_settlement as st  # noqa: E402


class FakeLoader:
    """注入用假加载器：固定敌人 XP 与掉落。"""

    def load_enemy_meta(self, name):
        return {"xp_reward": 100, "drop_rate": 0.0, "drop_items": []}


class XPCurveTests(unittest.TestCase):
    def test_xp_needed_matches_design(self):
        # 180 + 40 × (level - 1)
        self.assertEqual(st.xp_needed(1), 180)
        self.assertEqual(st.xp_needed(5), 340)
        self.assertEqual(st.xp_needed(10), 540)
        self.assertEqual(st.xp_needed(0), 180)  # 非法等级回落 1

    def test_participation_shares(self):
        self.assertEqual(st.xp_share(in_battle=True, alive=True), 1.00)
        self.assertEqual(st.xp_share(in_battle=True, alive=False), 0.70)
        self.assertEqual(st.xp_share(in_battle=False, alive=True), 0.30)

    def test_catchup_multiplier(self):
        self.assertEqual(st.catchup_multiplier(5, 8), 1.25)  # 差 3 级
        self.assertEqual(st.catchup_multiplier(6, 8), 1.0)   # 差 2 级不启用
        self.assertEqual(st.catchup_multiplier(8, 8), 1.0)
        self.assertEqual(st.catchup_multiplier(1, None), 1.0)

    def test_reward_mult_clamp(self):
        self.assertEqual(st.clamp_reward_mult(1.30), 1.20)   # 突袭上限
        self.assertEqual(st.clamp_reward_mult(1.10), 1.10)
        self.assertEqual(st.clamp_reward_mult(0.50), 0.75)   # 谈判下限
        self.assertEqual(st.clamp_reward_mult(0.20), 0.20)   # 撤退保留
        self.assertEqual(st.clamp_reward_mult(0.0), 0.0)


class GrowthDecouplingTests(unittest.TestCase):
    def test_level_up_grants_points_not_attributes(self):
        # 400 XP：1→2 花 180、2→3 花 220 → 连升 2 级、剩 0，得 2 专精点
        res = st.compute_character_growth(
            "测试", {"物理强度": 5}, {"level": 1, "xp": 0}, 400)
        self.assertEqual(res["level_after"], 3)
        self.assertEqual(res["level_delta"], 2)
        self.assertEqual(res["specialization_points_gained"], 2)
        self.assertEqual(res["attribute_changes"], [],
                         "v1 升级不得自动提升属性")
        self.assertEqual(res["xp_after"], 0)

    def test_node_unlock_every_three_levels(self):
        res = st.compute_character_growth(
            "测试", {}, {"level": 1, "xp": 0}, 2000)
        self.assertGreaterEqual(res["level_after"], 4)
        unlocked = [lu["level"] for lu in res["level_ups"] if lu["node_unlocked"]]
        self.assertTrue(unlocked, "每 3 级应解锁职业节点")
        self.assertTrue(all(lv % st.NODE_UNLOCK_EVERY == 0 for lv in unlocked))
        self.assertEqual(res["nodes_unlocked_gained"], len(unlocked))

    def test_dead_character_gets_seventy_percent(self):
        res = st.compute_character_growth(
            "测试", {}, {"level": 1, "xp": 0}, 1000, alive=False)
        self.assertEqual(res["xp_gained"], 700)
        self.assertEqual(res["xp_share"], 0.70)

    def test_reserve_character_gets_catchup(self):
        res = st.compute_character_growth(
            "测试", {}, {"level": 1, "xp": 0}, 1000,
            in_battle=False, team_max_level=6)
        self.assertEqual(res["xp_gained"], int(round(1000 * 0.30 * 1.25)))

    def test_writeback_payload_carries_spec_points(self):
        res = st.compute_character_growth(
            "测试", {}, {"level": 1, "xp": 0, "specialization_points": 2}, 400)
        payload = st.build_writeback_payload(res)
        self.assertEqual(payload["progress"]["level"], 3)
        self.assertEqual(payload["progress"]["specialization_points"], 4)
        self.assertIn("nodes_unlocked", payload["progress"])
        self.assertNotIn("metadata", payload, "无属性变化时不应写回属性覆盖")


class RewardRollTests(unittest.TestCase):
    def test_enemy_xp_weighted_and_mult_clamped(self):
        encounter = {"rewards": {"xp": 100, "items": []}}
        enemies = [{"name": "E1"}, {"name": "E2"}]  # 每个 100 XP
        rolled = st.roll_rewards(encounter, enemies, reward_mult=1.5,
                                 loader=FakeLoader())
        # (100 + 0.35 × 200) × 1.20 = 204
        self.assertEqual(rolled["enemy_xp"], 200)
        self.assertEqual(rolled["reward_mult_applied"], 1.20)
        self.assertEqual(rolled["xp"], int((100 + 0.35 * 200) * 1.20))

    def test_retreat_keeps_low_multiplier(self):
        encounter = {"rewards": {"xp": 100}}
        rolled = st.roll_rewards(encounter, [], reward_mult=0.0, loader=FakeLoader())
        self.assertEqual(rolled["xp"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
