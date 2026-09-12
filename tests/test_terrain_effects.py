"""地形效果与统一曼哈顿度量的引擎级行为。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from combat_engine.card import Card  # noqa: E402
from combat_engine.dice import HitResult, check_hit, compute_damage  # noqa: E402
from combat_engine.engine import CombatEngine  # noqa: E402
from combat_engine.entity import CombatUnit  # noqa: E402
from combat_map import resolve_map  # noqa: E402


# ── 构造助手 ──

def make_unit(name: str, team: str = "player", hp: int = 100, **stats) -> CombatUnit:
    unit = CombatUnit(unit_id=name, name=name, team=team, max_hp=hp, hp=hp,
                      char_class=stats.pop("char_class", "近卫"), **stats)
    return unit


def make_card(card_id: str = "t_strike", *, target="SINGLE", card_range=1,
              damage=10, damage_type="physical", cost=1) -> Card:
    return Card(card_id=card_id, name=card_id, description="", damage_type=damage_type,
                min_damage=damage, max_damage=damage, atk_scale=0.0,
                target=target, range=card_range, cost=cost, tier="basic")


def build_engine(tiles, *, rows=None, cols=None, rules=None, deploy=None):
    if isinstance(tiles, str):
        rows = rows or 5
        cols = cols or 5
    else:
        rows = rows or len(tiles)
        cols = cols or len(tiles[0])
    raw = {
        "rows": rows,
        "cols": cols,
        "tiles": tiles,
        "deploy": deploy or {
            "player": {"rect": [0, 0, rows - 1, 0]},
            "enemy": {"rect": [0, cols - 1, rows - 1, cols - 1]},
        },
    }
    battle_map = resolve_map(raw)
    return CombatEngine(battle_map=battle_map, rules=rules or {})


def engine_with_units(tiles, player_pos, enemy_pos, *, rules=None,
                      card=None, enemy_card=None):
    """返回 (engine, player, enemy, card)：card 必须复用同一实例（手牌校验按对象身份）。"""
    engine = build_engine(tiles, rules=rules)
    player = make_unit("P", hp=200, AP=3, MAX_AP=3)
    enemy = make_unit("E", team="enemy", hp=200)
    player_card = card or make_card()
    engine.add_player_unit(player, cards=[player_card], pos=player_pos)
    engine.add_enemy_unit(enemy, pos=enemy_pos)
    engine.start_battle()
    return engine, player, enemy, player_card


# ── 度量：射程判定 ──

def test_manhattan_range_blocks_diagonal_melee_by_default():
    engine, player, enemy, card = engine_with_units("ground", (0, 0), (1, 1))
    card.range = 1
    assert engine.distance(player.pos, enemy.pos) == 2
    assert engine.validate_card_play("P", card, enemy.pos) is not None


def test_chebyshev_metric_allows_diagonal_melee():
    engine, player, enemy, card = engine_with_units(
        "ground", (0, 0), (1, 1), rules={"range_metric": "chebyshev"})
    card.range = 1
    assert engine.distance(player.pos, enemy.pos) == 1
    assert engine.validate_card_play("P", card, enemy.pos) is None


def test_manhattan_melee_range_two_reaches_diagonals():
    """近战射程 1→2 的补偿：曼哈顿 r=2 覆盖 4 个斜角邻格。"""
    engine, player, enemy, card = engine_with_units("ground", (0, 0), (1, 1))
    card.range = 2
    assert engine.validate_card_play("P", card, enemy.pos) is None


# ── 视线 ──

def test_wall_blocks_ranged_attack():
    tiles = [
        ["ground", "wall", "ground", "ground", "ground"],
    ] * 3
    engine, player, enemy, card = engine_with_units(tiles, (1, 0), (1, 2))
    card.range = 3
    assert engine.validate_card_play("P", card, enemy.pos) == "Target is blocked by terrain"


def test_cover_in_line_does_not_block_sight_to_far_cell():
    """掩体只挡"穿过它"的视线：站在掩体上的目标仍可被瞄准。"""
    tiles = [
        ["ground", "ground", "cover", "ground", "ground"],
    ] * 3
    engine, player, enemy, card = engine_with_units(tiles, (1, 0), (1, 2))
    card.range = 3
    assert engine.validate_card_play("P", card, enemy.pos) is None


def test_melee_ignores_line_of_sight():
    tiles = [
        ["ground", "wall"],
        ["ground", "ground"],
    ]
    engine, player, enemy, card = engine_with_units(
        tiles, (0, 0), (1, 1), rules={"range_metric": "chebyshev"})
    card.range = 1
    assert engine.validate_card_play("P", card, enemy.pos) is None


# ── 伤害修正（纯函数层）──

def test_cover_defense_bonus_reduces_damage():
    attacker = make_unit("A", PATK=20)
    defender = make_unit("D", team="enemy", DEF=5)
    card = make_card(damage=10)
    hit = HitResult(10, True, False, False)
    base = compute_damage(attacker, defender, card, hit)
    covered = compute_damage(attacker, defender, card, hit,
                             {"defense_bonus": 3})
    assert covered.final == base.final - 3


def test_high_ground_damage_bonus():
    attacker = make_unit("A", PATK=20)
    defender = make_unit("D", team="enemy", DEF=5)
    card = make_card(damage=10)
    hit = HitResult(10, True, False, False)
    base = compute_damage(attacker, defender, card, hit)
    boosted = compute_damage(attacker, defender, card, hit, {"damage_bonus": 4})
    assert boosted.final == base.final + 4


def test_cover_evasion_bonus_lowers_hit_rate():
    attacker = make_unit("A", HIT=6)
    defender = make_unit("D", team="enemy", EVA=10)

    def hits(terrain):
        hit_count = 0
        for seed in range(200):
            import random
            random.seed(seed)
            if check_hit(attacker, defender, terrain).hit:
                hit_count += 1
        return hit_count

    assert hits({"evasion_bonus": 5}) < hits(None)


# ── 格子效果（引擎层）──

def test_hazard_tile_damages_on_enter():
    tiles = [
        ["ground", "hazard_fire", "ground"],
        ["ground", "ground", "ground"],
        ["ground", "ground", "ground"],
    ]
    engine, player, _, _card = engine_with_units(tiles, (0, 0), (2, 2))
    hp_before = player.hp
    assert engine.move_unit("P", (0, 1))
    assert player.hp == hp_before - 4        # hazard_fire on_enter.damage = 4
    assert any(ev.type == "damage" and ev.data.get("source_type") == "terrain"
               for ev in engine.state.events)


def test_hazard_tile_damages_on_round_start():
    tiles = [
        ["hazard_fire", "ground", "ground"],
        ["ground", "ground", "ground"],
        ["ground", "ground", "ground"],
    ]
    engine, player, _, _card = engine_with_units(tiles, (0, 0), (2, 2))
    hp_before = player.hp
    engine.end_player_round()                # 敌人回合 + 下一轮 ROUND_START
    assert player.hp <= hp_before - 2        # on_round_start.damage = 2


def test_tile_status_effect_applies_on_enter():
    tiles = [
        [
            {"tile_id": "ground", "name": "地面"},
            {"tile_id": "mire", "name": "泥沼", "on_enter": {"status": "slow", "stacks": 2}},
            {"tile_id": "ground", "name": "地面"},
        ],
    ] * 3
    # 直接构造带内联 tile_defs 的地图
    raw = {
        "rows": 3, "cols": 3,
        "tiles": "mire" if False else [
            ["ground", "mire", "ground"],
            ["ground", "ground", "ground"],
            ["ground", "ground", "ground"],
        ],
        "tile_defs": {"mire": {"name": "泥沼", "move_cost": 2,
                               "on_enter": {"status": "slow", "stacks": 2}}},
        "deploy": {"player": {"rect": [0, 0, 2, 0]}, "enemy": {"rect": [0, 2, 2, 2]}},
    }
    engine = CombatEngine(battle_map=resolve_map(raw))
    player = make_unit("P", hp=200, AP=3, MAX_AP=3)
    engine.add_player_unit(player, cards=[make_card()], pos=(0, 0))
    engine.add_enemy_unit(make_unit("E", team="enemy", hp=200), pos=(2, 2))
    engine.start_battle()
    assert engine.move_unit("P", (0, 1))
    assert player.status_amount("slow") == 2


def test_hazard_can_kill_and_removes_unit():
    raw = {
        "rows": 3, "cols": 3, "tiles": "ground",
        "tile_defs": {"ground": {"on_enter": {"damage": 999}}},
        "deploy": {"player": {"rect": [0, 0, 2, 0]}, "enemy": {"rect": [0, 2, 2, 2]}},
    }
    engine = CombatEngine(battle_map=resolve_map(raw))
    player = make_unit("P", hp=50, AP=3, MAX_AP=3)
    engine.add_player_unit(player, cards=[make_card()], pos=(0, 0))
    engine.add_enemy_unit(make_unit("E", team="enemy", hp=50), pos=(2, 2))
    engine.start_battle()
    assert engine.move_unit("P", (0, 1))
    assert not player.is_alive
    assert engine.is_battle_over()


# ── 落位与波次 ──

def test_placement_rejects_blocked_and_occupied():
    tiles = [
        ["ground", "wall", "ground"],
        ["ground", "ground", "ground"],
        ["ground", "ground", "ground"],
    ]
    engine = build_engine(tiles)
    unit = make_unit("P")
    with pytest.raises(ValueError):
        engine.add_player_unit(unit, cards=[], pos=(0, 1))
    engine.add_player_unit(unit, cards=[], pos=(0, 0))
    with pytest.raises(ValueError):
        engine.add_enemy_unit(make_unit("E2", team="enemy"), pos=(0, 0))


def test_out_of_bounds_placement_rejected():
    engine = build_engine("ground", rows=3, cols=3)
    with pytest.raises(ValueError):
        engine.add_player_unit(make_unit("P"), cards=[], pos=(9, 9))


def test_wave_spawn_spills_when_declared_cell_taken():
    engine = build_engine("ground", rows=4, cols=4)
    engine.add_player_unit(make_unit("P", hp=200, AP=3, MAX_AP=3),
                           cards=[make_card()], pos=(0, 0))
    first = make_unit("W1", team="enemy", hp=30)
    second = make_unit("W2", team="enemy", hp=30)
    engine.load_waves([[(first, (3, 3))], [(second, (3, 3))]])
    engine.start_battle()
    alive = [u for u in engine.units.values() if u.team == "enemy" and u.is_alive]
    assert len(alive) == 1
    first.hp = 0
    engine.grid.remove_unit(first)
    engine._check_battle_end()
    assert second.unit_id in engine.units
    assert engine.grid.get_unit_at(second.pos) is second


def test_move_budget_uses_manhattan_cost_and_slow_halves_it():
    engine, player, _, _card = engine_with_units("ground", (0, 0), (4, 4))
    player.attributes = {"mobility": 8}
    assert engine.move_budget(player) == 4
    player.apply_status("slow", 2)
    assert engine.move_budget(player) == 2
