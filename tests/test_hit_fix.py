# -*- coding: utf-8 -*-
"""命中/闪避检定修复：dodge = 0 伤害 + DC 重平衡。

运行：python -m pytest tests/test_hit_fix.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from combat_engine.dice import check_hit, compute_damage, HitResult  # noqa: E402
from combat_engine.entity import CombatUnit  # noqa: E402
from combat_engine.card import Card  # noqa: E402


def _card():
    return Card("c", "攻击", "", "physical", 10, 10, 0.5, "SINGLE", 1, 1, "basic", "any")


def _units():
    attacker = CombatUnit(unit_id="a", name="a", team="player", PATK=10, MATK=10)
    defender = CombatUnit(unit_id="b", name="b", team="enemy", DEF=5, RES=5)
    return attacker, defender


def test_dodge_deals_zero_damage():
    a, d = _units()
    dodge = HitResult(5, False, False, False)  # 未命中且非自然1
    assert compute_damage(a, d, _card(), dodge).final == 0


def test_miss_deals_zero_damage():
    a, d = _units()
    miss = HitResult(1, False, False, True)  # 自然1
    assert compute_damage(a, d, _card(), miss).final == 0


def test_hit_deals_damage():
    a, d = _units()
    hit = HitResult(15, True, False, False)
    assert compute_damage(a, d, _card(), hit).final > 0


def test_crit_doubles_damage():
    a, d = _units()
    hit = HitResult(15, True, False, False)
    crit = HitResult(20, True, True, False)
    dr_hit = compute_damage(a, d, _card(), hit)
    dr_crit = compute_damage(a, d, _card(), crit)
    assert dr_crit.final == dr_hit.final * 2


def test_dc_is_six_plus_eva(monkeypatch):
    import combat_engine.dice as dice_mod
    attacker = CombatUnit(unit_id="a", name="a", team="player", HIT=6)
    defender = CombatUnit(unit_id="b", name="b", team="enemy", EVA=8)
    # dc = 6 + 8 = 14
    monkeypatch.setattr(dice_mod, "roll_d20", lambda: 10)  # total 16 → hit
    assert check_hit(attacker, defender).hit is True
    monkeypatch.setattr(dice_mod, "roll_d20", lambda: 4)   # total 10 → dodge
    r = check_hit(attacker, defender)
    assert r.hit is False and r.miss is False
