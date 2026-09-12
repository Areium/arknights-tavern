"""战斗地图：JSON 规格解析、格子类型注册表与校验。

地图是**数据**而非代码：尺寸、每格类型（含可扩展的格子效果）、部署区全部写在
节点战斗 JSON 的 `map` 段里。本模块只做解析与校验，不含任何战斗规则。

地图 JSON 结构::

    {
      "rows": 9,
      "cols": 12,
      "tiles": [["ground", "wall", ...], ...],   # rows × cols 的 tile_id
      "tile_defs": {                              # 可选，内联格子定义（覆盖注册表）
        "wall": {"blocks_movement": true, "blocks_los": true, "color": "#4b5563"}
      },
      "deploy": {                                 # 可选，缺省按左右三分之一推导
        "player": {"rect": [3, 0, 5, 2]},         # 矩阵对角（含端点）
        "enemy":  {"cells": [[3, 5], [5, 5]]},    # 显式坐标
        "enemy_random_shift": false
      }
    }

格子效果（v1 生效）：``blocks_movement`` / ``blocks_los`` / ``move_cost`` /
``defense_bonus`` / ``evasion_bonus`` / ``damage_bonus`` /
``on_enter{damage,heal,status,stacks}`` / ``on_round_start{...}`` /
``deployable_player`` / ``deployable_enemy``。未知键与未知效果键只产生**警告**，
便于向后兼容地扩展新效果（例如未来的 ``on_attack`` / ``aura``）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 规模上限（防止误填天文数字把前端/引擎拖垮）──
MAX_ROWS = 40
MAX_COLS = 40
MAX_CELLS = 1200

DEFAULT_TILE_ID = "ground"


# ── 内置格子类型 ──
# 战术常用地形开箱可用；项目可在 data/combat/tiles/*.json 追加或覆盖。
BUILTIN_TILES: dict[str, dict] = {
    "ground": {"name": "地面", "glyph": ".", "color": "#374151"},
    "wall": {
        "name": "墙体", "glyph": "#", "color": "#4b5563",
        "blocks_movement": True, "blocks_los": True,
    },
    "cover": {
        "name": "掩体", "glyph": "H", "color": "#a16207",
        "blocks_los": True, "defense_bonus": 2, "evasion_bonus": 1,
    },
    "high_ground": {
        "name": "高台", "glyph": "^", "color": "#0e7490", "damage_bonus": 2,
    },
    "hazard_fire": {
        "name": "火场", "glyph": "F", "color": "#b91c1c",
        "on_enter": {"damage": 4}, "on_round_start": {"damage": 2},
    },
}

# 效果字典允许的键（其余键只警告）
_EFFECT_KEYS = {"damage", "heal", "status", "stacks"}
# 格子定义允许的键（其余键只警告，留作扩展位）
_TILE_KEYS = {
    "tile_id", "name", "glyph", "color", "blocks_movement", "blocks_los",
    "move_cost", "defense_bonus", "evasion_bonus", "damage_bonus",
    "deployable_player", "deployable_enemy", "on_enter", "on_round_start",
    "tags", "description",
}


class MapError(ValueError):
    """地图校验失败。`errors` 为可读的逐条原因（含行列定位）。"""

    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("；".join(self.errors))


@dataclass(frozen=True)
class TileType:
    """一种格子类型（不可变，可安全共享）。"""

    tile_id: str
    name: str = ""
    glyph: str = "."
    color: str = "#374151"
    blocks_movement: bool = False
    blocks_los: bool = False
    move_cost: int = 1
    defense_bonus: int = 0
    evasion_bonus: int = 0
    damage_bonus: int = 0
    deployable_player: bool = True
    deployable_enemy: bool = True
    on_enter: dict = field(default_factory=dict)
    on_round_start: dict = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def effect(self, hook: str) -> dict:
        """取某个触发点的效果（无则空 dict；全零效果视为无）。"""
        data = self.on_enter if hook == "enter" else self.on_round_start
        if not data:
            return {}
        if any(int(data.get(k, 0) or 0) for k in ("damage", "heal", "stacks")) or data.get("status"):
            return dict(data)
        return {}

    def to_dict(self) -> dict:
        return {
            "tile_id": self.tile_id, "name": self.name, "glyph": self.glyph,
            "color": self.color, "blocks_movement": self.blocks_movement,
            "blocks_los": self.blocks_los, "move_cost": self.move_cost,
            "defense_bonus": self.defense_bonus, "evasion_bonus": self.evasion_bonus,
            "damage_bonus": self.damage_bonus,
            "deployable_player": self.deployable_player,
            "deployable_enemy": self.deployable_enemy,
            "on_enter": dict(self.on_enter), "on_round_start": dict(self.on_round_start),
            "tags": list(self.tags),
        }


def build_tile_type(tile_id: str, raw: dict | None = None,
                    warnings: list[str] | None = None) -> TileType:
    """由原始定义构建 TileType（未知键记警告）。"""
    raw = dict(raw or {})
    unknown = set(raw) - _TILE_KEYS
    if unknown and warnings is not None:
        warnings.append(f"格子 '{tile_id}' 含未知字段 {sorted(unknown)}（已忽略，可用于未来扩展）")

    def _num(key: str, default=0) -> int:
        try:
            return int(raw.get(key, default) or 0)
        except (TypeError, ValueError):
            if warnings is not None:
                warnings.append(f"格子 '{tile_id}' 的 {key} 非整数，已回落 {default}")
            return default

    def _effects(key: str) -> dict:
        value = raw.get(key) or {}
        if not isinstance(value, dict):
            if warnings is not None:
                warnings.append(f"格子 '{tile_id}' 的 {key} 应为对象，已忽略")
            return {}
        unknown_fx = set(value) - _EFFECT_KEYS
        if unknown_fx and warnings is not None:
            warnings.append(f"格子 '{tile_id}' 的 {key} 含未知效果 {sorted(unknown_fx)}（已忽略）")
        out = {k: value[k] for k in value if k in _EFFECT_KEYS}
        status = out.get("status") or ""
        return {
            "damage": _num_from(out, "damage", warnings, tile_id, key),
            "heal": _num_from(out, "heal", warnings, tile_id, key),
            "status": str(status),
            "stacks": _num_from(out, "stacks", warnings, tile_id, key),
        } if out else {}

    return TileType(
        tile_id=tile_id,
        name=str(raw.get("name", "") or tile_id),
        glyph=str(raw.get("glyph", ".") or ".")[:2],
        color=str(raw.get("color", "#374151") or "#374151"),
        blocks_movement=bool(raw.get("blocks_movement", False)),
        blocks_los=bool(raw.get("blocks_los", False)),
        move_cost=max(1, _num("move_cost", 1)),
        defense_bonus=_num("defense_bonus", 0),
        evasion_bonus=_num("evasion_bonus", 0),
        damage_bonus=_num("damage_bonus", 0),
        deployable_player=bool(raw.get("deployable_player", True)),
        deployable_enemy=bool(raw.get("deployable_enemy", True)),
        on_enter=_effects("on_enter"),
        on_round_start=_effects("on_round_start"),
        tags=tuple(str(t) for t in (raw.get("tags") or [])),
    )


def _num_from(raw: dict, key: str, warnings, tile_id: str, hook: str) -> int:
    try:
        return int(raw.get(key, 0) or 0)
    except (TypeError, ValueError):
        if warnings is not None:
            warnings.append(f"格子 '{tile_id}' 的 {hook}.{key} 非整数，已回落 0")
        return 0


def load_tile_registry(tiles_dir: Path | None) -> tuple[dict[str, TileType], list[str]]:
    """读取全局格子注册表：内置 + `data/combat/tiles/*.json`（后者覆盖前者）。"""
    warnings: list[str] = []
    registry = {tid: build_tile_type(tid, raw, warnings) for tid, raw in BUILTIN_TILES.items()}
    if tiles_dir and Path(tiles_dir).is_dir():
        for path in sorted(Path(tiles_dir).glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                warnings.append(f"格子文件解析失败 {path.name}: {exc}")
                continue
            if not isinstance(raw, dict):
                warnings.append(f"格子文件 {path.name} 应为对象，已跳过")
                continue
            tile_id = str(raw.get("tile_id") or path.stem)
            registry[tile_id] = build_tile_type(tile_id, raw, warnings)
    return registry, warnings


@dataclass
class BattleMap:
    """一场战斗的战场：尺寸 + 每格类型 + 部署区。"""

    rows: int
    cols: int
    tiles: list[list[str]]
    tile_types: dict[str, TileType]
    deploy_player: list[tuple[int, int]] = field(default_factory=list)
    deploy_enemy: list[tuple[int, int]] = field(default_factory=list)
    enemy_random_shift: bool = False
    warnings: list[str] = field(default_factory=list)

    # ── 查询 ──

    def in_bounds(self, pos) -> bool:
        row, col = pos
        return 0 <= row < self.rows and 0 <= col < self.cols

    def tile_id(self, pos) -> str:
        row, col = pos
        if not self.in_bounds(pos):
            raise IndexError(f"坐标越界: {pos}")
        return self.tiles[row][col]

    def tile(self, pos) -> TileType:
        return self.tile_types.get(self.tile_id(pos)) or self.tile_types[DEFAULT_TILE_ID]

    def is_blocked(self, pos) -> bool:
        """不可通行（越界也视为不可通行，便于寻路统一处理）。"""
        if not self.in_bounds(pos):
            return True
        return self.tile(pos).blocks_movement

    def blocks_los(self, pos) -> bool:
        return self.tile(pos).blocks_los

    def move_cost(self, pos) -> int:
        return self.tile(pos).move_cost

    def deploy_zone(self, team: str) -> list[tuple[int, int]]:
        return list(self.deploy_player if team == "player" else self.deploy_enemy)

    # ── 导出（前端渲染） ──

    def to_dict(self) -> dict:
        return {
            "rows": self.rows,
            "cols": self.cols,
            "tiles": [list(row) for row in self.tiles],
            "tile_defs": {tid: tt.to_dict() for tid, tt in self.tile_types.items()},
            "deploy": {
                "player": [list(p) for p in self.deploy_player],
                "enemy": [list(p) for p in self.deploy_enemy],
                "enemy_random_shift": self.enemy_random_shift,
            },
        }


# ── 解析与校验 ──

def _parse_zone(raw, default: list[tuple[int, int]], team: str,
                warnings: list[str], rows: int, cols: int) -> list[tuple[int, int]]:
    """解析部署区：{"rect": [r0,c0,r1,c1]} 或 {"cells": [[r,c], ...]}。"""
    if raw is None:
        warnings.append(f"未声明 {team} 部署区，按左右三分之一推导")
        return list(default)

    cells: list[tuple[int, int]] = []
    if isinstance(raw, dict):
        if "rect" in raw:
            rect = raw.get("rect") or []
            if not (isinstance(rect, (list, tuple)) and len(rect) == 4):
                warnings.append(f"{team} 部署区 rect 需为 [r0,c0,r1,c1]，已改用推导值")
                return list(default)
            r0, c0, r1, c1 = (int(v) for v in rect)
            lo_r, hi_r = sorted((r0, r1))
            lo_c, hi_c = sorted((c0, c1))
            cells = [(r, c) for r in range(lo_r, hi_r + 1) for c in range(lo_c, hi_c + 1)]
        elif "cells" in raw:
            for item in raw.get("cells") or []:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    cells.append((int(item[0]), int(item[1])))
        else:
            warnings.append(f"{team} 部署区需含 rect 或 cells，已改用推导值")
            return list(default)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                cells.append((int(item[0]), int(item[1])))
    else:
        warnings.append(f"{team} 部署区格式无法识别，已改用推导值")
        return list(default)

    if not cells:
        warnings.append(f"{team} 部署区为空，已改用推导值")
        return list(default)
    # 去重并保序
    seen: set[tuple[int, int]] = set()
    unique = [c for c in cells if not (c in seen or seen.add(c))]
    out_of_bounds = [c for c in unique if not (0 <= c[0] < rows and 0 <= c[1] < cols)]
    if out_of_bounds:
        warnings.append(f"{team} 部署区有越界坐标 {out_of_bounds[:5]}（已剔除）")
        unique = [c for c in unique if c not in set(out_of_bounds)]
    return unique or list(default)


def _default_zones(rows: int, cols: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """缺省部署区：左侧三分之一给玩家，右侧三分之一给敌人。"""
    width = max(1, cols // 3)
    player = [(r, c) for r in range(rows) for c in range(0, min(width, cols))]
    enemy = [(r, c) for r in range(rows) for c in range(max(0, cols - width), cols)]
    return player, enemy


def resolve_map(raw: dict | None, tiles_dir: Path | None = None) -> BattleMap:
    """把节点/遭遇的 `map` 段解析为 BattleMap（校验失败抛 MapError）。"""
    if not raw:
        raise MapError("缺少 map 段：战斗必须显式声明战场（尺寸/格子/部署区）")

    errors: list[str] = []
    warnings: list[str] = []

    try:
        rows = int(raw.get("rows", 0) or 0)
        cols = int(raw.get("cols", 0) or 0)
    except (TypeError, ValueError):
        raise MapError("rows/cols 必须为整数")

    if rows <= 0 or cols <= 0:
        errors.append(f"rows/cols 必须为正整数（当前 {rows}×{cols}）")
    elif rows > MAX_ROWS or cols > MAX_COLS:
        errors.append(f"地图过大：{rows}×{cols} 超过上限 {MAX_ROWS}×{MAX_COLS}")
    elif rows * cols > MAX_CELLS:
        errors.append(f"地图格数 {rows * cols} 超过上限 {MAX_CELLS}")

    registry, reg_warnings = load_tile_registry(tiles_dir)
    warnings.extend(reg_warnings)
    for tile_id, tile_raw in (raw.get("tile_defs") or {}).items():
        if not isinstance(tile_raw, dict):
            warnings.append(f"内联格子 '{tile_id}' 应为对象，已忽略")
            continue
        base = registry[tile_id].to_dict() if tile_id in registry else {}
        merged = {**base, **tile_raw}
        merged.pop("tile_id", None)
        registry[tile_id] = build_tile_type(tile_id, merged, warnings)

    tiles_raw = raw.get("tiles")
    tiles: list[list[str]] = []
    if isinstance(tiles_raw, str):
        # 简写：整张地图同一格类型（"tiles": "ground"）
        tile_id = tiles_raw or DEFAULT_TILE_ID
        if rows > 0 and cols > 0:
            if tile_id not in registry:
                errors.append(f"tiles 引用了未定义的格子 '{tile_id}'")
            else:
                tiles = [[tile_id] * cols for _ in range(rows)]
    elif not isinstance(tiles_raw, list) or not tiles_raw:
        errors.append("缺少 tiles（二维 tile_id 数组，或统一填充的字符串简写）")
    else:
        if len(tiles_raw) != rows:
            errors.append(f"tiles 行数 {len(tiles_raw)} 与 rows {rows} 不一致")
        for r, row in enumerate(tiles_raw):
            if not isinstance(row, list):
                errors.append(f"tiles 第 {r} 行不是数组")
                continue
            if len(row) != cols:
                errors.append(f"tiles 第 {r} 行长度 {len(row)} 与 cols {cols} 不一致")
            norm_row: list[str] = []
            for c, tile_id in enumerate(row):
                tid = str(tile_id or DEFAULT_TILE_ID)
                if tid not in registry:
                    errors.append(f"({r},{c}) 引用了未定义的格子 '{tid}'")
                    tid = DEFAULT_TILE_ID
                norm_row.append(tid)
            tiles.append(norm_row)

    if errors:
        raise MapError(errors)

    default_player, default_enemy = _default_zones(rows, cols)
    deploy_raw = raw.get("deploy") or {}
    if not isinstance(deploy_raw, dict):
        warnings.append("deploy 段应为对象，已按推导值处理")
        deploy_raw = {}
    deploy_player = _parse_zone(deploy_raw.get("player"), default_player, "player",
                               warnings, rows, cols)
    deploy_enemy = _parse_zone(deploy_raw.get("enemy"), default_enemy, "enemy",
                              warnings, rows, cols)

    battle_map = BattleMap(
        rows=rows, cols=cols, tiles=tiles, tile_types=registry,
        deploy_player=deploy_player, deploy_enemy=deploy_enemy,
        enemy_random_shift=bool(deploy_raw.get("enemy_random_shift", False)),
        warnings=warnings,
    )

    # 语义校验：部署区落在阻挡格 / 出生点被完全封死（只警告，可能是有意设计）
    for team, zone in (("player", deploy_player), ("enemy", deploy_enemy)):
        blocked = [pos for pos in zone if battle_map.is_blocked(pos)]
        if blocked:
            battle_map.warnings.append(
                f"{team} 部署区有 {len(blocked)} 格为不可通行（{blocked[:3]}…），"
                "引擎会跳过这些格")
    _warn_unreachable(battle_map, warnings)
    return battle_map


def _warn_unreachable(battle_map: BattleMap, warnings: list[str]) -> None:
    """若敌人部署区与玩家部署区之间无路可通，给出软锁警告。"""
    from collections import deque

    starts = [p for p in battle_map.deploy_player if not battle_map.is_blocked(p)]
    goals = {p for p in battle_map.deploy_enemy if not battle_map.is_blocked(p)}
    if not starts or not goals:
        return
    seen = set(starts)
    queue = deque(starts)
    while queue:
        cur = queue.popleft()
        if cur in goals:
            return
        for nxt in _neighbors4(cur):
            if nxt in seen or battle_map.is_blocked(nxt):
                continue
            seen.add(nxt)
            queue.append(nxt)
    battle_map.warnings.append("玩家部署区与敌人部署区之间不存在通路（可能软锁，请检查地形）")


def _neighbors4(pos: tuple[int, int]) -> list[tuple[int, int]]:
    row, col = pos
    return [(row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]


def neighbors8(pos: tuple[int, int]) -> list[tuple[int, int]]:
    """8 向邻格（含对角）。"""
    row, col = pos
    return [
        (row - 1, col - 1), (row - 1, col), (row - 1, col + 1),
        (row, col - 1), (row, col + 1),
        (row + 1, col - 1), (row + 1, col), (row + 1, col + 1),
    ]


def default_map(rows: int = 7, cols: int = 7) -> BattleMap:
    """最小可用战场（全地面、左右三分之一部署区）：测试与模板用。"""
    tiles = [[DEFAULT_TILE_ID] * cols for _ in range(rows)]
    return resolve_map({"rows": rows, "cols": cols, "tiles": tiles},
                       tiles_dir=None)
