# -*- coding: utf-8 -*-
"""复现并诊断 sim_combat_pacing 中的「打不完」回合（只读，不改游戏文件）。"""

import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

import sim_combat_pacing as sim  # noqa: E402
from combat_session import CombatSession  # noqa: E402


def trace_run(target_index, patk_mult, enemy_atk_mult, seed=20260910):
    random.seed(seed)
    for _ in range(target_index - 1):
        sim.run_once(sim.DEFAULT_ENCOUNTER, sim.DEFAULT_PARTY, patk_mult, enemy_atk_mult, 1.0)

    cs = CombatSession("sim-debug")
    cs.start(sim.DEFAULT_ENCOUNTER, character_names=list(sim.DEFAULT_PARTY))
    sim._apply_multipliers(cs.engine, patk_mult, enemy_atk_mult, 1.0)
    engine = cs.engine

    for rnd in range(1, 16):
        print(f"\n===== 回合 {engine.state.round_num} =====")
        for u in engine.units.values():
            if u.is_alive:
                print(f"  [{u.team[:2]}] {u.name:<12} pos={u.pos} hp={u.hp}/{u.max_hp} "
                      f"AP={u.AP} shared={engine.shared_ap} mob={u.mobility} "
                      f"PATK={u.PATK} MATK={u.MATK} 状态={ {k: v for k, v in u.status.items() if v} }")
        hand = engine.shared_pool.hand if engine.shared_pool else []
        print("  手牌:", [(c.name, c.owner, c.class_required, c.cost, c.range, c.damage_type)
                          for c in hand])
        play = sim._best_play(engine)
        print("  _best_play ->", None if not play else (hand[play[0]].name, hand[play[0]].owner, play[1]))
        if engine.is_battle_over():
            print("  battle over:", engine.state.winner)
            break
        sim._player_round(cs)
        if engine.is_battle_over():
            print("  battle over after player round:", engine.state.winner)
            break
        cs.end_turn()


if __name__ == "__main__":
    trace_run(8, 2.0, 2.0)
