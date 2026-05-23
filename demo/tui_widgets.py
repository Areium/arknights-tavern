"""Textual widgets for the combat TUI — grid, cards, status bars, event log."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, RichLog, Label
from textual import events
from textual import on
from rich.text import Text
from rich.style import Style
from rich.panel import Panel

from demo.combat.grid import (
    TOTAL_ROWS, TOTAL_COLS,
    is_player_zone, is_enemy_zone,
)
from demo.combat.card import Card
from demo.combat.entity import CombatUnit


# ==============================================================================
#  Grid Cells
# ==============================================================================

class CellWidget(Static):
    """A single clickable cell in the combat grid."""

    class Clicked(Message):
        """Posted when a cell is clicked."""
        def __init__(self, row: int, col: int):
            self.row = row
            self.col = col
            super().__init__()

    def __init__(self, row: int, col: int, **kwargs):
        self.row = row
        self.col = col
        self._cell_type = "gap"
        self._label = ""
        self._highlight = ""
        super().__init__("", id=f"c{row}x{col}", **kwargs)

    def on_click(self, _click: events.Click = None) -> None:
        self.post_message(self.Clicked(self.row, self.col))

    def configure(self, cell_type: str, label: str = "", highlight: str = ""):
        self._cell_type = cell_type
        self._label = label
        self._highlight = highlight
        self.refresh()

    def render(self) -> Text:
        if self._cell_type == "gap":
            base = Style(color="rgb(50,50,50)")
        elif self._cell_type == "player_unit":
            base = Style(color="cyan", bold=True)
        elif self._cell_type == "enemy_unit":
            base = Style(color="red", bold=True)
        elif self._cell_type == "empty_player":
            base = Style(color="rgb(60,60,80)")
        elif self._cell_type == "empty_enemy":
            base = Style(color="rgb(80,60,60)")
        else:
            base = Style()

        if self._highlight == "target":
            base = Style(color="white", bgcolor="green", bold=True)
        elif self._highlight == "move":
            base = Style(color="white", bgcolor="rgb(30,60,130)", bold=True)
        elif self._highlight == "cursor":
            base = Style(color="black", bgcolor="yellow", bold=True)

        label = self._label if self._label else ("." if self._cell_type != "gap" else " ")
        return Text(f" {label} ", style=base, justify="center")


# ==============================================================================
#  Grid
# ==============================================================================

class GridWidget(Widget):
    """4x8 combat grid with clickable cells."""

    class CellClicked(Message):
        """Posted to parent when any cell is clicked."""
        def __init__(self, row: int, col: int):
            self.row = row
            self.col = col
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cells: dict[tuple[int, int], CellWidget] = {}

    def compose(self) -> ComposeResult:
        yield Label(self._make_header(), id="grid-header")
        for row in range(TOTAL_ROWS):
            with Horizontal(id=f"grid-r{row}", classes="grid-row"):
                for col in range(TOTAL_COLS):
                    cw = CellWidget(row, col)
                    self._cells[(row, col)] = cw
                    yield cw

    @staticmethod
    def _make_header() -> str:
        parts = ["    "]
        for c in range(TOTAL_COLS):
            parts.append(f" {c}   ")
        return "".join(parts)

    @on(CellWidget.Clicked)
    def _on_cell_clicked(self, event: CellWidget.Clicked) -> None:
        event.stop()
        self.post_message(self.CellClicked(event.row, event.col))

    def update_grid(self, units: dict[str, CombatUnit],
                    cursor: tuple[int, int] | None = None,
                    target_positions: set[tuple[int, int]] | None = None,
                    move_positions: set[tuple[int, int]] | None = None):
        target_positions = target_positions or set()
        move_positions = move_positions or set()

        # Build position → unit lookup
        pos_map: dict[tuple[int, int], CombatUnit] = {}
        for u in units.values():
            if u.is_alive:
                pos_map[u.pos] = u

        for row in range(TOTAL_ROWS):
            for col in range(TOTAL_COLS):
                cell = self._cells.get((row, col))
                if not cell:
                    continue
                pos = (row, col)
                unit = pos_map.get(pos)

                if unit:
                    cell_type = "player_unit" if unit.team == "player" else "enemy_unit"
                    label = unit.name[:2]
                elif is_player_zone(col):
                    cell_type = "empty_player"
                    label = ""
                elif is_enemy_zone(col):
                    cell_type = "empty_enemy"
                    label = ""
                else:
                    cell_type = "gap"
                    label = ""

                if pos == cursor:
                    highlight = "cursor"
                elif pos in target_positions:
                    highlight = "target"
                elif pos in move_positions:
                    highlight = "move"
                else:
                    highlight = ""

                cell.configure(cell_type, label, highlight)


# ==============================================================================
#  Card Widget
# ==============================================================================

class CardWidget(Static):
    """A single card, clickable to select."""

    class Clicked(Message):
        def __init__(self, index: int):
            self.index = index
            super().__init__()

    def __init__(self, card: Card, index: int, affordable: bool = True, **kwargs):
        self.card = card
        self.index = index
        self._affordable = affordable
        self._selected = False
        super().__init__("", id=f"card-{index}", **kwargs)

    def on_click(self, _click: events.Click = None) -> None:
        if self._affordable:
            self.post_message(self.Clicked(self.index))

    def refresh_state(self, card: Card, affordable: bool = True, selected: bool = False):
        self.card = card
        self._affordable = affordable
        self._selected = selected
        self.refresh()

    def render(self) -> Panel:
        dmg_type = {"physical": "物理", "arts": "法术",
                    "healing": "治疗", "mixed": "混合"}.get(self.card.damage_type, "?")
        tier = " *" if self.card.tier == "elite" else ""
        rng = "全图" if self.card.range < 0 else f"{self.card.range}格"

        body = Text()
        body.append(f"[{self.index}]{tier} ", style="bold")
        body.append(f"{self.card.name}\n", style="bold yellow")
        body.append(f"{dmg_type} {self.card.min_damage}-{self.card.max_damage} ")
        body.append(f"x{self.card.atk_scale:.1f}\n")
        body.append(f"{self.card.target} {rng}")
        body.append(f"  AP:{self.card.cost}", style="bold cyan")

        if not self._affordable:
            border = "dim red"
        elif self._selected:
            border = "bold yellow"
        else:
            border = "rgb(60,60,60)"

        return Panel(body, border_style=border, padding=(0, 1))


# ==============================================================================
#  Hand Bar
# ==============================================================================

class HandBar(Widget):
    """Horizontal card hand, scrollable."""

    class CardClicked(Message):
        def __init__(self, index: int):
            self.index = index
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._card_widgets: list[CardWidget] = []
        self._container: Horizontal | None = None

    def compose(self) -> ComposeResult:
        yield Horizontal(id="hand-inner")

    @on(CardWidget.Clicked)
    def _on_card_clicked(self, event: CardWidget.Clicked) -> None:
        event.stop()
        self.post_message(self.CardClicked(event.index))

    def update_hand(self, cards: list[Card], active_ap: int,
                    selected_idx: int | None = None):
        container = self.query_one("#hand-inner", Horizontal)

        # Rebuild if count changed
        if len(container.children) != len(cards):
            container.remove_children()
            self._card_widgets = []
            for i, card in enumerate(cards):
                cw = CardWidget(card, i, card.cost <= active_ap)
                self._card_widgets.append(cw)
                container.mount(cw)
        else:
            for i, card in enumerate(cards):
                self._card_widgets[i].refresh_state(
                    card,
                    affordable=card.cost <= active_ap,
                    selected=(i == selected_idx),
                )


# ==============================================================================
#  Status Panel
# ==============================================================================

class StatusPanel(Widget):
    """Side panel showing all unit HP/AP bars."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield Vertical(id="status-list")

    def update_units(self, player_units: list[CombatUnit],
                     enemy_units: list[CombatUnit],
                     active_unit_id: str = ""):
        container = self.query_one("#status-list", Vertical)
        container.remove_children()

        for u in player_units:
            container.mount(self._make_bar(u, u.unit_id == active_unit_id))

        container.mount(Static(""))

        for u in enemy_units:
            container.mount(self._make_bar(u, u.unit_id == active_unit_id))

    @staticmethod
    def _make_bar(unit: CombatUnit, is_active: bool) -> Static:
        hp_pct = max(0, unit.hp / max(1, unit.max_hp))
        ap_pct = max(0, unit.AP / max(1, unit.MAX_AP))

        def bar(val: float, w: int = 10) -> str:
            f = round(val * w)
            return "#" * f + "-" * (w - f)

        team_color = "cyan" if unit.team == "player" else "red"
        marker = " <<" if is_active else ""

        text = Text()
        text.append(f"{unit.name}{marker}\n", style=f"bold {team_color}")
        text.append(f"HP [{bar(hp_pct)}] {unit.hp}/{unit.max_hp}\n")
        text.append(f"AP [{bar(ap_pct)}] {unit.AP}/{unit.MAX_AP}")
        return Static(text)


