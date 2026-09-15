"""
会话管理器：支持多会话并行，每个会话包含 SceneManager + 环境状态。

设计：
- Session 代表一个独立的对话场景（一组角色 + 环境 + 对话历史）
- SessionManager 管理多个 Session 的创建/查询/销毁
- 每个 Session 可从 LLMBackendManager 获取 LLM 实例
"""

import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Callable

from SceneManager import SceneManager
from avatar_color import get_theme_color
from environment_state import EnvironmentState
from wiki_manager import WikiManager
from llm_backend_manager import LLMBackendManager
from session_overlay import SessionOverlay
from session_context import SessionContext
from combat_resume import read_resume, session_resume_path, summarize as _summarize_resume
from combat_engine.engine import CombatEvent

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SESSIONS_DIR = _PROJECT_ROOT / "data" / "memory" / "sessions"

# Shared registry — all sessions share the same entity index
_registry: Optional[WikiManager] = None

#: 会话目录所属的合法 mode 子目录。删除会话时据此校验路径口径，
#: 避免用错误的 mode 拼出别的会话目录（见 `_session_dir`）。
_VALID_MODES = ("free", "story")


class SessionCleanupError(RuntimeError):
    """删除会话时的资源清理失败。

    会话删除是「级联 + 事务性」操作：挂起战斗存档、内存战斗态、会话目录必须
    一并清除，且**不能只删一半**。该异常表示某一项清理未成功，调用方应把它
    转成结构化错误返回给前端，让用户重试，而不是静默留下残留数据。
    """


def _get_registry() -> WikiManager:
    global _registry
    if _registry is None:
        _registry = WikiManager()
        _registry.validate_imports()
    return _registry


