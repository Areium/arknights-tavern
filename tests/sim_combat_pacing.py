# -*- coding: utf-8 -*-
"""战斗节奏模拟器 —— 贪心玩家 AI vs 引擎敌人 AI，统计战斗结束回合数。

用途：验证「攻击数值 ×2 后战斗是否能在 4 回合内结束」。
本脚本只读游戏数据（data/）+ 调用真实引擎（src/combat_engine/），不改动任何游戏文件。

用法：
    python tests/sim_combat_pacing.py                        # 基线（当前数据）
    python tests/sim_combat_pacing.py --patk-mult 2          # 我方攻击 ×2
    python tests/sim_combat_pacing.py --patk-mult 2 --enemy-atk-mult 2
    python tests/sim_combat_pacing.py --card-mult 2          # 卡牌基础伤害 ×2
    python tests/sim_combat_pacing.py --runs 50 --seed 7
"""

import argparse
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from combat_session import CombatSession  # noqa: E402
from combat_engine.grid import range_between, resolve_targets  # noqa: E402

DEFAULT_PARTY = ["阿米娅", "银灰", "陈", "闪灵"]
DEFAULT_ENCOUNTER = "初遇整合运动"


# ── 辅助 ──

def _alive(engine, team):
    return [u for u in engine.units.values() if u.team == team and u.is_alive]


def _affected_enemies(engine, owner, card, target_pos):
    """卡牌在 target_pos 处实际覆盖到的敌方单位（含射程过滤）。"""
    if card.target == "ALL_ALLIES":
        return []
    if card.target == "GLOBAL":
        return _alive(engine, "enemy")
    if card.target == "LINE_3":
        dr = 0 if owner.pos[0] == target_pos[0] else (1 if target_pos[0] > owner.pos[0] else -1)
        dc = 0 if owner.pos[1] == target_pos[1] else (1 if target_pos[1] > owner.pos[1] else -1)
        if dr == 0 and dc == 0:
            dr, dc = 0, 1
        positions = resolve_targets(card.target, target_pos, direction=(dr, dc))
    else:
        positions = resolve_targets(card.target, target_pos)

    hit = []
    for pos in positions:
        if card.range >= 0 and range_between(owner.pos, pos) > card.range:
            continue
        target = engine.grid.get_unit_at(pos)
        if target and target.team == "enemy" and target.is_alive:
            hit.append(target)
    return hit


def _estimated_damage(engine, owner, card, target):
    """复用引擎的伤害估算（不掷骰）：命中后期望伤害。"""
    lo, hi = engine._estimate_card_damage(owner, card, target)
    return (lo + hi) / 2.0


def _best_play(engine):
    """挑一张期望总伤害最高的可打出卡牌；返回 (card_index, target_pos) 或 None。"""
    pool = engine.shared_pool
    if not pool:
        return None
    players = {u.name: u for u in _alive(engine, "player")}
    enemies = _alive(engine, "enemy")
    if not enemies:
        return None

    best = None
    best_score = 0.0
    for idx, card in enumerate(pool.hand):
        owner = players.get(card.owner)
        if not owner:
            continue
        if card.class_required not in ("any", "", None) and card.class_required != owner.char_class:
            continue
        if card.cost > owner.AP + engine.shared_ap:
            continue

        if card.damage_type == "healing":
            # 只在有人明显掉血时治疗，避免浪费 AP
            for ally in _alive(engine, "player"):
                if ally.hp >= ally.max_hp * 0.7:
                    continue
                lo, hi = card.min_damage, card.max_damage
                score = (lo + hi) / 2.0
                if score > best_score:
                    best_score = score
                    best = (idx, ally.pos)
            continue

        for enemy in enemies:
            if card.range >= 0 and range_between(owner.pos, enemy.pos) > card.range:
                continue
            hits = _affected_enemies(engine, owner, card, enemy.pos)
            if not hits:
                continue
            score = sum(_estimated_damage(engine, owner, card, t) for t in hits)
            if score > best_score:
                best_score = score
                best = (idx, enemy.pos)
    return best


def _move_toward(engine, unit, target_pos, max_step):
    """朝目标走 max_step 格（切比雪夫），落点必须是空格；找不到就原地不动。"""
    r, c = unit.pos
    tr, tc = target_pos
    for step in range(max_step, 0, -1):
        nr = r + max(-step, min(step, tr - r))
        nc = c + max(-step, min(step, tc - c))
        if (nr, nc) == unit.pos:
            continue
        if not engine.grid.is_valid_position((nr, nc), unit.team):
            continue
        if engine.grid.get_unit_at((nr, nc)):
            continue
        return (nr, nc)
    return unit.pos


