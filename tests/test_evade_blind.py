# -*- coding: utf-8 -*-
"""闪避姿态（evade）+ 致盲（blind）状态效果。

运行：python -m pytest tests/test_evade_blind.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from combat_engine import dice as dice_mod  # noqa: E402
from combat_engine.entity import CombatUnit  # noqa: E402
from combat_engine.card_data import get_cards_for_class  # noqa: E402


def _units():
    attacker = CombatUnit(unit_id="a", name="a", team="player", HIT=6)
    defender = CombatUnit(unit_id="b", name="b", team="enemy", EVA=5)
    return attacker, defender


def test_evade_raises_dc(monkeypatch):
    a, d = _units()
    monkeypatch.setattr(dice_mod, "roll_d20", lambda: 7)  # total 13 vs dc 11 → 命中
    assert dice_mod.check_hit(a, d).hit is True
    d.apply_status("evade", 2)  # dc 11→14
    r = dice_mod.check_hit(a, d)
    assert r.hit is False and r.miss is False  # 13 vs 14 → dodge


def test_blind_reduces_hit(monkeypatch):
    a, d = _units()
    monkeypatch.setattr(dice_mod, "roll_d20", lambda: 7)  # total 13 vs dc 11 → 命中
    assert dice_mod.check_hit(a, d).hit is True
    a.apply_status("blind", 2)  # HIT 6→3, total 10 vs 11 → dodge
    r = dice_mod.check_hit(a, d)
    assert r.hit is False and r.miss is False


def test_cards_declare_effects():
    cards = {c.card_id: c for c in get_cards_for_class("特种")}
    assert cards["spec_evade"].effects == [{"type": "evade", "duration": 2, "self": True}]
    assert cards["spec_smoke"].effects == [{"type": "blind", "duration": 2}]
