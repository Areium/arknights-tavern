"""
CombatDataLoader — loads enemies and encounters from data/combat/ markdown.
"""

import logging
from pathlib import Path

import frontmatter

from combat_engine.entity import CombatUnit

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

