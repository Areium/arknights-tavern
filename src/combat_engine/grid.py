"""
Grid system for combat positioning.

- Player zone: 6 rows × 3 cols (left side, cols 0-2)
- Gap: 2 cols (cols 3-4)
- Enemy zone:  6 rows × 3 cols (right side, cols 5-7)
- Chebyshev distance: max(|dx|, |dy|)
"""

from typing import Optional
from combat_engine.entity import CombatUnit

# ── Grid dimensions ──
PLAYER_ROWS = 3
PLAYER_COLS = 3
ENEMY_ROWS = 3
ENEMY_COLS = 3

# Logical column ranges
PLAYER_COL_START = 0
PLAYER_COL_END = 2
GAP_COL_START = 3
GAP_COL_END = 3
ENEMY_COL_START = 4
ENEMY_COL_END = 7
TOTAL_COLS = 8
TOTAL_ROWS = 6


def is_player_zone(col: int) -> bool:
    return PLAYER_COL_START <= col <= PLAYER_COL_END


def is_enemy_zone(col: int) -> bool:
    return ENEMY_COL_START <= col <= ENEMY_COL_END


# ══════════════════════════════════════════════════════════════════════════════
#  Grid
# ══════════════════════════════════════════════════════════════════════════════

class Grid:
    """Combat grid holding all placed units."""

    def __init__(self):
        # (row, col) → CombatUnit
        self._cells: dict[tuple[int, int], CombatUnit] = {}
        # unit_id → (row, col)
        self._positions: dict[str, tuple[int, int]] = {}

    def place_unit(self, unit: CombatUnit, pos: tuple[int, int]):
        """Place a unit at the given position."""
        # Remove from old position if any
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

    def get_position(self, unit: CombatUnit) -> Optional[tuple[int, int]]:
        return self._positions.get(unit.unit_id)

    def get_units(self, team: str = "") -> list[CombatUnit]:
        """Get all units, optionally filtered by team."""
        units = list(self._cells.values())
        if team:
            units = [u for u in units if u.team == team]
        return units

    def get_alive_units(self, team: str = "") -> list[CombatUnit]:
        return [u for u in self.get_units(team) if u.is_alive]

    def move_unit(self, unit: CombatUnit, new_pos: tuple[int, int]) -> bool:
        """Move unit to new_pos. Returns True on success."""
        if not self.is_valid_position(new_pos, unit.team):
            return False
        if self._cells.get(new_pos):
            return False  # Occupied
        self.place_unit(unit, new_pos)
        return True

    def is_valid_position(self, pos: tuple[int, int], team: str) -> bool:
        """Check if pos is within the unit's zone."""
        row, col = pos
        if row < 0 or row >= TOTAL_ROWS:
            return False
        if team == "player":
            return 0 <= col <= PLAYER_COL_END
        else:
            return ENEMY_COL_START <= col <= ENEMY_COL_END

    def get_valid_moves(self, unit: CombatUnit, ap_cost: int = 1) -> list[tuple[int, int]]:
        """Get all positions the unit can move to within a Manhattan distance of *range* cells."""
        if unit.AP < ap_cost:
            return []
        current = unit.pos
        if current == (-1, -1):
            return []
        moves = []
        for dr in range(-ap_cost, ap_cost + 1):
            for dc in range(-ap_cost, ap_cost + 1):
                if dr == 0 and dc == 0:
                    continue
                npos = (current[0] + dr, current[1] + dc)
                if self.is_valid_position(npos, unit.team) and not self._cells.get(npos):
                    moves.append(npos)
        return moves

    # ── Query ──

    def units_in_range(self, origin: tuple[int, int], max_range: int,
                       target_team: str = "") -> list[CombatUnit]:
        """Get all units within Chebyshev range of origin."""
        result = []
        for pos, unit in self._cells.items():
            if target_team and unit.team != target_team:
                continue
            if range_between(origin, pos) <= max_range:
                result.append(unit)
        return result


# ══════════════════════════════════════════════════════════════════════════════
#  Range
# ══════════════════════════════════════════════════════════════════════════════

def range_between(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Chebyshev distance: max(|dx|, |dy|)."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


# ══════════════════════════════════════════════════════════════════════════════
#  Target Pattern Resolution
# ══════════════════════════════════════════════════════════════════════════════

def resolve_targets(pattern: str, origin: tuple[int, int],
                    direction: tuple[int, int] = (0, 1)) -> list[tuple[int, int]]:
    """Given a card's target pattern and origin cell, return affected positions.

    direction: for LINE_3, which way the line extends (dr, dc).
               Default (0, 1) = rightward.
    """
    r, c = origin
    cells: list[tuple[int, int]] = []

    if pattern == "SINGLE":
        cells = [origin]

    elif pattern == "SELF":
        cells = [origin]

    elif pattern == "ADJACENT":
        cells = [origin]
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            cells.append((r + dr, c + dc))

    elif pattern == "CROSS":
        cells = [origin]
        for dr, dc in [(-2, 0), (-1, 0), (1, 0), (2, 0), (0, -2), (0, -1), (0, 1), (0, 2)]:
            cells.append((r + dr, c + dc))

    elif pattern == "LINE_3":
        dr, dc = direction
        for i in range(3):
            cells.append((r + dr * i, c + dc * i))

    elif pattern == "ROW":
        for col in range(TOTAL_COLS):
            cells.append((r, col))

    elif pattern == "AREA_2X2":
        for dr in range(2):
            for dc in range(2):
                cells.append((r + dr, c + dc))

    elif pattern == "ALL_ALLIES":
        # Resolved by engine (needs grid context)
        pass

    elif pattern == "GLOBAL":
        # Resolved by engine (needs grid context)
        pass

    # Filter out-of-bounds
    valid = []
    for rr, cc in cells:
        if 0 <= rr < TOTAL_ROWS and 0 <= cc < TOTAL_COLS:
            valid.append((rr, cc))
    return valid
