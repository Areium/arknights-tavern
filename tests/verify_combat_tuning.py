# -*- coding: utf-8 -*-
"""战斗数值调参验收脚本（只读，不修改任何游戏文件）。

对照 git HEAD（改动前）验证三项断言：
  1. 我方角色卡：PATK / MATK 恰好 ×2，HP / DEF / RES / HEAL 不变；
  2. 我方角色卡：移动格数 = floor(战场机动 / 2) 恰好 +1（引擎 move_unit 实际判定）；
  3. 敌人卡：combat_stats.patk / matk 恰好 ×2，其余字段不变。

用法：python tests/verify_combat_tuning.py
退出码 0 = 全部通过。
"""

import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "src"))

import frontmatter  # noqa: E402
from combat_engine.entity import CombatUnit  # noqa: E402
from combat_engine.card_data import get_starting_deck  # noqa: E402
from combat_engine.engine import CombatEngine  # noqa: E402
from combat_data_loader import CombatDataLoader  # noqa: E402
from combat_session import CombatSession  # noqa: E402

failures: list[str] = []
notes: list[str] = []

# 调参前的基线提交（改动前的 main）；用 --base 可指定其它对照点。
BASE_REF = "431e363"


def git_show(rel: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_REF}:{rel}"],
                          capture_output=True, text=True, encoding="utf-8").stdout


def load_meta_from_text(text: str) -> dict:
    import io
    return frontmatter.load(io.StringIO(text)).metadata


def check(cond: bool, msg: str):
    if not cond:
        failures.append(msg)


def check_character_cards():
    print("─" * 100)
    print("① 角色卡：攻击 ×2 / 移动格 +1")
    print(f"{'角色':<16}{'PATK 旧→新':>16}{'MATK 旧→新':>16}{'移动格 旧→新':>16}"
          f"{'HP/DEF/RES/HEAL':>18}{'SPD/HIT/EVA/pAP 变化':>26}")
    for card in sorted((ROOT / "data" / "characters").glob("*/index.md")):
        rel = card.relative_to(ROOT).as_posix()
        name = card.parent.name
        old = load_meta_from_text(git_show(rel))
        new = frontmatter.load(str(card)).metadata
        u_old = CombatUnit.from_character_metadata(old, team="player")
        u_new = CombatUnit.from_character_metadata(new, team="player")

        check(u_new.PATK == 2 * u_old.PATK,
              f"{name}: PATK 不是 ×2（{u_old.PATK} → {u_new.PATK}）")
        check(u_new.MATK == 2 * u_old.MATK,
              f"{name}: MATK 不是 ×2（{u_old.MATK} → {u_new.MATK}）")
        for attr in ("max_hp", "DEF", "RES", "HEAL"):
            check(getattr(u_new, attr) == getattr(u_old, attr),
                  f"{name}: {attr} 被意外改动（{getattr(u_old, attr)} → {getattr(u_new, attr)}）")
        check(u_new.mobility // 2 == u_old.mobility // 2 + 1,
              f"{name}: 移动格不是 +1（{u_old.mobility // 2} → {u_new.mobility // 2}）")

        deltas = []
        for attr in ("SPD", "HIT", "EVA", "MAX_AP"):
            if getattr(u_new, attr) != getattr(u_old, attr):
                deltas.append(f"{attr} {getattr(u_old, attr)}→{getattr(u_new, attr)}")
        patk_txt = f"{u_old.PATK} → {u_new.PATK}"
        matk_txt = f"{u_old.MATK} → {u_new.MATK}"
        move_txt = f"{u_old.mobility // 2} → {u_new.mobility // 2}"
        print(f"{name:<16}{patk_txt:>16}{matk_txt:>16}{move_txt:>16}"
              f"{'不变 ✓':>18}{(', '.join(deltas) or '不变'):>26}")
        if deltas:
            notes.append(f"{name}: 战场机动派生项随之变化 —— {', '.join(deltas)}")


def check_enemy_cards():
    print("─" * 100)
    print("② 敌人卡：攻击 ×2，其余字段不变")
    print(f"{'敌人':<16}{'patk 旧→新':>16}{'matk 旧→新':>16}{'其余字段':>14}")
    for card in sorted((ROOT / "data" / "combat" / "enemies").glob("*.md")):
        rel = card.relative_to(ROOT).as_posix()
        name = card.stem
        old = load_meta_from_text(git_show(rel)).get("combat_stats", {})
        new = frontmatter.load(str(card)).metadata.get("combat_stats", {})
        check(new.get("patk") == 2 * old.get("patk"),
              f"{name}: patk 不是 ×2（{old.get('patk')} → {new.get('patk')}）")
        check(new.get("matk") == 2 * old.get("matk"),
              f"{name}: matk 不是 ×2（{old.get('matk')} → {new.get('matk')}）")
        for key in ("hp", "defense", "resist", "spd", "hit", "eva", "max_ap"):
            check(new.get(key) == old.get(key),
                  f"{name}: {key} 被意外改动（{old.get(key)} → {new.get(key)}）")
        old_patk, new_patk = old.get("patk"), new.get("patk")
        old_matk, new_matk = old.get("matk"), new.get("matk")
        print(f"{name:<16}{f'{old_patk} → {new_patk}':>16}"
              f"{f'{old_matk} → {new_matk}':>16}{'不变 ✓':>14}")


