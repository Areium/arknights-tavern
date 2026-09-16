"""战斗网格：占位、地形、路径与视线。

规则要点（批次 1 起）：

- **尺寸自由**：行列来自 `BattleMap`（节点 JSON 的地图段），不再是模块常量。
- **距离 = 曼哈顿**：8 向移动，斜向步代价 ×2，因此"能斜走但绕一格"；
  移动预算按代价累加（`mobility // 2`），攻击范围同样按曼哈顿判定。
- **地形**：`blocks_movement`（不可通行）、`move_cost`（通行代价）、
  `blocks_los`（阻挡视线）、格子效果（`on_enter` / `on_round_start`）。
- **切角**：默认禁止斜穿墙角（两个正交邻格都须可通行），可用 `corner_cut=True` 放开。
"""

from __future__ import annotations

import heapq
from typing import Optional

from combat_engine.entity import CombatUnit
from combat_map import BattleMap, default_map, neighbors8

# ── 距离度量 ──

MANHATTAN = "manhattan"
CHEBYSHEV = "chebyshev"


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    """曼哈顿距离 |Δr| + |Δc|。"""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    """切比雪夫距离 max(|Δr|, |Δc|)。"""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def metric_distance(a: tuple[int, int], b: tuple[int, int],
                    metric: str = MANHATTAN) -> int:
    """按度量取距离；未知度量回落曼哈顿。"""
    return chebyshev(a, b) if metric == CHEBYSHEV else manhattan(a, b)


def is_diagonal(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] != b[0] and a[1] != b[1]


# ══════════════════════════════════════════════════════════════════════════════
#  Grid
# ══════════════════════════════════════════════════════════════════════════════

