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

    # ── 战斗模式设置 ──

    def get_combat_mode(self) -> str:
        """获取战斗模式。返回 "narrative"（默认）或 "tactical"。"""
        return self._data.get("combat_mode", "narrative")

    def set_combat_mode(self, mode: str):
        """设置战斗模式。mode 为 "narrative" 或 "tactical"。"""
        if mode not in ("narrative", "tactical"):
            raise ValueError(f"无效的战斗模式: {mode}，可选值: narrative, tactical")
        self._data["combat_mode"] = mode
        self._save()
        logger.info("会话 %s: 战斗模式切换为 %s", self.session_id, mode)

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

    # ── 剧情/任务 ──

    def get_plot_id(self) -> str | None:
        """获取当前会话绑定的剧情 ID。"""
        return self._data.get("plot_id")

    def set_plot_id(self, plot_id: str):
        """设置当前会话绑定的剧情 ID。"""
        self._data["plot_id"] = plot_id
        self._save()
        logger.info("会话 %s: 剧情绑定为 %s", self.session_id, plot_id)

    # ── 剧情开场上下文 ──

    def set_plot_context(self, context: str):
        """存储剧情开场上下文（首次叙述时注入）。"""
        self._data["plot_context"] = context
        self._save()
        logger.info("会话 %s: 剧情开场上下文已存储 (%d 字)", self.session_id, len(context))

    def get_plot_context(self) -> str | None:
        """获取剧情开场上下文。"""
        return self._data.get("plot_context")

    def has_plot_context(self) -> bool:
        """是否有待注入的开场上下文。"""
        return "plot_context" in self._data

    def clear_plot_context(self):
        """清除开场上下文（首次叙述注入后调用）。"""
        self._data.pop("plot_context", None)
        self._save()

    def get_quest_states(self) -> dict:
        """获取所有任务状态 {quest_id: {status, updated_at}}。"""
        return self._data.get("quest_states", {})

    def set_quest_state(self, quest_id: str, status: str):
        """更新单个任务状态（locked/active/completed/failed）。"""
        if "quest_states" not in self._data:
            self._data["quest_states"] = {}
        import time
        self._data["quest_states"][quest_id] = {
            "status": status,
            "updated_at": time.time(),
        }
        self._save()

    def load_quests_from_plot(self, plot_id: str):
        """加载剧情并初始化所有任务状态。

        规则：
        - 所有任务初始为 hidden（不在前端显示）
        - 当玩家在剧情中通过对话/行动触发任务时，LLM/系统将其设为 visible 或 active
        - 序章/开场自动触发的任务由 narrate 推进时激活
        """
        self._data["plot_id"] = plot_id
        if "quest_states" not in self._data:
            self._data["quest_states"] = {}

        quests = _parse_quests_md(plot_id)
        existing = self._data["quest_states"]

        for q in quests:
            qid = q["id"]
            if qid not in existing:
                existing[qid] = {"status": "hidden", "updated_at": 0}

        self._data["quest_states"] = existing
        self._save()
        logger.info("会话 %s: 已加载剧情 %s，共 %d 个任务（全部隐藏）", self.session_id, plot_id, len(quests))

    # ── 全量导出 ──

    def to_dict(self) -> dict:
        """返回全部覆盖数据（供 API 使用）。"""
        return {
            "session_id": self.session_id,
            "plot_id": self._data.get("plot_id"),
            "combat_mode": self.get_combat_mode(),
            "characters": self._data.get("characters", {}),
            "items": self._data.get("items", {}),
            "environment": self._data.get("environment", {}),
            "quest_states": self._data.get("quest_states", {}),
            "has_plot_context": self.has_plot_context(),
        }

    @staticmethod
    def delete_session_overlays(session_id: str, mode: str = "free"):
        """删除整个会话的覆盖目录。"""
        import shutil
        session_dir = _SESSIONS_DIR / mode / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info("已删除会话覆盖数据: %s/%s", mode, session_id)


