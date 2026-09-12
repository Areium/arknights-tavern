"""
CombatDataLoader — 加载战斗节点（JSON）与统一敌人库（`data/enemies/*.md`）。

数据布局（批次 1 起）::

    data/combat/nodes/<node_id>.json   战斗节点：地图/波形/条件/奖励/打法/绑定
    data/combat/tiles/<tile_id>.json   格子类型注册表（可选，内置 ground/wall/cover/...）
    data/enemies/<name>.md             敌人：叙事属性 attributes + 战斗字段 combat_stats
    data/combat/backgrounds/<id>/      战斗背景

敌人既可写绝对 `combat_stats`（设计者直接调血量），也可只写 `attributes`
（引擎按与玩家同一套公式派生战斗数值）。
"""

import json
import logging
from pathlib import Path

import frontmatter

from combat_engine.entity import CombatUnit

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data" / "combat"

# 敌人可写字段 → CombatUnit 属性（战斗数值覆盖用）
_ENEMY_STAT_FIELDS = {
    "hp": ("max_hp", "hp"),
    "patk": ("PATK",),
    "matk": ("MATK",),
    "heal": ("HEAL",),
    "defense": ("DEF",),
    "resist": ("RES",),
    "spd": ("SPD",),
    "hit": ("HIT",),
    "eva": ("EVA",),
    "max_ap": ("AP", "MAX_AP"),
}
# 敌人可写字段 → CombatUnit 元数据
_ENEMY_META_FIELDS = (
    "class", "level", "power_tier", "role", "action_slots", "threat_points",
    "ai_behavior", "ai_skills", "drop_items", "drop_rate", "xp_reward",
)


def apply_enemy_overrides(unit: CombatUnit, overrides: dict | None) -> CombatUnit:
    """把（会话/节点级的）敌人覆盖应用到单位实例，返回同一实例。

    `overrides` 可含 `combat_stats` 子字典或直接平铺数值键，
    外加 `class/level/ai_behavior/ai_skills/action_slots/threat_points/...`。
    """
    if not overrides:
        return unit
    stats = dict(overrides.get("combat_stats") or {})
    for key, value in overrides.items():
        if key in _ENEMY_STAT_FIELDS:
            stats[key] = value

    for key, value in stats.items():
        fields = _ENEMY_STAT_FIELDS.get(key)
        if not fields or value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            logger.warning("敌人覆盖 %s=%r 非数值，已忽略", key, value)
            continue
        if key in ("hp",):
            number = int(number)
        for field in fields:
            setattr(unit, field, int(number) if field in ("max_hp", "hp", "DEF", "RES",
                                                          "HIT", "EVA", "AP", "MAX_AP")
                    else number)

    for key in _ENEMY_META_FIELDS:
        if key in overrides and overrides[key] is not None:
            value = overrides[key]
            if key == "class":
                unit.char_class = str(value)
            elif key == "ai_skills":
                unit.ai_skills = list(value or [])
            elif key == "action_slots":
                unit.action_slots = max(0, int(value))
            elif key == "threat_points":
                unit.threat_points = int(value)
            else:
                setattr(unit, key, value if not isinstance(value, str) else value)
    return unit


