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

    # ── Background loading ──

    _BG_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
    _DEFAULT_BG_ID = "default"

    def load_background(self, bg_id: str) -> dict | None:
        """Load background metadata from data/combat/backgrounds/<bg_id>/index.md."""
        path = self._root / "backgrounds" / bg_id / "index.md"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return dict(frontmatter.load(f).metadata)
        except (OSError, ValueError) as e:
            logger.error("Failed to load background %s: %s", bg_id, e)
            return None

    def list_background_ids(self) -> list[str]:
        """枚举全局可用战斗背景 ID（目录含 index.md）。"""
        root = self._root / "backgrounds"
        if not root.is_dir():
            return []
        return sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and (p / "index.md").is_file()
        )

    def background_image_url(self, bg_id: str) -> str | None:
        """Return the asset URL of a background's image file, or None if absent.

        The image is the frontmatter `image` field when set, otherwise the
        first image file found in the background directory.
        """
        bg_dir = self._root / "backgrounds" / bg_id
        if not bg_dir.is_dir():
            return None

        candidates: list[str] = []
        meta = self.load_background(bg_id)
        if meta and meta.get("image"):
            candidates.append(str(meta["image"]))
        try:
            candidates += sorted(
                p.name for p in bg_dir.iterdir()
                if p.is_file() and p.suffix.lower() in self._BG_IMAGE_EXTS
            )
        except OSError:
            return None

        for name in candidates:
            if (bg_dir / name).is_file():
                return f"/api/assets/combat_backgrounds/{bg_id}/{name}"
        return None

    def resolve_background(self, encounter: dict | None,
                           location_name: str = "",
                           session_dir: str | Path | None = None,
                           session_id: str = "") -> str | None:
        """Pick the combat background image URL.

        Priority: encounter `background` field → location doc `combat_bg`
        field → the "default" background. At each level, a session-local
        override (<session_dir>/backgrounds/<bg_id>.<ext>) wins over the
        global image. Returns None when no candidate has an image
        (frontend falls back to the solid background color).
        """
        bg_id = str((encounter or {}).get("background") or "")
        if not bg_id and location_name:
            bg_id = self._location_combat_bg(location_name)

        candidates = [bg_id] if bg_id else []
        if self._DEFAULT_BG_ID not in candidates:
            candidates.append(self._DEFAULT_BG_ID)

        for cand in candidates:
            if session_dir and session_id:
                url = self._session_background_url(Path(session_dir), session_id, cand)
                if url:
                    return url
            url = self.background_image_url(cand)
            if url:
                return url
        return None

    def _session_background_url(self, session_dir: Path, session_id: str,
                                bg_id: str) -> str | None:
        """Session-local override: <session_dir>/backgrounds/<bg_id>.<ext>."""
        bg_dir = session_dir / "backgrounds"
        for ext in self._BG_IMAGE_EXTS:
            f = bg_dir / f"{bg_id}{ext}"
            if f.is_file():
                return f"/api/sessions/{session_id}/backgrounds/{f.name}"
        return None

    def _location_combat_bg(self, location_name: str) -> str:
        """Find the `combat_bg` field of a location doc matching name/alias/dir."""
        loc_base = self._root.parent / "environment" / "Location"
        if not loc_base.is_dir():
            return ""
        for index_md in sorted(loc_base.rglob("index.md")):
            try:
                with open(index_md, "r", encoding="utf-8") as f:
                    meta = frontmatter.load(f).metadata
            except (OSError, ValueError):
                continue
            if location_name in (meta.get("name"), meta.get("alias"),
                                 index_md.parent.name):
                return str(meta.get("combat_bg") or "")
        return ""

