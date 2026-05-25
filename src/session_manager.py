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
from typing import Optional

from SceneManager import SceneManager
from avatar_color import get_theme_color
from environment_state import EnvironmentState
from wiki_manager import WikiManager
from llm_backend_manager import LLMBackendManager
from session_overlay import SessionOverlay
from session_context import SessionContext

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SESSIONS_DIR = _PROJECT_ROOT / "data" / "memory" / "sessions"

# Shared registry — all sessions share the same entity index
_registry: Optional[WikiManager] = None


def _get_registry() -> WikiManager:
    global _registry
    if _registry is None:
        _registry = WikiManager()
        _registry.validate()
    return _registry


class Session:
    """一个独立的对话会话。"""

    def __init__(self, session_id: str, llm_backend_manager: LLMBackendManager,
                 name: str = "", mode: str = "free", wiki_manager=None):
        self.id = session_id
        mode_label = "剧情" if mode == "story" else "自由"
        self.name = name or f"{mode_label}对话"
        self.mode = mode  # "free" | "story"
        self.created_at = time.time()
        self._llm_backend = llm_backend_manager

        # 会话覆盖层
        self.overlay = SessionOverlay(session_id, mode)

        # 共享组件
        self.registry = _get_registry()

        # Wiki 文档上下文
        self._wiki_manager = wiki_manager
        self.wiki_context = SessionContext()

        # LLM 延迟检测 — 首次 get_llm() 调用时才探测后端
        self._llm = None
        self.scene_manager = SceneManager(
            self._llm, self.registry, overlay=self.overlay,
            wiki_manager=wiki_manager, session_context=self.wiki_context,
        )
        self.environment = EnvironmentState()
        self.environment.load_default()

        # 应用环境覆盖
        env_overrides = self.overlay.get_environment_overrides()
        if env_overrides:
            if env_overrides.get("time_of_day"):
                self.environment.time_of_day = env_overrides["time_of_day"]
            if env_overrides.get("atmosphere"):
                self.environment.atmosphere = env_overrides["atmosphere"]

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

    # ── 回忆系统 ──

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

    def start_combat(self, encounter_id: str, character_names: list[str] = None):
        """启动会话战斗。"""
        from combat_session import CombatSession
        if character_names is None:
            character_names = self.scene_manager.get_scene_characters()
        combat = CombatSession(self.id)
        combat.start(encounter_id, character_names=character_names)
        self.combat = combat
        return combat

    def get_memories(self) -> list[dict]:
        return list(self._memories)

    def add_narration(self, narrative: str, user_action: str = ""):
        """记录一轮叙述到持久化历史。"""
        self.narration_count += 1
        self._narration_history.append({
            "round": self.narration_count,
            "text": narrative[:1500] if narrative else "",
            "action": user_action,
        })
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
            response = self._llm.chat([
                {"role": "system", "content": "你是一个专业的剧情编辑，负责为TRPG游戏记录详尽的剧情摘要。需要包含关键情节转折、角色互动和重要事件。只输出JSON，不要有其他内容。"},
                {"role": "user", "content": prompt},
            ], stream=False)
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
                ], stream=False)
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
            "combat_mode": self.overlay.get_combat_mode(),
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
            "in_combat": self.combat is not None,
            "combat": self.combat.get_state() if self.combat else None,
        }


class SessionManager:
    """管理多个并行会话。"""

    def __init__(self, llm_backend_manager: LLMBackendManager, wiki_manager=None):
        self._llm_backend = llm_backend_manager
        self._wiki_manager = wiki_manager
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._next_id = 0
        self._restore_sessions()

    def create_session(self, name: str = "", mode: str = "free", plot_name: str = "") -> Session:
        """创建新会话。"""
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
        session = Session(session_id, self._llm_backend, name=name, mode=mode,
                         wiki_manager=self._wiki_manager)
        with self._lock:
            self._sessions[session_id] = session
        self._save_session_meta(session)
        logger.info("创建会话: %s (mode=%s, chars=%s)",
                     session_id, mode, session.scene_manager.get_scene_characters())
        return session

    def _save_session_meta(self, session: Session):
        """保存会话元数据到 session.json。"""
        self._save_session_meta_raw(session.id, session.mode, session.name, session.created_at)

    def _restore_sessions(self):
        """从磁盘恢复会话元数据。

        兼容三种情况：
        1. {mode}/{id}/session.json 存在 → 直接读取
        2. {mode}/{id}/overrides.json 存在但 session.json 不存在 → 从目录结构推断
        3. 旧版 {id}/overrides.json (无 mode 子目录) → 视为 free 模式
        """
        if not _SESSIONS_DIR.exists():
            return

        max_counter = 0
        to_restore: list[tuple[str, str, str, float]] = []  # (id, mode, name, created_at)

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
            elif (entry / "overrides.json").exists():
                # 旧版：session 目录直接在 sessions/ 下，无 mode 子目录
                sid = entry.name
                meta = self._read_session_meta(entry, sid, "free")
                if meta:
                    to_restore.append(meta)

        for sid, mode, name, created_at in to_restore:
            try:
                session = Session(sid, self._llm_backend, name=name, mode=mode,
                                 wiki_manager=self._wiki_manager)
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
                        data.get("name", ""), data.get("created_at", 0))
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
            return (sid, mode, name, created_at)

        return None

    def _save_session_meta_raw(self, sid: str, mode: str, name: str, created_at: float):
        """直接写入 session.json（不依赖 Session 对象）。"""
        session_file = _SESSIONS_DIR / mode / sid / "session.json"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({
                "id": sid,
                "name": name,
                "mode": mode,
                "created_at": created_at,
            }, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """销毁会话（含覆盖数据）。"""
        with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                mode = session.mode
                del self._sessions[session_id]
                SessionOverlay.delete_session_overlays(session_id, mode)
                logger.info("删除会话: %s (mode=%s)", session_id, mode)
                return True
            return False

    def rename_session(self, session_id: str, new_name: str) -> bool:
        """重命名会话。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session and new_name.strip():
                session.name = new_name.strip()
                self._save_session_meta(session)
                return True
            return False

    def list_sessions(self) -> list[dict]:
        """列出所有会话摘要。"""
        with self._lock:
            return [s.to_dict() for s in self._sessions.values()]

    def _generate_id(self) -> str:
        self._next_id += 1
        timestamp = hex(int(time.time() * 1000))[2:]
        return f"sess_{self._next_id}_{timestamp}"
