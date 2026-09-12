"""战斗地图 JSON 的解析与校验（`src/combat_map.py`）。"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from combat_map import (  # noqa: E402
    BUILTIN_TILES, MapError, build_tile_type, default_map, load_tile_registry,
    resolve_map,
)

NODE_DIR = ROOT / "data" / "combat" / "nodes"


def _map(**overrides) -> dict:
    base = {
        "rows": 3,
        "cols": 4,
        "tiles": "ground",
        "deploy": {"player": {"rect": [0, 0, 2, 0]}, "enemy": {"rect": [0, 3, 2, 3]}},
    }
    base.update(overrides)
    return base


def test_uniform_tiles_shorthand_fills_grid():
    battle_map = resolve_map(_map())
    assert (battle_map.rows, battle_map.cols) == (3, 4)
    assert len(battle_map.tiles) == 3
    assert all(len(row) == 4 for row in battle_map.tiles)
    assert {tid for row in battle_map.tiles for tid in row} == {"ground"}


def test_explicit_tiles_matrix():
    battle_map = resolve_map(_map(tiles=[["wall", "ground", "ground", "ground"]] * 3))
    assert battle_map.is_blocked((0, 0))
    assert not battle_map.is_blocked((1, 1))
    assert battle_map.blocks_los((0, 0))


def test_tile_defs_inline_override_registry():
    raw = _map(tile_defs={"ground": {"move_cost": 3, "on_enter": {"damage": 5}}})
    battle_map = resolve_map(raw)
    assert battle_map.tile((0, 0)).move_cost == 3
    assert battle_map.tile((0, 0)).effect("enter")["damage"] == 5


def test_unknown_tile_id_is_error():
    with pytest.raises(MapError) as err:
        resolve_map(_map(tiles=[["swamp", "ground", "ground", "ground"]] * 3))
    assert "未定义的格子" in str(err.value)


def test_tiles_dimension_mismatch_is_error():
    with pytest.raises(MapError) as err:
        resolve_map(_map(tiles=[["ground", "ground"]] * 3))
    assert "长度" in str(err.value)


def test_missing_map_is_error():
    with pytest.raises(MapError):
        resolve_map(None)


def test_oversized_map_is_error():
    with pytest.raises(MapError):
        resolve_map({"rows": 99, "cols": 99, "tiles": "ground"})


def test_deploy_rect_expands_row_major():
    battle_map = resolve_map(_map(deploy={"player": {"rect": [0, 0, 1, 1]}}))
    assert battle_map.deploy_zone("player") == [(0, 0), (0, 1), (1, 0), (1, 1)]
    # 未声明一侧按左右三分之一推导
    assert battle_map.deploy_zone("enemy")
    assert any("推导" in w for w in battle_map.warnings)


def test_deploy_cells_form():
    battle_map = resolve_map(_map(deploy={"enemy": {"cells": [[1, 3], [2, 3]]}}))
    assert battle_map.deploy_zone("enemy") == [(1, 3), (2, 3)]


def test_deploy_out_of_bounds_is_filtered_with_warning():
    battle_map = resolve_map(_map(deploy={"player": {"cells": [[0, 0], [9, 9]]}}))
    assert battle_map.deploy_zone("player") == [(0, 0)]
    assert any("越界" in w for w in battle_map.warnings)


def test_softlock_warning_when_zones_walled_off():
    tiles = [
        ["ground", "ground", "wall", "ground"],
        ["ground", "ground", "wall", "ground"],
        ["ground", "ground", "wall", "ground"],
    ]
    battle_map = resolve_map(_map(tiles=tiles))
    assert any("不存在通路" in w for w in battle_map.warnings)


def test_blocked_deploy_cell_warns():
    tiles = [
        ["wall", "ground", "ground", "ground"],
        ["ground", "ground", "ground", "ground"],
        ["ground", "ground", "ground", "ground"],
    ]
    battle_map = resolve_map(_map(tiles=tiles))
    assert any("不可通行" in w for w in battle_map.warnings)


def test_enemy_random_shift_flag_passthrough():
    battle_map = resolve_map(_map(deploy={
        "player": {"rect": [0, 0, 2, 0]},
        "enemy": {"rect": [0, 3, 2, 3]},
        "enemy_random_shift": True,
    }))
    assert battle_map.enemy_random_shift is True


def test_unknown_tile_field_only_warns():
    warnings: list[str] = []
    tile = build_tile_type("weird", {"on_attack": {"damage": 3}, "move_cost": 2}, warnings)
    assert tile.move_cost == 2
    assert warnings and "未知字段" in warnings[0]


def test_builtin_registry_has_tactical_tiles():
    assert {"ground", "wall", "cover", "high_ground", "hazard_fire"} <= set(BUILTIN_TILES)
    registry, _ = load_tile_registry(None)
    assert registry["wall"].blocks_movement and registry["wall"].blocks_los
    assert registry["cover"].defense_bonus > 0


def test_default_map_is_square_and_playable():
    battle_map = default_map(7, 7)
    assert (battle_map.rows, battle_map.cols) == (7, 7)
    assert len(battle_map.deploy_zone("player")) > 0
    assert len(battle_map.deploy_zone("enemy")) > 0


def test_to_dict_round_trips_through_resolve_map():
    battle_map = default_map(5, 6)
    payload = battle_map.to_dict()
    again = resolve_map(payload)
    assert (again.rows, again.cols) == (5, 6)
    assert again.deploy_zone("player") == battle_map.deploy_zone("player")


@pytest.mark.parametrize("path", sorted(NODE_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_all_shipped_nodes_have_valid_maps(path: Path):
    node = json.loads(path.read_text(encoding="utf-8"))
    battle_map = resolve_map(node.get("map"), tiles_dir=ROOT / "data" / "combat" / "tiles")
    assert battle_map.rows > 0 and battle_map.cols > 0
    assert battle_map.deploy_zone("player") and battle_map.deploy_zone("enemy")
    for wave in node.get("waves", []) or []:
        for entry in wave.get("enemies", []) or []:
            for pos in entry.get("positions") or []:
                assert battle_map.in_bounds(tuple(pos)), f"{path.stem} 站位越界 {pos}"
                assert not battle_map.is_blocked(tuple(pos)), f"{path.stem} 站位被阻挡 {pos}"
