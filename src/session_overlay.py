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
import re
import copy
import logging
from pathlib import Path
from typing import Optional

import frontmatter

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

    # ── 会话索引配置 ──

    def get_index_config(self) -> dict:
        """获取会话索引配置，不存在返回默认 {mode: "all"}。"""
        return self._data.get("index_config", {
            "mode": "all",
            "enabled_categories": [],
            "enabled_entities": {},
        })

    def set_index_config(self, config: dict):
        """设置会话索引配置。"""
        self._data["index_config"] = {
            "mode": config.get("mode", "all"),
            "enabled_categories": config.get("enabled_categories", []),
            "enabled_entities": config.get("enabled_entities", {}),
        }
        self._save()

    def reset_index_config(self):
        """重置会话索引配置为默认。"""
        self._data.pop("index_config", None)
        self._save()

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

    # ── 剧情节拍跟踪 ──

    def init_beat_state(self, plot_id: str):
        """解析 narrative.md 并初始化节拍跟踪状态。

        从 narrative.md 提取章节/节拍结构，初始化为第一个节拍。
        beat_state 持久化到 overrides.json，narrative 全文缓存在内存。
        """
        resolved = _resolve_plot_dir(plot_id) or plot_id
        narrative_path = _PROJECT_ROOT / "data" / "plots" / resolved / "narrative.md"

        if not narrative_path.is_file():
            logger.debug("剧情 %s 无 narrative.md，跳过节拍初始化", plot_id)
            self._narrative_beats = []
            self._narrative_text = ""
            return

        with open(narrative_path, "r", encoding="utf-8") as f:
            text = f.read()

        self._narrative_text = text
        self._narrative_beats = _parse_narrative_beats(text)

        # 持久化节拍进度
        if "beat_state" not in self._data:
            self._data["beat_state"] = {
                "chapter_idx": 0,
                "beat_idx": 0,
                "completed_beats": [],
                "narrations_on_beat": 0,
            }
            self._save()

        total_beats = sum(len(ch["beats"]) for ch in self._narrative_beats)
        logger.info(
            "会话 %s: 节拍状态已初始化，共 %d 章 %d 个节拍",
            self.session_id, len(self._narrative_beats), total_beats,
        )

    def get_beat_state(self) -> dict:
        """获取当前节拍进度状态。"""
        return self._data.get("beat_state", {})

    def get_current_beat(self) -> dict | None:
        """获取当前节拍信息（content + dialogue + reveals）。"""
        beats = self._narrative_beats if hasattr(self, "_narrative_beats") else []
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return None
        ci = bs.get("chapter_idx", 0)
        bi = bs.get("beat_idx", 0)
        if ci < len(beats) and bi < len(beats[ci]["beats"]):
            return beats[ci]["beats"][bi]
        return None

    def get_current_chapter(self) -> dict | None:
        """获取当前章节信息。"""
        beats = self._narrative_beats if hasattr(self, "_narrative_beats") else []
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return None
        ci = bs.get("chapter_idx", 0)
        if ci < len(beats):
            return {k: v for k, v in beats[ci].items() if k != "beats"}
        return None

    def _build_beat_roadmap(self) -> str:
        """构建节拍路线图——展示全剧情结构并标注当前位置。"""
        beats = self._narrative_beats if hasattr(self, "_narrative_beats") else []
        bs = self._data.get("beat_state", {})
        if not beats:
            return ""
        ci = bs.get("chapter_idx", 0)
        bi = bs.get("beat_idx", 0)
        completed = set(bs.get("completed_beats", []))

        lines = []
        for i, ch in enumerate(beats):
            marker = ">>" if i == ci else ("OK" if all(b["id"] in completed for b in ch["beats"]) else "  ")
            lines.append(f"{marker} Chapter {i + 1}: {ch['title']}")
            for j, b in enumerate(ch["beats"]):
                if b["id"] in completed:
                    bmarker = "  [DONE]"
                elif i == ci and j == bi:
                    bmarker = "  [HERE]"
                else:
                    bmarker = "  [    ]"
                lines.append(f"{bmarker} {b['id']} — {b['summary'][:60]}")
        return "\n".join(lines)

    def get_beat_context(self) -> str:
        """构建完整的剧情节拍上下文，供注入 LLM prompt。

        包含：剧情路线图 + 当前节拍详细描述 + 下一节拍预告。
        """
        beats = self._narrative_beats if hasattr(self, "_narrative_beats") else []
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return ""

        ci = bs.get("chapter_idx", 0)
        bi = bs.get("beat_idx", 0)
        narrations = bs.get("narrations_on_beat", 0)
        ch = beats[ci] if ci < len(beats) else None
        beat = beats[ci]["beats"][bi] if ch and bi < len(ch["beats"]) else None

        parts = []

        # 路线图
        roadmap = self._build_beat_roadmap()
        if roadmap:
            parts.append(f"【剧情路线图】\n{roadmap}")

        # 当前节拍
        if ch and beat:
            parts.append(f"\n【当前节拍】第{ci + 1}章 · {ch['title']} · {beat['id']}")
            parts.append(f"已在此节拍进行 {narrations} 轮叙述")
            if beat.get("content"):
                parts.append(f"\n节拍内容：{beat['content']}")
            if beat.get("dialogue"):
                parts.append(f"\n强制对话：{beat['dialogue']}")
            if beat.get("reveals"):
                parts.append(f"\n需揭示信息：{beat['reveals']}")

        # 下一节拍预告
        next_beats = []
        if ch:
            for j in range(bi + 1, min(bi + 3, len(ch["beats"]))):
                nb = ch["beats"][j]
                next_beats.append(f"{nb['id']} — {nb['summary'][:80]}")
        if not next_beats and ci + 1 < len(beats):
            # 下一章的第一个节拍
            nch = beats[ci + 1]
            if nch["beats"]:
                nb = nch["beats"][0]
                next_beats.append(f"{nb['id']} — {nb['summary'][:80]}")
        if next_beats:
            parts.append(f"\n【后续节拍】" + " → ".join(next_beats))

        # 指示
        parts.append(
            "\n---\n请在当前节拍的框架内推进剧情。"
            "当节拍的核心事件（强制对话 + 揭示信息）已通过叙述呈现后，"
            "在叙述文本末尾输出 [BEAT_COMPLETE] 标记以推进到下一节拍。"
        )

        return "\n".join(parts)

    def get_narrative_full_text(self) -> str:
        """获取 narrative.md 全文（缓存在内存中）。"""
        if hasattr(self, "_narrative_text"):
            return self._narrative_text
        return ""

    def advance_beat(self):
        """推进到下一个节拍。跨章节自动处理。"""
        beats = self._narrative_beats if hasattr(self, "_narrative_beats") else []
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return

        ci = bs.get("chapter_idx", 0)
        bi = bs.get("beat_idx", 0)
        ch = beats[ci] if ci < len(beats) else None
        if not ch:
            return

        # 记录当前节拍为已完成
        current_beat = ch["beats"][bi] if bi < len(ch["beats"]) else None
        if current_beat:
            if "completed_beats" not in bs:
                bs["completed_beats"] = []
            if current_beat["id"] not in bs["completed_beats"]:
                bs["completed_beats"].append(current_beat["id"])

        # 推进
        if bi + 1 < len(ch["beats"]):
            bs["beat_idx"] = bi + 1
        elif ci + 1 < len(beats):
            bs["chapter_idx"] = ci + 1
            bs["beat_idx"] = 0
        else:
            logger.info("会话 %s: 已是最后一个节拍", self.session_id)
            bs["narrations_on_beat"] = 0
            self._save()
            return

        bs["narrations_on_beat"] = 0
        self._data["beat_state"] = bs
        self._save()

        new_beat = self.get_current_beat()
        new_name = new_beat["id"] if new_beat else "end"
        logger.info("会话 %s: 节拍推进 → %s", self.session_id, new_name)

    def record_narration_on_beat(self):
        """记录当前节拍的一次叙述。若超过阈值自动推进。"""
        bs = self._data.get("beat_state", {})
        if not bs:
            return
        bs["narrations_on_beat"] = bs.get("narrations_on_beat", 0) + 1
        self._data["beat_state"] = bs

        # 超过 8 轮未完成则强制推进
        if bs["narrations_on_beat"] > 8:
            logger.info("会话 %s: 节拍 %s 已 %d 轮，自动推进",
                         self.session_id,
                         (self.get_current_beat() or {}).get("id", "?"),
                         bs["narrations_on_beat"])
            self.advance_beat()
        else:
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
        result = {
            "session_id": self.session_id,
            "plot_id": self._data.get("plot_id"),
            "combat_mode": self.get_combat_mode(),
            "characters": self._data.get("characters", {}),
            "items": self._data.get("items", {}),
            "environment": self._data.get("environment", {}),
            "quest_states": self._data.get("quest_states", {}),
            "has_plot_context": self.has_plot_context(),
        }
        if "index_config" in self._data:
            result["index_config"] = self._data["index_config"]
        return result

    @staticmethod
    def delete_session_overlays(session_id: str, mode: str = "free"):
        """删除整个会话的覆盖目录。"""
        import shutil
        session_dir = _SESSIONS_DIR / mode / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info("已删除会话覆盖数据: %s/%s", mode, session_id)


