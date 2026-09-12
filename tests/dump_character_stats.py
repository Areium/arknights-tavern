# -*- coding: utf-8 -*-
"""打印全部角色卡的属性派生战斗数值（只读，用于改动前后对照）。

用法：python tests/dump_character_stats.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import frontmatter  # noqa: E402
from combat_engine.entity import CombatUnit  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHARS = ROOT / "data" / "characters"


def main():
    rows = []
    for card in sorted(CHARS.glob("*/index.md")):
        meta = frontmatter.load(str(card)).metadata
        attrs = meta.get("attributes", {}) or {}
        unit = CombatUnit.from_character_metadata(meta, team="player")
        rows.append((
            meta.get("name", card.parent.name),
            unit.char_class,
            attrs.get("战场机动"),
            attrs.get("物理强度"),
            attrs.get("战斗技巧"),
            attrs.get("源石技艺适应性"),
            attrs.get("战术规划"),
            int(unit.PATK), int(unit.MATK), int(unit.HEAL),
            unit.max_hp, unit.DEF, unit.RES, unit.SPD, unit.HIT, unit.EVA,
            unit.mobility // 2, unit.MAX_AP,
        ))

    header = ("角色", "职业", "机动", "强度", "技巧", "技艺", "规划",
              "PATK", "MATK", "HEAL", "HP", "DEF", "RES", "SPD", "HIT", "EVA",
              "移动格", "pAP")
    print(" | ".join(header))
    print("-" * 150)
    for r in rows:
        print(" | ".join(str(x) for x in r))
    print("-" * 150)
    print(f"角色卡数量: {len(rows)}")


if __name__ == "__main__":
    main()
