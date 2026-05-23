"""Textual TUI for the card combat system — mouse-driven grid + hand interaction."""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import frontmatter

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Button, Footer
from textual import events

from demo.combat.entity import CombatUnit
from demo.combat.grid import (
    TOTAL_ROWS, TOTAL_COLS, resolve_targets, range_between,
)
from demo.combat.card import Card
from demo.combat.card_data import get_starting_deck
from demo.combat.engine import CombatEngine, CombatEvent

from demo.tui_widgets import (
    GridWidget, HandBar, StatusPanel, HeaderBanner, EventLog,
)


# ==============================================================================
#  Battle Setup (reused from run_demo.py)
# ==============================================================================

def load_character_meta(filename: str) -> dict:
    path = os.path.join(_project_root, filename)
    with open(path, "r", encoding="utf-8") as f:
        return frontmatter.load(f).metadata


PLAYER_SETUP = [
    ("data/characters/博士/index.md", "辅助", (1, 0)),
    ("data/characters/阿米娅/index.md", None, (0, 1)),
    ("data/characters/银灰/index.md", None, (2, 1)),
    ("data/characters/闪灵/index.md", None, (1, 2)),
]

ENEMY_DEFS = [
    ("整合运动士兵", "近卫", 90, 12, 8, 5, 4, 9, 6, 5),
    ("整合运动术师", "术师", 70, 6, 14, 3, 8, 8, 5, 4),
    ("整合运动盾卫", "重装", 140, 7, 5, 10, 6, 4, 5, 3),
    ("整合运动狙击手", "狙击", 75, 10, 5, 4, 4, 12, 8, 5),
]

ENEMY_POSITIONS = [(0, 4), (2, 5), (1, 3), (3, 6)]


def setup_battle() -> CombatEngine:
    engine = CombatEngine()

    for filename, class_override, pos in PLAYER_SETUP:
        meta = load_character_meta(filename)
        unit = CombatUnit.from_character_metadata(meta, team="player")
        if class_override:
            unit.char_class = class_override
        cards = get_starting_deck(unit.char_class, count=5)
        if not cards:
            cards = get_starting_deck("辅助", count=5)
        engine.add_player_unit(unit, cards, pos)

    for name, cls, hp, patk, matk, def_, res, spd, hit, eva in ENEMY_DEFS:
        unit = CombatUnit.create_enemy(
            name, cls, hp=hp, patk=patk, matk=matk,
            defense=def_, resist=res, spd=spd, hit=hit, eva=eva,
            max_ap=3,
        )
        idx = ENEMY_DEFS.index((name, cls, hp, patk, matk, def_, res, spd, hit, eva))
        engine.add_enemy_unit(unit, ENEMY_POSITIONS[idx])

    return engine


# ==============================================================================
#  Combat Screen
# ==============================================================================

