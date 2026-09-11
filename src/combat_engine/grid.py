"""
Grid system for combat positioning.

- Player zone: 7 rows × 3 cols (left side, cols 0-2)
- Enemy zone: 7 rows × 4 cols (right side, cols 3-6)
- Chebyshev distance: max(|dx|, |dy|)
"""

from typing import Optional
from combat_engine.entity import CombatUnit

# ── Grid dimensions ──
# Column layout: cols 0-2 player zone, cols 3-6 enemy zone
TOTAL_COLS = 7
TOTAL_ROWS = 7
ENEMY_COL_START = 3


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

    def get_units(self, team: str = "") -> list[CombatUnit]:
        """Get all units, optionally filtered by team."""
        units = list(self._cells.values())
        if team:
            units = [u for u in units if u.team == team]
        return units

    def move_unit(self, unit: CombatUnit, new_pos: tuple[int, int]) -> bool:
        """Move unit to new_pos. Returns True on success."""
        if not self.is_valid_position(new_pos, unit.team):
            return False
        if self._cells.get(new_pos):
            return False  # Occupied
        self.place_unit(unit, new_pos)
        return True

    def is_valid_position(self, pos: tuple[int, int], team: str = "") -> bool:
        """Check if pos is within the grid bounds (units may move anywhere)."""
        row, col = pos
        return 0 <= row < TOTAL_ROWS and 0 <= col < TOTAL_COLS


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
