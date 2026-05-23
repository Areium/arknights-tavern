"""
CombatDataLoader — loads enemies, cards, and encounters from data/combat/ markdown.

Uses the project's existing frontmatter library. Maps YAML frontmatter
to demo/combat entity and card dataclasses.
"""

import os
import random
import logging
from pathlib import Path
from typing import Optional

import frontmatter

from combat_engine.entity import CombatUnit
from combat_engine.card import Card

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data" / "combat"


class CombatDataLoader:
    """Loads combat data from data/combat/ markdown files."""

    def __init__(self, data_dir: str = ""):
        self._root = Path(data_dir) if data_dir else _DATA_DIR

    # ── Enemy loading ──

    def load_enemy(self, name: str) -> CombatUnit | None:
        """Load an enemy by name from data/combat/enemies/<name>.md."""
        path = self._root / "enemies" / f"{name}.md"
        if not path.exists():
            logger.warning("Enemy file not found: %s", path)
            return None
        return self.load_enemy_from_file(str(path))

    @staticmethod
    def load_enemy_from_file(path: str) -> CombatUnit | None:
        """Load an enemy from a specific markdown file path."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = frontmatter.load(f).metadata
        except (OSError, ValueError) as e:
            logger.error("Failed to load enemy from %s: %s", path, e)
            return None

        stats = meta.get("combat_stats", {})
        if not stats:
            logger.warning("Enemy %s has no combat_stats", meta.get("name", path))
            return None

        return CombatUnit.create_enemy(
            name=meta.get("name", "未知"),
            char_class=meta.get("class", ""),
            hp=stats.get("hp", 80),
            patk=stats.get("patk", 8),
            matk=stats.get("matk", 8),
            defense=stats.get("defense", 4),
            resist=stats.get("resist", 4),
            spd=stats.get("spd", 8),
            hit=stats.get("hit", 4),
            eva=stats.get("eva", 4),
            max_ap=stats.get("max_ap", 3),
        )

    def list_enemies(self) -> list[str]:
        """List all available enemy names."""
        enemies_dir = self._root / "enemies"
        if not enemies_dir.exists():
            return []
        names = []
        for f in enemies_dir.glob("*.md"):
            if f.name.startswith("_") or f.name.startswith("TEMPLATE"):
                continue
            names.append(f.stem)
        return sorted(names)

    # ── Card loading ──

    def load_card(self, class_name: str, card_name: str) -> Card | None:
        """Load a single card by class and card name."""
        path = self._root / "cards" / class_name / f"{card_name}.md"
        if not path.exists():
            return None
        return self.load_card_from_file(str(path))

    @staticmethod
    def load_card_from_file(path: str) -> Card | None:
        """Load a Card from a markdown file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = frontmatter.load(f).metadata
        except (OSError, ValueError) as e:
            logger.error("Failed to load card from %s: %s", path, e)
            return None

        try:
            return Card(
                card_id=meta.get("card_id", ""),
                name=meta.get("name", ""),
                description=meta.get("description", ""),
                damage_type=meta.get("damage_type", "physical"),
                min_damage=meta.get("min_damage", 1),
                max_damage=meta.get("max_damage", 1),
                atk_scale=meta.get("atk_scale", 0.4),
                target=meta.get("target", "SINGLE"),
                range=meta.get("range", 1),
                cost=meta.get("cost", 1),
                tier=meta.get("tier", "basic"),
                class_required=meta.get("class_required", "any"),
                owner=meta.get("owner"),
            )
        except (TypeError, KeyError) as e:
            logger.error("Invalid card data in %s: %s", path, e)
            return None

    def load_cards_for_class(self, class_name: str) -> list[Card]:
        """Load all cards for a given class."""
        class_dir = self._root / "cards" / class_name
        if not class_dir.exists():
            return []
        cards = []
        for f in sorted(class_dir.glob("*.md")):
            if f.name.startswith("_") or f.name.startswith("TEMPLATE"):
                continue
            card = self.load_card_from_file(str(f))
            if card:
                cards.append(card)
        return cards

    def build_starting_deck(self, class_name: str, count: int = 5) -> list[Card]:
        """Draw a random starting deck of basic cards for a class."""
        pool = self.load_cards_for_class(class_name)
        basics = [c for c in pool if c.tier == "basic"]
        if len(basics) < count:
            count = len(basics)
        if count == 0:
            return []
        return random.sample(basics, count)

    # ── Encounter loading ──

    def load_encounter(self, encounter_id: str) -> dict | None:
        """Load an encounter by ID from data/combat/encounters/<id>.md."""
        path = self._root / "encounters" / f"{encounter_id}.md"
        if not path.exists():
            logger.warning("Encounter file not found: %s", path)
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return dict(frontmatter.load(f).metadata)
        except (OSError, ValueError) as e:
            logger.error("Failed to load encounter %s: %s", encounter_id, e)
            return None

    def list_encounters(self) -> list[str]:
        """List all available encounter IDs."""
        enc_dir = self._root / "encounters"
        if not enc_dir.exists():
            return []
        ids = []
        for f in enc_dir.glob("*.md"):
            if f.name.startswith("_") or f.name.startswith("TEMPLATE"):
                continue
            ids.append(f.stem)
        return sorted(ids)