class Grid:
    """战场网格：地图（尺寸/地形）+ 单位占位。"""

    def __init__(self, battle_map: BattleMap | None = None,
                 corner_cut: bool = False):
        self.map: BattleMap = battle_map or default_map()
        self.corner_cut = bool(corner_cut)
        # (row, col) → CombatUnit
        self._cells: dict[tuple[int, int], CombatUnit] = {}
        # unit_id → (row, col)
        self._positions: dict[str, tuple[int, int]] = {}

    # ── 尺寸 / 地形（转发地图） ──

    @property
    def rows(self) -> int:
        return self.map.rows

    @property
    def cols(self) -> int:
        return self.map.cols

    def in_bounds(self, pos: tuple[int, int]) -> bool:
        return self.map.in_bounds(pos)

    def is_valid_position(self, pos: tuple[int, int]) -> bool:
        """界内即可（地形/单位阻挡由 can_place / path_to 判定）。"""
        return self.map.in_bounds(pos)

    def is_blocked(self, pos: tuple[int, int]) -> bool:
        """不可通行（地形阻挡或越界）。"""
        return self.map.is_blocked(pos)

    def tile(self, pos: tuple[int, int]):
        return self.map.tile(pos)

    def terrain_at(self, pos: tuple[int, int]) -> dict:
        """给伤害结算用的地形修正（攻方取 damage_bonus，守方取防御/闪避）。"""
        tile = self.map.tile(pos)
        return {
            "defense_bonus": tile.defense_bonus,
            "evasion_bonus": tile.evasion_bonus,
            "damage_bonus": tile.damage_bonus,
        }

    # ── 占位 ──

    def place_unit(self, unit: CombatUnit, pos: tuple[int, int]):
        """放置单位（覆盖旧位置）。调用方负责合法性校验（见 can_place）。"""
        if unit.unit_id in self._positions:
            old = self._positions[unit.unit_id]
            self._cells.pop(old, None)
        self._cells[pos] = unit
        self._positions[unit.unit_id] = pos
        unit.pos = pos

    def remove_unit(self, unit: CombatUnit):
        pos = self._positions.pop(unit.unit_id, None)
        if pos:
            self._cells.pop(pos, None)

    def get_unit_at(self, pos: tuple[int, int]) -> Optional[CombatUnit]:
        return self._cells.get(pos)

    def get_units(self, team: str = "") -> list[CombatUnit]:
        units = list(self._cells.values())
        if team:
            units = [u for u in units if u.team == team]
        return units

    def can_place(self, pos: tuple[int, int], *, ignore_unit_id: str = "") -> bool:
        """该格能否落脚：界内 + 非阻挡 + 无其他单位。"""
        if not self.map.in_bounds(pos) or self.map.is_blocked(pos):
            return False
        occupant = self._cells.get(pos)
        return occupant is None or occupant.unit_id == ignore_unit_id

    def free_deploy_cells(self, team: str) -> list[tuple[int, int]]:
        """部署区中当前可落脚的格子（保序）。"""
        return [pos for pos in self.map.deploy_zone(team) if self.can_place(pos)]

    def move_unit(self, unit: CombatUnit, new_pos: tuple[int, int]) -> bool:
        """移动单位（不做距离校验；距离由 path_to/validate_move 负责）。"""
        if not self.can_place(new_pos, ignore_unit_id=unit.unit_id):
            return False
        self.place_unit(unit, new_pos)
        return True

    # ── 路径与可达 ──

    def step_cost(self, to_pos: tuple[int, int], diagonal: bool) -> int:
        """一步的代价：目标格 move_cost ×（斜向 2 倍）。"""
        return self.map.move_cost(to_pos) * (2 if diagonal else 1)

    def _passable(self, pos: tuple[int, int], mover_id: str) -> bool:
        occupant = self._cells.get(pos)
        return self.map.in_bounds(pos) and not self.map.is_blocked(pos) \
            and (occupant is None or occupant.unit_id == mover_id)

    def _diagonal_blocked(self, cur: tuple[int, int], nxt: tuple[int, int],
                          mover_id: str) -> bool:
        """禁止切角：斜向移动要求两个正交邻格都可通行。"""
        if self.corner_cut:
            return False
        side_a = (cur[0], nxt[1])
        side_b = (nxt[0], cur[1])
        return not self._passable(side_a, mover_id) or not self._passable(side_b, mover_id)

    def reachable(self, from_pos: tuple[int, int], budget: int,
                  mover_id: str = "") -> dict[tuple[int, int], int]:
        """Dijkstra：返回预算内可达格 → 累计代价（不含起点自身）。"""
        if budget <= 0:
            return {}
        best: dict[tuple[int, int], int] = {}
        heap: list[tuple[int, tuple[int, int]]] = [(0, from_pos)]
        while heap:
            cost, cur = heapq.heappop(heap)
            if cur != from_pos and cost > best.get(cur, 1 << 30):
                continue
            for nxt in neighbors8(cur):
                if not self._passable(nxt, mover_id):
                    continue
                diagonal = is_diagonal(cur, nxt)
                if diagonal and self._diagonal_blocked(cur, nxt, mover_id):
                    continue
                new_cost = cost + self.step_cost(nxt, diagonal)
                if new_cost > budget:
                    continue
                if new_cost < best.get(nxt, 1 << 30):
                    best[nxt] = new_cost
                    heapq.heappush(heap, (new_cost, nxt))
        best.pop(from_pos, None)   # 起点不算"可达格"
        return best

    def path_to(self, from_pos: tuple[int, int], to_pos: tuple[int, int],
                budget: Optional[int] = None, mover_id: str = "",
                goal_may_be_occupied: bool = False) -> Optional[list[tuple[int, int]]]:
        """最短路（Dijkstra）。返回含起点与终点的坐标序列；不可达或超预算返回 None。

        `goal_may_be_occupied`：允许终点被别的单位占着（敌人"朝目标逼近一格"时用，
        终点只是方向指引，真正落点由调用方再取 path[1]）。
        """
        if from_pos == to_pos:
            return [from_pos]
        if not goal_may_be_occupied and not self.can_place(to_pos, ignore_unit_id=mover_id):
            return None
        if not self.map.in_bounds(to_pos) or self.map.is_blocked(to_pos):
            return None
        best: dict[tuple[int, int], int] = {from_pos: 0}
        prev: dict[tuple[int, int], tuple[int, int]] = {}
        heap: list[tuple[int, tuple[int, int]]] = [(0, from_pos)]
        while heap:
            cost, cur = heapq.heappop(heap)
            if cur == to_pos:
                break
            if cost > best.get(cur, 1 << 30):
                continue
            for nxt in neighbors8(cur):
                if nxt != to_pos and not self._passable(nxt, mover_id):
                    continue
                diagonal = is_diagonal(cur, nxt)
                if diagonal and self._diagonal_blocked(cur, nxt, mover_id):
                    continue
                new_cost = cost + self.step_cost(nxt, diagonal)
                if budget is not None and new_cost > budget:
                    continue
                if new_cost < best.get(nxt, 1 << 30):
                    best[nxt] = new_cost
                    prev[nxt] = cur
                    heapq.heappush(heap, (new_cost, nxt))
        if to_pos not in best:
            return None
        path = [to_pos]
        while path[-1] != from_pos:
            path.append(prev[path[-1]])
        return list(reversed(path))

    # ── 视线 ──

    def has_line_of_sight(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        """超覆盖直线视线：途经格或斜向拐角被 `blocks_los` 阻挡即不可见。

        起点与终点所在格不参与阻挡判定——站在掩体里的单位仍可被瞄准，
        掩体阻挡的是"穿过它"的视线。
        """
        if a == b:
            return True
        for cell in self._los_path(a, b):
            if cell == a or cell == b:
                continue
            if not self.map.in_bounds(cell) or self.map.blocks_los(cell):
                return False
        return True

    def _los_path(self, a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
        """Bresenham + 拐角：斜向推进时把两个正交拐角也纳入路径（任一被挡即遮挡）。"""
        r0, c0 = a
        r1, c1 = b
        dr, dc = abs(r1 - r0), abs(c1 - c0)
        sr = 0 if r1 == r0 else (1 if r1 > r0 else -1)
        sc = 0 if c1 == c0 else (1 if c1 > c0 else -1)
        err = dr - dc
        cells: list[tuple[int, int]] = []
        r, c = r0, c0
        while True:
            cells.append((r, c))
            if (r, c) == (r1, c1):
                break
            e2 = 2 * err
            moved_r = moved_c = False
            if e2 > -dc:
                err -= dc
                r += sr
                moved_r = True
            if e2 < dr:
                err += dr
                c += sc
                moved_c = True
            if moved_r and moved_c:
                # 斜向：记录两侧拐角，任一为阻挡且另一侧也阻挡时由调用方判定
                cells.append((r - sr, c))
                cells.append((r, c - sc))
        return cells


# ══════════════════════════════════════════════════════════════════════════════
#  目标形状
# ══════════════════════════════════════════════════════════════════════════════

def resolve_targets(pattern: str, origin: tuple[int, int],
                    direction: tuple[int, int] = (0, 1),
                    rows: int = 0, cols: int = 0) -> list[tuple[int, int]]:
    """按卡牌目标形状展开受影响格（越界剔除）。

    rows/cols 为战场尺寸；0 表示不裁切（调用方自行过滤）。
    """
    r, c = origin
    cells: list[tuple[int, int]] = []

    if pattern in ("SINGLE", "SELF"):
        cells = [origin]
    elif pattern == "ADJACENT":
        # 四正交邻格（与曼哈顿距离 1 一致）
        cells = [origin, (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
    elif pattern == "CROSS":
        cells = [origin]
        for dr, dc in [(-2, 0), (-1, 0), (1, 0), (2, 0), (0, -2), (0, -1), (0, 1), (0, 2)]:
            cells.append((r + dr, c + dc))
    elif pattern == "LINE_3":
        dr, dc = direction
        for i in range(3):
            cells.append((r + dr * i, c + dc * i))
    elif pattern == "ROW":
        width = cols if cols > 0 else c + 1
        for col in range(width):
            cells.append((r, col))
    elif pattern == "AREA_2X2":
        for dr in range(2):
            for dc in range(2):
                cells.append((r + dr, c + dc))
    elif pattern in ("ALL_ALLIES", "GLOBAL"):
        # 由引擎按上下文解析
        pass

    if rows <= 0 or cols <= 0:
        return cells
    return [(rr, cc) for rr, cc in cells if 0 <= rr < rows and 0 <= cc < cols]
