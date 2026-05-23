"""
CombatSession — server-side wrapper around CombatEngine.

Manages a single battle's lifecycle: setup → player actions → enemy AI → events.
Integrates with the project's Session system and SSE event streaming.
"""

import queue
import logging
import os
import sys
import random
from typing import Optional

# Ensure project root and src/ are importable
_src_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_src_dir)
for _p in (_src_dir, _project_root):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from combat_engine.entity import CombatUnit
from combat_engine.card import Card
from combat_engine.card_data import get_starting_deck
from combat_engine.engine import CombatEngine, CombatEvent
from combat_engine.grid import resolve_targets, range_between, TOTAL_ROWS, TOTAL_COLS, ENEMY_COL_START
from combat_data_loader import CombatDataLoader

logger = logging.getLogger(__name__)


class CombatSession:
    """Server-side combat session wrapping a CombatEngine instance."""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.engine: CombatEngine | None = None
        self.loader = CombatDataLoader()
        self.event_queue: queue.Queue[CombatEvent] = queue.Queue()
        self._character_metas: list[dict] = []
        self._encounter_id: str = ""

    # ── Setup ──

    def start(self, encounter_id: str,
              character_names: list[str] = None,
              character_metas: list[dict] = None) -> dict:
        """Initialize a battle from an encounter definition and character list.

        Args:
            encounter_id: Key in data/combat/encounters/ (without .md)
            character_names: List of character names to load from data/characters/
            character_metas: List of character metadata dicts (takes precedence over names)

        Returns:
            dict: Initial combat state snapshot.
        """
        encounter = self.loader.load_encounter(encounter_id)
        if not encounter:
            raise ValueError(f"Encounter not found: {encounter_id}")

        self._encounter_id = encounter_id
        self.engine = CombatEngine()

        # Wire up event forwarding into the SSE queue
        self.engine.on_event = self._enqueue_event

        # ── Load player characters ──
        if character_metas:
            self._character_metas = character_metas
        elif character_names:
            self._character_metas = []
            for name in character_names:
                meta = self._load_character_meta(name)
                if meta:
                    self._character_metas.append(meta)

        # Default positions for 4 players in 3×3 zone spanning rows 3-5, cols 0-2
        default_positions = [(3, 0), (4, 0), (5, 0), (4, 1)]

        for i, meta in enumerate(self._character_metas):
            unit = CombatUnit.from_character_metadata(meta, team="player")
            char_class = unit.char_class

            # Use class card pool; fall back to 辅助
            cards = get_starting_deck(char_class, count=5)
            if not cards:
                cards = get_starting_deck("辅助", count=5)
                logger.warning("No card pool for class '%s', using 辅助 fallback", char_class)

            pos = default_positions[i] if i < len(default_positions) else (3 + i % 3, 0)
            self.engine.add_player_unit(unit, cards, pos)

        # ── Load enemies ──
        waves = encounter.get("waves", [])
        for wave in waves:
            for enemy_def in wave.get("enemies", []):
                enemy_name = enemy_def.get("enemy", "")
                count = enemy_def.get("count", 1)
                positions = enemy_def.get("positions", [])

                for j in range(count):
                    enemy_unit = self.loader.load_enemy(enemy_name)
                    if not enemy_unit:
                        logger.warning("Enemy '%s' not found, skipping", enemy_name)
                        continue

                    # Use specified position or auto-place
                    if j < len(positions):
                        pos = tuple(positions[j])
                    else:
                        # Auto-place in enemy zone (cols 5-7)
                        pos = (random.randint(0, TOTAL_ROWS - 1),
                               random.randint(ENEMY_COL_START, TOTAL_COLS - 1))

                    self.engine.add_enemy_unit(enemy_unit, pos)

        # Start the state machine
        self.engine.start_battle()

        # Flush initial events into the queue
        self._flush_engine_events()

        return self.get_state()

    def _load_character_meta(self, name: str) -> dict | None:
        """Load a character's YAML frontmatter from data/characters/<name>/index.md."""
        import frontmatter
        from pathlib import Path
        project_root = Path(__file__).resolve().parent.parent
        path = project_root / "data" / "characters" / name / "index.md"
        if not path.exists():
            logger.warning("Character file not found: %s", path)
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return frontmatter.load(f).metadata
        except Exception as e:
            logger.error("Failed to load character %s: %s", name, e)
            return None

    # ── Event handling ──

    def _enqueue_event(self, ev: CombatEvent) -> None:
        """Forward engine events into the SSE queue."""
        self.event_queue.put(ev)

    def _flush_engine_events(self) -> None:
        """Move events from engine state into the SSE queue (for init events)."""
        if self.engine:
            for ev in self.engine.state.events:
                self.event_queue.put(ev)
            self.engine.state.events.clear()

    # ── Player actions ──

    def handle_action(self, action: dict) -> dict:
        """Execute a player action and return updated state.

        Args:
            action: {
                "action": "play_card" | "move",
                "card_index": int (for play_card),
                "target": [row, col]
            }

        Returns:
            dict with keys: "ok", "events" (list), "state" (full snapshot)
        """
        if not self.engine:
            return {"ok": False, "error": "No active battle"}

        if self.engine.is_battle_over():
            return {"ok": False, "error": "Battle is over"}

        active = self.engine.get_active_unit()
        if not active or active.team != "player":
            return {"ok": False, "error": "Not a player turn"}

        action_type = action.get("action", "")
        target = tuple(action.get("target", [0, 0]))

        try:
            if action_type == "play_card":
                card_index = action.get("card_index", 0)
                hand = self.engine.get_unit_hand(active.unit_id)
                if card_index < 0 or card_index >= len(hand):
                    return {"ok": False, "error": f"Invalid card index: {card_index}"}

                card = hand[card_index]
                if card.cost > active.AP:
                    return {"ok": False, "error": "Insufficient AP"}

                # For auto-target cards, use caster position
                if card.target in ("SELF", "ALL_ALLIES", "GLOBAL"):
                    target = active.pos

                results = self.engine.play_card(active.unit_id, card, target)
                self._flush_engine_events()

                # Auto-end turn after playing a card
                self.engine.end_current_turn()
                self._flush_engine_events()
                self._auto_enemy_turns()

            elif action_type == "move":
                if self.engine.move_unit(active.unit_id, target):
                    self._flush_engine_events()
                    # Don't end turn — player can still play a card after moving
                else:
                    return {"ok": False, "error": "Invalid move target"}

            else:
                return {"ok": False, "error": f"Unknown action: {action_type}"}

        except Exception as e:
            logger.exception("Error executing action")
            return {"ok": False, "error": str(e)}

        return {"ok": True, "state": self.get_state()}

    def end_turn(self) -> dict:
        """Manually end the current player's turn."""
        if not self.engine:
            return {"ok": False, "error": "No active battle"}

        if self.engine.is_battle_over():
            return {"ok": False, "error": "Battle is over"}

        self.engine.end_current_turn()
        self._flush_engine_events()
        self._auto_enemy_turns()

        return {"ok": True, "state": self.get_state()}

    def _auto_enemy_turns(self) -> None:
        """Execute all consecutive enemy turns."""
        if not self.engine:
            return
        while True:
            if self.engine.is_battle_over():
                break
            active = self.engine.get_active_unit()
            if not active or active.team != "enemy":
                break
            self.engine.execute_enemy_turn(active.unit_id)
            self._flush_engine_events()
            self.engine.end_current_turn()
            self._flush_engine_events()

    # ── State queries ──

    def get_state(self) -> dict:
        """Return a full state snapshot for the frontend."""
        if not self.engine:
            return {"phase": "NONE", "error": "No active battle"}

        e = self.engine
        active = e.get_active_unit()

        units = []
        for u in e.units.values():
            units.append({
                "unit_id": u.unit_id,
                "name": u.name,
                "team": u.team,
                "char_class": u.char_class,
                "hp": u.hp,
                "max_hp": u.max_hp,
                "personal_ap": u.AP,
                "max_personal_ap": u.MAX_AP,
                "patk": u.PATK,
                "matk": u.MATK,
                "def": u.DEF,
                "res": u.RES,
                "spd": u.SPD,
                "hit": u.HIT,
                "eva": u.EVA,
                "mobility": u.mobility,
                "pos": list(u.pos),
                "is_alive": u.is_alive,
            })

        # Active unit's hand (only for player turns)
        shared_hand = []
        if active and active.team == "player":
            for card in e.get_unit_hand(active.unit_id):
                shared_hand.append(card.to_dict())

        # Valid targets for targeting mode
        valid_targets = self._compute_valid_targets()

        # Grid (positions only)
        grid_cells = {}
        for pos_key, unit in e.grid._cells.items():
            grid_cells[f"{pos_key[0]},{pos_key[1]}"] = unit.unit_id

        return {
            "round_num": e.state.round_num,
            "phase": e.state.phase,
            "winner": e.state.winner or None,
            "grid_size": max(TOTAL_ROWS, TOTAL_COLS),
            "units": units,
            "shared_hand": shared_hand,
            "valid_targets": valid_targets,
            "active_unit_id": active.unit_id if active else None,
            "grid": grid_cells,
            "battle_over": e.is_battle_over(),
        }

    def _compute_valid_targets(self) -> list[list[int]]:
        """Compute valid target positions for the active player unit."""
        if not self.engine:
            return []
        active = self.engine.get_active_unit()
        if not active or active.team != "player":
            return []

        targets = []
        enemies = [u for u in self.engine.units.values()
                    if u.team == "enemy" and u.is_alive]
        for enemy in enemies:
            targets.append(list(enemy.pos))
        return targets

    # ── Serialization ──

    def to_dict(self) -> dict:
        """Serialize for save/load."""
        if not self.engine:
            return {"active": False}

        return {
            "active": True,
            "encounter_id": self._encounter_id,
            "session_id": self.session_id,
            "engine_state": {
                "round_num": self.engine.state.round_num,
                "phase": self.engine.state.phase,
                "winner": self.engine.state.winner,
                "turn_order": self.engine.state.turn_order,
                "current_idx": self.engine.state.current_idx,
            },
            "units": {uid: u.to_dict() for uid, u in self.engine.units.items()},
            "pools": {uid: p.to_dict() for uid, p in self.engine.pools.items()},
            "character_metas": self._character_metas,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CombatSession":
        """Restore from a saved state."""
        cs = cls(session_id=data.get("session_id", ""))
        cs._encounter_id = data.get("encounter_id", "")
        cs._character_metas = data.get("character_metas", [])

        # Reconstruct engine
        from combat_engine.engine import CombatState
        engine = CombatEngine()
        es = data.get("engine_state", {})
        engine.state = CombatState(
            round_num=es.get("round_num", 0),
            turn_order=es.get("turn_order", []),
            current_idx=es.get("current_idx", 0),
            phase=es.get("phase", "INIT"),
            winner=es.get("winner", ""),
        )

        # Restore units
        for uid, udict in data.get("units", {}).items():
            unit = CombatUnit(
                unit_id=udict["unit_id"],
                name=udict["name"],
                team=udict["team"],
                char_class=udict.get("char_class", ""),
                max_hp=udict["max_hp"],
                hp=udict["hp"],
                PATK=udict.get("PATK", 10),
                MATK=udict.get("MATK", 10),
                HEAL=udict.get("HEAL", 10),
                DEF=udict.get("DEF", 5),
                RES=udict.get("RES", 5),
                SPD=udict.get("SPD", 10),
                HIT=udict.get("HIT", 5),
                EVA=udict.get("EVA", 5),
                AP=udict.get("AP", 3),
                MAX_AP=udict.get("MAX_AP", 3),
                attributes=udict.get("attributes", {}),
                pos=tuple(udict.get("pos", (-1, -1))),
            )
            engine.units[uid] = unit
            if unit.pos != (-1, -1) and unit.is_alive:
                engine.grid._cells[unit.pos] = unit
                engine.grid._positions[uid] = unit.pos

        # Restore card pools
        for uid, pdict in data.get("pools", {}).items():
            from combat_engine.card import CardPool
            pool = CardPool()
            pool.deck = [Card.from_dict(c) for c in pdict.get("deck", [])]
            pool.hand = [Card.from_dict(c) for c in pdict.get("hand", [])]
            pool.discard = [Card.from_dict(c) for c in pdict.get("discard", [])]
            pool.exhaust = [Card.from_dict(c) for c in pdict.get("exhaust", [])]
            engine.pools[uid] = pool

        cs.engine = engine
        cs.engine.on_event = cs._enqueue_event
        return cs
