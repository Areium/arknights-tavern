"""
会话管理器：支持多会话并行，每个会话包含 SceneManager + 环境状态。

设计：
- Session 代表一个独立的对话场景（一组角色 + 环境 + 对话历史）
- SessionManager 管理多个 Session 的创建/查询/销毁
- 每个 Session 可从 LLMBackendManager 获取 LLM 实例
"""

import time
import logging
import threading
from typing import Optional

from GameAgent import GameAgent
from SceneManager import SceneManager
from environment_state import EnvironmentState
from registry_manager import RegistryManager
from llm_backend_manager import LLMBackendManager
from session_overlay import SessionOverlay

logger = logging.getLogger(__name__)


class Session:
    """一个独立的对话会话。"""

    def __init__(self, session_id: str, llm_backend_manager: LLMBackendManager,
                 name: str = "", mode: str = "free"):
        self.id = session_id
        mode_label = "剧情" if mode == "story" else "自由"
        self.name = name or f"{mode_label}对话 · {time.strftime('%m/%d %H:%M', time.localtime())}"
        self.mode = mode  # "free" | "story"
        self.created_at = time.time()
        self._llm_backend = llm_backend_manager

        # 会话覆盖层
        self.overlay = SessionOverlay(session_id, mode)

        # 共享组件
        self.registry = RegistryManager()
        self.registry.validate()

        # 按需选择 LLM
        llm, _ = llm_backend_manager.get_llm()
        if llm is None:
            logger.error("无可用 LLM 后端，会话 %s 创建但不可用", session_id)

        self._llm = llm
        self.scene_manager = SceneManager(self._llm, self.registry, overlay=self.overlay)
        self.environment = EnvironmentState()
        self.environment.load_default()

        # 应用环境覆盖
        env_overrides = self.overlay.get_environment_overrides()
        if env_overrides:
            if env_overrides.get("time_of_day"):
                self.environment.time_of_day = env_overrides["time_of_day"]
            if env_overrides.get("atmosphere"):
                self.environment.atmosphere = env_overrides["atmosphere"]

    @property
    def is_usable(self) -> bool:
        """会话是否可以正常对话。"""
        return self._llm is not None

    def get_llm(self):
        """获取当前 LLM 实例（可能为 None）。"""
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
            "created_at": self.created_at,
            "usable": self.is_usable,
            "characters": self.scene_manager.get_scene_characters(),
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
        }


class SessionManager:
    """管理多个并行会话。"""

    def __init__(self, llm_backend_manager: LLMBackendManager):
        self._llm_backend = llm_backend_manager
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._next_id = 0

    def create_session(self, name: str = "", mode: str = "free") -> Session:
        """创建新会话。"""
        session_id = self._generate_id()
        session = Session(session_id, self._llm_backend, name=name, mode=mode)
        with self._lock:
            self._sessions[session_id] = session
        logger.info("创建会话: %s (mode=%s, chars=%s)",
                     session_id, mode, session.scene_manager.get_scene_characters())
        return session

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