# ==============================================================================
#  Header Banner
# ==============================================================================

class HeaderBanner(Static):
    """Top banner showing round, phase, and turn info."""

    def update_info(self, round_num: int, phase: str, unit_count: int,
                    active_name: str = "", active_team: str = ""):
        text = Text()
        text.append(f"  Round {round_num}  |  {phase}", style="bold")
        text.append(f"  |  Units: {unit_count}")

        if active_name:
            color = "cyan" if active_team == "player" else "red"
            text.append(f"\n  [{color}]>> {active_name} 行动中[/{color}]", style="bold")
        self.update(text)


# ==============================================================================
#  Event Log
# ==============================================================================

class EventLog(RichLog):
    """Scrollable combat event log."""

    def add_event(self, event_type: str, data: dict):
        if event_type == "round_start":
            self.write(f"=== Round {data.get('round', '?')} ===")
        elif event_type == "turn_start":
            color = "cyan" if data.get("team") == "player" else "red"
            self.write(f"[{color}]> {data.get('name','?')} 的回合[/{color}]")
        elif event_type == "damage":
            self.write(
                f"  [bold]{data.get('caster','?')}[/] "
                f"使用 [yellow]{data.get('card','?')}[/] "
                f"-> {data.get('target','?')}: "
                f"[red]-{data.get('damage',0)}[/] [{data.get('hit_result','')}]"
            )
        elif event_type == "heal":
            self.write(
                f"  [bold]{data.get('caster','?')}[/] "
                f"治疗 {data.get('target','?')}: "
                f"[green]+{data.get('amount',0)}[/]"
            )
        elif event_type == "death":
            self.write(f"  [magenta]DEAD  {data.get('name','?')} 已阵亡[/magenta]")
        elif event_type == "battle_end":
            winner = "玩家" if data.get("winner") == "player" else "敌方"
            self.write(f"[bold]=== {winner}胜利! ===[/bold]")
        elif event_type == "error":
            self.write(f"  [yellow]ERR {data.get('msg','?')}[/yellow]")
