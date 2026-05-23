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
from combat_engine.card import Card, CardPool
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
              character_metas: list[dict] = None,
              enemies_override: list[dict] = None) -> dict:
        """Initialize a battle from an encounter definition and character list.

        Args:
            encounter_id: Key in data/combat/encounters/ (without .md)
            character_names: List of character names to load from data/characters/
            character_metas: List of character metadata dicts (takes precedence over names)
            enemies_override: Optional list of {name, count, positions} dicts.
                              When provided, replaces encounter waves.

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
            cards = get_starting_deck(char_class, count=7)
            if not cards:
                cards = get_starting_deck("辅助", count=7)
                logger.warning("No card pool for class '%s', using 辅助 fallback", char_class)

            pos = default_positions[i] if i < len(default_positions) else (4 + i % 3, 0)
            self.engine.add_player_unit(unit, cards, pos)

        # ── Load enemies ──
        if enemies_override:
            enemy_defs = enemies_override
        else:
            enemy_defs = []
            for wave in encounter.get("waves", []):
                enemy_defs.extend(wave.get("enemies", []))

        for enemy_def in enemy_defs:
            enemy_name = enemy_def.get("enemy", enemy_def.get("name", ""))
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
                    # Auto-place in enemy zone (cols 3-7)
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
                "unit_id": str (for move),
                "target": [row, col]
            }

        Returns:
            dict with keys: "ok", "events" (list), "state" (full snapshot)
        """
        if not self.engine:
            return {"ok": False, "error": "No active battle"}

        if self.engine.is_battle_over():
            return {"ok": False, "error": "Battle is over"}

        if self.engine.state.phase != "PLAYER_TURN":
            return {"ok": False, "error": "Not player turn"}

        action_type = action.get("action", "")
        target = tuple(action.get("target", [0, 0]))

        try:
            if action_type == "play_card":
                card_index = action.get("card_index", 0)
                hand = self.engine.shared_pool.hand if self.engine.shared_pool else []
                if card_index < 0 or card_index >= len(hand):
                    return {"ok": False, "error": f"Invalid card index: {card_index}"}

                card = hand[card_index]
                if card.cost > self.engine.shared_ap:
                    return {"ok": False, "error": f"共用 AP 不足 ({self.engine.shared_ap} < {card.cost})"}

                # Find the unit that owns this card
                owner_unit = None
                for u in self.engine.units.values():
                    if u.team == "player" and u.is_alive and u.name == card.owner:
                        owner_unit = u
                        break
                if not owner_unit:
                    return {"ok": False, "error": f"Card owner '{card.owner}' not found or not alive"}

                # For auto-target cards, use caster position
                if card.target in ("SELF", "ALL_ALLIES", "GLOBAL"):
                    target = owner_unit.pos

                self.engine.play_card(owner_unit.unit_id, card, target)
                self._flush_engine_events()

            elif action_type == "move":
                unit_id = action.get("unit_id", "")
                unit = self.engine.units.get(unit_id)
                if not unit or unit.team != "player" or not unit.is_alive:
                    return {"ok": False, "error": "Invalid unit for move"}

                if self.engine.move_unit(unit_id, target):
                    self._flush_engine_events()
                else:
                    return {"ok": False, "error": "Invalid move target"}

            else:
                return {"ok": False, "error": f"Unknown action: {action_type}"}

        except Exception as e:
            logger.exception("Error executing action")
            return {"ok": False, "error": str(e)}

        return {"ok": True, "state": self.get_state()}

    def end_turn(self) -> dict:
        """End the player's round: execute enemy phase, draw new hand."""
        if not self.engine:
            return {"ok": False, "error": "No active battle"}

        if self.engine.is_battle_over():
            return {"ok": False, "error": "Battle is over"}

        self.engine.end_player_round()
        self._flush_engine_events()

        return {"ok": True, "state": self.get_state()}

    # ── State queries ──

    def get_state(self) -> dict:
        """Return a full state snapshot for the frontend."""
        if not self.engine:
            return {"phase": "NONE", "error": "No active battle"}

        e = self.engine

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
                "attributes": dict(u.attributes) if u.attributes else {},
            })

        # Shared hand — always available from shared pool
        shared_hand = []
        if e.shared_pool:
            for card in e.shared_pool.hand:
                shared_hand.append(card.to_dict())

        # Shared card pool data (deck, discard, exhaust)
        shared_pool_data = e.shared_pool.to_dict() if e.shared_pool else {}

        # Per-player hand breakdown for character selection UI
        player_hands: dict[str, list[dict]] = {}
        if e.shared_pool:
            for u in e.units.values():
                if u.team == "player" and u.is_alive:
                    player_hands[u.unit_id] = [
                        c.to_dict() for c in e.shared_pool.hand
                        if c.owner == u.name
                    ]

        # Valid targets for targeting mode
        valid_targets = self._compute_valid_targets()

        # Valid move destinations (computed client-side for selected unit)
        valid_moves: list[list[int]] = []

        # Grid (positions only)
        grid_cells = {}
        for pos_key, unit in e.grid._cells.items():
            grid_cells[f"{pos_key[0]},{pos_key[1]}"] = unit.unit_id

        return {
            "round_num": e.state.round_num,
            "phase": e.state.phase,
            "winner": e.state.winner or None,
            "grid_size": max(TOTAL_ROWS, TOTAL_COLS),
            "shared_ap": e.shared_ap,
            "shared_ap_max": e.SHARED_AP_MAX,
            "units": units,
            "shared_hand": shared_hand,
            "player_hands": player_hands,
            "shared_pool": {"deck": shared_pool_data.get("deck", []),
                           "discard": shared_pool_data.get("discard", []),
                           "exhaust": shared_pool_data.get("exhaust", [])},
            "valid_targets": valid_targets,
            "valid_moves": valid_moves,
            "active_unit_id": None,
            "grid": grid_cells,
            "battle_over": e.is_battle_over(),
        }

    def _compute_valid_targets(self) -> list[list[int]]:
        """Compute valid target positions (all alive enemies) during player phase."""
        if not self.engine:
            return []
        if self.engine.state.phase != "PLAYER_TURN":
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
            "shared_pool": self.engine.shared_pool.to_dict() if self.engine.shared_pool else {},
            "enemy_pools": {uid: p.to_dict() for uid, p in self.engine.enemy_pools.items()},
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

        # Restore shared card pool
        sp = data.get("shared_pool", {})
        if sp:
            engine.shared_pool = CardPool(hand_size=CombatEngine.SHARED_HAND_SIZE)
            engine.shared_pool.deck = [Card.from_dict(c) for c in sp.get("deck", [])]
            engine.shared_pool.hand = [Card.from_dict(c) for c in sp.get("hand", [])]
            engine.shared_pool.discard = [Card.from_dict(c) for c in sp.get("discard", [])]
            engine.shared_pool.exhaust = [Card.from_dict(c) for c in sp.get("exhaust", [])]

        # Restore enemy card pools
        for uid, pdict in data.get("enemy_pools", {}).items():
            pool = CardPool(hand_size=5)
            pool.deck = [Card.from_dict(c) for c in pdict.get("deck", [])]
            pool.hand = [Card.from_dict(c) for c in pdict.get("hand", [])]
            pool.discard = [Card.from_dict(c) for c in pdict.get("discard", [])]
            pool.exhaust = [Card.from_dict(c) for c in pdict.get("exhaust", [])]
            engine.enemy_pools[uid] = pool

        cs.engine = engine
        cs.engine.on_event = cs._enqueue_event
        return cs