def _resolve_plot_dir(plot_id: str) -> str | None:
    """通过 plots/_index.md 解析 plot_id 对应的目录名。"""
    import re
    index_path = _PROJECT_ROOT / "data" / "plots" / "_index.md"
    if not index_path.exists():
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 查找 plot_id 对应的 file 字段
        pattern = rf"{re.escape(plot_id)}:\s*\n\s+file:\s*\"([^\"]+)\""
        m = re.search(pattern, content)
        if m:
            file_path = m.group(1)  # e.g. "near-light/index.md"
            return file_path.rsplit("/", 1)[0]  # e.g. "near-light"
    except Exception:
        pass
    return None


def _parse_quests_md(plot_id: str) -> list[dict]:
    """解析指定剧情的 quests.md，返回结构化任务列表。"""
    import re

    # 先尝试直接用 plot_id 作为目录名
    path = _PROJECT_ROOT / "data" / "plots" / plot_id / "quests.md"
    if not path.exists():
        # 通过 _index.md 解析实际目录名
        resolved = _resolve_plot_dir(plot_id)
        if resolved:
            path = _PROJECT_ROOT / "data" / "plots" / resolved / "quests.md"

    if not path.exists():
        logger.warning("未找到剧情任务文件: %s (plot_id=%s)", path, plot_id)
        return []

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    quests = []
    current_chapter = ""
    current_type = "main"  # "main" | "side" | "deep"

    # 检测当前所在章节
    lines = text.split("\n")
    for i, line in enumerate(lines):
        # 追踪章节
        ch_match = re.match(r"^### 第([一二三四五六七八九十\d]+)章", line)
        if ch_match:
            ch_num = ch_match.group(1)
            cn_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8"}
            current_chapter = cn_map.get(ch_num, ch_num)
            continue

        # 追踪任务类型
        if "## 主线任务" in line or "## 主线任务链" in line:
            current_type = "main"
            continue
        if "## 支线任务" in line:
            current_type = "side"
            continue
        if "## 偏离触发的深层任务" in line:
            current_type = "deep"
            continue

        # 匹配任务标题: #### M1-1：名称 或 #### S1-1：名称
        q_match = re.match(r"^#### ([A-Z]+\d*-[A-Za-z]?\d+)[：:](.+)", line)
        if not q_match:
            continue

        quest_id = q_match.group(1).strip()
        quest_name = q_match.group(2).strip()

        # 读取该任务的属性表（后续几行中的 | **X** | **Y** | 格式）
        attrs = {"id": quest_id, "name": quest_name, "type": current_type, "chapter": current_chapter}
        for j in range(i + 1, min(i + 20, len(lines))):
            attr_line = lines[j].strip()
            # 匹配 | **属性** | 内容 |
            m = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|", attr_line)
            if not m:
                # 也匹配 | 属性 | 内容 | (无粗体)
                m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", attr_line)
                if not m:
                    # 遇到下一个标题或空表行则停止
                    if re.match(r"^#### |^---$|^\s*$", attr_line) and j > i + 3:
                        break
                    continue
            key = m.group(1).strip()
            value = m.group(2).strip()
            key_lower = key.lower()

            if key in ("目标", "**目标**"):
                attrs["objective"] = value
            elif key in ("触发", "**触发**"):
                attrs["trigger"] = value
            elif key in ("完成条件", "**完成条件**"):
                attrs["completion"] = value
            elif key in ("奖励", "**奖励**"):
                attrs["reward"] = value
            elif key in ("失败条件", "**失败条件**"):
                attrs["failure"] = value
            elif key in ("任务 ID", "**任务 ID**"):
                attrs["task_id"] = value
            elif key in ("类型", "**类型**"):
                attrs["subtype"] = value

        quests.append(attrs)

    return quests


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。override 中的值覆盖 base，嵌套字典递归合并。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
