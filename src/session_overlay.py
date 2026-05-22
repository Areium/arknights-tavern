"""
会话覆盖层：管理单个会话对模板数据的修改。

设计：
- 每个会话在 data/memory/sessions/{mode}/{session_id}/overrides.json 维护一份覆盖数据
- 自由模式和剧情模式的会话分目录存储
- 加载角色/物品/环境时，先读模板，再合并会话覆盖
- 只存储与模板不同的字段，未覆盖的字段跟随模板更新

覆盖优先级：会话覆盖 > 模板原始值
"""

import json
import os
import copy
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SESSIONS_DIR = _PROJECT_ROOT / "data" / "memory" / "sessions"


def _get_overlay_path(mode: str, session_id: str) -> Path:
    return _SESSIONS_DIR / mode / session_id / "overrides.json"


class SessionOverlay:
    """单个会话的覆盖数据管理器。"""

    def __init__(self, session_id: str, mode: str = "free"):
        self.session_id = session_id
        self.mode = mode
        self._data: dict = {}
        self._load()

    # ── 持久化 ──

    def _load(self):
        path = _get_overlay_path(self.mode, self.session_id)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.debug("已加载会话覆盖: %s (%d 个角色, %d 个物品)",
                             self.session_id,
                             len(self._data.get("characters", {})),
                             len(self._data.get("items", {})))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("读取会话覆盖文件失败: %s", e)
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        path = _get_overlay_path(self.mode, self.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        import time
        self._data["updated_at"] = time.time()
        self._data["session_id"] = self.session_id
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # ── 角色覆盖 ──

    def get_character_overrides(self, name: str) -> dict:
        """获取指定角色的覆盖数据（metadata + content）。"""
        chars = self._data.get("characters", {})
        return chars.get(name, {})

    def has_character_overrides(self, name: str) -> bool:
        """检查角色是否有覆盖数据。"""
        return name in self._data.get("characters", {})

    def set_character_overrides(self, name: str, overrides: dict):
        """设置角色覆盖。overrides 可包含 metadata 和/或 content 字段。"""
        if "characters" not in self._data:
            self._data["characters"] = {}
        existing = self._data["characters"].get(name, {})
        merged = _deep_merge(existing, overrides)
        self._data["characters"][name] = merged
        self._save()
        logger.info("会话 %s: 角色 %s 覆盖已更新", self.session_id, name)

    def delete_character_overrides(self, name: str) -> bool:
        """删除角色覆盖，还原为模板。"""
        chars = self._data.get("characters", {})
        if name in chars:
            del chars[name]
            self._save()
            logger.info("会话 %s: 角色 %s 覆盖已删除", self.session_id, name)
            return True
        return False

    def apply_character_overrides(self, name: str, metadata: dict, content: str) -> tuple[dict, str]:
        """将覆盖数据合并到模板数据上，返回 (merged_metadata, merged_content)。"""
        overrides = self.get_character_overrides(name)
        if not overrides:
            return metadata, content

        merged_meta = _deep_merge(copy.deepcopy(metadata), overrides.get("metadata", {}))
        merged_content = overrides.get("content") if overrides.get("content") is not None else content
        return merged_meta, merged_content

    # ── 物品覆盖 ──

    def get_item_overrides(self, item_id: str) -> dict:
        items = self._data.get("items", {})
        return items.get(item_id, {})

    def has_item_overrides(self, item_id: str) -> bool:
        return item_id in self._data.get("items", {})

    def set_item_overrides(self, item_id: str, overrides: dict):
        if "items" not in self._data:
            self._data["items"] = {}
        existing = self._data["items"].get(item_id, {})
        merged = _deep_merge(existing, overrides)
        self._data["items"][item_id] = merged
        self._save()
        logger.info("会话 %s: 物品 %s 覆盖已更新", self.session_id, item_id)

    def delete_item_overrides(self, item_id: str) -> bool:
        items = self._data.get("items", {})
        if item_id in items:
            del items[item_id]
            self._save()
            logger.info("会话 %s: 物品 %s 覆盖已删除", self.session_id, item_id)
            return True
        return False

    def apply_item_overrides(self, item_id: str, metadata: dict, content: str) -> tuple[dict, str]:
        """将物品覆盖合并到模板数据上。"""
        overrides = self.get_item_overrides(item_id)
        if not overrides:
            return metadata, content

        merged_meta = _deep_merge(copy.deepcopy(metadata), overrides.get("metadata", {}))
        merged_content = overrides.get("content") if overrides.get("content") is not None else content
        return merged_meta, merged_content

    # ── 环境覆盖 ──

    def get_environment_overrides(self) -> dict:
        return self._data.get("environment", {})

    def set_environment_overrides(self, overrides: dict):
        existing = self._data.get("environment", {})
        merged = _deep_merge(existing, overrides)
        self._data["environment"] = merged
        self._save()
        logger.info("会话 %s: 环境覆盖已更新", self.session_id)

    def delete_environment_overrides(self) -> bool:
        if "environment" in self._data:
            del self._data["environment"]
            self._save()
            return True
        return False

    # ── 全量导出 ──

    def to_dict(self) -> dict:
        """返回全部覆盖数据（供 API 使用）。"""
        return {
            "session_id": self.session_id,
            "characters": self._data.get("characters", {}),
            "items": self._data.get("items", {}),
            "environment": self._data.get("environment", {}),
        }

    @staticmethod
    def delete_session_overlays(session_id: str, mode: str = "free"):
        """删除整个会话的覆盖目录。"""
        import shutil
        session_dir = _SESSIONS_DIR / mode / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info("已删除会话覆盖数据: %s/%s", mode, session_id)


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。override 中的值覆盖 base，嵌套字典递归合并。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
