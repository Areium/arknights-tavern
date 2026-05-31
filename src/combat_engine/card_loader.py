"""
Card loader — loads cards from JSON data files.

Data sources (in priority order):
  1. data/characters/<name>/combat.json — character-specific cards
  2. data/classes/<class>/cards.json — class-level card pools
  3. combat_engine.card_data.get_starting_deck() — hardcoded fallback
"""

import json
import os
import logging
from pathlib import Path
from typing import Optional

from combat_engine.card import Card

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CHAR_DIR = PROJECT_ROOT / "data" / "characters"
CLASS_DIR = PROJECT_ROOT / "data" / "classes"


def _load_json(path: Path) -> Optional[dict]:
    """Load a JSON file, returning None if missing or malformed."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load %s: %s", path, e)
        return None


def load_character_cards(character_name: str) -> Optional[list[Card]]:
    """Load a character's full card deck from combat.json.

    Combines exclusive cards (from combat.json) with class cards
    (from data/classes/<class>/cards.json). Returns None if no combat.json
    exists, signaling the caller to fall back to hardcoded pools.
    """
    combat_path = CHAR_DIR / character_name / "combat.json"
    combat_data = _load_json(combat_path)
    if not combat_data:
        return None

    cards: list[Card] = []

    # Load exclusive cards
    for card_dict in combat_data.get("exclusive_cards", []):
        try:
            cards.append(_dict_to_card(card_dict))
        except Exception as e:
            logger.warning("Failed to parse exclusive card '%s': %s",
                           card_dict.get("name", "?"), e)

    # Load class cards referenced by the character
    class_name = combat_data.get("class_name")
    class_cards_data = combat_data.get("class_cards", [])

    if class_cards_data and isinstance(class_cards_data[0], dict):
        # Inline full card definitions (from table-format combat.md)
        for card_dict in class_cards_data:
            try:
                c = _dict_to_card(card_dict)
                c.class_required = class_name or c.class_required
                cards.append(c)
            except Exception as e:
                logger.warning("Failed to parse class card '%s': %s",
                               card_dict.get("name", "?"), e)
    elif class_cards_data and isinstance(class_cards_data[0], str):
        # Card ID references — load from class pool
        class_cards = load_class_cards(class_name)
        if class_cards:
            class_by_id = {c.card_id: c for c in class_cards}
            for ref_id in class_cards_data:
                if ref_id in class_by_id:
                    cards.append(class_by_id[ref_id])

    return cards if cards else None


def load_class_cards(class_name: str) -> Optional[list[Card]]:
    """Load a class's card pool from data/classes/<class>/cards.json."""
    if not class_name:
        return None
    class_path = CLASS_DIR / class_name / "cards.json"
    data = _load_json(class_path)
    if not data:
        return None

    cards: list[Card] = []
    for card_dict in data.get("cards", []):
        try:
            cards.append(_dict_to_card(card_dict))
        except Exception as e:
            logger.warning("Failed to parse class card '%s': %s",
                           card_dict.get("name", "?"), e)
    return cards if cards else None


def _dict_to_card(d: dict) -> Card:
    """Convert a dict to a Card object, mapping extended fields to standard fields."""
    # Map extended schema fields to Card dataclass fields
    card_data = {
        "card_id": d.get("card_id", ""),
        "name": d.get("name", ""),
        "description": d.get("description") or d.get("effect", ""),
        "damage_type": d.get("damage_type", "physical"),
        "min_damage": d.get("min_damage", 0),
        "max_damage": d.get("max_damage", 0),
        "atk_scale": d.get("atk_scale", 0.0),
        "target": d.get("target", "SINGLE"),
        "range": d.get("range", 1),
        "cost": d.get("cost", 0),
        "tier": d.get("tier", "basic"),
        "class_required": d.get("class_required", "any"),
        "owner": d.get("owner"),
    }
    return Card(**card_data)
