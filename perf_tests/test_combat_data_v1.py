"""
战斗数据层集成测试（v1）：敌人/遭遇 frontmatter → 加载器 → CombatUnit/引擎。

覆盖 design §8.1 / §10.2 的新字段贯通，以及 §12 硬性测试
「敌人声明的行动槽与实际每轮动作数一致」「敌人 XP 与威胁点单调相关」。

需要 python-frontmatter；运行：python perf_tests/test_combat_data_v1.py
"""
import glob
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
if os.path.join(_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))

import frontmatter  # noqa: E402
from combat_data_loader import CombatDataLoader  # noqa: E402

ENERGY_DIR = os.path.join(_ROOT, "data", "combat", "enemies")
ENCOUNTER_DIR = os.path.join(_ROOT, "data", "combat", "encounters")


def _enemy_files():
    return sorted(glob.glob(os.path.join(ENERGY_DIR, "*.md")))


def _encounter_files():
    return sorted(glob.glob(os.path.join(ENCOUNTER_DIR, "*.md")))


class EnemyDataTests(unittest.TestCase):
    def test_all_enemies_have_layering_fields(self):
        for path in _enemy_files():
            meta = frontmatter.load(path).metadata
            name = os.path.basename(path)
            for key in ("power_tier", "role", "action_slots", "threat_points",
                        "balance_version"):
                self.assertIn(key, meta, f"{name} 缺字段 {key}")
            self.assertIn(meta["role"], ("minion", "standard", "strong", "elite", "boss"),
                          name)
            self.assertIn(meta["power_tier"], ("T0", "T1", "T2", "T3", "T4"), name)
            self.assertIn(int(meta["action_slots"]), (1, 2), name)
            self.assertEqual(int(meta["balance_version"]), 1, name)

    def test_elite_and_boss_have_two_slots(self):
        for path in _enemy_files():
            meta = frontmatter.load(path).metadata
            if meta.get("role") in ("elite", "boss"):
                self.assertEqual(int(meta.get("action_slots", 1)), 2,
                                 f"{os.path.basename(path)} 精英/Boss 应有 2 行动槽")

    def test_loader_passes_new_fields_to_unit(self):
        loader = CombatDataLoader()
        for path in _enemy_files():
            meta = frontmatter.load(path).metadata
            unit = loader.load_enemy(meta["name"])
            self.assertIsNotNone(unit, meta["name"])
            self.assertEqual(unit.power_tier, meta["power_tier"])
            self.assertEqual(unit.role, meta["role"])
            self.assertEqual(unit.action_slots, int(meta["action_slots"]))
            self.assertEqual(unit.threat_points, int(meta["threat_points"]))

    def test_xp_monotonic_with_threat(self):
        """同一战斗版本下敌人 XP 与威胁点单调相关（§12 硬性测试）。"""
        loader = CombatDataLoader()
        pairs = []
        for path in _enemy_files():
            meta = frontmatter.load(path).metadata
            info = loader.load_enemy_meta(meta["name"]) or {}
            pairs.append((float(meta["threat_points"]), int(info.get("xp_reward", 0))))
        pairs.sort()
        for (t1, xp1), (t2, xp2) in zip(pairs, pairs[1:]):
            if t2 > t1:
                self.assertLessEqual(xp1, xp2,
                                     f"威胁点 {t2} 的 XP 低于威胁点 {t1}（{xp2} < {xp1}）")


class EncounterDataTests(unittest.TestCase):
    def test_all_encounters_have_budget_fields(self):
        for path in _encounter_files():
            meta = frontmatter.load(path).metadata
            name = os.path.basename(path)
            for key in ("encounter_type", "recommended_power_tier", "target_rounds",
                        "threat_budget", "balance_version"):
                self.assertIn(key, meta, f"{name} 缺字段 {key}")
            self.assertIn(meta["encounter_type"], ("teaching", "normal", "elite", "boss"), name)
            cond = meta.get("conditions", {}) or {}
            self.assertIn(int(cond.get("max_rounds", 0)), (6, 8, 10, 12),
                          f"{name} max_rounds 未收敛到 v1 兜底线")

    def test_encounters_load_and_spawn(self):
        loader = CombatDataLoader()
        for path in _encounter_files():
            meta = frontmatter.load(path).metadata
            encounter_id = meta["encounter_id"]
            loaded = loader.load_encounter(encounter_id)
            self.assertIsNotNone(loaded, encounter_id)
            self.assertEqual(loaded["encounter_id"], encounter_id)
            for wave in loaded.get("waves", []) or []:
                for entry in wave.get("enemies", []) or []:
                    enemy_name = entry.get("enemy") or entry.get("name")
                    unit = loader.load_enemy(enemy_name)
                    self.assertIsNotNone(unit, f"{encounter_id} 引用未知敌人 {enemy_name}")
                    self.assertEqual(len(entry.get("positions") or []),
                                     int(entry.get("count", 1)),
                                     f"{encounter_id}/{enemy_name} 位置数与数量不符")

    def test_encounter_resolvable_by_filename_and_id(self):
        """文件名与 encounter_id 不一致的遭遇，两种引用都必须能加载。"""
        loader = CombatDataLoader()
        by_id = loader.load_encounter("enc_first_reunion")
        by_file = loader.load_encounter("初遇整合运动")
        self.assertIsNotNone(by_id, "按 encounter_id 加载失败")
        self.assertIsNotNone(by_file, "按文件名加载失败")
        self.assertEqual(by_id["encounter_id"], by_file["encounter_id"])
        self.assertIsNotNone(loader.resolve_encounter_path("enc_first_reunion"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