def check_loader_roundtrip():
    """端到端：CombatDataLoader 从敌人卡加载出的 PATK/MATK = 卡面值（×2 后）。"""
    print("─" * 100)
    print("④ 端到端：CombatDataLoader 加载敌人卡的攻击数值")
    loader = CombatDataLoader()
    for name in ("整合运动士兵", "冰原狂战士", "整合运动术师"):
        meta = frontmatter.load(str(ROOT / "data" / "combat" / "enemies" / f"{name}.md")).metadata
        stats = meta.get("combat_stats", {})
        unit = loader.load_enemy(name)
        check(unit is not None and unit.PATK == stats.get("patk"),
              f"{name}: 加载后 PATK={getattr(unit, 'PATK', None)} ≠ 卡面 {stats.get('patk')}")
        check(unit is not None and unit.MATK == stats.get("matk"),
              f"{name}: 加载后 MATK={getattr(unit, 'MATK', None)} ≠ 卡面 {stats.get('matk')}")
        print(f"{name:<16}PATK={unit.PATK:<6}MATK={unit.MATK:<6}（卡面 {stats.get('patk')}/"
              f"{stats.get('matk')}）✓")


def check_player_roundtrip():
    """端到端：CombatSession.start 建出的我方单位攻击数值 = 角色卡 combat_stats。"""
    print("─" * 100)
    print("⑤ 端到端：CombatSession 建出的我方单位攻击数值")
    cs = CombatSession("verify-tuning")
    state = cs.start("初遇整合运动", character_names=["阿米娅", "银灰", "陈", "闪灵"])
    for u in state["units"]:
        if u["team"] != "player":
            continue
        meta = frontmatter.load(str(ROOT / "data" / "characters" / u["name"] / "index.md")).metadata
        cs_meta = meta.get("combat_stats", {})
        check(u["patk"] == cs_meta.get("patk"),
              f"{u['name']}: 战斗中 PATK={u['patk']} ≠ 卡面 {cs_meta.get('patk')}")
        check(u["matk"] == cs_meta.get("matk"),
              f"{u['name']}: 战斗中 MATK={u['matk']} ≠ 卡面 {cs_meta.get('matk')}")
        print(f"{u['name']:<8}PATK={u['patk']:<5}MATK={u['matk']:<5}"
              f"移动 {u['mobility'] // 2} 格（机动 {u['mobility']}）✓")

def check_engine_move_range():
    """端到端：引擎实际接受的移动距离 = 新格数，且旧格数已不再够用。"""
    print("─" * 100)
    print("③ 引擎端到端：move_unit 实际可移动距离")
    for name, old_grids, new_grids in (("阿米娅", 2, 3), ("陈", 4, 5), ("大长老", 1, 2)):
        meta = frontmatter.load(str(ROOT / "data" / "characters" / name / "index.md")).metadata
        unit = CombatUnit.from_character_metadata(meta, team="player")
        eng = CombatEngine()
        eng.add_player_unit(unit, get_starting_deck(unit.char_class, 7), (3, 0))
        eng.start_battle()
        unit.AP = 9
        eng.shared_ap = 9
        far = (3, new_grids)
        beyond = (3, new_grids + 1)
        ok_new = eng.move_unit(unit.unit_id, far)
        unit.pos = (3, 0)
        eng.grid.place_unit(unit, (3, 0))
        unit.AP = 9
        ok_beyond = eng.move_unit(unit.unit_id, beyond)
        check(ok_new, f"{name}: 移动 {new_grids} 格被拒绝")
        check(not ok_beyond, f"{name}: 移动 {new_grids + 1} 格被接受（超出预期）")
        print(f"{name:<16}机动={unit.mobility}  可移动 {old_grids}→{new_grids} 格："
              f"走 {new_grids} 格 {'✓ 允许' if ok_new else '✗ 被拒'}，"
              f"走 {new_grids + 1} 格 {'✓ 被拒' if not ok_beyond else '✗ 被接受'}")


def main():
    global BASE_REF
    for i, arg in enumerate(sys.argv):
        if arg == "--base" and i + 1 < len(sys.argv):
            BASE_REF = sys.argv[i + 1]
    print("=" * 100)
    print(f"战斗数值调参验收（基线 = git {BASE_REF}）")
    print("=" * 100)
    check_character_cards()
    check_enemy_cards()
    check_engine_move_range()
    check_loader_roundtrip()
    check_player_roundtrip()

    if notes:
        print("─" * 100)
        print("已知派生项变化（战场机动同时驱动 SPD/HIT/EVA/pAP，属属性系统的必然联动）：")
        for n in notes:
            print(f"  · {n}")

    print("=" * 100)
    if failures:
        print(f"✗ 失败 {len(failures)} 项：")
        for f in failures:
            print(f"  · {f}")
        return 1
    print("✓ 全部断言通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
