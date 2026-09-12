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

import frontmatter

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SESSIONS_DIR = _PROJECT_ROOT / "data" / "memory" / "sessions"

_PLOT_LOG_HEADER = (
    "# 剧情进度日志\n\n"
    "> 以下记录已发生的剧情事件。每次叙述时请参考已有内容，"
    "在此基础之上推进新的剧情发展，不要重复已记录的场景和对话。\n\n"
)

_MAX_PLOT_LOG_ENTRIES = 15


def _get_overlay_path(mode: str, session_id: str) -> Path:
    return _SESSIONS_DIR / mode / session_id / "overrides.json"


class SessionOverlay:
    """单个会话的覆盖数据管理器。"""

    def __init__(self, session_id: str, mode: str = "free"):
        self.session_id = session_id
        self.mode = mode
        self._data: dict = {}
        self._doc_cache: dict = {}
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
        """原子落盘：先写临时文件再 os.replace，避免中途崩溃损坏存档。

        战斗结算会连续多次调用本方法（逐角色写成长），原子替换保证
        任何一次失败都不会留下截断的 overrides.json。
        """
        path = _get_overlay_path(self.mode, self.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        import time
        self._data["updated_at"] = time.time()
        self._data["session_id"] = self.session_id
        tmp_path = path.with_name(path.name + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    # ── 场景状态（场景角色/物品/当前对话目标） ──

    def get_scene_state(self) -> dict:
        """读取持久化的场景状态：{characters, items, active}。"""
        scene = self._data.get("scene")
        if not isinstance(scene, dict):
            return {"characters": [], "items": [], "active": None}
        chars = scene.get("characters")
        items = scene.get("items")
        return {
            "characters": chars if isinstance(chars, list) else [],
            "items": items if isinstance(items, list) else [],
            "active": scene.get("active"),
        }

    def save_scene_state(self, characters: list, items: list, active) -> None:
        """持久化场景状态到 overrides.json（后端重启后恢复用）。"""
        self._data["scene"] = {
            "characters": list(characters),
            "items": items,
            "active": active,
        }
        self._save()

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

    # ── 世界书绑定 ──

    def get_worldbook_id(self) -> str | None:
        """获取会话绑定的世界书 ID（未绑定返回 None，回落到全局默认书）。"""
        return self._data.get("worldbook_id")

    def set_worldbook_id(self, worldbook_id: str | None):
        """绑定/解绑会话的世界书。"""
        if worldbook_id:
            self._data["worldbook_id"] = worldbook_id
            logger.info("会话 %s: 世界书绑定为 %s", self.session_id, worldbook_id)
        else:
            self._data.pop("worldbook_id", None)
            logger.info("会话 %s: 已解绑世界书", self.session_id)
        self._save()

    # ── 环境覆盖 ──

    def get_environment_overrides(self) -> dict:
        return self._data.get("environment", {})

    def set_environment_overrides(self, overrides: dict):
        existing = self._data.get("environment", {})
        merged = _deep_merge(existing, overrides)
        self._data["environment"] = merged
        self._save()
        logger.info("会话 %s: 环境覆盖已更新", self.session_id)

    # ── 战斗结算（待结算记录） ──

    def get_pending_settlement(self) -> dict | None:
        """读取未完成的战斗结算记录（无则 None）。

        结算记录与角色成长写在同一个 overrides.json，保证「战斗结算」与
        「剧情角色数值」共用同一数据源与同一次落盘。
        """
        pending = self._data.get("pending_settlement")
        return pending if isinstance(pending, dict) else None

    def set_pending_settlement(self, pending: dict) -> None:
        """持久化待结算记录（含逐角色写回进度，供失败重试幂等跳过）。"""
        self._data["pending_settlement"] = pending
        self._save()

    def clear_pending_settlement(self) -> None:
        """清除待结算记录（结算全部写回成功后调用）。"""
        if "pending_settlement" in self._data:
            del self._data["pending_settlement"]
            self._save()

    # ── 剧情/任务 ──

    def get_plot_id(self) -> str | None:
        """获取当前会话绑定的剧情 ID。"""
        return self._data.get("plot_id")

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

    # ── 自定义 Prompt ──

    def get_custom_prompt(self) -> str | None:
        """获取用户自定义提示词。"""
        return self._data.get("custom_prompt")

    def set_custom_prompt(self, prompt: str):
        """设置用户自定义提示词。"""
        self._data["custom_prompt"] = prompt
        self._save()
        logger.info("会话 %s: 自定义提示词已更新 (%d 字)", self.session_id, len(prompt))

    def delete_custom_prompt(self):
        """删除用户自定义提示词。"""
        if "custom_prompt" in self._data:
            del self._data["custom_prompt"]
            self._save()
            logger.info("会话 %s: 自定义提示词已删除", self.session_id)

    # ── 剧情节拍跟踪 ──

    def _load_narrative_text(self, plot_id: str) -> str:
        """加载剧情节拍文本。

        从 index.md 提取所有「## 章节 N」节，到下一个非章节的「## 」标题为止。
        """
        result = _read_plot_file(plot_id)
        if result:
            body = result[1]
            ch_match = re.search(r'^## 章节\s+\d+[：:]', body, re.MULTILINE)
            if not ch_match:
                return ""
            start = ch_match.start()
            remaining = body[start:]
            end_match = re.search(r'^## (?!章节\s+\d+[：:])\S', remaining, re.MULTILINE)
            if end_match:
                return remaining[:end_match.start()].strip()
            return remaining.strip()
        return ""

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

    def get_current_beat_combat_id(self) -> str:
        """从当前节拍的 content 提取确定性战斗目标 `[COMBAT:enc_id]`。

        章节战斗目标由代码确定（docs/combat-core-design.md A2.5 / D2.2），
        优先于 LLM 的 combat_trigger 提取；无标记返回空串。
        """
        beat = self.get_current_beat()
        if not beat:
            return ""
        content = beat.get("content", "") or ""
        m = re.search(r"\[COMBAT:([\w-]+)\]", content)
        return m.group(1) if m else ""

    def get_next_beat(self) -> dict | None:
        """获取下一节拍的完整信息（content + dialogue + reveals）。

        用于预取 hook 提前加载下一节拍可能需要的 wiki 文档。
        如果当前是最后一个节拍则返回 None。
        """
        beats = self._narrative_beats if hasattr(self, "_narrative_beats") else []
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return None
        ci = bs.get("chapter_idx", 0)
        bi = bs.get("beat_idx", 0)
        ch = beats[ci] if ci < len(beats) else None
        if not ch:
            return None
        if bi + 1 < len(ch["beats"]):
            return ch["beats"][bi + 1]
        if ci + 1 < len(beats) and beats[ci + 1]["beats"]:
            return beats[ci + 1]["beats"][0]
        return None

    def _build_beat_roadmap(self) -> str:
        """构建节拍路线图——展示当前章节 ±1，远章节折叠为一行。"""
        beats = self._narrative_beats if hasattr(self, "_narrative_beats") else []
        bs = self._data.get("beat_state", {})
        if not beats:
            return ""
        ci = bs.get("chapter_idx", 0)
        bi = bs.get("beat_idx", 0)
        completed = set(bs.get("completed_beats", []))

        lines = []
        for i, ch in enumerate(beats):
            if i < ci - 1 or i > ci + 1:
                continue

            if i == ci - 1:
                # 上一章：折叠为一行的已完成摘要
                lines.append(f"OK Chapter {i + 1}: {ch['title']}（已完成）")
                continue

            marker = ">>" if i == ci else "  "
            lines.append(f"{marker} Chapter {i + 1}: {ch['title']}")
            if i == ci:
                for j, b in enumerate(ch["beats"]):
                    if b["id"] in completed:
                        bmarker = "  [DONE]"
                    elif j == bi:
                        bmarker = "  [HERE]"
                    else:
                        bmarker = "  [    ]"
                    lines.append(f"{bmarker} {b['id']} — {b['summary'][:60]}")
            # 下一章（i == ci + 1）：仅显示章节标题，不展开节拍
        return "\n".join(lines)

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
        self._rewrite_plot_state()
        self._save()

        new_beat = self.get_current_beat()
        new_name = new_beat["id"] if new_beat else "end"
        logger.info("会话 %s: 节拍推进 → %s", self.session_id, new_name)

    # ── 会话自有文档管理 ──

    def _get_doc_path(self, name: str) -> Path:
        """获取会话文档的完整路径。"""
        return _SESSIONS_DIR / self.mode / self.session_id / name

    def init_session_docs(self, plot_id: str):
        """从剧情模板生成会话自有文档（plot_state.md + plot_log.md）。

        仅在会话创建时调用一次。后续所有剧情上下文均从会话文档读取，
        不再重新加载模板文件。

        从 index.md 提取各节。
        """
        plot_name = plot_id
        overview = ""

        result = _read_plot_file(plot_id)
        if result:
            meta, body = result
            plot_name = meta.get("name", plot_id)
            overview = _extract_section(body, "剧情概述")
            if not overview:
                overview = meta.get("summary", "")
            dialogue_ref = _extract_section(body, "关键对话参考")
            if dialogue_ref:
                self._data["dialogue_ref"] = dialogue_ref
            # 解析偏离点 stat_check 备用
            self._plot_stat_checks = _parse_deviation_stat_checks(body)
            if self._plot_stat_checks:
                logger.info(
                    "会话 %s: 已缓存 %d 个偏离点检定节点",
                    self.session_id, len(self._plot_stat_checks),
                )
            narrative_text = self._load_narrative_text(plot_id)
        else:
            narrative_text = ""

        if not narrative_text:
            logger.debug("剧情 %s 无节拍数据，跳过文档初始化", plot_id)
            self._narrative_beats = []
            self._narrative_text = ""
            return

        self._narrative_text = narrative_text
        self._narrative_beats = _parse_narrative_beats(narrative_text)

        # 初始化节拍状态
        if "beat_state" not in self._data:
            self._data["beat_state"] = {
                "chapter_idx": 0,
                "beat_idx": 0,
                "completed_beats": [],
                "narrations_on_beat": 0,
            }
        self._data["plot_name"] = plot_name
        self._data["plot_overview"] = overview
        self._save()

        # 写入会话文档
        self._rewrite_plot_state()
        self.write_session_doc("plot_log.md", _PLOT_LOG_HEADER)

        total_beats = sum(len(ch["beats"]) for ch in self._narrative_beats)
        logger.info("会话 %s: 剧情文档已初始化，%d 章 %d 个节拍 → %s",
                     self.session_id, len(self._narrative_beats), total_beats,
                     self._get_doc_path(""))

    def read_session_doc(self, name: str) -> str | None:
        """读取会话文档内容（带缓存）。"""
        if name in self._doc_cache:
            return self._doc_cache[name]
        path = self._get_doc_path(name)
        if not path.is_file():
            return None
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self._doc_cache[name] = content
        return content

    def write_session_doc(self, name: str, content: str):
        """写入会话文档并更新缓存。"""
        path = self._get_doc_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self._doc_cache[name] = content

    def append_plot_log(self, summary: str):
        """追加一行剧情进度日志，自动递增轮次。

        自动截断旧条目，只保留最近 _MAX_PLOT_LOG_ENTRIES 轮。
        """
        round_num = self._data.get("narration_round", 0) + 1
        self._data["narration_round"] = round_num
        self._save()

        path = self._get_doc_path("plot_log.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            with open(path, "w", encoding="utf-8") as f:
                f.write(_PLOT_LOG_HEADER)

        # 读取已有条目
        existing = self._doc_cache.get("plot_log.md", "")
        if not existing and path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read()

        # 提取已有条目行（以 [轮次 开头）
        entry_lines = [l for l in existing.split("\n") if l.startswith("[轮次")]
        entry_lines.append(f"[轮次 {round_num}] {summary}")

        # 只保留最近 N 条
        if len(entry_lines) > _MAX_PLOT_LOG_ENTRIES:
            entry_lines = entry_lines[-_MAX_PLOT_LOG_ENTRIES:]

        # 重建文件内容
        new_content = _PLOT_LOG_HEADER + "\n".join(entry_lines) + "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        self._doc_cache["plot_log.md"] = new_content

    def update_beat_progress(self):
        """更新节拍进度：计数自增，超阈值自动推进，重写 plot_state.md。"""
        bs = self._data.get("beat_state", {})
        if not bs:
            return
        bs["narrations_on_beat"] = bs.get("narrations_on_beat", 0) + 1
        self._data["beat_state"] = bs

        if bs["narrations_on_beat"] > 8:
            logger.info("会话 %s: 节拍 %s 已 %d 轮，自动推进",
                         self.session_id,
                         (self.get_current_beat() or {}).get("id", "?"),
                         bs["narrations_on_beat"])
            self.advance_beat()
        else:
            self._rewrite_plot_state()
            self._save()

    def _rewrite_plot_state(self):
        """从当前内存状态重写 plot_state.md。

        包含 YAML frontmatter（机器可读状态）和 Markdown body（LLM 可读上下文）。
        """
        beats = self._narrative_beats if hasattr(self, "_narrative_beats") else []
        bs = self._data.get("beat_state", {})

        body_parts = []
        plot_name = self._data.get("plot_name", "")
        if plot_name:
            body_parts.append(f"# {plot_name}\n")

        overview_text = self._data.get("plot_overview", "")
        if overview_text:
            body_parts.append(f"## 剧情概要\n{overview_text}\n")

        # 注入关键对话参考，帮助 LLM 校准角色语气
        dialogue_ref = self._data.get("dialogue_ref", "")
        if dialogue_ref:
            body_parts.append(f"## 角色对话参考\n{dialogue_ref}\n")

        if beats:
            body_parts.append("## 章节结构")
            for i, ch in enumerate(beats):
                body_parts.append(f"- 第{i + 1}章 {ch['title']}：{ch.get('summary', '')}")
            body_parts.append("")

        # 路线图（标注 HERE/DONE 位置）
        roadmap = self._build_beat_roadmap()
        if roadmap:
            body_parts.append(
                "## 节拍路线图\n"
                "> 标注了当前位置 [HERE] 和已完成 [DONE] 的节拍。"
                "请将此路线图用作剧情推进方向参考，而不是逐字执行的脚本。\n"
            )
            body_parts.append(roadmap + "\n")

        # 当前进度摘要（不含场景描写/对话——避免 LLM 逐字重复）
        current_beat = self.get_current_beat()
        if current_beat:
            bid = current_beat["id"]
            narrations = bs.get("narrations_on_beat", 0)
            body_parts.append(f"## 当前进度\n- 当前节拍：**{bid}**（已在该节拍进行 {narrations} 轮叙述）")

            # 下一节拍方向提示（仅提供走向，不含具体内容）
            ci = bs.get("chapter_idx", 0)
            bi = bs.get("beat_idx", 0)
            next_infos = []
            for offset in range(1, 4):
                ni = bi + offset
                nc = ci
                if nc < len(beats) and ni >= len(beats[nc]["beats"]):
                    nc += 1
                    ni = 0
                if nc < len(beats) and ni < len(beats[nc]["beats"]):
                    nb = beats[nc]["beats"][ni]
                    next_infos.append(f"{nb['id']} — {nb.get('summary', '')[:60]}")
            if next_infos:
                body_parts.append(f"- 后续节拍方向：{' → '.join(next_infos[:3])}")
            body_parts.append("")

        body = "\n".join(body_parts)

        post = frontmatter.Post(body, **{
            "chapter_idx": bs.get("chapter_idx", 0),
            "beat_idx": bs.get("beat_idx", 0),
            "completed_beats": bs.get("completed_beats", []),
            "narrations_on_beat": bs.get("narrations_on_beat", 0),
            "plot_id": self._data.get("plot_id", ""),
        })
        self.write_session_doc("plot_state.md", frontmatter.dumps(post))

    # ── 任务 ──

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

    # ── 角色运行时状态 ──

    def get_character_state(self, name: str) -> dict:
        """获取指定角色的运行时状态（conditions + check_history）。"""
        states = self._data.get("character_states", {})
        return states.get(name, {"conditions": [], "check_history": []})

    def add_condition(self, name: str, condition: dict) -> None:
        """给角色添加一个临时状态（受伤/疲劳/buff等）。

        condition 格式：
            {"name": "轻伤", "modifier": -1, "applies_to": "all", "round": 3}
        """
        if "character_states" not in self._data:
            self._data["character_states"] = {}
        if name not in self._data["character_states"]:
            self._data["character_states"][name] = {"conditions": [], "check_history": []}

        state = self._data["character_states"][name]
        condition["round"] = condition.get("round", self._data.get("narration_round", 0))
        state["conditions"].append(condition)
        self._save()
        logger.info("会话 %s: %s 获得状态 %s", self.session_id, name, condition["name"])

    def remove_condition(self, name: str, condition_name: str) -> bool:
        """移除角色指定名称的状态。"""
        state = self.get_character_state(name)
        conds = state.get("conditions", [])
        for i, c in enumerate(conds):
            if c.get("name") == condition_name:
                conds.pop(i)
                self._data["character_states"][name]["conditions"] = conds
                self._save()
                logger.info("会话 %s: %s 移除了状态 %s", self.session_id, name, condition_name)
                return True
        return False

    def get_condition_modifier(self, name: str, attribute: str) -> int:
        """汇总角色所有 condition 对指定属性的修正值。

        applies_to="all" 的条件对所有属性生效，
        具名条件只对匹配的属性名生效。
        """
        state = self.get_character_state(name)
        total = 0
        for c in state.get("conditions", []):
            applies = c.get("applies_to", "all")
            if applies == "all" or applies == attribute:
                total += c.get("modifier", 0)
        return total

    def record_check(self, name: str, result: dict) -> None:
        """记录一次属性检定结果到角色检定历史。

        result 格式：DiceSystem.roll_d20_structured() 的返回值
        附加 round 字段。
        """
        if "character_states" not in self._data:
            self._data["character_states"] = {}
        if name not in self._data["character_states"]:
            self._data["character_states"][name] = {"conditions": [], "check_history": []}

        entry = {
            "round": self._data.get("narration_round", 0),
            "attribute": result.get("attribute", ""),
            "roll": result.get("roll", 0),
            "modifier": result.get("modifier", 0),
            "dc": result.get("difficulty"),
            "success": result.get("success"),
        }
        history = self._data["character_states"][name].get("check_history", [])
        history.append(entry)
        # 只保留最近 20 条
        if len(history) > 20:
            history = history[-20:]
        self._data["character_states"][name]["check_history"] = history
        self._save()

    # ── 剧情偏离点检定节点 ──

    def get_plot_stat_checks(self) -> dict:
        """获取缓存的剧情偏离点 stat_check 映射。

        Returns:
            {偏离点ID: {"trigger": str, "stat_check": {属性: dc}, "fail_forward": str}}
        """
        if not hasattr(self, "_plot_stat_checks"):
            self._plot_stat_checks = {}
        return self._plot_stat_checks

    def get_stat_check_for_context(self, user_action: str) -> dict | None:
        """根据用户动作匹配剧情偏离点的 stat_check。

        简单匹配：检查 user_action 是否包含偏离点的 trigger 关键词。
        返回最匹配的偏离点 stat_check，或 None。
        """
        checks = self.get_plot_stat_checks()
        if not checks:
            return None
        for dp_id, dp in checks.items():
            trigger = dp.get("trigger", "")
            if trigger and any(
                keyword in user_action for keyword in trigger.split() if len(keyword) >= 2
            ):
                return dp.get("stat_check")
        return None

    # ── 全量导出 ──

    def to_dict(self) -> dict:
        """返回全部覆盖数据（供 API 使用）。"""
        result = {
            "session_id": self.session_id,
            "plot_id": self._data.get("plot_id"),
            "worldbook_id": self._data.get("worldbook_id"),
            "characters": self._data.get("characters", {}),
            "items": self._data.get("items", {}),
            "environment": self._data.get("environment", {}),
            "quest_states": self._data.get("quest_states", {}),
            "character_states": self._data.get("character_states", {}),
            "has_plot_context": self.has_plot_context(),
        }
        custom = self.get_custom_prompt()
        if custom:
            result["custom_prompt"] = custom
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
    if (base / plot_id / "index.md").is_file():
        return plot_id
    for entry in sorted(base.iterdir()):
        if entry.is_dir():
            md = entry / "index.md"
            if md.is_file():
                try:
                    with open(md, "r", encoding="utf-8") as f:
                        fm = frontmatter.load(f)
                    if fm.metadata.get("id") == plot_id:
                        return entry.name
                except Exception:
                    continue
    return None


def _read_plot_file(plot_id: str) -> tuple[dict, str] | None:
    """读取 index.md，返回 (frontmatter_metadata, body_text)。"""
    resolved = _resolve_plot_dir(plot_id)
    if not resolved:
        return None
    md = _PROJECT_ROOT / "data" / "plots" / resolved / "index.md"
    if md.is_file():
        with open(md, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        return (dict(post.metadata), post.content)
    return None


# 顶层节的边界标题模式（用于 _extract_section 判断何时停止提取）
_SECTION_BOUNDARY_PATTERN = re.compile(
    r"^## (?:剧情概述|开场设置|关键对话参考|任务|章节\s+\d+[：:])\s*$"
)


def _extract_section(text: str, heading: str) -> str:
    """从 markdown body 中提取指定 ## heading 节的内容。

    从匹配的 `## heading` 行开始截取，到下一个顶层 ## 标题处停止。
    顶层标题匹配 _SECTION_BOUNDARY_PATTERN，嵌套的 ## 子标题（如任务内的
    「## 主线任务」、开场设置内的「## 一、开场总览」）不会中断提取。
    """
    pattern = rf"^## {re.escape(heading)}\s*$"
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if re.match(pattern, line):
            start = i + 1
            break
    if start is None:
        return ""

    result_lines = []
    for i in range(start, len(lines)):
        if _SECTION_BOUNDARY_PATTERN.match(lines[i]):
            break
        result_lines.append(lines[i])

    return "\n".join(result_lines).strip()


def _parse_quests_text(text: str) -> list[dict]:
    """解析任务文本为结构化任务列表（纯解析，不涉及文件 I/O）。"""
    quests = []
    current_chapter = ""
    current_type = "main"

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

        # 匹配任务标题: #### M1-1：名称
        q_match = re.match(r"^#### ([A-Z]+\d*-[A-Za-z]?\d+)[：:](.+)", line)
        if not q_match:
            continue

        quest_id = q_match.group(1).strip()
        quest_name = q_match.group(2).strip()

        # 读取该任务的属性表
        attrs = {"id": quest_id, "name": quest_name, "type": current_type, "chapter": current_chapter}
        for j in range(i + 1, min(i + 20, len(lines))):
            attr_line = lines[j].strip()
            m = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|", attr_line)
            if not m:
                m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", attr_line)
                if not m:
                    if re.match(r"^#### |^---$|^\s*$", attr_line) and j > i + 3:
                        break
                    continue
            key = m.group(1).strip()
            value = m.group(2).strip()

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


def _parse_quests_md(plot_id: str) -> list[dict]:
    """解析指定剧情的任务，返回结构化任务列表。

    从 index.md 提取「## 任务」节后解析。
    """
    result = _read_plot_file(plot_id)
    if result:
        section = _extract_section(result[1], "任务")
        if section:
            return _parse_quests_text(section)
    return []


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
        nonlocal current_section, section_buf
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

        # 节拍标题: #### beat_name（keep_on_deviate: true）或 #### beat_name（check: 魅力 DC14）
        beat_m = re.match(r"^####\s+(beat_\w+)\s*(?:[（(]([^）)]+)[）)])?\s*$", line)
        if beat_m:
            flush_beat()
            beat_id = beat_m.group(1)
            flags_str = (beat_m.group(2) or "").strip()
            keep_on_deviate = "keep_on_deviate" in flags_str.lower()
            stat_check = None
            # 解析 check: 属性 DC14, 属性2 DC15 格式
            if flags_str:
                check_m = re.search(
                    r"check\s*[：:]\s*(.+?)(?:\s*[,，]\s*(?:keep_on_deviate|$)|$)",
                    flags_str, re.IGNORECASE,
                )
                if check_m:
                    check_body = check_m.group(1).strip()
                    attr_entries = re.findall(
                        r"([一-鿿]+)\s*[Dd][Cc]\s*(\d+)", check_body
                    )
                    if attr_entries:
                        stat_check = {attr: int(dc) for attr, dc in attr_entries}
            current_beat = {
                "id": beat_id,
                "summary": "",
                "content": "",
                "dialogue": "",
                "reveals": "",
                "keep_on_deviate": keep_on_deviate,
                "stat_check": stat_check,
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


def _parse_deviation_stat_checks(body: str) -> dict:
    """从剧情 body 中解析偏离点（deviation points）的 stat_check。

    扫描 `#### 偏离 DN：...` 标题块，提取其中的 stat_check JSON
    和 trigger/fail_forward 文本。

    Returns:
        {偏离点ID: {"trigger": str, "stat_check": {属性: dc}, "fail_forward": str}}
    """
    import json as _json

    checks = {}
    # 分割为偏离点块
    blocks = re.split(r"^####\s+偏离\s+(\S+)[：:]", body, flags=re.MULTILINE)
    # blocks[0] = 标题前内容, blocks[1]=D1, blocks[2]=D1内容, blocks[3]=D2, ...
    for i in range(1, len(blocks), 2):
        dp_id = blocks[i].strip()
        dp_body = blocks[i + 1] if i + 1 < len(blocks) else ""

        # 提取 stat_check JSON
        sc_match = re.search(r"stat_check\s*[：:]\s*(\{[^}]+\})", dp_body)
        stat_check = None
        if sc_match:
            try:
                stat_check = _json.loads(sc_match.group(1))
            except _json.JSONDecodeError:
                continue

        # 提取触发场景
        trigger = ""
        trig_match = re.search(r"\*\*触发场景\*\*[：:](.+)", dp_body)
        if trig_match:
            trigger = trig_match.group(1).strip()

        # 提取 fail_forward
        ff_match = re.search(r"\*\*fail_forward\*\*[：:](.+)", dp_body)
        fail_forward = ff_match.group(1).strip() if ff_match else ""

        checks[dp_id] = {
            "trigger": trigger,
            "stat_check": stat_check,
            "fail_forward": fail_forward,
        }

    return checks


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。override 中的值覆盖 base，嵌套字典递归合并。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