def _resolve_plot_dir(plot_id: str) -> str | None:
    """通过扫描 data/plots/ 子目录查找指定 plot_id 对应的目录名。"""
    base = _PROJECT_ROOT / "data" / "plots"
    if not base.is_dir():
        return None
    # 首先直接匹配目录名
    if (base / plot_id / "index.md").is_file():
        return plot_id
    # 扫描所有子目录，匹配 frontmatter id
    for entry in sorted(base.iterdir()):
        if entry.is_dir():
            index_md = entry / "index.md"
            if index_md.is_file():
                try:
                    with open(index_md, "r", encoding="utf-8") as f:
                        fm = frontmatter.load(f)
                    if fm.metadata.get("id") == plot_id:
                        return entry.name
                except Exception:
                    continue
    return None


def _parse_quests_md(plot_id: str) -> list[dict]:
    """解析指定剧情的 quests.md，返回结构化任务列表。"""
    import re

    # 先尝试直接用 plot_id 作为目录名
    path = _PROJECT_ROOT / "data" / "plots" / plot_id / "quests.md"
    if not path.exists():
        # 通过目录扫描解析实际目录名
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


def _parse_narrative_beats(text: str) -> list[dict]:
    """解析 narrative.md 为章节/节拍结构。

    Returns:
        [{title, id, summary, beats: [{id, summary, content, dialogue, reveals}]}, ...]
    """
    chapters = []
    current_chapter = None
    current_beat = None
    current_section = None  # "content" | "dialogue" | "reveals"
    section_buf = []

    def flush_section():
        nonlocal current_beat, current_section, section_buf
        if current_beat and current_section and section_buf:
            text = "\n".join(section_buf).strip()
            if text:
                current_beat[current_section] = text
        section_buf = []
        current_section = None

    def flush_beat():
        nonlocal current_beat
        flush_section()
        if current_beat and current_chapter:
            current_chapter["beats"].append(current_beat)
        current_beat = None

    for line in text.split("\n"):
        # 章节标题: ## 章节 N：Title
        ch_m = re.match(r"^## 章节\s*(\d+)[：:]\s*(.+)$", line)
        if ch_m:
            flush_beat()
            current_chapter = {
                "title": ch_m.group(2).strip(),
                "id": "",
                "summary": "",
                "beats": [],
            }
            chapters.append(current_chapter)
            continue

        # 章节 ID: **ID**：`blood_opener`
        if current_chapter and not current_chapter.get("id"):
            id_m = re.match(r"^\*\*ID\*\*[：:]\s*`?(\w+)`?", line)
            if id_m:
                current_chapter["id"] = id_m.group(1)
                continue

        # 章节概要: **概要**：...
        if current_chapter and not current_chapter.get("summary"):
            sum_m = re.match(r"^\*\*概要\*\*[：:]\s*(.+)$", line)
            if sum_m:
                current_chapter["summary"] = sum_m.group(1)
                continue

        # 节拍标题: #### beat_name（keep_on_deviate: true）
        beat_m = re.match(r"^####\s+(beat_\w+)\s*([（(].+[）)])?$", line)
        if beat_m:
            flush_beat()
            beat_id = beat_m.group(1)
            current_beat = {
                "id": beat_id,
                "summary": "",
                "content": "",
                "dialogue": "",
                "reveals": "",
            }
            continue

        if not current_beat:
            continue

        # 节拍内容: **内容**：...
        if re.match(r"^\*\*内容\*\*[：:]", line):
            flush_section()
            current_section = "content"
            section_buf.append(re.sub(r"^\*\*内容\*\*[：:]\s*", "", line))
            continue

        # 强制对话: **强制对话**：
        if re.match(r"^\*\*强制对话\*\*[：:]", line):
            flush_section()
            current_section = "dialogue"
            section_buf.append(re.sub(r"^\*\*强制对话\*\*[：:]\s*", "", line))
            continue

        # 揭示信息: **揭示信息**：
        if re.match(r"^\*\*揭示信息\*\*[：:]", line):
            flush_section()
            current_section = "reveals"
            section_buf.append(re.sub(r"^\*\*揭示信息\*\*[：:]\s*", "", line))
            continue

        # 发现路径 / 玩家选项 / 对话方向 — 不属于我们关注的 section
        if re.match(r"^\*\*(发现路径|玩家选项方向|对话方向)\*\*[：:]", line):
            flush_section()
            continue

        # 如果是节拍内的第一段非空文本（没有 **key** 前缀），作为 summary 的补充
        if current_section == "content" and not section_buf:
            # 检查是否是普通段落
            pass

        if current_section:
            stripped = line.strip()
            if stripped:
                section_buf.append(stripped)

    flush_beat()

    # 为每个 beat 生成 summary（取 content 前 80 字）
    for ch in chapters:
        for b in ch["beats"]:
            if not b.get("summary") and b.get("content"):
                b["summary"] = b["content"][:80].replace("\n", " ")

    return chapters


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。override 中的值覆盖 base，嵌套字典递归合并。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
