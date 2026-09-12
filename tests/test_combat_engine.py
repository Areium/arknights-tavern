# -*- coding: utf-8 -*-
"""战斗引擎：敌人意图 + SPD 行动顺序 测试。

运行：python -m pytest tests/test_combat_engine.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from combat_engine.engine import CombatEngine  # noqa: E402
from combat_engine.entity import CombatUnit  # noqa: E402
from combat_engine.card_data import get_starting_deck  # noqa: E402


def _player(name, pos, hp=100, atk=12):
    return CombatUnit(
        unit_id=name, name=name, team="player", char_class="近卫",
        max_hp=hp, hp=hp, PATK=atk, MATK=atk, DEF=5, RES=5,
        SPD=10, HIT=6, EVA=5, AP=3, MAX_AP=3,
        attributes={"physical_strength": 5, "combat_skill": 5},
        pos=pos,
    )


def _enemy(name, pos, spd=8, ai="aggressive", hp=80, patk=10):
    e = CombatUnit.create_enemy(
        name=name, char_class="近卫", hp=hp, patk=patk,
        defense=4, resist=4, spd=spd, hit=4, eva=4, max_ap=3,
        ai_behavior=ai,
    )
    e.pos = pos
    return e


def _make_engine(players, enemies):
    eng = CombatEngine()
    for p in players:
        eng.add_player_unit(p, get_starting_deck("近卫", 7), p.pos)
    for e in enemies:
        eng.add_enemy_unit(e, e.pos)
    eng.start_battle()
    return eng


def test_intents_populated_at_round_start():
    eng = _make_engine(
        [_player("A", (3, 0)), _player("B", (4, 0))],
        [_enemy("fast", (3, 1), spd=12), _enemy("slow", (4, 1), spd=6)],
    )
    intents = eng.state.enemy_intents
    assert set(intents.keys()) == {"fast", "slow"}
    for it in intents.values():
        assert it["type"] in ("attack", "heavy", "aoe", "move", "defend")
        assert it["label"]


def test_aggressive_enemy_moves_when_out_of_range():
    # 敌人在第 5 列，玩家在第 0 列，近战范围 1 → 够不着 → aggressive 应「移动」逼近
    eng = _make_engine(
        [_player("A", (3, 0))],
        [_enemy("chaser", (3, 5), spd=10, ai="aggressive")],
    )
    assert eng.state.enemy_intents["chaser"]["type"] == "move"


def test_defensive_enemy_holds_when_out_of_range():
    # 同为够不着：defensive 敌人应「坚守」而非追击
    eng = _make_engine(
        [_player("A", (3, 0))],
        [_enemy("guard", (3, 5), spd=6, ai="defensive")],
    )
    assert eng.state.enemy_intents["guard"]["type"] == "defend"


def test_attack_intent_carries_target_and_damage():
    eng = _make_engine(
        [_player("A", (3, 0))],
        [_enemy("raider", (3, 1), spd=9, ai="aggressive")],
    )
    it = eng.state.enemy_intents["raider"]
    assert it["type"] in ("attack", "heavy", "aoe")
    assert it["target_id"] == "A"
    assert it["card_id"]
    assert it["damage_min"] is not None and it["damage_max"] >= it["damage_min"]


def test_enemy_turns_ordered_by_spd(monkeypatch):
    # 两个敌人相邻且都能打到玩家：高 SPD 应先行动
    import combat_engine.dice as dice_mod
    monkeypatch.setattr(dice_mod, "roll_d20", lambda: 10)  # 固定命中，消除随机性
    eng = _make_engine(
        [_player("A", (3, 0)), _player("B", (4, 0))],
        [_enemy("fast", (3, 1), spd=12), _enemy("slow", (4, 1), spd=6)],
    )
    eng.end_player_round()
    damage_casters = [
        ev.data.get("caster") for ev in eng.state.events if ev.type == "damage"
    ]
    assert damage_casters, "应产生伤害事件"
    assert damage_casters[0] == "fast", f"高 SPD 敌人应先行动，实际 {damage_casters}"


def test_get_state_exposes_enemy_intents():
    from combat_session import CombatSession
    cs = CombatSession("sess-test")
    state = cs.start(
        "enc_training",
        character_names=["阿米娅", "银灰", "霜星", "陈"],
    )
    intents = state.get("enemy_intents", {})
    assert isinstance(intents, dict) and intents
    for it in intents.values():
        assert "type" in it and "label" in it