class CombatDataLoader:
    """加载战斗节点、敌人、格子注册表与背景。"""

    def __init__(self, data_dir: str = ""):
        self._root = Path(data_dir) if data_dir else _DATA_DIR
        self._enemy_dir = self._root.parent / "enemies"
        self._node_dir = self._root / "nodes"
        self._tiles_dir = self._root / "tiles"
        self._node_index_cache: dict | None = None
        self._enemy_cache: dict[str, dict] = {}

    # ── Enemy loading ──

    def enemy_path(self, name: str) -> Path:
        return self._enemy_dir / f"{name}.md"

    def load_enemy(self, name: str, stat_overrides: dict | None = None) -> CombatUnit | None:
        """按名字加载敌人（`data/enemies/<name>.md`），可选逐实例数值覆盖。"""
        path = self.enemy_path(name)
        meta = self._read_enemy_meta(name)
        if meta is None:
            logger.warning("Enemy file not found: %s", path)
            return None
        return self.load_enemy_from_meta(meta, stat_overrides=stat_overrides)

    def _read_enemy_meta(self, name: str) -> dict | None:
        if name in self._enemy_cache:
            return self._enemy_cache[name]
        path = self.enemy_path(name)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = dict(frontmatter.load(f).metadata)
        except (OSError, ValueError) as e:
            logger.error("Failed to load enemy %s: %s", path, e)
            return None
        self._enemy_cache[name] = meta
        return meta

    @staticmethod
    def load_enemy_from_meta(meta: dict, stat_overrides: dict | None = None) -> CombatUnit | None:
        """由敌人元数据构建战斗单位。

        有 `combat_stats` 时用绝对值；否则按 `attributes` 派生（与玩家同一套公式），
        因此纯叙事条目也能直接上战场。
        """
        if not meta:
            return None
        name = meta.get("name", "未知")
        stats = meta.get("combat_stats") or {}
        role = str(meta.get("role", "") or "")
        declared_slots = meta.get("action_slots")
        if declared_slots is None:
            action_slots = 2 if role in ("elite", "boss", "精英", "首领", "队长") else 1
        else:
            action_slots = int(declared_slots)

        if stats:
            unit = CombatUnit.create_enemy(
                name=name,
                char_class=meta.get("class", ""),
                hp=int(stats.get("hp", 80) or 80),
                patk=float(stats.get("patk", 8) or 8),
                matk=float(stats.get("matk", 8) or 8),
                defense=int(stats.get("defense", 4) or 4),
                resist=int(stats.get("resist", 4) or 4),
                spd=float(stats.get("spd", 8) or 8),
                hit=int(stats.get("hit", 4) or 4),
                eva=int(stats.get("eva", 4) or 4),
                max_ap=int(stats.get("max_ap", 3) or 3),
                ai_behavior=meta.get("ai_behavior", "aggressive"),
                ai_skills=meta.get("ai_skills"),
                action_slots=action_slots,
                power_tier=str(meta.get("power_tier", "") or ""),
                role=role,
                threat_points=int(meta.get("threat_points", 0) or 0),
            )
        else:
            unit = CombatUnit.from_character_metadata(meta, team="enemy")
            unit.name = name
            unit.unit_id = name
            if meta.get("class"):
                unit.char_class = str(meta["class"])
            unit.ai_behavior = str(meta.get("ai_behavior", "aggressive") or "aggressive")
            unit.ai_skills = list(meta.get("ai_skills") or [])
            unit.action_slots = action_slots
            unit.power_tier = str(meta.get("power_tier", "") or "")
            unit.role = role
            unit.threat_points = int(meta.get("threat_points", 0) or 0)

        return apply_enemy_overrides(unit, stat_overrides)

    def load_enemy_meta(self, name: str) -> dict | None:
        """敌人奖励元数据（掉落/掉率/经验）；缺省视为无奖励。"""
        meta = self._read_enemy_meta(name)
        if meta is None:
            return None
        return {
            "drop_items": meta.get("drop_items", []),
            "drop_rate": float(meta.get("drop_rate", 0.0) or 0.0),
            "xp_reward": int(meta.get("xp_reward", 0) or 0),
        }

    def list_enemy_names(self) -> list[str]:
        if not self._enemy_dir.is_dir():
            return []
        return sorted(p.stem for p in self._enemy_dir.glob("*.md")
                      if p.stem != "TEMPLATE")

    def list_enemy_catalog(self) -> list[dict]:
        """敌人图鉴（编辑器/选择器用）：叙事字段 + 战斗数值 + 是否纯派生。"""
        catalog: list[dict] = []
        for name in self.list_enemy_names():
            meta = self._read_enemy_meta(name) or {}
            stats = meta.get("combat_stats") or {}
            derived = not stats
            unit = self.load_enemy_from_meta(meta)
            catalog.append({
                "name": name,
                "summary": meta.get("summary", ""),
                "race": meta.get("race", ""),
                "faction": meta.get("faction", ""),
                "class": meta.get("class", ""),
                "level": int(meta.get("level", 1) or 1),
                "power_tier": meta.get("power_tier", ""),
                "role": meta.get("role", ""),
                "action_slots": int(meta.get("action_slots", 1) or 1),
                "threat_points": float(meta.get("threat_points", 0) or 0),
                "ai_behavior": meta.get("ai_behavior", "aggressive"),
                "ai_skills": list(meta.get("ai_skills") or []),
                "drop_items": list(meta.get("drop_items") or []),
                "drop_rate": float(meta.get("drop_rate", 0) or 0),
                "xp_reward": int(meta.get("xp_reward", 0) or 0),
                "derived_from_attributes": derived,
                "combat_stats": {
                    "hp": getattr(unit, "max_hp", 0),
                    "patk": getattr(unit, "PATK", 0),
                    "matk": getattr(unit, "MATK", 0),
                    "defense": getattr(unit, "DEF", 0),
                    "resist": getattr(unit, "RES", 0),
                    "spd": getattr(unit, "SPD", 0),
                    "hit": getattr(unit, "HIT", 0),
                    "eva": getattr(unit, "EVA", 0),
                    "max_ap": getattr(unit, "MAX_AP", 0),
                } if unit else {},
            })
        return catalog

    # ── Item loading ──

    def load_item_meta(self, name: str) -> dict | None:
        """Load an item's frontmatter (name, category, combat_effect) from data/items/."""
        base = self._root.parent / "items"
        for path in (base / name / "index.md", base / f"{name}.md"):
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return dict(frontmatter.load(f).metadata)
                except (OSError, ValueError) as e:
                    logger.error("Failed to load item %s: %s", path, e)
                    return None
        return None

    # ── Node loading（战斗节点 JSON）──

    def _node_index(self) -> dict:
        """node_id / 文件名 / 中文名 → 文件路径（首次调用构建并缓存）。"""
        if self._node_index_cache is not None:
            return self._node_index_cache

        index: dict = {}
        if self._node_dir.is_dir():
            for path in sorted(self._node_dir.glob("*.json")):
                if path.stem.upper().startswith("TEMPLATE"):
                    continue
                index.setdefault(path.stem, path)
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for key in ("node_id", "name", "alias"):
                    value = str(data.get(key) or "").strip()
                    if value:
                        index.setdefault(value, path)
        self._node_index_cache = index
        return index

    def resolve_node_path(self, node_id: str):
        """解析节点引用（node_id / 文件名 / 中文名）到文件路径。"""
        if not node_id:
            return None
        direct = self._node_dir / f"{node_id}.json"
        if direct.exists():
            return direct
        return self._node_index().get(str(node_id).strip())

    def load_node(self, node_id: str) -> dict | None:
        """加载战斗节点（id / 文件名 / 中文名均可）。"""
        path = self.resolve_node_path(node_id)
        if path is None:
            logger.warning("战斗节点不存在: %s", node_id)
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.error("战斗节点解析失败 %s: %s", path, e)
            return None
        data.setdefault("node_id", path.stem)
        return data

    def list_nodes(self) -> list[dict]:
        """节点摘要列表（下拉选择 / 编辑器用）。"""
        summaries: list[dict] = []
        if not self._node_dir.is_dir():
            return summaries
        for path in sorted(self._node_dir.glob("*.json")):
            if path.stem.upper().startswith("TEMPLATE"):
                continue
            data = self.load_node(path.stem)
            if not data:
                continue
            battle_map = (data.get("map") or {})
            waves = data.get("waves") or []
            unit_total = sum(int(e.get("count", 1) or 1)
                             for wave in waves for e in (wave.get("enemies") or []))
            summaries.append({
                "node_id": data.get("node_id", path.stem),
                "name": data.get("name", path.stem),
                "summary": data.get("summary", ""),
                "rows": battle_map.get("rows"),
                "cols": battle_map.get("cols"),
                "unit_total": unit_total,
                "wave_count": len(waves),
                "category": (data.get("difficulty") or {}).get("category", ""),
                "band": (data.get("difficulty") or {}).get("band", ""),
                "bind": data.get("bind", {}),
                "background": data.get("background", ""),
            })
        return summaries

    def load_map(self, node: dict):
        """解析节点的 `map` 段为 BattleMap（校验失败抛 MapError）。"""
        from combat_map import resolve_map
        return resolve_map((node or {}).get("map"), tiles_dir=self._tiles_dir)

    def load_tile_registry(self):
        """格子类型注册表（内置 + `data/combat/tiles/*.json`）。"""
        from combat_map import load_tile_registry
        return load_tile_registry(self._tiles_dir)

    def rules_of(self, node: dict | None) -> dict:
        """节点规则开关（度量/切角）；缺省为统一曼哈顿 + 禁止切角。"""
        rules = dict((node or {}).get("rules") or {})
        rules.setdefault("range_metric", "manhattan")
        rules.setdefault("allow_corner_cut", False)
        return rules

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

