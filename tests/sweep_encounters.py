# -*- coding: utf-8 -*-
"""跨遭遇战 / 队伍的节奏扫描：验证「4 回合内结束」的适用范围（只读）。

用法：python tests/sweep_encounters.py [--runs 15]
"""

import argparse
import os
import random
import statistics
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

import frontmatter  # noqa: E402
import sim_combat_pacing as sim  # noqa: E402

ROOT = Path(_HERE).resolve().parent
ENCOUNTERS = ROOT / "data" / "combat" / "encounters"
ENEMIES = ROOT / "data" / "combat" / "enemies"

PARTIES = {
    "标准队(阿米娅/银灰/陈/闪灵)": ["阿米娅", "银灰", "陈", "闪灵"],
    "指挥队(博士/阿米娅/银灰/临光)": ["博士", "阿米娅", "银灰", "临光"],
    "低星队(佐菲娅/初雪/灵知/瑕光)": ["佐菲娅", "初雪", "灵知", "瑕光"],
}


def enemy_hp(name):
    meta = frontmatter.load(str(ENEMIES / f"{name}.md")).metadata
    return int(meta.get("combat_stats", {}).get("hp", 0))


def encounter_profile(eid):
    meta = frontmatter.load(str(ENCOUNTERS / f"{eid}.md")).metadata
    waves = meta.get("waves", []) or []
    total, comp = 0, []
    for w in waves:
        for e in w.get("enemies", []) or []:
            n = int(e.get("count", 1))
            hp = enemy_hp(e.get("enemy", ""))
            total += hp * n
            comp.append(f"{e.get('enemy')}×{n}")
    return len(waves), total, ", ".join(comp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--seed", type=int, default=20260910)
    args = ap.parse_args()

    ids = sorted(p.stem for p in ENCOUNTERS.glob("*.md") if not p.stem.startswith("TEMPLATE"))
    for party_name, party in PARTIES.items():
        print("=" * 108)
        print(f"队伍: {party_name}")
        print(f"{'遭遇战':<24}{'波次':>4}{'敌总HP':>8}{'样本':>5}{'胜率':>7}{'≤4回合':>8}"
              f"{'中位':>6}{'最大':>6}   敌人构成")
        print("-" * 108)
        for eid in ids:
            random.seed(args.seed)
            results = [sim.run_once(eid, party, 1.0, 1.0, 1.0) for _ in range(args.runs)]
            rounds = [r["rounds"] for r in results]
            wins = sum(1 for r in results if r["winner"] == "player")
            within4 = sum(1 for r in results
                          if r["winner"] == "player" and r["rounds"] <= 4)
            waves, hp, comp = encounter_profile(eid)
            print(f"{eid:<24}{waves:>4}{hp:>8}{args.runs:>5}{wins / args.runs:>7.0%}"
                  f"{within4 / args.runs:>8.0%}{statistics.median(rounds):>6}"
                  f"{max(rounds):>6}   {comp}")


if __name__ == "__main__":
    main()