def _reposition_once(cs, verbose=False):
    """把一个打不到敌人的单位朝最近敌人挪一步；成功返回 True。"""
    engine = cs.engine
    enemies = _alive(engine, "enemy")
    if not enemies:
        return False
    for unit in _alive(engine, "player"):
        if unit.AP <= 0:
            continue
        nearest = min(enemies, key=lambda e: range_between(unit.pos, e.pos))
        if range_between(unit.pos, nearest.pos) <= 1:
            continue
        new_pos = _move_toward(engine, unit, nearest.pos, unit.mobility // 2)
        if new_pos == unit.pos:
            continue
        r = cs.handle_action({"action": "move", "unit_id": unit.unit_id,
                              "target": list(new_pos)})
        if verbose and not r.get("ok"):
            print("   move 失败:", r.get("error"))
        if r.get("ok"):
            return True
    return False


def _player_round(cs, verbose=False):
    """贪心循环：能出牌就出牌，出不了牌就把够不着的单位往前挪，直到没有行动。"""
    engine = cs.engine
    actions = 0
    while not engine.is_battle_over() and actions < 200:
        actions += 1
        play = _best_play(engine)
        if play:
            idx, target = play
            r = cs.handle_action({"action": "play_card", "card_index": idx,
                                  "target": list(target)})
            if not r.get("ok"):
                if verbose:
                    print("   play_card 失败:", r.get("error"))
                break
            continue
        if not _reposition_once(cs, verbose=verbose):
            break


def _apply_multipliers(engine, patk_mult, enemy_atk_mult, card_mult):
    """按倍率缩放单位攻击 / 卡牌基础伤害（模拟数据层改动效果）。"""
    if patk_mult != 1.0:
        for u in engine.units.values():
            if u.team == "player":
                u.PATK = round(u.PATK * patk_mult)
                u.MATK = round(u.MATK * patk_mult)
    if enemy_atk_mult != 1.0:
        for u in engine.units.values():
            if u.team == "enemy":
                u.PATK = round(u.PATK * enemy_atk_mult)
                u.MATK = round(u.MATK * enemy_atk_mult)
    if card_mult != 1.0:
        pools = [engine.shared_pool] + list(engine.enemy_pools.values())
        for pool in pools:
            if not pool:
                continue
            for card in pool.deck + pool.hand + pool.discard:
                card.min_damage = round(card.min_damage * card_mult)
                card.max_damage = round(card.max_damage * card_mult)


def run_once(encounter, party, patk_mult, enemy_atk_mult, card_mult, verbose=False):
    cs = CombatSession("sim-pacing")
    cs.start(encounter, character_names=list(party))
    _apply_multipliers(cs.engine, patk_mult, enemy_atk_mult, card_mult)

    guard = 0
    while not cs.engine.is_battle_over() and guard < 100:
        guard += 1
        _player_round(cs, verbose=verbose)
        if cs.engine.is_battle_over():
            break
        cs.end_turn()

    engine = cs.engine
    players_alive = len(_alive(engine, "player"))
    enemies_alive = len(_alive(engine, "enemy"))
    enemy_hp_left = sum(u.hp for u in _alive(engine, "enemy"))
    player_hp_left = sum(u.hp for u in _alive(engine, "player"))
    return {
        "rounds": engine.state.round_num,
        "winner": engine.state.winner,
        "players_alive": players_alive,
        "enemies_alive": enemies_alive,
        "enemy_hp_left": enemy_hp_left,
        "player_hp_left": player_hp_left,
    }


def main():
    ap = argparse.ArgumentParser(description="战斗节奏模拟（只读数据，不改游戏文件）")
    ap.add_argument("--encounter", default=DEFAULT_ENCOUNTER)
    ap.add_argument("--party", default=",".join(DEFAULT_PARTY))
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--patk-mult", type=float, default=1.0, help="我方单位 PATK/MATK 倍率")
    ap.add_argument("--enemy-atk-mult", type=float, default=1.0, help="敌方单位 PATK/MATK 倍率")
    ap.add_argument("--card-mult", type=float, default=1.0, help="卡牌基础伤害倍率")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--list", action="store_true", help="逐场打印结果")
    args = ap.parse_args()

    random.seed(args.seed)
    party = [n.strip() for n in args.party.split(",") if n.strip()]

    results = [run_once(args.encounter, party, args.patk_mult, args.enemy_atk_mult,
                        args.card_mult, verbose=args.verbose)
               for _ in range(args.runs)]

    rounds = [r["rounds"] for r in results]
    wins = sum(1 for r in results if r["winner"] == "player")
    within4 = sum(1 for r in results if r["winner"] == "player" and r["rounds"] <= 4)

    if args.list:
        for i, r in enumerate(results, 1):
            print(f"  #{i:02d} rounds={r['rounds']:>3} winner={r['winner']:<8} "
                  f"敌存活={r['enemies_alive']} 敌余HP={r['enemy_hp_left']:>4} "
                  f"我存活={r['players_alive']} 我余HP={r['player_hp_left']:>4}")

    print("=" * 72)
    print(f"遭遇战: {args.encounter}   队伍: {', '.join(party)}   样本: {args.runs}")
    print(f"倍率: 我方ATK ×{args.patk_mult}  敌方ATK ×{args.enemy_atk_mult}  卡牌伤害 ×{args.card_mult}")
    print("-" * 72)
    print(f"我方胜率        : {wins}/{args.runs} ({wins / args.runs:.0%})")
    print(f"≤4 回合获胜占比 : {within4}/{args.runs} ({within4 / args.runs:.0%})")
    print(f"回合数          : min={min(rounds)}  中位数={statistics.median(rounds)}  "
          f"mean={statistics.mean(rounds):.2f}  max={max(rounds)}")
    print(f"平均剩余敌HP    : {statistics.mean(r['enemy_hp_left'] for r in results):.1f}")
    print(f"平均剩余我方HP  : {statistics.mean(r['player_hp_left'] for r in results):.1f}")
    print("=" * 72)


if __name__ == "__main__":
    main()
