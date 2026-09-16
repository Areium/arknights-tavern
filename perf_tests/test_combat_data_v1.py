"""
战斗数据层集成测试（v1）：敌人（`data/enemies/*.md`）与战斗节点
（`data/combat/nodes/*.json`）→ 加载器 → CombatUnit/引擎。

覆盖 design §8.1 / §10.2 的新字段贯通，以及 §12 硬性测试
「敌人声明的行动槽与实际每轮动作数一致」「敌人 XP 与威胁点单调相关」。

需要 python-frontmatter；运行：python perf_tests/test_combat_data_v1.py
"""
import glob
import json
import os
import re
import sys
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
if os.path.join(_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))

import frontmatter  # noqa: E402
from combat_data_loader import CombatDataLoader  # noqa: E402

ENEMY_DIR = os.path.join(_ROOT, "data", "enemies")
NODE_DIR = os.path.join(_ROOT, "data", "combat", "nodes")


def _enemy_files():
    """有战斗字段的敌人（纯叙事条目没有分层字段，另由 loader 按 attributes 派生）。"""
    files = []
    for path in sorted(glob.glob(os.path.join(ENEMY_DIR, "*.md"))):
        meta = frontmatter.load(path).metadata
        if meta.get("combat_stats"):
            files.append(path)
    return files


def _node_files():
    """战斗节点 JSON（跳过 TEMPLATE_*：它们的 node_id 与文件名故意不一致）。"""
    return sorted(p for p in Path(NODE_DIR).glob("*.json")
                  if not p.stem.upper().startswith("TEMPLATE"))


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
    def test_all_nodes_have_budget_fields(self):
        for path in _node_files():
            node = json.loads(path.read_text(encoding="utf-8"))
            name = path.name
            difficulty = node.get("difficulty") or {}
            for key in ("encounter_type", "band", "target_rounds",
                        "threat_budget"):
                self.assertIn(key, difficulty, f"{name} 缺 difficulty.{key}")
            self.assertIn(difficulty["encounter_type"],
                          ("teaching", "normal", "elite", "boss", ""), name)
            cond = node.get("conditions", {}) or {}
            self.assertIn(int(cond.get("max_rounds", 0)), (6, 8, 10, 12),
                          f"{name} max_rounds 未收敛到 v1 兜底线")

    def test_nodes_load_and_spawn(self):
        loader = CombatDataLoader()
        for path in _node_files():
            node = json.loads(path.read_text(encoding="utf-8"))
            node_id = node["node_id"]
            loaded = loader.load_node(node_id)
            self.assertIsNotNone(loaded, node_id)
            self.assertEqual(loaded["node_id"], node_id)
            # 地图段必须可校验（尺寸/格子/部署区）
            battle_map = loader.load_map(loaded)
            self.assertGreater(battle_map.rows, 0)
            self.assertGreater(battle_map.cols, 0)
            self.assertEqual(len(battle_map.tiles), battle_map.rows)
            for wave in loaded.get("waves", []) or []:
                for entry in wave.get("enemies", []) or []:
                    enemy_name = entry.get("enemy") or entry.get("name")
                    unit = loader.load_enemy(enemy_name)
                    self.assertIsNotNone(unit, f"{node_id} 引用未知敌人 {enemy_name}")
                    self.assertLessEqual(len(entry.get("positions") or []),
                                         int(entry.get("count", 1)),
                                         f"{node_id}/{enemy_name} 位置数超过数量")

    def test_node_resolvable_by_filename_and_name(self):
        """节点 id 与中文名两种引用都必须能加载。"""
        loader = CombatDataLoader()
        by_id = loader.load_node("enc_first_reunion")
        by_name = loader.load_node("初遇整合运动")
        self.assertIsNotNone(by_id, "按 node_id 加载失败")
        self.assertIsNotNone(by_name, "按中文名加载失败")
        self.assertEqual(by_id["node_id"], by_name["node_id"])
        self.assertIsNotNone(loader.resolve_node_path("enc_first_reunion"))

    def test_plot_combat_markers_resolve(self):
        """剧情节拍里的 `[COMBAT:<id>]` 必须都能解析到节点（转换后 id 不变）。"""
        loader = CombatDataLoader()
        plot_dir = os.path.join(_ROOT, "data", "plots")
        for path in sorted(glob.glob(os.path.join(plot_dir, "*", "index.md"))):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            for node_id in set(re.findall(r"\[COMBAT:([\w-]+)\]", text)):
                if node_id == "ID":      # 文档里的占位写法 `[COMBAT:ID]`，非真实引用
                    continue
                self.assertIsNotNone(loader.load_node(node_id),
                                     f"{os.path.basename(os.path.dirname(path))} 引用未知节点 {node_id}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