class Session:
    """一个独立的对话会话。"""

    def __init__(self, session_id: str, llm_backend_manager: LLMBackendManager,
                 name: str = "", mode: str = "free", combat_mode: str = "narrative",
                 player_identity: str = "博士",
                 wiki_manager=None, worldbook_manager=None,
                 empty_environment: bool | None = None):
        self.id = session_id
        mode_label = "剧情" if mode == "story" else "自由"
        self.name = name or f"{mode_label}对话"
        self.mode = mode  # "free" | "story"
        self.combat_mode = combat_mode  # "narrative" | "tactical"，创建时选定，不可更改
        # 玩家身份角色（用户自身）：默认"博士"，创建时可选择其他角色卡
        self.player_identity = (player_identity or "").strip() or "博士"
        self.created_at = time.time()
        self._llm_backend = llm_backend_manager

        # 会话覆盖层
        self.overlay = SessionOverlay(session_id, mode)

        # 共享组件
        self.registry = _get_registry()

        # Wiki 文档上下文
        self._wiki_manager = wiki_manager
        self.wiki_context = SessionContext()
        # CharacterAgent 复用该上下文，借此取得会话级世界书候选范围。
        self.wiki_context.overlay = self.overlay

        # LLM 延迟检测 — 首次 get_llm() 调用时才探测后端
        self._llm = None
        self.scene_manager = SceneManager(
            self._llm, self.registry, overlay=self.overlay,
            wiki_manager=wiki_manager, session_context=self.wiki_context,
            combat_mode=self.combat_mode,
            worldbook_manager=worldbook_manager,
        )
        self.environment = EnvironmentState()
        self.environment.load_default()

        # 应用环境覆盖（优先恢复本会话上次持久化的场景）
        env_overrides = self.overlay.get_environment_overrides()
        has_env = bool(
            env_overrides.get("location")
            or env_overrides.get("weather")
            or env_overrides.get("time_of_day")
            or env_overrides.get("atmosphere")
        )

        # 无预设场景的剧情会话：不套用默认地点/天气，留空交由角色卡开场与 LLM 生成。
        # empty_environment=True 表示新建时已明确不绑定剧情；
        # empty_environment=None 表示恢复旧会话，按 overlay 中是否已有剧情/环境自动判断。
        if empty_environment is True:
            self.environment.reset()
        elif empty_environment is None and self.mode == "story" and not self.overlay.get_plot_id() and not has_env:
            self.environment.reset()

        if env_overrides.get("location"):
            self.environment.set_location(env_overrides["location"])
        if env_overrides.get("weather"):
            self.environment.set_weather(env_overrides["weather"])
        if env_overrides.get("time_of_day"):
            self.environment.time_of_day = env_overrides["time_of_day"]
        if env_overrides.get("atmosphere"):
            self.environment.atmosphere = env_overrides["atmosphere"]
        if not env_overrides.get("location") and self.mode == "story":
            # 旧会话可能没有持久化环境；有剧情绑定时回退到剧情开场场景
            self._restore_plot_initial_environment()

        # 战斗系统
        self.combat = None  # CombatSession | None

        # 回忆系统
        self.narration_count = 0
        self._narration_history: list[dict] = []   # 完整叙述历史 [{round, text, action}]
        self._last_memory_end = 0
        self._memories: list[dict] = []

        # Token 用量累计
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        self._load_memories()
        self.scene_manager._restoring_scope = True
        self._restore_scene()
        self.scene_manager._restoring_scope = False

    @property
    def is_usable(self) -> bool:
        """会话是否可以正常对话。"""
        return self._llm is not None

    def get_llm(self):
        """获取当前 LLM 实例，首次调用时自动探测后端。"""
        if self._llm is None:
            self.refresh_llm()
        return self._llm

    def refresh_llm(self) -> bool:
        """重新从后端管理器获取 LLM 实例（在降级/恢复时调用）。"""
        llm, _ = self._llm_backend.get_llm()
        if llm:
            self._llm = llm
            self.scene_manager._llm = llm
            # Pass overlay to SceneManager if not already set
            if not self.scene_manager._overlay:
                self.scene_manager._overlay = self.overlay
            return True
        return False

    def persist_environment(self):
        """把当前环境状态持久化到会话 overrides，重启/重新进入后不丢失。"""
        self.overlay.set_environment_overrides({
            "location": self.environment.location,
            "weather": self.environment.weather,
            "time_of_day": self.environment.time_of_day,
            "atmosphere": list(self.environment.atmosphere),
        })

    def apply_environment_updates(self, updates: dict):
        """应用 LLM 返回的环境更新，并同步持久化。"""
        if not updates:
            return
        self.environment.apply_update(updates)
        self.persist_environment()

    def _restore_plot_initial_environment(self):
        """旧剧情会话无持久化环境时，用剧情开场配置补环境。"""
        try:
            from session_overlay import _read_plot_file
            plot_id = self.overlay.get_plot_id()
            if not plot_id:
                return
            result = _read_plot_file(plot_id)
            if not result:
                return
            meta = result[0]
            location = meta.get("initial_location", "")
            if not location:
                return
            self.environment.set_location(location)
            time_val = meta.get("initial_time", "")
            if time_val:
                self.environment.time_of_day = time_val
            atmosphere = meta.get("initial_atmosphere", "")
            if atmosphere:
                if isinstance(atmosphere, str):
                    self.environment.atmosphere = [atmosphere]
                elif isinstance(atmosphere, list):
                    self.environment.atmosphere = atmosphere
            self.persist_environment()
            logger.info("会话 %s: 从剧情开场恢复环境 loc=%s time=%s",
                        self.id, location, time_val)
        except Exception as e:
            logger.warning("从剧情开场恢复环境失败 %s: %s", self.id, e)

    def _restore_scene(self):
        """从持久化场景状态恢复角色/物品/当前对话目标（后端重启后不丢失）。

        story 会话无持久化场景状态时（修复前创建的旧会话），兜底从剧情的
        initial_characters 重新加载——story 模式不允许卸载角色，角色集合稳定。
        """
        state = self.overlay.get_scene_state()
        characters = state.get("characters")
        if not characters and self.mode == "story":
            characters = self._plot_initial_characters()
        if not characters:
            return  # 无场景角色，无需恢复（也不触发 LLM 探测）
        # 先确保 LLM 就绪，使恢复的角色可立即对话
        if self._llm is None:
            self.refresh_llm()
        for name in characters:
            try:
                self.scene_manager.load_character(name)
            except Exception as e:
                logger.warning("恢复场景角色失败 %s: %s", name, e)
        for item in state.get("items", []):
            item_id = item.get("id") if isinstance(item, dict) else str(item)
            try:
                self.scene_manager.add_item(item_id, item)
            except Exception as e:
                logger.warning("恢复场景物品失败 %s: %s", item_id, e)
        active = state.get("active")
        if active and active in self.scene_manager.get_scene_characters():
            self.scene_manager.active = active
        # 统一落盘最终态（恢复过程会触发中间态持久化，需覆盖）
        self.scene_manager._persist_scene()

    def _plot_initial_characters(self) -> list[str]:
        """读取绑定剧情的 initial_characters（排除当前玩家身份）。"""
        try:
            from session_overlay import _read_plot_file
            plot_id = self.overlay.get_plot_id()
            if not plot_id:
                return []
            result = _read_plot_file(plot_id)
            if not result:
                return []
            player = self.player_identity
            return [
                n.strip() for n in result[0].get("initial_characters", [])
                if n.strip() and n.strip() != player
            ]
        except Exception as e:
            logger.warning("读取剧情初始角色失败: %s", e)
            return []

    # ── 回忆系统 ──

    @property
    def data_dir(self) -> Path:
        """会话数据目录（记忆存档、会话文档、会话级资源覆盖）。"""
        return _SESSIONS_DIR / self.mode / self.id

    def _memories_path(self) -> Path:
        return _SESSIONS_DIR / self.mode / self.id / "memories.json"

    def _load_memories(self):
        path = self._memories_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._memories = data.get("memories", [])
                self._narration_history = data.get("narration_history", [])
                self.narration_count = data.get("narration_count", len(self._narration_history))
                self._last_memory_end = data.get("last_memory_end", 0)
                saved_usage = data.get("total_usage")
                if saved_usage and isinstance(saved_usage, dict):
                    self.total_usage = {
                        "prompt_tokens": saved_usage.get("prompt_tokens", 0),
                        "completion_tokens": saved_usage.get("completion_tokens", 0),
                        "total_tokens": saved_usage.get("total_tokens", 0),
                    }
            except Exception:
                self._memories = []

    def _save_memories(self):
        path = self._memories_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "memories": self._memories,
                "narration_history": self._narration_history,
                "narration_count": self.narration_count,
                "last_memory_end": self._last_memory_end,
                "total_usage": self.total_usage,
            }, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def accumulate_usage(self, usage: dict | None):
        """累加一次 LLM 调用的 token 用量到会话总计。"""
        if not usage:
            return
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if usage.get(k):
                self.total_usage[k] = self.total_usage.get(k, 0) + usage[k]

    def get_memories(self) -> list[dict]:
        return list(self._memories)

    def add_narration(self, narrative: str, user_action: str = "",
                      dialogue_segments: list | None = None):
        """记录一轮叙述到持久化历史。"""
        self.narration_count += 1
        entry = {
            "round": self.narration_count,
            "text": narrative[:1500] if narrative else "",
            "action": user_action,
        }
        if dialogue_segments:
            entry["segments"] = dialogue_segments
        self._narration_history.append(entry)
        self._save_memories()

    def update_narration(self, round_num: int, narrative: str):
        """更新指定轮次的叙述文本（用于前端切换变体时同步）。"""
        for h in self._narration_history:
            if h["round"] == round_num:
                h["text"] = narrative[:1500] if narrative else ""
                self._save_memories()
                return

    def should_generate_memory(self, interval: int) -> bool:
        """检查是否应该生成回忆（总轮次达到 interval 的倍数时触发）。"""
        if interval <= 0:
            return False
        return self.narration_count % interval == 0 and self.narration_count > self._last_memory_end

    def generate_memory(self) -> dict | None:
        """从最近未总结的叙述历史生成回忆摘要。保留原始历史不删除。"""
        if not self._llm:
            return None

        recent = [h for h in self._narration_history
                  if h["round"] > self._last_memory_end]
        if not recent:
            return None

        lines = []
        for h in recent:
            if h["text"]:
                lines.append(f"[第{h['round']}轮] {h['text']}")
            if h["action"]:
                lines.append(f"  → 玩家选择: {h['action']}")

        history_text = "\n".join(lines)
        prompt = (
            "基于以下剧情对话记录，总结这段情节的进展。"
            "输出 JSON 格式（不要输出其他内容）：\n"
            '{"title": "简短的章节标题（不超过15字）", "summary": "情节摘要（不超过300字，包含关键对话和事件细节）"}\n\n'
            f"剧情记录：\n---\n{history_text}\n---"
        )

        try:
            _t0 = time.monotonic()
            response = self._llm.chat([
                {"role": "system", "content": (
                    "<role>你是专业TRPG剧情编辑，负责记录详尽的剧情摘要。</role>\n"
                    "<output_format>\n"
                    '强制 JSON：{"title": "标题≤15字", "summary": "摘要≤300字，含关键情节转折、角色互动和重要事件"}\n'
                    "只输出 JSON，不要其他内容。\n"
                    "</output_format>"
                )},
                {"role": "user", "content": prompt},
            ], stream=False, thinking="none")
            logger.info("[TIMING] generate_memory LLM调用: %.0fms", (time.monotonic() - _t0) * 1000)
            response_text = response.get("content", "") if isinstance(response, dict) else str(response)
        except Exception as e:
            logger.warning("生成回忆失败 (LLM 调用): %s", e)
            return None

        import re
        match = re.search(r'\{[^{}]*"title"\s*:\s*"[^"]*"\s*,\s*"summary"\s*:\s*"[^"]*"\s*\}', response_text, re.DOTALL)
        if not match:
            match = re.search(r'\{.*"title".*"summary".*\}', response_text, re.DOTALL)

        if match:
            try:
                result = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning("生成回忆失败 (JSON 解析): %s", response_text[:200])
                return None
        else:
            logger.warning("生成回忆失败 (无 JSON): %s", response_text[:200])
            return None

        title = result.get("title", "").strip()
        summary = result.get("summary", "").strip()
        if not title or not summary:
            return None

        round_start = self._last_memory_end + 1
        round_end = recent[-1]["round"]

        memory = {
            "id": f"mem_{len(self._memories) + 1}",
            "title": title,
            "summary": summary,
            "round_start": round_start,
            "round_end": round_end,
            "created_at": time.time(),
        }
        self._memories.append(memory)
        self._last_memory_end = round_end
        self._save_memories()

        logger.info("会话 %s: 生成回忆 #%d — %s (第%d-%d轮)",
                     self.id, len(self._memories), title, round_start, round_end)
        return memory

    def regenerate_memories(self, interval: int) -> list[dict]:
        """清除已有回忆，用当前间隔重新从完整历史生成。"""
        if not self._llm or not self._narration_history:
            return []

        self._memories = []
        self._last_memory_end = 0
        new_memories = []

        # 按 interval 分批生成
        rounds = sorted(self._narration_history, key=lambda h: h["round"])
        for i in range(0, len(rounds), interval):
            batch = rounds[i:i + interval]
            if not batch:
                continue

            lines = []
            for h in batch:
                if h["text"]:
                    lines.append(f"[第{h['round']}轮] {h['text']}")
                if h["action"]:
                    lines.append(f"  → 玩家选择: {h['action']}")

            history_text = "\n".join(lines)
            prompt = (
                "基于以下剧情对话记录，总结这段情节的进展。"
                "输出 JSON 格式（不要输出其他内容）：\n"
                '{"title": "简短的章节标题（不超过15字）", "summary": "情节摘要（不超过300字，包含关键对话和事件细节）"}\n\n'
                f"剧情记录：\n---\n{history_text}\n---"
            )

            try:
                response = self._llm.chat([
                    {"role": "system", "content": "你是一个专业的剧情编辑，负责为TRPG游戏记录详尽的剧情摘要。需要包含关键情节转折、角色互动和重要事件。只输出JSON，不要有其他内容。"},
                    {"role": "user", "content": prompt},
                ], stream=False, thinking="none")
                response_text = response.get("content", "") if isinstance(response, dict) else str(response)

                import re
                match = re.search(r'\{[^{}]*"title"\s*:\s*"[^"]*"\s*,\s*"summary"\s*:\s*"[^"]*"\s*\}', response_text, re.DOTALL)
                if not match:
                    match = re.search(r'\{.*"title".*"summary".*\}', response_text, re.DOTALL)

                title = ""
                summary = ""
                if match:
                    try:
                        result = json.loads(match.group())
                        title = result.get("title", "").strip()
                        summary = result.get("summary", "").strip()
                    except json.JSONDecodeError:
                        pass

                if not title or not summary:
                    title = f"第{batch[0]['round']}-{batch[-1]['round']}轮"
                    summary = history_text[:150]

                round_start = batch[0]["round"]
                round_end = batch[-1]["round"]
                memory = {
                    "id": f"mem_{len(new_memories) + 1}",
                    "title": title,
                    "summary": summary,
                    "round_start": round_start,
                    "round_end": round_end,
                    "created_at": time.time(),
                }
                new_memories.append(memory)

            except Exception as e:
                logger.warning("重新生成回忆失败 (第%d-%d轮): %s",
                               batch[0]["round"], batch[-1]["round"], e)
                continue

        self._memories = new_memories
        if new_memories:
            self._last_memory_end = new_memories[-1]["round_end"]
        self._save_memories()

        logger.info("会话 %s: 重新生成 %d 条回忆 (interval=%d)", self.id, len(new_memories), interval)
        return new_memories

    def rollback_to_round(self, target_round: int) -> dict:
        """回退到指定轮次，删除之后的叙述历史和回忆。

        返回被删除的轮次范围和回忆数量，供前端确认。
        """
        if target_round < 0:
            target_round = 0

        old_history_len = len(self._narration_history)
        old_memory_len = len(self._memories)

        # 删除 target_round 之后的叙述历史
        self._narration_history = [
            h for h in self._narration_history
            if h["round"] <= target_round
        ]

        # 删除覆盖范围在 target_round 之后的回忆
        self._memories = [
            m for m in self._memories
            if m["round_end"] <= target_round
        ]

        # 更新计数器
        self.narration_count = target_round
        if self._memories:
            self._last_memory_end = self._memories[-1]["round_end"]
        else:
            self._last_memory_end = 0

        self._save_memories()

        # 节点快照与已删除的轮次保持一致（封闭「回滚不动 overrides」缺口）
        try:
            self.overlay.prune_node_history(target_round)
        except Exception:
            logger.warning("回滚后裁剪节点快照失败", exc_info=True)

        deleted_rounds = old_history_len - len(self._narration_history)
        deleted_memories = old_memory_len - len(self._memories)

        logger.info("会话 %s: 回退到第 %d 轮，删除 %d 轮历史 + %d 条回忆",
                     self.id, target_round, deleted_rounds, deleted_memories)

        return {
            "target_round": target_round,
            "narration_count": self.narration_count,
            "deleted_rounds": deleted_rounds,
            "deleted_memories": deleted_memories,
            "memories": self.get_memories(),
        }

    def rollback_to_node(self, node_id: str) -> dict:
        """回档到某个已记录的关键节点，并恢复该节点时的全部状态。

        优先按「剧情树节点」处理（LLM 生成的新节点，树上回档）：设置 current_id、
        恢复角色/任务/环境/剧情日志/节拍，并截断叙述历史。树本身保留，因此回档后
        仍可重新走其它分支。若节点不在树上，则回退到旧的节点快照机制。

        Raises:
            ValueError: 节点无快照或不在当前剧情结构中。
        """
        tree_node = self.overlay.get_tree_node(node_id) if self.overlay else None
        if tree_node is not None:
            st = tree_node.get("state") or {}
            if not st:
                raise ValueError(f"节点尚无状态快照，无法回档: {node_id}")
            target_round = int(st.get("round_end") or 0)
            base = self.rollback_to_round(target_round)
            restored = self.overlay.rollback_to_tree_node(node_id)
            self.reload_environment_from_overlay()
            return {
                **base,
                "node_id": node_id,
                "round_range": [st.get("round_start"), target_round],
                "restored": restored,
                "story_state": self.overlay.build_story_state(),
            }

        snap = self.overlay.get_node_snapshot(node_id)
        if snap is None:
            raise ValueError(f"未找到节点快照: {node_id}")
        target_round = int(snap.get("round_end") or 0)

        base = self.rollback_to_round(target_round)
        restored = self.overlay.restore_from_snapshot(node_id)
        self.reload_environment_from_overlay()

        return {
            **base,
            "node_id": node_id,
            "round_range": [snap.get("round_start"), target_round],
            "restored": restored,
            "story_state": self.overlay.build_story_state(),
        }

    def reload_environment_from_overlay(self):
        """把 overrides.json 中持久化的环境同步到 EnvironmentState（回档后调用）。"""
        env = self.overlay.get_environment_overrides() or {}
        try:
            if env.get("location"):
                self.environment.set_location(env["location"])
            if env.get("weather"):
                self.environment.set_weather(env["weather"])
            if env.get("time_of_day"):
                self.environment.time_of_day = env["time_of_day"]
            if env.get("atmosphere"):
                self.environment.atmosphere = list(env["atmosphere"])
        except Exception:
            logger.warning("会话 %s: 从覆盖恢复环境失败", self.id, exc_info=True)

    def to_dict(self) -> dict:
        overridden_chars = [
            name for name in self.scene_manager.get_scene_characters()
            if self.overlay.has_character_overrides(name)
        ]
        overridden_items = [
            item["id"] for item in self.scene_manager.get_scene_items()
            if self.overlay.has_item_overrides(item["id"])
        ]
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "combat_mode": self.combat_mode,
            "player_identity": self.player_identity,
            "plot_id": self.overlay.get_plot_id(),
            "worldbook_id": self.overlay.get_worldbook_id(),
            "worldbook_scope": self.overlay.get_worldbook_scope(),
            "custom_prompt": self.overlay.get_custom_prompt(),
            "created_at": self.created_at,
            "usable": self.is_usable,
            "characters": self.scene_manager.get_scene_characters(),
            "character_colors": {
                name: c
                for name in self.scene_manager.get_scene_characters()
                if (c := get_theme_color(name))
            },
            "active_character": self.scene_manager.active,
            "items": self.scene_manager.get_scene_items(),
            "environment": {
                "location": self.environment.location,
                "weather": self.environment.weather,
                "time": self.environment.time_of_day,
                "atmosphere": self.environment.atmosphere,
            },
            "scene_log": self.scene_manager._scene_log[-5:],
            "has_overrides": bool(overridden_chars or overridden_items),
            "overridden_characters": overridden_chars,
            "overridden_items": overridden_items,
            "narration_count": self.narration_count,
            "total_usage": self.total_usage,
            "backgrounds_dir": str(self.data_dir / "backgrounds"),
            "in_combat": self.combat is not None,
            "combat": self.combat.get_state() if self.combat else None,
            # 可恢复的战斗：内存中仍在，或磁盘上有挂起存档（临时返回后继续打）
            "combat_resumable": self.combat_resumable,
            "combat_resume": self.combat_resume_summary(),
        }

    # ── 战斗挂起存档 ──

    @property
    def combat_resumable(self) -> bool:
        """是否存在可恢复的战斗（内存中仍在，或磁盘上有挂起存档）。"""
        if self.combat is not None:
            return True
        return session_resume_path(self).is_file()

    def combat_resume_summary(self) -> Optional[dict]:
        """挂起存档摘要（轮数/遭遇战/手牌数），无存档返回 None。"""
        if self.combat is not None:
            # 未挂起：战斗仍在内存，无存档可摘要
            return None
        return _summarize_resume(read_resume(session_resume_path(self)))

    def release_combat(self) -> bool:
        """摘下并作废本会话的战斗（内存态 + 挂起存档）。

        供删除会话时级联调用。返回值表示**是否清理干净**：
        - 无战斗、无存档 → True（本就干净）
        - 有存档 → 删除成功才 True；删除失败留待调用方中止删除
        - 内存中仍有战斗 → 先标记 `suspended` 并投哨兵事件唤醒阻塞在
          `event_queue.get(timeout=30)` 的 SSE 线程，再释放引用（理由同
          `blueprints/combat.py::_detach_combat`：直接置 None 会让 SSE 白等 30 秒）。
          内存态释放不会失败，因此不影响返回值。
        """
        combat = self.combat
        if combat is not None:
            try:
                combat.suspended = True
                combat.event_queue.put_nowait(
                    CombatEvent("suspend", {"reason": "会话已删除"}))
            except Exception:
                # 哨兵投递失败只是让 SSE 线程多等一个 timeout，不应阻断删除
                logger.debug("会话 %s: 投递战斗挂起哨兵失败", self.id, exc_info=True)
            self.combat = None

        try:
            session_resume_path(self).unlink()
            removed_resume = True
        except FileNotFoundError:
            removed_resume = True  # 本就没有存档
        except OSError as e:
            logger.error("会话 %s: 删除战斗挂起存档失败: %s", self.id, e)
            removed_resume = False

        if combat is not None or not removed_resume:
            logger.info("会话 %s: 已释放战斗资源 (in_memory=%s, resume_removed=%s)",
                        self.id, combat is not None, removed_resume)
        return removed_resume


