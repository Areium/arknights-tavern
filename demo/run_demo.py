#!/usr/bin/env python3
"""
Combat system demo — preset 4v4 battle with interactive terminal UI.

Player team (left, 3×3): 博士, 阿米娅, 银灰, 闪灵
Enemy team (right, 4×5): 4 enemies

Controls:
  数字键: 选择卡牌 (0-6)
  w/a/s/d: 移动目标光标
  Enter: 确认目标
  f: 结束回合
  q: 退出
"""

import sys
import os

# Ensure project root is on path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import frontmatter

from demo.combat.entity import CombatUnit
from demo.combat.grid import (Grid, PLAYER_ROWS, PLAYER_COLS, ENEMY_ROWS,
                              ENEMY_COLS, PLAYER_COL_START, ENEMY_COL_START,
                              TOTAL_ROWS, TOTAL_COLS, resolve_targets,
                              range_between)
from demo.combat.card_data import get_starting_deck, get_cards_for_class
from demo.combat.engine import CombatEngine
from demo.combat.renderer import render_full, render_hand, render_grid

# ══════════════════════════════════════════════════════════════════════════════
#  Setup: load real character data
# ══════════════════════════════════════════════════════════════════════════════

def load_character_meta(filename: str) -> dict:
    """Load a character's YAML frontmatter from data/ directory."""
    path = os.path.join(_project_root, filename)
    with open(path, "r", encoding="utf-8") as f:
        return frontmatter.load(f).metadata


# Map character file → (card pool class override, position on grid)
PLAYER_SETUP = [
    ("data/characters/博士.md", "辅助", (1, 0)),    # 博士 → 辅助 class cards
    ("data/characters/阿米娅.md", None, (0, 1)),     # 阿米娅 (术师)
    ("data/characters/银灰.md", None, (2, 1)),       # 银灰 (近卫)
    ("data/characters/闪灵.md", None, (1, 2)),       # 闪灵 (医疗)
]

ENEMY_DEFS = [
    ("整合运动士兵", "近卫", 90, 12, 8, 5, 4, 9, 6, 5),
    ("整合运动术师", "术师", 70, 6, 14, 3, 8, 8, 5, 4),
    ("整合运动盾卫", "重装", 140, 7, 5, 10, 6, 4, 5, 3),
    ("整合运动狙击手", "狙击", 75, 10, 5, 4, 4, 12, 8, 5),
]

ENEMY_POSITIONS = [(0, 4), (2, 5), (1, 3), (3, 6)]


def setup_battle() -> CombatEngine:
    """Create and initialize a 4v4 battle."""
    engine = CombatEngine()

    # ── Player units ──
    for filename, class_override, pos in PLAYER_SETUP:
        meta = load_character_meta(filename)
        unit = CombatUnit.from_character_metadata(meta, team="player")
        if class_override:
            unit.char_class = class_override

        char_class = unit.char_class
        cards = get_starting_deck(char_class, count=5)
        if not cards:
            cards = get_starting_deck("辅助", count=5)  # fallback
            print(f"[警告] {unit.name} 职业 '{char_class}' 无卡池，使用辅助卡池")

        engine.add_player_unit(unit, cards, pos)

    # ── Enemy units ──
    for name, cls, hp, patk, matk, def_, res, spd, hit, eva in ENEMY_DEFS:
        unit = CombatUnit.create_enemy(
            name, cls, hp=hp, patk=patk, matk=matk,
            defense=def_, resist=res, spd=spd, hit=hit, eva=eva,
            max_ap=3,
        )
        pos = ENEMY_POSITIONS[ENEMY_DEFS.index((name, cls, hp, patk, matk, def_, res, spd, hit, eva))]
        engine.add_enemy_unit(unit, pos)

    engine.start_battle()
    return engine


# ══════════════════════════════════════════════════════════════════════════════
#  Input Handling
# ══════════════════════════════════════════════════════════════════════════════

def get_cursor_moves(pos: tuple[int, int], unit: CombatUnit) -> list[tuple[int, int]]:
    """Get valid cursor positions for targeting."""
    # For now: show all enemy positions + adjacent to current
    moves = []
    for r in range(TOTAL_ROWS):
        for c in range(TOTAL_COLS):
            moves.append((r, c))
    return moves


def render_target_grid(engine: CombatEngine, cursor: tuple[int, int],
                       target_positions: list[tuple[int, int]]) -> str:
    """Render grid with highlighted target positions."""
    grid = engine.grid
    lines = []
    lines.append("    " + " ".join(f"{c:<3}" for c in range(TOTAL_COLS)))
    lines.append("   ┌" + "───┬" * (TOTAL_COLS - 1) + "───┐")

    for row in range(TOTAL_ROWS):
        cells = []
        for col in range(TOTAL_COLS):
            unit = grid.get_unit_at((row, col))
            if (row, col) == cursor:
                cells.append("\033[43m\033[30m[ ]\033[0m")  # cursor highlight
            elif (row, col) in target_positions:
                cells.append("\033[42m[ ]\033[0m")  # target highlight
            elif unit:
                name_short = unit.name[:2]
                if unit.team == "player":
                    cells.append(f"\033[36m {name_short}\033[0m")
                else:
                    cells.append(f"\033[31m {name_short}\033[0m")
            else:
                cells.append(" . ")
        lines.append(f" {row}  " + "│".join(cells) + "│")
        if row < TOTAL_ROWS - 1:
            lines.append("   ├" + "───┼" * (TOTAL_COLS - 1) + "───┤")
    lines.append("   └" + "───┴" * (TOTAL_COLS - 1) + "───┘")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Main Loop
