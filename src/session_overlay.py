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
import hashlib
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

    def get_worldbook_scope(self) -> dict | None:
        """返回会话固定的世界书候选范围；旧会话返回 None 以保持兼容。"""
        scope = self._data.get("worldbook_scope")
        return copy.deepcopy(scope) if isinstance(scope, dict) else None

    def set_worldbook_scope(self, scope: dict | None):
        if scope:
            self._data["worldbook_scope"] = copy.deepcopy(scope)
        else:
            self._data.pop("worldbook_scope", None)
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

    def _ensure_narrative_beats(self) -> list[dict]:
        """惰性加载节拍结构。

        节拍结构只在会话创建（init_session_docs）时解析进内存；服务重启后
        恢复的会话没有该属性，会导致状态展示/推进/回档全部失效。此处按
        plot_id 从剧情模板重新解析一次，保证恢复会话也能读取节点结构。
        """
        if hasattr(self, "_narrative_beats"):
            return self._narrative_beats
        self._narrative_beats: list[dict] = []
        plot_id = self._data.get("plot_id")
        if plot_id:
            text = self._load_narrative_text(plot_id)
            if text:
                self._narrative_text = text
                self._narrative_beats = _parse_narrative_beats(text)
                logger.debug("会话 %s: 惰性加载剧情结构 %s（%d 章）",
                             self.session_id, plot_id, len(self._narrative_beats))
        return self._narrative_beats

    def get_beat_state(self) -> dict:
        """获取当前节拍进度状态。"""
        return self._data.get("beat_state", {})

    def get_current_beat(self) -> dict | None:
        """获取当前节拍信息（content + dialogue + reveals）。"""
        beats = self._ensure_narrative_beats()
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
        beats = self._ensure_narrative_beats()
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
        beats = self._ensure_narrative_beats()
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
        """推进到下一个节拍。跨章节自动处理。

        若 beat_state 中存在待生效的分支落点（pending_branch）且目标节拍合法，
        则直接跳转到该节拍（分支自由进入的确定性落点）；否则顺序推进。
        """
        beats = self._ensure_narrative_beats()
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return

        # 分支落点优先：玩家上轮选择的目标节拍
        pending = bs.get("pending_branch") if isinstance(bs, dict) else None
        target = (pending or {}).get("target_beat_id") or ""
        if target and target in self._beat_index():
            if self.jump_to_beat(target):
                self.clear_pending_branch()
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

        # 清理待生效分支（未命中合法目标 / 已顺序推进）
        bs.pop("pending_branch", None)

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

        # 剧情树根节点（入口）——无论是否有节拍骨架都先建好
        self.init_story_tree(plot_id)

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

    # ── 分支（LLM 生成 + 作者手写） ──

    def _beat_index(self) -> dict[str, tuple[int, int]]:
        """beat_id → (chapter_idx, beat_idx) 索引。"""
        beats = self._ensure_narrative_beats()
        index: dict[str, tuple[int, int]] = {}
        for ci, ch in enumerate(beats):
            for bi, b in enumerate(ch.get("beats", [])):
                index[b["id"]] = (ci, bi)
        return index

    def jump_to_beat(self, beat_id: str) -> bool:
        """直接跳转到指定节拍（仅由分支落点调用，非顺序推进）。

        把当前节拍记入 completed_beats 后定位到目标节拍。目标不存在返回 False。
        """
        beats = self._ensure_narrative_beats()
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return False
        index = self._beat_index()
        if beat_id not in index:
            return False
        # 记录当前节拍为已完成（与 advance_beat 语义一致）
        current = self.get_current_beat()
        if current:
            bs.setdefault("completed_beats", [])
            if current["id"] not in bs["completed_beats"]:
                bs["completed_beats"].append(current["id"])
        ci, bi = index[beat_id]
        bs["chapter_idx"] = ci
        bs["beat_idx"] = bi
        bs["narrations_on_beat"] = 0
        self._data["beat_state"] = bs
        self._rewrite_plot_state()
        self._save()
        logger.info("会话 %s: 分支落点跳转 → %s", self.session_id, beat_id)
        return True

    def set_pending_branch(self, branch: dict) -> None:
        """记录玩家本轮选择的分支（作为推进时的落点提示）。"""
        bs = self._data.get("beat_state", {})
        if not bs:
            return
        bs["pending_branch"] = {
            "target_beat_id": branch.get("target_beat_id") or "",
            "intent": branch.get("intent") or "",
            "label": branch.get("label") or "",
            "round": branch.get("round", self._data.get("narration_round", 0)),
        }
        self._data["beat_state"] = bs
        self._save()

    def set_emitted_branches(self, branches: list[dict]) -> None:
        """记录上一轮下发给前端的分支列表（供选择回传时按 id 恢复）。"""
        self._data["emitted_branches"] = list(branches or [])
        self._save()

    def get_emitted_branches(self) -> list[dict]:
        """读取上一轮下发的分支列表。"""
        emitted = self._data.get("emitted_branches")
        return list(emitted) if isinstance(emitted, list) else []

    def get_pending_branch(self) -> dict | None:
        """读取待生效的分支落点提示（无则 None）。"""
        bs = self._data.get("beat_state", {})
        pending = bs.get("pending_branch") if isinstance(bs, dict) else None
        return pending if isinstance(pending, dict) and pending.get("target_beat_id") else None

    def clear_pending_branch(self) -> None:
        """清除待生效的分支落点。"""
        bs = self._data.get("beat_state", {})
        if isinstance(bs, dict) and "pending_branch" in bs:
            bs.pop("pending_branch", None)
            self._data["beat_state"] = bs
            self._save()

    def build_branch_context(self) -> str:
        """构建注入 Call 2 的「玩家当前节点状态」文本块。

        树模式下以**当前剧情树节点**为准（标题/概要/内容/已走路径/已探索分支），
        使 LLM 生成的下一步分支建立在玩家真实所处的位置上；无树时回退到
        作者节拍骨架（兼容旧会话）。
        """
        tree_ctx = self._build_tree_branch_context()
        if tree_ctx:
            return tree_ctx
        return self._build_beat_branch_context()

    def _build_tree_branch_context(self) -> str:
        """树模式的分支上下文（当前节点 + 已走路径 + 已探索分支 + 作者方向）。"""
        tree = self.get_story_tree()
        nodes = tree.get("nodes", {})
        cur = nodes.get(tree.get("current_id") or "")
        if not cur:
            return ""

        lines = ["<current_node>"]
        lines.append(f"节点标题：{cur.get('title') or '未命名'}")
        if cur.get("intent"):
            lines.append(f"进入方式：{cur['intent']}")
        if cur.get("summary"):
            lines.append(f"节点概要：{cur['summary']}")
        if cur.get("content"):
            lines.append(f"节点内容：{cur['content'][:400]}")

        # 已走路径（祖先链）——保证新节点与来路连续
        chain: list[str] = []
        nid = cur.get("parent_id")
        seen: set[str] = set()
        while nid and nid in nodes and nid not in seen:
            seen.add(nid)
            chain.append(nodes[nid].get("title") or nid)
            nid = nodes[nid].get("parent_id")
        chain.reverse()
        if chain:
            lines.append("已走路径：" + " → ".join(chain))

        # 已探索过的分支（其子节点已存在）——提示 LLM 给出新方向
        taken = [b.get("label") for b in cur.get("branches", [])
                 if b.get("child_id") in (cur.get("children") or [])]
        if taken:
            lines.append("已探索过的分支（请给出不同的新方向）：" + "；".join(t for t in taken if t))

        authored = self.get_authored_branches()
        if authored:
            authored_txt = "；".join(
                f"{b['label']}（{b['intent']}）" if b.get("intent") else b["label"]
                for b in authored
            )
            lines.append(f"作者预设方向参考：{authored_txt}")

        lines.append(
            "说明：请基于当前节点与世界观，推导玩家接下来可以走向的 2-4 个不同方向；"
            "每个方向都会被展开成一个**新的剧情节点**（不必局限于既有节拍）。"
        )
        lines.append("</current_node>")
        return "\n".join(lines)

    def _build_beat_branch_context(self) -> str:
        """旧会话回退：以作者节拍骨架为上下文。"""
        beats = self._ensure_narrative_beats()
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return ""
        current = self.get_current_beat()
        if not current:
            return ""

        ci = bs.get("chapter_idx", 0)
        lines = ["<current_node>"]
        if ci < len(beats):
            lines.append(f"章节：第{ci + 1}章 {beats[ci]['title']}")
        lines.append(f"当前节拍：{current['id']}")
        content = (current.get("content") or "").strip()
        if content:
            lines.append(f"节拍内容：{content[:300]}")
        reveals = (current.get("reveals") or "").strip()
        if reveals:
            lines.append(f"已揭示信息：{reveals[:200]}")

        flat = [(c, b) for c, ch in enumerate(beats) for b in ch.get("beats", [])]
        cur_pos = next(
            (p for p, (c, b) in enumerate(flat) if c == ci and b["id"] == current["id"]),
            None,
        )
        next_infos = []
        if cur_pos is not None:
            for p in range(cur_pos + 1, min(cur_pos + 6, len(flat))):
                c, b = flat[p]
                label = b["id"] if c == ci else f"{b['id']}（第{c + 1}章）"
                next_infos.append(f"{label} — {(b.get('summary') or '')[:50]}")
        if next_infos:
            lines.append("后续节拍候选：" + "；".join(next_infos))

        authored = self.get_authored_branches()
        if authored:
            authored_txt = "；".join(
                f"{b['label']}（{b['intent']}）" if b.get("intent") else b["label"]
                for b in authored
            )
            lines.append(f"作者预设选项方向：{authored_txt}")

        paths = current.get("discovery_paths") or []
        if paths:
            lines.append("发现路径参考：" + "；".join(p[:60] for p in paths))

        lines.append("</current_node>")
        return "\n".join(lines)

    def get_authored_branches(self) -> list[dict]:
        """当前章节的作者手写分支（结构化）。

        「玩家选项方向」在剧情文件里是**章节级**的（写在章节最后一个节拍之后），
        因此只要处于该章节内就返回，而不是仅限最后一个节拍。
        """
        beats = self._ensure_narrative_beats()
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return []
        ci = bs.get("chapter_idx", 0)
        if ci >= len(beats):
            return []
        # 章节内任一节拍携带的作者分支（通常落在最后一个节拍上）
        for b in beats[ci].get("beats", []):
            authored = b.get("authored_branches") or []
            if authored:
                return list(authored)
        return []

    # ── 动态剧情树（LLM 生成的新节点，树状结构） ──
    #
    # 与「作者节拍骨架」不同：树上的节点不是剧情文件里写死的节拍，而是每一轮
    # 由 LLM 依据「当前节点 + 世界书背景」现场生成的场景节点。玩家选择一个分支
    # 就生成/复用一个子节点，于是结构自然长成树（可分叉、可多层展开）。
    # 每个节点内嵌该时刻的状态快照，使「位置显示 / 逐节点状态记录 / 回档」在
    # 树上依然成立。

    def _tree_node_id(self, parent_id: str, branch_label: str) -> str:
        """由（父节点, 分支标签）确定性子节点 id。

        同一父节点下重复走同一分支会命中同一节点（复访而非重复建点），
        这样结构保持为树，而不是每次选择都无限膨胀。
        """
        key = f"{parent_id}|{branch_label}".encode("utf-8")
        return "n_" + hashlib.sha1(key).hexdigest()[:10]

    def _ensure_story_tree(self) -> dict:
        """读取剧情树；不存在则按 plot_id 惰性创建（恢复会话同样适用）。"""
        tree = self._data.get("story_tree")
        if isinstance(tree, dict) and isinstance(tree.get("nodes"), dict) and tree["nodes"]:
            return tree
        return self.init_story_tree(self._data.get("plot_id") or "")

    def init_story_tree(self, plot_id: str) -> dict:
        """创建剧情树根节点（入口），仅在无树时执行。

        根节点由作者提供的开场（opening_scene / 首个节拍）播种——它是入口，
        其后的所有节点都由 LLM 生成。
        """
        tree = self._data.get("story_tree")
        if isinstance(tree, dict) and tree.get("nodes"):
            return tree

        title = self._data.get("plot_name") or plot_id or "序章"
        summary = self._data.get("plot_overview") or ""
        content = ""
        if plot_id:
            result = _read_plot_file(plot_id)
            if result:
                meta, _body = result
                title = meta.get("name", title) or title
                summary = summary or meta.get("summary", "")
                content = (meta.get("opening_scene") or "").strip()
        if not content:
            beats = self._ensure_narrative_beats()
            if beats and beats[0].get("beats"):
                b0 = beats[0]["beats"][0]
                title = beats[0].get("title") or title
                summary = summary or b0.get("summary", "")
                content = b0.get("content", "")

        root = {
            "id": "n_root",
            "parent_id": None,
            "depth": 0,
            "title": (title or "序章")[:40],
            "summary": (summary or "")[:120],
            "content": (content or "")[:800],
            "intent": "起点",
            "branch_label": "开始",
            "created_round": 0,
            "children": [],
            "branches": [],
            "state": None,
        }
        tree = {"version": 1, "root_id": "n_root", "current_id": "n_root",
                "nodes": {"n_root": root}}
        self._data["story_tree"] = tree
        self._save()
        logger.info("会话 %s: 剧情树已初始化（根节点来自剧情入口 %s）",
                    self.session_id, plot_id or "-")
        return tree

    def get_story_tree(self) -> dict:
        """剧情树原始结构（无则返回空树）。"""
        tree = self._data.get("story_tree")
        if isinstance(tree, dict) and isinstance(tree.get("nodes"), dict):
            return tree
        return {"version": 1, "root_id": "", "current_id": "", "nodes": {}}

    def get_tree_node(self, node_id: str) -> dict | None:
        return self.get_story_tree().get("nodes", {}).get(node_id)

    def get_current_tree_node(self) -> dict | None:
        tree = self.get_story_tree()
        return tree.get("nodes", {}).get(tree.get("current_id") or "")

    def _tree_state_snapshot(self, round_num: int, prev: dict | None = None) -> dict:
        """节点状态快照：角色/任务/环境/节拍 + 轮次区间 + 剧情日志长度。"""
        return {
            "round_start": int((prev or {}).get("round_start") or round_num),
            "round_end": int(round_num),
            "narration_round": int(self._data.get("narration_round", 0)),
            "plot_log_len": len(self._plot_log_entries()),
            "environment": copy.deepcopy(self._data.get("environment", {})),
            "character_states": copy.deepcopy(self._data.get("character_states", {})),
            "quest_states": copy.deepcopy(self._data.get("quest_states", {})),
            "beat_state": copy.deepcopy(self._data.get("beat_state", {})),
        }

    def _attach_tree_branches(self, node: dict, branches: list[dict] | None) -> None:
        """把 LLM 给出的分支挂到节点上，并预算出各自的子节点 id。"""
        out: list[dict] = []
        for i, b in enumerate(branches or []):
            label = str(b.get("label") or "").strip()
            if not label:
                continue
            out.append({
                "id": b.get("id") or f"tb_{i + 1}",
                "label": label[:30],
                "intent": (b.get("intent") or None),
                "source": b.get("source") or "llm",
                "child_id": self._tree_node_id(node["id"], label),
            })
        node["branches"] = out

    def commit_tree_step(self, *, narrative: str = "", summary: str = "",
                         title: str = "", branches: list[dict] | None = None,
                         branch: dict | None = None,
                         round_num: int | None = None) -> dict:
        """把本轮叙述落成一棵树节点，并推进 current_id。

        - 首轮（无节点状态）：本轮叙述填充根节点；
        - 本轮玩家选了分支（branch 非空）：在父节点下生成/复用子节点并进入；
        - 否则：停留在当前节点内，更新其内容与可选分支。

        节点标题/概要/内容/分支均来自 LLM（title/summary/narrative/branches），
        因此生成的是**新节点结果**，而不是从作者节拍里挑落点。
        """
        tree = self._ensure_story_tree()
        nodes = tree["nodes"]
        if round_num is None:
            round_num = int(self._data.get("narration_round", 0))
        round_num = int(round_num)

        cur = nodes.get(tree.get("current_id") or "")

        if cur is None or not cur.get("state"):
            # 首轮：根节点
            node = nodes.get(tree.get("root_id") or "n_root")
            if node is None:
                node = self.init_story_tree(self._data.get("plot_id") or "")
                nodes = self.get_story_tree()["nodes"]
                node = nodes["n_root"]
            if narrative:
                node["content"] = narrative[:800]
            if summary:
                node["summary"] = summary[:120]
            if title:
                node["title"] = title[:40]
            self._attach_tree_branches(node, branches)
            node["state"] = self._tree_state_snapshot(round_num, node.get("state"))
            tree["current_id"] = node["id"]
        elif branch:
            # 玩家选了分支 → 生成/复用一个子节点
            label = str(branch.get("label") or "").strip() or "分支"
            child_id = self._tree_node_id(cur["id"], label)
            child = nodes.get(child_id)
            if child is None:
                child = {
                    "id": child_id,
                    "parent_id": cur["id"],
                    "depth": int(cur.get("depth", 0)) + 1,
                    "title": (title or label)[:40],
                    "summary": (summary or "")[:120],
                    "content": (narrative or "")[:800],
                    "intent": (branch.get("intent") or "").strip(),
                    "branch_label": label[:30],
                    "created_round": round_num,
                    "children": [],
                    "branches": [],
                    "state": None,
                }
                nodes[child_id] = child
                cur.setdefault("children", [])
                if child_id not in cur["children"]:
                    cur["children"].append(child_id)
                logger.info("会话 %s: 剧情树新增节点 %s（深度 %d，来自分支「%s」）",
                            self.session_id, child_id, child["depth"], label)
            else:
                # 复访：刷新内容
                if narrative:
                    child["content"] = narrative[:800]
                if summary:
                    child["summary"] = summary[:120]
                if title:
                    child["title"] = title[:40]
            self._attach_tree_branches(child, branches)
            child["state"] = self._tree_state_snapshot(round_num, child.get("state"))
            tree["current_id"] = child_id
            node = child
        else:
            # 同一节点内继续
            node = cur
            if narrative:
                node["content"] = narrative[:800]
            if summary:
                node["summary"] = summary[:120]
            if title:
                node["title"] = title[:40]
            self._attach_tree_branches(node, branches)
            node["state"] = self._tree_state_snapshot(round_num, node.get("state"))

        self._data["story_tree"] = tree
        self._save()
        return node

    def build_tree_state(self) -> dict:
        """剧情树视图：节点列表（含深度/父子/状态）+ 当前路径 + 当前节点的可走分支。"""
        tree = self.get_story_tree()
        nodes = tree.get("nodes", {})
        if not nodes:
            return {"has_tree": False, "nodes": [], "root_id": "", "current_id": "", "path": []}

        current_id = tree.get("current_id") or ""
        path: list[str] = []
        nid = current_id
        seen: set[str] = set()
        while nid and nid in nodes and nid not in seen:
            seen.add(nid)
            path.append(nid)
            nid = nodes[nid].get("parent_id")
        path.reverse()

        out = []
        for nid, n in nodes.items():
            st = n.get("state") or {}
            if nid == current_id:
                state = "current"
            elif nid in path:
                state = "path"
            else:
                state = "visited"
            branches = []
            for b in n.get("branches", []):
                branches.append({**b, "taken": b.get("child_id") in (n.get("children") or [])})
            out.append({
                "id": nid,
                "parent_id": n.get("parent_id"),
                "depth": int(n.get("depth", 0)),
                "title": n.get("title", ""),
                "summary": n.get("summary", ""),
                "intent": n.get("intent", ""),
                "branch_label": n.get("branch_label", ""),
                "children": list(n.get("children", [])),
                "branches": branches,
                "round_start": st.get("round_start"),
                "round_end": st.get("round_end"),
                "has_state": bool(st),
                "state": state,
            })
        # 按深度 + 创建顺序稳定排序，便于前端缩进渲染
        out.sort(key=lambda x: (x["depth"], x["id"]))
        current = next((x for x in out if x["id"] == current_id), None)
        return {
            "has_tree": True,
            "root_id": tree.get("root_id", ""),
            "current_id": current_id,
            "path": path,
            "nodes": out,
            "current_node": current,
        }

    def rollback_to_tree_node(self, node_id: str) -> dict:
        """回档到剧情树上的某个节点，恢复该节点时刻的全部状态。

        树本身保留（不删后续节点），因此回档后仍可重新走其它分支。
        """
        tree = self.get_story_tree()
        nodes = tree.get("nodes", {})
        node = nodes.get(node_id)
        if node is None:
            raise ValueError(f"剧情树中不存在节点: {node_id}")
        st = node.get("state") or {}
        if not st:
            raise ValueError(f"节点尚无状态快照，无法回档: {node_id}")

        tree["current_id"] = node_id
        self._data["story_tree"] = tree
        if "character_states" in st:
            self._data["character_states"] = copy.deepcopy(st["character_states"])
        if "quest_states" in st:
            self._data["quest_states"] = copy.deepcopy(st["quest_states"])
        if "environment" in st:
            self._data["environment"] = copy.deepcopy(st["environment"])
        if st.get("beat_state"):
            self._data["beat_state"] = copy.deepcopy(st["beat_state"])
        self._data["narration_round"] = int(st.get("round_end") or 0)
        self._save()
        try:
            self._rewrite_plot_state()
        except Exception:
            logger.warning("剧情树回档后重写 plot_state 失败", exc_info=True)

        # 剧情日志截断到该节点时刻
        log_len = int(st.get("plot_log_len") or 0)
        entries = self._plot_log_entries()[:log_len]
        content = _PLOT_LOG_HEADER + "\n".join(entries)
        if entries:
            content += "\n"
        self.write_session_doc("plot_log.md", content)

        # 恢复该节点的可选分支，回档后可继续走别的分支
        self.set_emitted_branches(node.get("branches", []))

        logger.info("会话 %s: 剧情树回档 → %s（第%d轮）",
                    self.session_id, node_id, st.get("round_end", 0))
        return {
            "node_id": node_id,
            "round_start": int(st.get("round_start") or 0),
            "round_end": int(st.get("round_end") or 0),
            "depth": int(node.get("depth", 0)),
            "title": node.get("title", ""),
        }

    # ── 节点历史（每节点状态快照，用于记录/回档） ──

    def _node_history_path(self) -> Path:
        return _SESSIONS_DIR / self.mode / self.session_id / "node_history.json"

    def _load_node_history(self) -> dict:
        path = self._node_history_path()
        if not path.is_file():
            return {"version": 1, "nodes": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
                return {"version": 1, "nodes": []}
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("会话 %s: 节点历史读取失败（按空处理）: %s", self.session_id, e)
            return {"version": 1, "nodes": []}

    def _save_node_history(self, data: dict) -> None:
        """原子落盘 node_history.json（tmp + os.replace）。"""
        path = self._node_history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
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

    def record_node_snapshot(self, round_num: int | None = None) -> dict | None:
        """记录「刚完成的节点」的完整状态快照。

        记录已完成的最后一个节拍（completed_beats[-1]）及其结束时的角色/任务/
        环境状态，供后续回档恢复。同一 node_id + round_end 幂等替换。
        无剧情或无已完成节拍时返回 None。
        """
        beats = self._ensure_narrative_beats()
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            return None
        completed = bs.get("completed_beats") or []
        if not completed:
            return None
        node_id = completed[-1]
        index = self._beat_index()
        if node_id not in index:
            return None
        ci, bi = index[node_id]

        history = self._load_node_history()
        nodes = history.get("nodes", [])

        if round_num is None:
            round_num = self._data.get("narration_round", 0)

        prev_round_end = nodes[-1].get("round_end", 0) if nodes else 0
        # 幂等：同节点同结束轮次已记录则跳过
        for n in nodes:
            if n.get("node_id") == node_id and n.get("round_end") == round_num:
                return n

        snapshot = {
            "node_id": node_id,
            "chapter_idx": ci,
            "beat_idx": bi,
            "chapter_title": beats[ci]["title"] if ci < len(beats) else "",
            "round_start": prev_round_end + 1,
            "round_end": round_num,
            "narration_round": self._data.get("narration_round", 0),
            "plot_log_len": len(self._plot_log_entries()),
            "environment": copy.deepcopy(self._data.get("environment", {})),
            "character_states": copy.deepcopy(self._data.get("character_states", {})),
            "quest_states": copy.deepcopy(self._data.get("quest_states", {})),
            "completed_beats": list(completed),
            "created_at": __import__("time").time(),
        }
        nodes.append(snapshot)
        history["nodes"] = nodes
        self._save_node_history(history)
        logger.info("会话 %s: 记录节点快照 %s（第%d-%d轮）",
                    self.session_id, node_id, snapshot["round_start"], round_num)
        return snapshot

    def _plot_log_entries(self) -> list[str]:
        """读取 plot_log.md 的条目行。"""
        content = self.read_session_doc("plot_log.md") or ""
        return [l for l in content.split("\n") if l.startswith("[轮次")]

    def get_node_history(self) -> list[dict]:
        """全部节点快照（按记录顺序）。"""
        return self._load_node_history().get("nodes", [])

    def get_node_snapshot(self, node_id: str) -> dict | None:
        """某节点的最后一个快照（无则 None）。"""
        snap = None
        for n in self.get_node_history():
            if n.get("node_id") == node_id:
                snap = n
        return snap

    def prune_node_history(self, keep_round: int) -> int:
        """删除 round_end 晚于 keep_round 的节点快照，返回删除数量。"""
        history = self._load_node_history()
        nodes = history.get("nodes", [])
        kept = [n for n in nodes if int(n.get("round_end") or 0) <= keep_round]
        removed = len(nodes) - len(kept)
        if removed:
            history["nodes"] = kept
            self._save_node_history(history)
            logger.info("会话 %s: 裁剪 %d 个滞后节点快照（>%d轮）",
                        self.session_id, removed, keep_round)
        return removed

    def restore_from_snapshot(self, node_id: str) -> dict:
        """从节点快照恢复会话覆盖态（节拍/角色/任务/环境/剧情日志）。

        时间旅行语义：整体替换而非合并。返回恢复摘要。
        """
        snap = self.get_node_snapshot(node_id)
        if not snap:
            raise ValueError(f"未找到节点快照: {node_id}")

        index = self._beat_index()
        if node_id not in index:
            raise ValueError(f"节点不在当前剧情结构中: {node_id}")
        ci, bi = index[node_id]

        bs = self._data.get("beat_state", {})
        bs["chapter_idx"] = ci
        bs["beat_idx"] = bi
        bs["narrations_on_beat"] = 0
        bs["completed_beats"] = list(snap.get("completed_beats") or [])
        bs.pop("pending_branch", None)
        self._data["beat_state"] = bs

        if "character_states" in snap:
            self._data["character_states"] = copy.deepcopy(snap["character_states"])
        if "quest_states" in snap:
            self._data["quest_states"] = copy.deepcopy(snap["quest_states"])
        if "environment" in snap:
            self._data["environment"] = copy.deepcopy(snap["environment"])
        self._data["narration_round"] = int(snap.get("round_end") or 0)

        self._save()
        self._rewrite_plot_state()

        # 重建 plot_log.md（截断到快照时长度）
        log_len = int(snap.get("plot_log_len") or 0)
        entries = self._plot_log_entries()[:log_len]
        new_content = _PLOT_LOG_HEADER + "\n".join(entries)
        if entries:
            new_content += "\n"
        self.write_session_doc("plot_log.md", new_content)

        logger.info("会话 %s: 已从节点快照恢复 %s（第%d轮）",
                    self.session_id, node_id, snap.get("round_end", 0))
        return {
            "node_id": node_id,
            "chapter_idx": ci,
            "beat_idx": bi,
            "round_end": int(snap.get("round_end") or 0),
            "completed_beats": list(snap.get("completed_beats") or []),
        }

    # ── 状态展示（当前位置） ──

    def build_story_state(self) -> dict:
        """构建剧情状态视图：剧情树（LLM 生成节点）+ 作者节拍骨架 + 角色状态。

        无剧情返回 {"has_plot": False, "roads": [], "tree": {...}}。
        """
        tree = self.build_tree_state()
        beats = self._ensure_narrative_beats()
        bs = self._data.get("beat_state", {})
        if not beats or not bs:
            # 无作者骨架：至少返回剧情树（LLM 生成结构独立于作者骨架成立）
            return {
                "has_plot": bool(tree.get("has_tree")),
                "plot_id": self._data.get("plot_id", ""),
                "plot_name": self._data.get("plot_name", ""),
                "roads": [],
                "tree": tree,
                "character_states": self._data.get("character_states", {}),
                "quest_states": self._data.get("quest_states", {}),
                "node_history": self._tree_node_history(tree),
            }

        ci = bs.get("chapter_idx", 0)
        bi = bs.get("beat_idx", 0)
        completed = set(bs.get("completed_beats", []))
        snap_by_node = {n["node_id"]: n for n in self.get_node_history()}

        roads = []
        for i, ch in enumerate(beats):
            ch_state = "locked"
            if i < ci:
                ch_state = "done"
            elif i == ci:
                ch_state = "current"
            ch_beats = []
            for j, b in enumerate(ch.get("beats", [])):
                if b["id"] in completed:
                    bstate = "done"
                elif i == ci and j == bi:
                    bstate = "current"
                else:
                    bstate = "locked"
                snap = snap_by_node.get(b["id"])
                ch_beats.append({
                    "id": b["id"],
                    "summary": (b.get("summary") or "")[:80],
                    "keep_on_deviate": b.get("keep_on_deviate", False),
                    "state": bstate,
                    "round_start": snap.get("round_start") if snap else None,
                    "round_end": snap.get("round_end") if snap else None,
                    "has_combat": "[COMBAT:" in (b.get("content") or ""),
                    "authored_branches": b.get("authored_branches", []),
                })
            roads.append({
                "chapter_idx": i,
                "title": ch.get("title", ""),
                "summary": (ch.get("summary") or "")[:120],
                "state": ch_state,
                "beats": ch_beats,
            })

        current_beat = self.get_current_beat()
        beat_info = None
        if current_beat:
            beat_info = {
                "idx": bi,
                "total": len(beats[ci]["beats"]) if ci < len(beats) else 0,
                "id": current_beat["id"],
                "summary": (current_beat.get("summary") or "")[:80],
                "narrations_on_beat": bs.get("narrations_on_beat", 0),
            }

        return {
            "has_plot": True,
            "plot_id": self._data.get("plot_id", ""),
            "plot_name": self._data.get("plot_name", ""),
            "chapter": {
                "idx": ci,
                "title": beats[ci]["title"] if ci < len(beats) else "",
                "total": len(beats),
                "id": beats[ci].get("id", "") if ci < len(beats) else "",
            },
            "beat": beat_info,
            "roads": roads,
            "tree": tree,
            "completed_beats": list(bs.get("completed_beats", [])),
            "pending_branch": self.get_pending_branch(),
            "character_states": self._data.get("character_states", {}),
            "quest_states": self._data.get("quest_states", {}),
            "node_history": self._tree_node_history(tree) or [
                {"node_id": n.get("node_id"), "round_start": n.get("round_start"),
                 "round_end": n.get("round_end")}
                for n in self.get_node_history()
            ],
        }

    @staticmethod
    def _tree_node_history(tree: dict) -> list[dict]:
        """从剧情树导出「经历过的节点」列表（回档点），按轮次排序。"""
        out = []
        for n in tree.get("nodes", []) if tree else []:
            if not n.get("has_state"):
                continue
            out.append({
                "node_id": n["id"],
                "title": n.get("title", ""),
                "depth": n.get("depth", 0),
                "round_start": n.get("round_start"),
                "round_end": n.get("round_end"),
            })
        out.sort(key=lambda x: (x.get("round_start") or 0, x["node_id"]))
        return out

    def _rewrite_plot_state(self):
        """从当前内存状态重写 plot_state.md。

        包含 YAML frontmatter（机器可读状态）和 Markdown body（LLM 可读上下文）。
        """
        beats = self._ensure_narrative_beats()
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
            "worldbook_scope": self._data.get("worldbook_scope"),
            "characters": self._data.get("characters", {}),
            "items": self._data.get("items", {}),
            "environment": self._data.get("environment", {}),
            "quest_states": self._data.get("quest_states", {}),
            "character_states": self._data.get("character_states", {}),
            "has_plot_context": self.has_plot_context(),
        }
        node_history = [
            {"node_id": n.get("node_id"), "round_start": n.get("round_start"),
             "round_end": n.get("round_end")}
            for n in self.get_node_history()
        ]
        if node_history:
            result["node_history"] = node_history
        custom = self.get_custom_prompt()
        if custom:
            result["custom_prompt"] = custom
        if "index_config" in self._data:
            result["index_config"] = self._data["index_config"]
        return result

    @staticmethod
    def delete_session_overlays(session_id: str, mode: str = "free"):
        """删除整个会话的覆盖目录（连目录内一切文件一并删除）。

        失败时**不吞异常**：`shutil.rmtree` 的 `OSError`（目录被占用、权限
        不足等）直接向上抛，由 `SessionManager.delete_session` 转成
        `SessionCleanupError`。会话删除是事务性的，静默半删会留下残留数据，
        比直接报错更难排查。

        `mode` 必须由调用方校验过（见 `SessionManager._session_dir`），
        否则本方法可能被指向 `sessions/` 之外。
        """
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
        [{title, id, summary, beats: [{id, summary, content, dialogue, reveals,
          keep_on_deviate, stat_check, option_directions, authored_branches,
          discovery_paths}]}, ...]
    """
    chapters = []
    current_chapter = None
    current_beat = None
    current_section = None  # "content" | "dialogue" | "reveals" | "option_directions" | "discovery_paths"
    section_buf = []

    def flush_section():
        nonlocal current_section, section_buf
        if current_beat and current_section and section_buf:
            if current_section in ("option_directions", "discovery_paths"):
                # 列表型 section：保留原始条目行（供作者分支/发现路径使用）
                items = [s.strip() for s in section_buf if s.strip()]
                if items:
                    current_beat[current_section] = items
            else:
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
                "option_directions": [],
                "authored_branches": [],
                "discovery_paths": [],
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

        # 作者手写选项方向（h3 形式）：### 玩家选项方向
        if re.match(r"^###\s*玩家选项方向\s*$", line):
            flush_section()
            current_section = "option_directions"
            continue

        # 对话方向（h3 形式）：仅作参考，解析后丢弃
        if re.match(r"^###\s*对话方向\s*$", line):
            flush_section()
            continue

        # 发现路径: **发现路径**： → 保留（供 prompt 上下文，非可点选项）
        if re.match(r"^\*\*发现路径\*\*[：:]", line):
            flush_section()
            current_section = "discovery_paths"
            section_buf.append(re.sub(r"^\*\*发现路径\*\*[：:]\s*", "", line))
            continue

        # 玩家选项方向（bold 形式）/ 对话方向 — 不关注
        if re.match(r"^\*\*(玩家选项方向|对话方向)\*\*[：:]", line):
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
            b["authored_branches"] = _derive_authored_branches(
                b.get("option_directions", [])
            )

    return chapters


def _derive_authored_branches(option_directions: list[str]) -> list[dict]:
    """把剧情里手写的「玩家选项方向」条目转成结构化作者分支。

    条目形如「接受银灰的"证人"邀请，明确表示罗德岛只记录事实（中立取向）」。
    括号尾的内容作为 intent 方向标签（截断到首个分句，≤20 字），其余作为 label。

    Returns:
        [{"label": str, "intent": str | None, "target_beat_id": None, "source": "author"}]
    """
    branches: list[dict] = []
    for raw in option_directions or []:
        text = str(raw).strip()
        # 去掉列表前缀（- / * / 数字.）
        text = re.sub(r"^[-*]\s*", "", text)
        text = re.sub(r"^\d+[.、]\s*", "", text)
        if not text:
            continue
        # 过滤分隔线（--- / ***）等非选项行
        if re.fullmatch(r"[-*_=\s]+", text):
            continue
        intent = None
        m = re.search(r"[（(]([^）)]+)[）)]\s*$", text)
        if m:
            # 括号内容可能很长的说明，取到首个分隔符为止作为方向标签
            raw_intent = m.group(1).strip()
            raw_intent = re.split(r"[：:，,；;]", raw_intent)[0].strip()
            intent = raw_intent[:20] or None
            text = text[:m.start()].strip()
        if not text:
            continue
        branches.append({
            "label": text[:30],
            "intent": intent,
            "target_beat_id": None,
            "source": "author",
        })
    return branches


def parse_narrative_beats(text: str) -> list[dict]:
    """公开包装：把剧情文档解析为章节/节拍结构。

    编辑器（战斗节点进度）与预取 hook 复用同一实现，避免两套解析器漂移。
    """
    return _parse_narrative_beats(text)


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
