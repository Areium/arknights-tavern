"""
ASCII renderer for combat state — terminal grid display, hand cards, status.

Renders:
  ┌── Top: Enemy units on right side of grid
  ├── Middle: Grid cells with unit markers
  ├── Bottom: Player units on left side of grid
  └── Below: Current hand cards, action log
"""

from typing import Optional
from .entity import CombatUnit
from .grid import (Grid, TOTAL_ROWS, TOTAL_COLS, PLAYER_COL_END,
                   ENEMY_COL_START, is_player_zone, is_enemy_zone)
from .card import Card
from .engine import CombatEngine, CombatEvent


# ==============================================================================
#  Grid Rendering
# ==============================================================================

def render_grid(engine: "CombatEngine") -> str:
    """Render the combat grid as ASCII art."""
    grid = engine.grid
    lines: list[str] = []

    # Column header
    lines.append("    " + " ".join(f"{c:<3}" for c in range(TOTAL_COLS)))
    lines.append("   ┌" + "───┬" * (TOTAL_COLS - 1) + "───┐")

    # Divider between player and enemy zones
    divider_col = PLAYER_COL_END + 0.5  # between col 2 and col 3

    for row in range(TOTAL_ROWS):
        # Build cell content
        cells: list[str] = []
        for col in range(TOTAL_COLS):
            unit = grid.get_unit_at((row, col))
            if unit:
                # First 2 chars of name
                name_short = unit.name[:2]
                if unit.team == "player":
                    cells.append(f"\033[36m{name_short:<3}\033[0m")  # cyan
                else:
                    cells.append(f"\033[31m{name_short:<3}\033[0m")  # red
            else:
                if is_player_zone(col) or is_enemy_zone(col):
                    cells.append(" . ")
                else:
                    cells.append("   ")

        lines.append(f" {row}  " + "│".join(cells) + "│")

        if row < TOTAL_ROWS - 1:
            lines.append("   ├" + "───┼" * (TOTAL_COLS - 1) + "───┤")

    lines.append("   └" + "───┴" * (TOTAL_COLS - 1) + "───┘")
    return "\n".join(lines)


# ==============================================================================
#  Unit Status
# ==============================================================================

def render_unit_status(unit: CombatUnit) -> str:
    """Single-line unit status with HP bar."""
    hp_pct = unit.hp / max(unit.max_hp, 1)
    bar_len = 10
    filled = round(hp_pct * bar_len)
    bar = "#" * filled + "-" * (bar_len - filled)

    color = "\033[36m" if unit.team == "player" else "\033[31m"
    reset = "\033[0m"

    return (f"{color}{unit.name:<6}{reset} "
            f"HP [{bar}] {unit.hp}/{unit.max_hp}"
            f"  AP:{unit.AP}/{unit.MAX_AP}"
            f"  ATK:{unit.PATK:.0f}/{unit.MATK:.0f}"
            f"  DEF:{unit.DEF} RES:{unit.RES}")


# ==============================================================================
#  Hand Cards
# ==============================================================================

def render_hand(cards: list[Card]) -> str:
    """Render the current hand of cards with details."""
    if not cards:
        return "  手牌为空"

    lines = []
    for i, card in enumerate(cards):
        dmg_type = {"physical": "物理", "arts": "法术",
                    "healing": "治疗", "mixed": "混合"}.get(card.damage_type, card.damage_type)
        tier_mark = " *" if card.tier == "elite" else "  "

        range_str = "全图" if card.range < 0 else f"{card.range}格"
        lines.append(
            f"  [{i}] {tier_mark} \033[33m{card.name:<10}\033[0m"
            f"  {dmg_type} {card.min_damage}-{card.max_damage}"
            f"  ×{card.atk_scale:.1f}ATK"
            f"  {card.target} {range_str}"
            f"  AP:{card.cost}"
        )
    return "\n".join(lines)


# ==============================================================================
#  Event Log
# ==============================================================================

def render_event(event: CombatEvent) -> str:
    """Render a single combat event."""
    d = event.data
    if event.type == "damage":
        hr = d.get("hit_result", "")
        return (f"  ATK {d.get('caster','?')} -> {d.get('card','?')}"
                f" -> {d.get('target','?')}: \033[31m-{d.get('damage',0)}\033[0m [{hr}]")
    elif event.type == "heal":
        return (f"  HEAL {d.get('caster','?')} -> {d.get('target','?')}:"
                f" \033[32m+{d.get('amount',0)}\033[0m")
    elif event.type == "death":
        return f"  \033[35mDEAD {d.get('name','?')} 已阵亡\033[0m"
    elif event.type == "move":
        return f"  MOVE {d.get('name','?')} 移动到 {d.get('pos','?')}"
    elif event.type == "round_start":
        return f"\n\033[1m=== 第 {d.get('round','?')} 回合 ===\033[0m"
    elif event.type == "battle_end":
        winner = "玩家" if d.get("winner") == "player" else "敌方"
        return f"\n\033[1m{'='*20} {winner}胜利 {'='*20}\033[0m"
    elif event.type == "turn_start":
        color = "\033[36m" if d.get("team") == "player" else "\033[31m"
        return f"\n{color}> {d.get('name','?')} 的回合\033[0m"
    elif event.type == "error":
        return f"  \033[33mERR {d.get('msg','?')}\033[0m"
    return f"  [{event.type}] {d}"


def render_recent_events(engine: "CombatEngine", count: int = 8) -> str:
    """Render the last N events."""
    events = engine.state.events[-count:]
    return "\n".join(render_event(e) for e in events)


# ==============================================================================
#  Full State
# ==============================================================================

def render_full(engine: "CombatEngine", active_unit_id: str = "") -> str:
    """Render complete combat state: grid, units, hand, events."""
    parts: list[str] = []

    # Battle header
    parts.append(f"\033[1m{'='*60}\033[0m")
    parts.append(f"  回合 {engine.state.round_num}  |  阶段: {engine.state.phase}"
                 f"  |  单位: {len(engine.units)}")
    parts.append("")

    # Units status
    player_units = [u for u in engine.units.values()
                    if u.team == "player" and u.is_alive]
    enemy_units = [u for u in engine.units.values()
                   if u.team == "enemy" and u.is_alive]

    parts.append("── 玩家 ──")
    for u in player_units:
        marker = " <- 当前" if u.unit_id == active_unit_id else ""
        parts.append("  " + render_unit_status(u) + marker)

    parts.append("── 敌方 ──")
    for u in enemy_units:
        parts.append("  " + render_unit_status(u))

    parts.append("")
    parts.append("── 战场 ──")
    parts.append(render_grid(engine))
    parts.append("")

    # Active unit's hand
    if active_unit_id:
        unit = engine.units.get(active_unit_id)
        if unit:
            hand = engine.get_unit_hand(active_unit_id)
            parts.append(f"── {unit.name} 的手牌 (AP: {unit.AP}) ──")
            parts.append(render_hand(hand))
            parts.append("")

    # Recent events
    parts.append("── 战斗日志 ──")
    parts.append(render_recent_events(engine, count=6))

    parts.append(f"\n\033[1m{'='*60}\033[0m")
    return "\n".join(parts)