# ══════════════════════════════════════════════════════════════════════════════

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def main():
    print("初始化战斗系统...")
    engine = setup_battle()

    # Collect events as they fire
    events_buffer: list[str] = []

    def on_event(ev):
        from demo.combat.renderer import render_event
        events_buffer.append(render_event(ev))

    engine.on_event = on_event

    target_mode = False
    selected_card_idx: int | None = None
    cursor: tuple[int, int] = (1, 5)
    target_positions: list[tuple[int, int]] = []

    while not engine.is_battle_over():
        clear_screen()

        # Determine active unit
        active = engine.get_active_unit()
        active_id = active.unit_id if active else ""

        # Print full state
        print(render_full(engine, active_id))

        # Print events since last turn
        for ev_line in events_buffer:
            print(ev_line)
        events_buffer.clear()

        # ── Player Turn ──
        if engine.state.phase == "PLAYER_TURN" and active:
            hand = engine.get_unit_hand(active_id)

            if target_mode and selected_card_idx is not None:
                # Targeting mode
                card = hand[selected_card_idx] if selected_card_idx < len(hand) else None
                if card:
                    if card.target in ("ALL_ALLIES", "GLOBAL"):
                        target_positions = []
                    else:
                        target_positions = resolve_targets(card.target, cursor)

                    print(f"\n\033[1m选择目标 [{card.name}]\033[0m")
                    print(render_target_grid(engine, cursor, target_positions))
                    print("\n  w/a/s/d: 移动  Enter: 确认  Esc: 取消")

                cmd = input("> ").strip().lower()

                if cmd == "":
                    # Confirm target
                    if card and card.target in ("ALL_ALLIES", "GLOBAL"):
                        engine.play_card(active_id, card, active.pos)
                    elif card:
                        engine.play_card(active_id, card, cursor)
                    target_mode = False
                    selected_card_idx = None
                    engine.end_current_turn()
                elif cmd == "w":
                    cursor = (max(0, cursor[0] - 1), cursor[1])
                elif cmd == "s":
                    cursor = (min(TOTAL_ROWS - 1, cursor[0] + 1), cursor[1])
                elif cmd == "a":
                    cursor = (cursor[0], max(0, cursor[1] - 1))
                elif cmd == "d":
                    cursor = (cursor[0], min(TOTAL_COLS - 1, cursor[1] + 1))
                elif cmd in ("esc", "c", "x"):
                    target_mode = False
                    selected_card_idx = None
                continue

            # Normal input mode
            print(f"\n\033[36m{active.name}\033[0m 的回合 (AP: {active.AP})")
            print(f"  手牌: {len(hand)} 张")
            print("  输入卡牌编号使用 | f 结束回合 | q 退出")
            cmd = input("> ").strip().lower()

            if cmd == "q":
                print("退出战斗。")
                break
            elif cmd == "f":
                engine.end_current_turn()
                continue
            elif cmd == "m":
                # Move
                print("  移动目标 (w/a/s/d 确认 Enter 取消 Esc):")
                # Simplified: just move 1 step
                sub = input("  >> ").strip().lower()
                if sub == "w":
                    new_pos = (active.pos[0] - 1, active.pos[1])
                    if engine.move_unit(active_id, new_pos):
                        print(f"  移动到 {new_pos}")
                elif sub == "s":
                    new_pos = (active.pos[0] + 1, active.pos[1])
                    if engine.move_unit(active_id, new_pos):
                        print(f"  移动到 {new_pos}")
                elif sub == "a":
                    new_pos = (active.pos[0], active.pos[1] - 1)
                    if engine.move_unit(active_id, new_pos):
                        print(f"  移动到 {new_pos}")
                elif sub == "d":
                    new_pos = (active.pos[0], active.pos[1] + 1)
                    if engine.move_unit(active_id, new_pos):
                        print(f"  移动到 {new_pos}")
                continue

            try:
                idx = int(cmd)
                if 0 <= idx < len(hand):
                    card = hand[idx]
                    if card.cost > active.AP:
                        print(f"  AP 不足! (需要 {card.cost}, 当前 {active.AP})")
                        input("  按 Enter 继续...")
                        continue
                    if card.target in ("SELF", "ALL_ALLIES", "GLOBAL"):
                        # Auto-target
                        engine.play_card(active_id, card, active.pos)
                        engine.end_current_turn()
                    else:
                        # Enter targeting mode
                        target_mode = True
                        selected_card_idx = idx
                        # Place cursor on nearest enemy
                        enemies = [u for u in engine.units.values()
                                   if u.team == "enemy" and u.is_alive]
                        if enemies:
                            nearest = min(enemies,
                                         key=lambda e: range_between(active.pos, e.pos))
                            cursor = nearest.pos
                else:
                    print(f"  无效编号: {idx}")
                    input("  按 Enter 继续...")
            except ValueError:
                pass

        # ── Enemy Turn ──
        elif engine.state.phase == "ENEMY_TURN":
            if active:
                results = engine.execute_enemy_turn(active_id)
                if results:
                    for dr in results:
                        pass  # events already captured
            import time
            time.sleep(0.3)  # Brief pause so player can see enemy actions
            engine.end_current_turn()

        # ── Battle End ──
        elif engine.state.phase == "END":
            continue

    # ── Result ──
    clear_screen()
    print(render_full(engine))
    print()
    if engine.state.winner == "player":
        print("\033[32m\033[1m=== 胜利！所有敌人已被击败。 ===\033[0m")
    else:
        print("\033[31m\033[1m=== 失败！你的队伍倒下了。 ===\033[0m")
    print()


if __name__ == "__main__":
    main()