class SessionManager:
    """管理多个并行会话。"""

    def __init__(self, llm_backend_manager: LLMBackendManager, wiki_manager=None,
                 worldbook_manager=None):
        self._llm_backend = llm_backend_manager
        self._wiki_manager = wiki_manager
        self._worldbook_manager = worldbook_manager
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._next_id = 0
        self._restore_sessions()

    def create_session(self, name: str = "", mode: str = "free", plot_name: str = "",
                        combat_mode: str = "narrative", worldbook_id: str = "",
                        player_identity: str = "博士", plot_id: str = "",
                        initializer: Callable[[Session], None] | None = None) -> Session:
        """创建新会话。

        Args:
            worldbook_id: 可选，创建时绑定世界书（未绑定则回落全局默认书）。
            player_identity: 玩家身份角色名（用户自身，默认"博士"）。
            plot_id: 可选，创建时绑定的剧情 ID；用于决定无剧情会话是否留空初始场景。
        """
        session_id = self._generate_id()
        if not name:
            if plot_name:
                base = plot_name
            else:
                mode_label = "剧情" if mode == "story" else "自由"
                base = f"{mode_label}对话"
            existing = {
                s.name for s in self._sessions.values()
                if s.mode == mode and s.name and s.name.startswith(base)
            }
            counter = 1
            name = f"{base}·{counter}"
            while name in existing:
                counter += 1
                name = f"{base}·{counter}"
        try:
            session = Session(session_id, self._llm_backend, name=name, mode=mode,
                              combat_mode=combat_mode,
                              player_identity=player_identity,
                              wiki_manager=self._wiki_manager,
                              worldbook_manager=self._worldbook_manager,
                              empty_environment=(mode == "story" and not plot_id))
            if worldbook_id:
                session.overlay.set_worldbook_id(worldbook_id)
            if initializer:
                initializer(session)
            self._save_session_meta(session)
        except Exception:
            # 新创建的会话还未公开；失败时只清理本次唯一 ID 对应的半成品。
            SessionOverlay.delete_session_overlays(session_id, mode)
            raise
        with self._lock:
            self._sessions[session_id] = session
        logger.info("创建会话: %s (mode=%s, chars=%s)",
                     session_id, mode, session.scene_manager.get_scene_characters())
        return session

    def _save_session_meta(self, session: Session):
        """保存会话元数据到 session.json。"""
        self._save_session_meta_raw(session.id, session.mode, session.name, session.created_at,
                                    session.combat_mode, session.player_identity)

    def _restore_sessions(self):
        """从磁盘恢复会话元数据。

        兼容两种情况：
        1. {mode}/{id}/session.json 存在 → 直接读取
        2. {mode}/{id}/overrides.json 存在但 session.json 不存在 → 从目录结构推断
        """
        if not _SESSIONS_DIR.exists():
            return

        max_counter = 0
        to_restore: list[tuple[str, str, str, float, str, str]] = []  # (id, mode, name, created_at, combat_mode, player_identity)

        for entry in _SESSIONS_DIR.iterdir():
            if not entry.is_dir():
                continue

            # 判断是 mode 子目录还是旧版 session 目录
            if entry.name in ("free", "story"):
                mode = entry.name
                for session_dir in entry.iterdir():
                    if not session_dir.is_dir():
                        continue
                    sid = session_dir.name
                    meta = self._read_session_meta(session_dir, sid, mode)
                    if meta:
                        to_restore.append(meta)

        for sid, mode, name, created_at, combat_mode, player_identity in to_restore:
            try:
                session = Session(sid, self._llm_backend, name=name, mode=mode,
                                 combat_mode=combat_mode,
                                 player_identity=player_identity,
                                 wiki_manager=self._wiki_manager,
                                 worldbook_manager=self._worldbook_manager)
                session.created_at = created_at
                self._sessions[sid] = session

                parts = sid.split("_")
                if len(parts) >= 2:
                    try:
                        max_counter = max(max_counter, int(parts[1]))
                    except ValueError:
                        pass

                logger.info("恢复会话: %s (mode=%s)", sid, mode)
            except Exception as e:
                logger.warning("恢复会话失败 %s: %s", sid, e)

        self._next_id = max_counter

    def _read_session_meta(self, session_dir: Path, sid: str, mode: str):
        """读取单个会话的元数据，必要时从目录结构推断并补写 session.json。"""
        session_file = session_dir / "session.json"

        if session_file.exists():
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return (data["id"], data.get("mode", mode),
                        data.get("name", ""), data.get("created_at", 0),
                        data.get("combat_mode", "narrative"),
                        data.get("player_identity", "博士"))
            except Exception:
                pass

        # session.json 不存在但有 overrides.json → 从目录结构推断
        if (session_dir / "overrides.json").exists():
            created_at = 0.0
            parts = sid.split("_")
            if len(parts) >= 3:
                try:
                    created_at = int(parts[2], 16) / 1000.0
                except ValueError:
                    created_at = time.time()
            else:
                created_at = time.time()

            mode_label = "剧情" if mode == "story" else "自由"
            name = f"{mode_label}对话 · {time.strftime('%m/%d %H:%M', time.localtime(created_at))}"

            # 补写 session.json
            self._save_session_meta_raw(sid, mode, name, created_at)

            logger.info("从 overrides.json 推断并补写 session.json: %s/%s", mode, sid)
            return (sid, mode, name, created_at, "narrative", "博士")

        return None

    def _save_session_meta_raw(self, sid: str, mode: str, name: str, created_at: float,
                                combat_mode: str = "narrative",
                                player_identity: str = "博士"):
        """直接写入 session.json（不依赖 Session 对象）。"""
        session_file = _SESSIONS_DIR / mode / sid / "session.json"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({
                "id": sid,
                "name": name,
                "mode": mode,
                "combat_mode": combat_mode,
                "player_identity": player_identity,
                "created_at": created_at,
            }, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(session_id)

    def import_session_dir(self, mode: str, session_id: str) -> Optional[Session]:
        """从磁盘注册一个已放置的会话目录到内存（会话导入用）。"""
        meta = self._read_session_meta(_SESSIONS_DIR / mode / session_id,
                                       session_id, mode)
        if not meta:
            return None
        _sid, _mode, name, created_at, combat_mode, player_identity = meta
        try:
            session = Session(_sid, self._llm_backend, name=name, mode=_mode,
                              combat_mode=combat_mode,
                              player_identity=player_identity,
                              wiki_manager=self._wiki_manager,
                              worldbook_manager=self._worldbook_manager)
        except Exception as e:
            logger.warning("导入会话构造失败 %s/%s: %s", mode, session_id, e)
            return None
        session.created_at = created_at
        with self._lock:
            self._sessions[_sid] = session
        logger.info("导入会话: %s (mode=%s)", _sid, _mode)
        return session

    def _session_dir(self, session_id: str, mode: str) -> Optional[Path]:
        """该会话的数据目录（经路径口径校验）。

        `mode` 会被拼进文件路径，因此必须确认它是 `free`/`story` 之一：拼错
        或传入奇怪的 mode 会让 `delete_session_overlays` 的 `rmtree` 作用在
        `sessions/` 之外的路径上。非法 mode 返回 None，由调用方拒绝删除 ——
        **不能**当成「没有目录可删」放行，那等于静默丢一个删不掉的会话。
        """
        if mode not in _VALID_MODES:
            logger.error("会话 %s: 非法 mode %r，拒绝磁盘清理", session_id, mode)
            return None
        return _SESSIONS_DIR / mode / session_id

    def delete_session(self, session_id: str) -> bool:
        """销毁会话：内存态、挂起战斗、覆盖数据一并清除（事务性）。

        删除顺序刻意设计成「先清战斗资源，再删目录」：

        1. **校验**：`session_id` 必须在内存注册表中，否则返回 False（路由
           据此回 404）。`session.mode` 非法则抛错中止 —— 既不能拿它去拼
           目录路径（可能删到 `sessions/` 之外），也不能当作「无目录可删」
           放行（那会静默丢一个会话）。
        2. **清战斗**：`release_combat()` 摘下内存战斗态（唤醒阻塞的 SSE
           线程）并删除挂起存档 `combat_resume.json`。挂起存档就在会话目录
           内，虽然随后的 `rmtree` 也会带走它，但若目录删除失败（被占用、
           权限不足）存档就会残留 —— 而残留的存档会让前端「继续战斗」入口
           指向一个已经不存在的会话。故这一步独立执行并**校验结果**。
        3. **清目录**：前两步都干净后才 `rmtree` 会话目录（覆盖数据、记忆、
           背景图等）；删除失败同样中止，保留内存态以便重试。

        任一步失败即抛 `SessionCleanupError`（内存态保持不变），调用方应
        转成 5xx 让用户重试，而不是静默返回成功留下残留数据。
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            mode = session.mode

            # 校验磁盘路径口径：mode 非法时既不删也不放行（放行会静默丢会话）
            session_dir = self._session_dir(session_id, mode)
            if session_dir is None:
                raise SessionCleanupError(
                    f"会话 {session_id} 的存储位置（mode={mode!r}）异常，已中止删除")
            existed = session_dir.exists()

            # ── 1. 级联清理该会话下的战斗（内存态 + 挂起存档）──
            if not session.release_combat():
                raise SessionCleanupError(
                    f"会话 {session_id} 的战斗挂起存档清理失败，请重试")

            # ── 2. 删除会话目录（覆盖数据 / 记忆 / 资源）──
            try:
                SessionOverlay.delete_session_overlays(session_id, mode)
            except OSError as e:
                logger.exception("会话 %s: 删除覆盖数据失败，中止删除", session_id)
                raise SessionCleanupError(
                    f"会话 {session_id} 的覆盖数据删除失败：{e}") from e

            # ── 3. 校验：确认磁盘上确无残留 ──
            if existed and session_dir.exists():
                logger.error("会话 %s: 删除后目录仍存在 %s", session_id, session_dir)
                raise SessionCleanupError(
                    f"会话 {session_id} 的目录未能删除：{session_dir}")

            # 全部清理成功后才摘掉内存注册（此前失败都可重试）
            del self._sessions[session_id]

            logger.info("删除会话: %s (mode=%s, 已清理战斗与覆盖数据)", session_id, mode)
            return True

    def rename_session(self, session_id: str, new_name: str) -> bool:
        """重命名会话。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session and new_name.strip():
                session.name = new_name.strip()
                self._save_session_meta(session)
                return True
            return False

    def set_player_identity(self, session_id: str, identity: str) -> bool:
        """设置会话的玩家身份角色，并持久化到 session.json。"""
        identity = (identity or "").strip() or "博士"
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session.player_identity = identity
            self._save_session_meta(session)
            return True

    def list_sessions(self) -> list[dict]:
        """列出所有会话摘要。"""
        with self._lock:
            return [s.to_dict() for s in self._sessions.values()]

    def _generate_id(self) -> str:
        self._next_id += 1
        timestamp = hex(int(time.time() * 1000))[2:]
        return f"sess_{self._next_id}_{timestamp}"
