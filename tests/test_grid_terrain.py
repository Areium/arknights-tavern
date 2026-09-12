"""网格地形与统一曼哈顿度量：可达集、路径、切角、视线。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from combat_engine.grid import (  # noqa: E402
    CHEBYSHEV, Grid, MANHATTAN, chebyshev, manhattan, metric_distance,
    resolve_targets,
)
from combat_map import resolve_map  # noqa: E402


def _grid(rows: int, cols: int, tiles=None, **deploy) -> Grid:
    raw = {
        "rows": rows,
        "cols": cols,
        "tiles": tiles if tiles is not None else "ground",
        "deploy": {
            "player": deploy.get("player", {"rect": [0, 0, rows - 1, 0]}),
            "enemy": deploy.get("enemy", {"rect": [0, cols - 1, rows - 1, cols - 1]}),
        },
    }
    return Grid(resolve_map(raw))


def test_metric_helpers():
    assert manhattan((0, 0), (2, 3)) == 5
    assert chebyshev((0, 0), (2, 3)) == 3
    assert metric_distance((0, 0), (2, 3), MANHATTAN) == 5
    assert metric_distance((0, 0), (2, 3), CHEBYSHEV) == 3
    assert metric_distance((0, 0), (2, 3), "unknown") == 5  # 未知度量回落曼哈顿


def test_open_field_reachable_matches_manhattan_budget():
    grid = _grid(7, 7)
    reach = grid.reachable((3, 3), 2)
    # 曼哈顿半径 2 的菱形：13 格含自身，去掉起点 12 格
    assert len(reach) == 12
    assert all(cost == manhattan((3, 3), pos) for pos, cost in reach.items())


def test_diagonal_step_costs_two():
    grid = _grid(7, 7)
    reach = grid.reachable((0, 0), 2)
    assert reach[(0, 1)] == 1
    assert reach[(1, 0)] == 1
    assert reach[(1, 1)] == 2          # 斜向一步 = 2
    assert (2, 2) not in reach          # 两个斜向步 = 4 > 预算


def test_walls_block_movement():
    tiles = [
        ["ground", "wall", "ground"],
        ["ground", "wall", "ground"],
        ["ground", "wall", "ground"],
    ]
    grid = _grid(3, 3, tiles=tiles)
    reach = grid.reachable((0, 0), 3)
    assert (0, 1) not in reach         # 墙本身不可达
    assert (2, 2) not in reach         # 需要绕行 6 步，超预算
    assert grid.path_to((0, 0), (2, 0), budget=4) == [(0, 0), (1, 0), (2, 0)]


def test_corner_cut_forbidden_by_default():
    tiles = [
        ["ground", "wall"],
        ["wall", "ground"],
    ]
    grid = _grid(2, 2, tiles=tiles)
    assert grid.path_to((0, 0), (1, 1)) is None          # 两个正交邻格都是墙 → 不能斜切

    open_cut = _grid(2, 2, tiles=tiles)
    open_cut.corner_cut = True
    assert open_cut.path_to((0, 0), (1, 1)) == [(0, 0), (1, 1)]


def test_move_cost_increases_step_price():
    tiles = [
        ["ground", "hazard_fire", "ground"],
        ["ground", "ground", "ground"],
        ["ground", "ground", "ground"],
    ]
    grid = _grid(3, 3, tiles=tiles)
    grid.map.tile_types["hazard_fire"] = grid.map.tile_types["hazard_fire"]
    # 火场 move_cost 缺省 1（效果在 on_enter），先验证普通代价
    assert grid.step_cost((0, 1), diagonal=False) == 1
    assert grid.step_cost((1, 1), diagonal=True) == 2


def test_line_of_sight_blocked_by_wall_not_by_target_cover():
    tiles = [
        ["ground", "ground", "wall", "ground", "ground"],
    ] * 3
    grid = _grid(3, 5, tiles=tiles)
    assert grid.has_line_of_sight((1, 0), (1, 1))
    assert not grid.has_line_of_sight((1, 0), (1, 3))     # 中间是墙

    cover_tiles = [
        ["ground", "ground", "ground", "cover", "ground"],
    ] * 3
    grid2 = _grid(3, 5, tiles=cover_tiles)
    # 掩体阻挡"穿过它"的视线，但站在掩体里的目标仍可被瞄准
    assert grid2.has_line_of_sight((1, 0), (1, 3))
    assert not grid2.has_line_of_sight((1, 0), (1, 4))


def test_line_of_sight_blocks_diagonal_corner():
    tiles = [
        ["ground", "wall"],
        ["wall", "ground"],
    ]
    grid = _grid(2, 2, tiles=tiles)
    assert not grid.has_line_of_sight((0, 0), (1, 1))


def test_placement_validation():
    grid = _grid(3, 3, tiles=[["ground", "wall", "ground"]] * 3)
    assert grid.can_place((0, 0))
    assert not grid.can_place((0, 1))       # 墙
    assert not grid.can_place((0, 9))       # 越界


def test_resolve_targets_uses_actual_dimensions():
    # ROW 形状按 cols 展开，而不是旧的模块常量
    cells = resolve_targets("ROW", (1, 0), rows=3, cols=5)
    assert cells == [(1, 0), (1, 1), (1, 2), (1, 3), (1, 4)]
    # 越界裁切
    cells = resolve_targets("AREA_2X2", (2, 4), rows=3, cols=5)
    assert cells == [(2, 4)]
    # ADJACENT 为四正交（与曼哈顿 1 一致）
    adj = resolve_targets("ADJACENT", (1, 1), rows=5, cols=5)
    assert set(adj) == {(1, 1), (0, 1), (2, 1), (1, 0), (1, 2)}


@pytest.mark.parametrize("budget,expected", [(1, 4), (2, 12), (3, 24)])
def test_reachable_count_scales_with_budget(budget, expected):
    """曼哈顿半径 r 的可达格数（不含起点）= 2r² + 2r。"""
    grid = _grid(9, 9)
    assert len(grid.reachable((4, 4), budget)) == expected