class CombatScreen(Screen):
    """Main combat screen — grid, hand, status, event log."""

    BINDINGS = [
        Binding("1", "key_card(0)", "Card 1"),
        Binding("2", "key_card(1)", "Card 2"),
        Binding("3", "key_card(2)", "Card 3"),
        Binding("4", "key_card(3)", "Card 4"),
        Binding("5", "key_card(4)", "Card 5"),
        Binding("6", "key_card(5)", "Card 6"),
        Binding("7", "key_card(6)", "Card 7"),
        Binding("f", "end_turn", "End Turn"),
        Binding("m", "move_mode", "Move"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "quit", "Quit"),
        Binding("up,w", "cursor_up", "", show=False),
        Binding("down,s", "cursor_down", "", show=False),
        Binding("left,a", "cursor_left", "", show=False),
        Binding("right,d", "cursor_right", "", show=False),
        Binding("enter,space", "confirm", "Confirm Target"),
    ]

    CSS = """
    CombatScreen {
        layout: vertical;
    }
    #header {
        height: 3;
        dock: top;
        background: $surface-darken-1;
    }
    #main-area {
        height: 1fr;
    }
    #grid-widget {
        width: 60%;
        border: solid $surface;
    }
    #grid-header {
        height: 1;
        text-style: bold;
        color: $text-muted;
    }
    #grid-widget .grid-row {
        height: 3;
    }
    #grid-widget CellWidget {
        width: 7;
        height: 3;
        content-align: center middle;
        border: solid rgb(40,40,40);
    }
    #status-panel {
        width: 40%;
        border: solid $surface;
        padding: 1;
    }
    #status-panel Static {
        width: 100%;
        height: 3;
    }
    #hand-bar {
        height: 8;
        dock: bottom;
        background: $surface-darken-1;
        overflow-x: auto;
    }
    #hand-inner {
        height: auto;
    }
    #hand-end-btn {
        min-width: 10;
        height: 5;
        margin: 1;
    }
    #log {
        height: 10;
        dock: bottom;
        border: solid $surface;
    }
    CardWidget {
        width: 22;
        height: 7;
        margin: 1;
        border: solid rgb(60,60,60);
    }
    Footer {
        dock: bottom;
    }
    """

    def __init__(self):
        super().__init__()
        self.engine = setup_battle()
        self._ui_mode = "INIT"  # INIT | VIEWING | TARGETING | MOVING | ENEMY | END
        self._selected_card_idx: int | None = None
        self._cursor: tuple[int, int] = (1, 4)  # cursor position for targeting
        self._active_unit_id: str = ""
        self._target_positions: set[tuple[int, int]] = set()
        self._move_positions: set[tuple[int, int]] = set()
        self._events_buf: list[CombatEvent] = []

    def compose(self) -> ComposeResult:
        yield HeaderBanner(id="header")
        with Horizontal(id="main-area"):
            yield GridWidget(id="grid")
            yield StatusPanel(id="status")
        yield HandBar(id="hand")
        yield EventLog(id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.engine.on_event = self._buffer_event
        self.engine.start_battle()
        self._drain_events()
        self._refresh_all()

    # ── Engine event buffer ──

    def _buffer_event(self, ev: CombatEvent) -> None:
        self._events_buf.append(ev)

    def _drain_events(self) -> None:
        log = self.query_one("#log", EventLog)
        for ev in self._events_buf:
            log.add_event(ev.type, ev.data)
            self._dispatch_event(ev)
        self._events_buf.clear()

    def _dispatch_event(self, ev: CombatEvent) -> None:
        if ev.type == "battle_end":
            self._ui_mode = "END"
        elif ev.type == "turn_start":
            self._active_unit_id = ev.data["unit_id"]
            if ev.data["team"] == "enemy":
                self._ui_mode = "ENEMY"
                self._schedule_enemy_turn(ev.data["unit_id"])
            else:
                self._ui_mode = "VIEWING"
                self._selected_card_idx = None
                self._target_positions.clear()
                self._move_positions.clear()
                # Place cursor on nearest enemy
                enemies = [u for u in self.engine.units.values()
                          if u.team == "enemy" and u.is_alive]
                if enemies:
                    active = self.engine.get_active_unit()
                    if active:
                        nearest = min(enemies,
                                     key=lambda e: range_between(active.pos, e.pos))
                        self._cursor = nearest.pos

    # ── Enemy turn (timer-driven chain) ──

    def _schedule_enemy_turn(self, unit_id: str) -> None:
        self.set_timer(0.35, lambda: self._exec_enemy(unit_id))

    def _exec_enemy(self, unit_id: str) -> None:
        if self.engine.is_battle_over():
            return
        self.engine.execute_enemy_turn(unit_id)
        self._drain_events()
        self.engine.end_current_turn()
        self._drain_events()
        self._refresh_all()

    # ── Refresh all widgets ──

    def _refresh_all(self) -> None:
        # Header
        header = self.query_one("#header", HeaderBanner)
        active = self.engine.get_active_unit()
        header.update_info(
            round_num=self.engine.state.round_num,
            phase=self.engine.state.phase,
            unit_count=len([u for u in self.engine.units.values() if u.is_alive]),
            active_name=active.name if active else "",
            active_team=active.team if active else "",
        )

        # Grid
        grid = self.query_one("#grid", GridWidget)
        grid.update_grid(
            self.engine.units,
            cursor=self._cursor if self._ui_mode in ("TARGETING", "MOVING") else None,
            target_positions=self._target_positions,
            move_positions=self._move_positions,
        )

        # Status
        status = self.query_one("#status", StatusPanel)
        players = [u for u in self.engine.units.values()
                   if u.team == "player" and u.is_alive]
        enemies = [u for u in self.engine.units.values()
                   if u.team == "enemy" and u.is_alive]
        status.update_units(players, enemies, self._active_unit_id)

        # Hand
        hand = self.query_one("#hand", HandBar)
        if self._active_unit_id and self._ui_mode == "VIEWING":
            cards = self.engine.get_unit_hand(self._active_unit_id)
            unit = self.engine.units.get(self._active_unit_id)
            ap = unit.AP if unit else 0
            hand.update_hand(cards, ap, self._selected_card_idx)
        elif self._ui_mode != "VIEWING":
            # Keep showing the same hand during TARGETING/MOVING
            pass

        # Show End Turn button if in VIEWING mode
        # (handled via keyboard 'f' and mouse on the button)

        # Battle end overlay
        if self._ui_mode == "END":
            self._show_battle_end()

    def _show_battle_end(self) -> None:
        winner = "VICTORY" if self.engine.state.winner == "player" else "DEFEAT"
        color = "green" if winner == "VICTORY" else "red"
        self.query_one("#log", EventLog).write(
            f"\n[{color}][bold]==========  {winner}!  ==========[/bold][/{color}]\n"
        )

    # ── Grid cell clicked ──

    def on_grid_widget_cell_clicked(self, event: GridWidget.CellClicked) -> None:
        row, col = event.row, event.col

        if self._ui_mode == "TARGETING":
            # Play selected card targeting this cell
            unit = self.engine.units.get(self._active_unit_id)
            if not unit:
                return
            hand = self.engine.get_unit_hand(self._active_unit_id)
            if self._selected_card_idx is None or self._selected_card_idx >= len(hand):
                return
            card = hand[self._selected_card_idx]
            self.engine.play_card(self._active_unit_id, card, (row, col))
            self._drain_events()
            self.engine.end_current_turn()
            self._drain_events()
            self._selected_card_idx = None
            self._target_positions.clear()
            self._refresh_all()

        elif self._ui_mode == "MOVING":
            if (row, col) in self._move_positions:
                self.engine.move_unit(self._active_unit_id, (row, col))
                self._ui_mode = "VIEWING"
                self._move_positions.clear()
                self._refresh_all()

    # ── Card clicked ──

    def on_hand_bar_card_clicked(self, event: HandBar.CardClicked) -> None:
        if self._ui_mode != "VIEWING":
            return
        self.action_key_card(event.index)

    # ── Keyboard actions ──

    def action_key_card(self, index: int) -> None:
        unit = self.engine.units.get(self._active_unit_id)
        if not unit:
            return
        hand = self.engine.get_unit_hand(self._active_unit_id)
        if index >= len(hand):
            return
        card = hand[index]
        if card.cost > unit.AP:
            return

        if card.target in ("SELF", "ALL_ALLIES", "GLOBAL"):
            # Auto-target: play immediately
            self.engine.play_card(self._active_unit_id, card, unit.pos)
            self._drain_events()
            self.engine.end_current_turn()
            self._drain_events()
            self._refresh_all()
            return

        # Enter targeting mode
        self._ui_mode = "TARGETING"
        self._selected_card_idx = index
        self._cursor = self._find_nearest_enemy_pos()
        self._update_targeting(card)
        self._refresh_all()

    def action_end_turn(self) -> None:
        if self._ui_mode not in ("VIEWING",):
            return
        self._selected_card_idx = None
        self._target_positions.clear()
        self.engine.end_current_turn()
        self._drain_events()
        self._refresh_all()

    def action_move_mode(self) -> None:
        if self._ui_mode not in ("VIEWING",):
            return
        unit = self.engine.units.get(self._active_unit_id)
        if not unit or unit.AP < 1:
            return
        moves = self.engine.grid.get_valid_moves(unit, ap_cost=1)
        if not moves:
            return
        self._ui_mode = "MOVING"
        self._move_positions = set(moves)
        self._cursor = unit.pos
        self._refresh_all()

    def action_cancel(self) -> None:
        if self._ui_mode in ("TARGETING", "MOVING"):
            self._ui_mode = "VIEWING"
            self._selected_card_idx = None
            self._target_positions.clear()
            self._move_positions.clear()
            self._refresh_all()

    def action_cursor_up(self) -> None:
        if self._ui_mode in ("TARGETING", "MOVING"):
            self._cursor = (max(0, self._cursor[0] - 1), self._cursor[1])
            if self._ui_mode == "TARGETING" and self._selected_card_idx is not None:
                self._update_targeting_for_cursor()
            self._refresh_all()

    def action_cursor_down(self) -> None:
        if self._ui_mode in ("TARGETING", "MOVING"):
            self._cursor = (min(TOTAL_ROWS - 1, self._cursor[0] + 1), self._cursor[1])
            if self._ui_mode == "TARGETING" and self._selected_card_idx is not None:
                self._update_targeting_for_cursor()
            self._refresh_all()

    def action_cursor_left(self) -> None:
        if self._ui_mode in ("TARGETING", "MOVING"):
            self._cursor = (self._cursor[0], max(0, self._cursor[1] - 1))
            if self._ui_mode == "TARGETING" and self._selected_card_idx is not None:
                self._update_targeting_for_cursor()
            self._refresh_all()

    def action_cursor_right(self) -> None:
        if self._ui_mode in ("TARGETING", "MOVING"):
            self._cursor = (self._cursor[0], min(TOTAL_COLS - 1, self._cursor[1] + 1))
            if self._ui_mode == "TARGETING" and self._selected_card_idx is not None:
                self._update_targeting_for_cursor()
            self._refresh_all()

    def action_confirm(self) -> None:
        """Enter/space: confirm target at cursor position."""
        if self._ui_mode == "TARGETING":
            self.on_grid_widget_cell_clicked(
                GridWidget.CellClicked(self._cursor[0], self._cursor[1])
            )
        elif self._ui_mode == "MOVING":
            self.on_grid_widget_cell_clicked(
                GridWidget.CellClicked(self._cursor[0], self._cursor[1])
            )

    # ── Helpers ──

    def _find_nearest_enemy_pos(self) -> tuple[int, int]:
        unit = self.engine.units.get(self._active_unit_id)
        enemies = [u for u in self.engine.units.values()
                   if u.team == "enemy" and u.is_alive]
        if unit and enemies:
            nearest = min(enemies, key=lambda e: range_between(unit.pos, e.pos))
            return nearest.pos
        return (1, 4)  # fallback

    def _update_targeting(self, card: Card) -> None:
        self._target_positions = set(resolve_targets(card.target, self._cursor))

    def _update_targeting_for_cursor(self) -> None:
        unit = self.engine.units.get(self._active_unit_id)
        if not unit or self._selected_card_idx is None:
            return
        hand = self.engine.get_unit_hand(self._active_unit_id)
        if self._selected_card_idx >= len(hand):
            return
        card = hand[self._selected_card_idx]
        self._target_positions = set(resolve_targets(card.target, self._cursor))


# ==============================================================================
#  App Entry Point
# ==============================================================================

class CombatApp(App):
    """Textual combat TUI application."""

    TITLE = "Arknights Combat"
    CSS = """
    Screen {
        align: center middle;
    }
    """

    def on_mount(self) -> None:
        self.push_screen(CombatScreen())


def main():
    app = CombatApp()
    app.run()


if __name__ == "__main__":
    main()
