import re
import logging

from CharacterAgent import CharacterAgent

logger = logging.getLogger(__name__)


class SceneManager:
    """场景角色管理器：管理多角色同场对话。

    职责：
    - 管理场景中的多个 CharacterAgent
    - 维护场景事件日志（共享上下文）
    - 解析 @mention 切换对话目标
    - 构建【同场角色】【场景动态】注入文本

    前端接口（设计用于 REST API 暴露）:
        get_scene_characters() -> list[str]
        get_active() -> str | None
        load_character(name) -> bool
        unload_character(name) -> bool
        switch_active(name) -> bool
        chat(user_input, player_info, env_context) -> (str, dict)
    """

    # 场景日志保留上限
    _MAX_SCENE_LOG = 20

    def __init__(self, llm, registry, overlay=None):
        self._llm = llm
        self._registry = registry
        self._overlay = overlay  # SessionOverlay instance

        # {name: CharacterAgent}
        self._agents: dict[str, CharacterAgent] = {}

        # 场景事件日志（所有角色共享）
        self._scene_log: list[str] = []

        # 当前对话目标
        self.active: str | None = None

        # 场景中的物品: {item_id: item_data}
        self._scene_items: dict[str, dict] = {}

    # ── 公开 API（前端友好）──

    def get_scene_items(self) -> list[dict]:
        """返回场景中所有物品。"""
        return [
            {"id": item_id, **data}
            for item_id, data in self._scene_items.items()
        ]

    def add_item(self, item_id: str, item_data: dict) -> bool:
        """添加物品到场景。会自动合并会话覆盖。"""
        if item_id in self._scene_items:
            return False
        # Merge session overrides if available
        if self._overlay:
            item_data, _ = self._overlay.apply_item_overrides(item_id, item_data, "")
        self._scene_items[item_id] = item_data
        self._log_event(f"📦 {item_data.get('name', item_id)} 出现在场景中")
        return True

    def remove_item(self, item_id: str) -> bool:
        """从场景移除物品。"""
        if item_id not in self._scene_items:
            return False
        data = self._scene_items.pop(item_id)
        self._log_event(f"📦 {data.get('name', item_id)} 从场景中移除")
        return True

    def get_scene_characters(self) -> list[str]:
        """返回场景中所有角色名。"""
        return list(self._agents.keys())

    def get_active(self) -> str | None:
        """返回当前对话目标角色名。"""
        return self.active

    def get_active_agent(self) -> CharacterAgent | None:
        """返回当前对话目标的 CharacterAgent 实例。"""
        if self.active and self.active in self._agents:
            return self._agents[self.active]
        return None

    def load_character(self, name: str) -> bool:
        """加载角色加入当前场景。首次加载会创建 CharacterAgent 并缓存。

        Args:
            name: 角色名（对应 data/characters/{name}/index.md 或 {name}.md）

        Returns:
            True 表示加载成功，False 表示文件不存在或解析失败。
        """
        if name in self._agents:
            logger.info("角色已在场景中: %s", name)
            return True

        char_overrides = {}
        if self._overlay:
            char_overrides = self._overlay.get_character_overrides(name)

        agent = CharacterAgent(name, self._llm, self._registry, overrides=char_overrides if char_overrides else None)
        if agent.character is None:
            logger.error("无法加载角色: %s", name)
            return False

        self._agents[name] = agent
        if self.active is None:
            self.active = name

        self._log_event(f"{name} 进入了场景")
        logger.info("角色加入场景: %s", name)
        return True

    def unload_character(self, name: str) -> bool:
        """角色离开场景。

        如果该角色是当前对话目标，会自动切换到其他角色。
        """
        if name not in self._agents:
            return False

        del self._agents[name]
        if self.active == name:
            others = [n for n in self._agents if n != name]
            self.active = others[0] if others else None

        self._log_event(f"{name} 离开了场景")
        logger.info("角色离开场景: %s", name)
        return True

    def switch_active(self, name: str) -> bool:
        """切换对话目标。

        Args:
            name: 目标角色名

        Returns:
            True 表示切换成功，False 表示角色不在场景中。
        """
        if name not in self._agents:
            logger.warning("切换目标不在场景中: %s", name)
            return False

        old = self.active
        self.active = name
        if old and old != name:
            self._log_event(f"玩家将注意力转向了 {name}")
        logger.info("对话目标切换: %s → %s", old, name)
        return True

    def chat(self, user_input: str, player_info: dict | None = None,
             env_context: str = "", stream_callback=None) -> tuple[str, dict]:
        """场景对话处理。

        流程:
        1. 解析 [@角色名] 语法自动切换对话目标
        2. 将输入路由到当前活跃角色
        3. 在角色 prompt 中注入【同场角色】【场景动态】上下文
        4. 更新场景事件日志

        Returns:
            tuple[str, dict]: (角色回复, 环境更新字典)
        """
        # 解析目标切换
        target, clean_input = self._parse_target(user_input)
        if target:
            if target in self._agents:
                if target != self.active:
                    self.switch_active(target)
            else:
                # @mention 了不在场景中的角色，给出提示
                return f"（{target} 不在这里）", {}

        if not self.active or self.active not in self._agents:
            return "场景中没有可对话的角色。", {}

        agent = self._agents[self.active]
        identity = (player_info or {}).get("identity", "博士")

        # 构建场景上下文注入
        scene_context = self._build_scene_context()

        # 路由到角色代理
        response, env_updates = agent.chat(
            clean_input,
            player_info,
            env_context,
            scene_context=scene_context,
            stream_callback=stream_callback,
        )

        # 更新场景日志
        self._log_event(f"{identity} → {self.active}: {clean_input}")
        summary = response[:100].replace("\n", " ")
        self._log_event(f"{self.active}: {summary}")

        return response, env_updates

    def group_chat(self, user_input: str, player_info: dict | None = None,
                   env_context: str = "", stream_callback=None) -> list[dict]:
        """群聊模式：将用户输入发送给场景中所有角色。

        每个角色独立调用 chat()，收集所有回复。

        Returns:
            list[dict]: [
                {"character": "阿米娅", "response": "...", "env_updates": {}},
                {"character": "银灰", "response": "...", "env_updates": {}},
            ]
        """
        if not self._agents:
            return [{"character": "", "response": "场景中没有角色。", "env_updates": {}}]

        identity = (player_info or {}).get("identity", "博士")
        scene_context = self._build_scene_context()
        results = []

        for name, agent in self._agents.items():
            try:
                response, env_updates = agent.chat(
                    user_input,
                    player_info,
                    env_context,
                    scene_context=scene_context,
                    stream_callback=stream_callback,
                )
                results.append({
                    "character": name,
                    "response": response,
                    "env_updates": env_updates,
                })
                self._log_event(f"{identity} → {name}: {user_input[:60]}")
                self._log_event(f"{name}: {response[:80].replace(chr(10), ' ')}")
            except Exception as e:
                logger.error("群聊中角色 %s 出错: %s", name, e)
                results.append({
                    "character": name,
                    "response": f"（{name} 暂时无法回应）",
                    "env_updates": {},
                })

        return results

    # ── 叙述模式 ──

    def build_status(self, env_context: str, player_info: dict | None = None) -> str:
        """构建场景状态显示（置于叙述最前）。

        Returns:
            格式化的状态文本。
        """
        scene_chars = self.get_scene_characters()
        active = self.active or ""
        identity = (player_info or {}).get("identity", "博士") if player_info else "博士"

        parts = []
        if env_context:
            parts.append(env_context)
        if scene_chars:
            chars_str = " · ".join(scene_chars)
            parts.append(f"场景角色：{chars_str}")
        else:
            parts.append("场景角色：（无）")
        if identity:
            parts.append(f"玩家：{identity}")
        return "  |  ".join(parts)

    _NARRATOR_SYSTEM = """你是明日方舟文字冒险游戏的【场景叙述者】，负责推进剧情。

规则：
1. 用第三人称叙述场景的进展，描写环境、角色的动作和表情
2. 角色对话用「」标注，自然地融入叙述中
3. 叙述生动但克制，不代替玩家做决定，不替玩家说话
4. 每次叙述控制在 150-250 字之间，保留悬念和继续的空间
5. 如果是继续之前的对话，保持对话的连贯性

请开始叙述当前场景的下一步发展。"""

    def narrate(self, player_info: dict | None = None, env_context: str = "",
                user_action: str = "") -> tuple[str, dict]:
        """生成剧情叙述。

        用于【继续推进剧情】模式。以场景叙述者的视角生成连贯的剧情文本，
        角色对话会自然嵌入叙述中。

        Args:
            player_info: 玩家信息
            env_context: 环境上下文
            user_action: 用户最近的操作（如有），用于衔接剧情

        Returns:
            tuple[str, dict]: (叙述文本, 环境更新字典)
        """
        identity = (player_info or {}).get("identity", "博士") if player_info else "博士"

        # 收集所有角色卡摘要
        char_summaries = []
        for name, agent in self._agents.items():
            meta = agent.metadata if hasattr(agent, 'metadata') else {}
            tags = meta.get("tags", [])
            tag_str = f"（{' '.join(tags[:3])}）" if tags else ""
            active_mark = " ← 对话中" if name == self.active else ""
            char_summaries.append(f"- {name}{tag_str}{active_mark}")

        context_parts = ["【场景状态】", env_context or "当前场景"]
        context_parts.append("\n【场景角色】")
        context_parts.extend(char_summaries)
        context_parts.append(f"\n【玩家身份】{identity}")

        if user_action:
            context_parts.append(f"\n【玩家操作】{user_action}")

        recent = self._scene_log[-8:]
        if recent:
            context_parts.append("\n【场景动态】")
            context_parts.extend(recent)

        # 注入战斗模式上下文
        combat_mode = "narrative"
        if self._overlay:
            combat_mode = self._overlay.get_combat_mode()
        if combat_mode == "narrative":
            combat_instruction = (
                "\n【战斗模式：叙事】如场景中出现战斗，通过剧情描述和关键判定推进，"
                "不展示 HP/SP 等数值，提供有叙事含义的战术选项。"
            )
        else:
            combat_instruction = (
                "\n【战斗模式：战术】如场景中出现战斗，使用完整 d20 回合制系统，"
                "展示 HP/SP/防御 DC/先攻顺序等完整数值结算。"
            )
        context_parts.append(combat_instruction)

        context_parts.append(
            "\n---\n请基于以上场景信息，继续推进剧情。"
            "描写场景和角色的反应，角色对话用「」标注。"
            "保持剧情连贯、自然，结束时留出继续的空间。"
        )

        context = "\n".join(context_parts)

        messages = [
            {"role": "system", "content": self._NARRATOR_SYSTEM},
            {"role": "user", "content": context},
        ]

        narrative = self._llm.chat(messages, stream=False)

        # 将叙述记入场景日志
        self._log_event(f"📖 剧情推进: {narrative[:80].replace(chr(10), ' ')}...")

        return narrative, {}

    # ── 内部方法 ──

    def _build_scene_context(self) -> str:
        """构建【同场角色】【场景物品】和【场景动态】上下文，注入角色 prompt。"""
        lines = ["【同场角色】"]
        for name in self._agents:
            lines.append(f"- {name}")

        if self._scene_items:
            lines.append("\n【场景物品】")
            for item_id, data in self._scene_items.items():
                name = data.get("name", item_id)
                owner = data.get("owner", "")
                effects = data.get("effects", [])
                effect_str = f"（{'、'.join(effects[:3])}）" if effects else ""
                owner_str = f" — 属于 {owner}" if owner else ""
                lines.append(f"- {name}{owner_str} {effect_str}")

        recent = self._scene_log[-10:]
        if recent:
            lines.append("\n【场景动态】")
            lines.extend(recent)

        return "\n".join(lines)

    @staticmethod
    def _parse_target(text: str) -> tuple[str | None, str]:
        """从输入中解析 [@角色名] 目标切换。

        "[凯尔希] 关于矿石病的事" → ("凯尔希", "关于矿石病的事")
        "没有标记的输入" → (None, "没有标记的输入")
        """
        stripped = text.strip()
        m = re.match(r'^\[(.+?)\]\s*(.*)', stripped)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return None, stripped

    def _log_event(self, event: str):
        """追加场景事件，自动裁剪超出上限的旧事件。"""
        self._scene_log.append(event)
        if len(self._scene_log) > self._MAX_SCENE_LOG:
            self._scene_log = self._scene_log[-self._MAX_SCENE_LOG:]
