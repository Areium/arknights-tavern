import json
import re
import queue
import threading
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

    def __init__(self, llm, registry, overlay=None, wiki_manager=None, session_context=None,
                 combat_mode: str = "narrative"):
        self._llm = llm
        self._registry = registry
        self._overlay = overlay  # SessionOverlay instance
        self._wiki_manager = wiki_manager
        self._session_context = session_context
        self._combat_mode = combat_mode

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
        entity_whitelist = None
        if self._overlay:
            char_overrides = self._overlay.get_character_overrides(name)
            entity_whitelist = self._overlay.get_index_config()

        agent = CharacterAgent(
            name, self._llm, self._registry,
            overrides=char_overrides if char_overrides else None,
            entity_whitelist=entity_whitelist,
            wiki_manager=self._wiki_manager,
            session_context=self._session_context,
        )
        if agent.character is None:
            logger.error("无法加载角色: %s", name)
            return False

        self._agents[name] = agent
        if self.active is None:
            self.active = name

        # 刷新预加载文档
        if self._session_context and self._wiki_manager:
            self._session_context.refresh_preload(
                self._wiki_manager, list(self._agents.keys()))

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

        # 刷新预加载文档
        if self._session_context and self._wiki_manager:
            self._session_context.refresh_preload(
                self._wiki_manager, list(self._agents.keys()))

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
             env_context: str = "", stream_callback=None) -> tuple[str, dict, dict | None]:
        """场景对话处理。

        流程:
        1. 解析 [@角色名] 语法自动切换对话目标
        2. 将输入路由到当前活跃角色
        3. 在角色 prompt 中注入【同场角色】【场景动态】上下文
        4. 更新场景事件日志

        Returns:
            tuple[str, dict, dict|None]: (角色回复, 环境更新字典, token使用量)
        """
        # 解析目标切换
        target, clean_input = self._parse_target(user_input)
        if target:
            if target in self._agents:
                if target != self.active:
                    self.switch_active(target)
            else:
                # @mention 了不在场景中的角色，给出提示
                return f"（{target} 不在这里）", {}, None

        if not self.active or self.active not in self._agents:
            return "场景中没有可对话的角色。", {}, None

        agent = self._agents[self.active]
        identity = (player_info or {}).get("identity", "博士")

        # 构建场景上下文注入
        scene_context = self._build_scene_context()

        # 路由到角色代理
        response, env_updates, usage = agent.chat(
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

        return response, env_updates, usage

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
        total_usage = None

        for name, agent in self._agents.items():
            try:
                response, env_updates, usage = agent.chat(
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
                    "usage": usage,
                })
                if usage:
                    if total_usage is None:
                        total_usage = dict(usage)
                    else:
                        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                            total_usage[k] = total_usage.get(k, 0) + usage.get(k, 0)
                self._log_event(f"{identity} → {name}: {user_input[:60]}")
                self._log_event(f"{name}: {response[:80].replace(chr(10), ' ')}")
            except Exception as e:
                logger.error("群聊中角色 %s 出错: %s", name, e)
                results.append({
                    "character": name,
                    "response": f"（{name} 暂时无法回应）",
                    "env_updates": {},
                    "usage": None,
                })

        return results, total_usage

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

    _NARRATOR_SYSTEM = """\
<role>
你是明日方舟文字冒险游戏的场景叙述者，负责推进剧情。
</role>

<core_rules>
- MUST：用第三人称叙述场景进展，描写环境、角色的动作和表情
- MUST：角色对话用「」标注，自然地融入叙述中
- MUST：叙述生动但克制，不代替玩家做决定，不替玩家说话
- MUST：每次叙述约 {word_limit} 字，在自然段落处收尾
- MUST：保持对话的连贯性，不重复已发生的事件
- MUST：推进到场景自然结束时，在叙述末尾输出 <beat_complete/>
</core_rules>

<output_format>
- 正常叙述：自然段落文本，角色对话用「」标注
- 场景结束：末尾输出 <beat_complete/>（单独一行）
{combat_rule}{choices_rules}</output_format>"""

    @staticmethod
    def _build_system_prompt(word_limit: int, structured: bool = False,
                             choices_count: int = 0,
                             combat_mode: str = "narrative") -> str:
        """根据 word_limit 和条件构建系统提示词，XML 标签分区 + MUST 语言。

        模板通过 .format() 注入 word_limit、combat_rule、choices_rules。
        """

        # 战斗规则（注入到 <output_format> 中）
        if combat_mode == "tactical":
            combat_rule = (
                "\n- MUST：如果场景存在明确的敌对威胁或战斗冲突，"
                "立即在叙述末尾输出 <combat:遭遇ID/>（单独一行）。"
                "不得继续叙述而不输出标记。正常叙述中禁止展示 HP/SP 数值。"
            )
        else:
            combat_rule = (
                "\n- MUST：如果场景出现战斗，通过剧情描述和关键判定推进。"
                "禁止展示 HP/SP 等数值，提供有叙事含义的战术选项。"
            )

        # 选项规则（注入到 <output_format> 中）
        if choices_count > 0:
            choices_rules = (
                f"\n- MUST：叙述结束后输出 <choices/>，"
                f"然后列出恰好 {choices_count} 个合理的后续行动选项（每行一个，≤15字，不编号）"
                f"\n- MUST：末尾输出 <summary/>（≤50字中文，只写事实不写评价）"
            )
        else:
            choices_rules = ""

        template = SceneManager._NARRATOR_SYSTEM_STRUCTURED if structured else SceneManager._NARRATOR_SYSTEM
        return template.format(word_limit=word_limit,
                               combat_rule=combat_rule,
                               choices_rules=choices_rules)

    _NARRATOR_SYSTEM_STRUCTURED = """\
<role>
你是明日方舟文字冒险游戏的场景叙述者，负责推进剧情。
</role>

<core_rules>
- MUST：用第三人称叙述场景进展，描写环境、角色的动作和表情
- MUST：叙述中的角色对话必须使用「」标注，严禁在 JSON 文本值中使用英文双引号 " 标注对话
- MUST：叙述生动但克制，不代替玩家做决定，不替玩家说话
- MUST：每次叙述约 {word_limit} 字，在自然段落处收尾
- MUST：保持对话的连贯性，不重复已发生的事件
- MUST：推进到场景自然结束时，在叙述末尾输出 <beat_complete/>
</core_rules>

<output_format>
严格输出 JSON 数组，禁止其他文字：
[
  {{"type": "narration", "text": "叙述文字（对话用「」标注）"}},
  {{"type": "dialogue", "text": "对话内容", "speaker": "角色名"}}
]
type 枚举：narration / dialogue
speaker 必须从场景角色列表选择，无法判断时用 null
相邻同类型元素合并
{combat_rule}{choices_rules}</output_format>"""

    @staticmethod
    def _build_conversation_history(history: list[dict],
                                     max_chars: int = 3000,
                                     structured: bool = False) -> str:
        """将最近对话历史格式化为提示词可注入的文本。

        从最近的轮次往前取，直到达到 max_chars 上限。
        当 structured=True 时，优先使用历史中存储的 JSON 片段作为格式示例。
        """
        if not history:
            return ""
        parts = []
        total = 0
        for entry in reversed(history):
            if not entry.get("text") and not entry.get("action"):
                continue
            line = f"第{entry['round']}轮"
            if entry.get("action"):
                line += f" — 玩家: {entry['action']}"
            if entry.get("text"):
                if structured and entry.get("segments"):
                    segments_json = json.dumps(entry["segments"], ensure_ascii=False)
                    line += f"\n叙述(JSON): {segments_json}"
                else:
                    line += f"\n叙述: {entry['text']}"
            if total + len(line) > max_chars and parts:
                break
            parts.append(line)
            total += len(line)
        if not parts:
            return ""
        return "【对话历史】\n" + "\n\n".join(reversed(parts))

    # 遭遇目录缓存（避免每次叙述都扫描文件系统）
    _encounters_cache: list[str] | None = None

    @classmethod
    def _list_encounters(cls) -> str:
        """返回可用遭遇的缓存列表字符串。"""
        if cls._encounters_cache is None:
            import os
            encounters_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "combat", "encounters",
            )
            result = []
            if os.path.isdir(encounters_dir):
                for f in sorted(os.listdir(encounters_dir)):
                    if f.endswith(".md"):
                        result.append(f[:-3])
            cls._encounters_cache = result
        return "、".join(cls._encounters_cache) if cls._encounters_cache else "初遇整合运动"

    def _build_narration_messages(
        self, player_info, env_context,
        user_action="", is_first_turn=True,
        conversation_history="",
        word_limit=500, structured=False,
        choices_count=0,
    ) -> list[dict]:
        """构建叙述的 messages 列表，XML 标签分区用户消息。"""
        identity = (player_info or {}).get("identity", "博士") if player_info else "博士"

        char_summaries = []
        for name, agent in self._agents.items():
            meta = agent.metadata if hasattr(agent, 'metadata') else {}
            tags = meta.get("tags", [])
            tag_str = f"（{' '.join(tags[:3])}）" if tags else ""
            active_mark = " ← 对话中" if name == self.active else ""
            char_summaries.append(f"- {name}{tag_str}{active_mark}")

        # 战术模式：在用户消息最前面插入战斗优先指令（primacy 效应）
        context_parts = []
        if self._combat_mode == "tactical":
            context_parts.append(
                "MUST：如果场景中存在战斗/敌对冲突，优先输出 <combat:遭遇ID/> 触发战斗系统。"
                "不要只叙述战斗场景而不输出标记。"
            )

        # 场景状态
        if is_first_turn:
            context_parts.append(f"<scene_state>\n{env_context or '当前场景'}\n</scene_state>")
        else:
            brief_lines = []
            for line in (env_context or "").split("\n"):
                stripped = line.strip()
                if not stripped or stripped.startswith("【"):
                    continue
                if stripped.startswith(("位置:", "天气:", "时间:")):
                    brief_lines.append(stripped)
            if brief_lines:
                context_parts.append("<scene_state>\n" + " / ".join(brief_lines) + "\n</scene_state>")

        # 对话历史
        if conversation_history:
            context_parts.append(f"<conversation_history>\n{conversation_history}\n</conversation_history>")

        # 场景角色 + 遭遇
        chars = "\n".join(char_summaries) if char_summaries else "（无）"
        context_parts.append(f"<characters>\n{chars}\n</characters>")
        if self._combat_mode == "tactical":
            encounter_str = self._list_encounters()
            context_parts.append(
                f"<encounters>\n{encounter_str}（选择最匹配剧情的遭遇，如无匹配使用第一个）\n"
                f"可选附加 JSON：{{\"status_effects\":{{\"角色名\":{{\"hp_penalty\":0.0~1.0,\"atk_bonus\":0.0~1.0,\"def_penalty\":0.0~1.0}}}}}}\n"
                f"</encounters>"
            )

        # 玩家
        player_lines = [f"身份：{identity}"]
        if user_action:
            player_lines.append(f"操作：{user_action}")
        context_parts.append(f"<player>\n" + "\n".join(player_lines) + "\n</player>")

        # 场景动态
        recent = self._scene_log[-8:]
        if recent:
            context_parts.append("<scene_events>\n" + "\n".join(recent) + "\n</scene_events>")

        # 参考层：剧情开场、结构、预加载资料、文档目录
        ref_parts = []
        if self._overlay and self._overlay.has_plot_context():
            opening = self._overlay.get_plot_context()
            if opening:
                ref_parts.append(opening)
                logger.info("已注入开场上下文到首次叙述")
            self._overlay.clear_plot_context()
        if self._overlay:
            plot_state = self._overlay.read_session_doc("plot_state.md")
            if plot_state:
                ref_parts.append("剧情结构参考（导航用，非脚本）：\n" + plot_state)
            plot_log = self._overlay.read_session_doc("plot_log.md")
            if plot_log:
                ref_parts.append("剧情进度日志（已发生的事件，请勿重复）：\n" + plot_log)
        if self._session_context:
            preloaded_text = self._session_context.format_preloaded()
            if preloaded_text:
                ref_parts.append(preloaded_text)
        if self._wiki_manager:
            catalog = self._wiki_manager.format_catalog_summary(
                self._wiki_manager.NARRATIVE_CATALOG_CATS
            )
            if catalog:
                ref_parts.append(catalog)
        if ref_parts:
            context_parts.append("<reference>\n" + "\n\n".join(ref_parts) + "\n</reference>")

        # 收尾指令（recency 效应）
        if structured:
            context_parts.append("MUST：只输出 JSON 数组，不要其他内容。")
            system_prompt = self._build_system_prompt(word_limit, structured=True,
                                                         choices_count=choices_count,
                                                         combat_mode=self._combat_mode)
        else:
            if self._combat_mode == "tactical":
                context_parts.append(
                    "MUST：如果存在战斗冲突，输出 <combat:遭遇ID/> 触发战斗系统，然后简要叙述。"
                )
            else:
                context_parts.append(
                    "请基于以上场景信息继续推进剧情。描写场景和角色的反应，"
                    "角色对话用「」标注。保持剧情连贯、自然，结束时留出继续的空间。"
                )
            system_prompt = self._build_system_prompt(word_limit, structured=False,
                                                         choices_count=choices_count,
                                                         combat_mode=self._combat_mode)

        context = "\n\n".join(context_parts)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

    def narrate(self, player_info: dict | None = None, env_context: str = "",
                user_action: str = "", structured: bool = False,
                max_tokens: int | None = None,
                word_limit: int = 500,
                choices_count: int = 0,
                conversation_history: str = "",
                is_first_turn: bool = True) -> tuple[str, dict, dict | None]:
        """生成剧情叙述。

        用于【继续推进剧情】模式。以场景叙述者的视角生成连贯的剧情文本，
        角色对话会自然嵌入叙述中。

        Args:
            player_info: 玩家信息
            env_context: 环境上下文
            user_action: 用户最近的操作（如有），用于衔接剧情
            structured: True 时要求 LLM 直接输出 JSON 片段数组
            conversation_history: 格式化的历史对话文本
            is_first_turn: 首轮时为 True，注入完整场景描述

        Returns:
            tuple[str, dict, dict|None]: (叙述文本, 环境更新字典, token使用量)
        """
        messages = self._build_narration_messages(
            player_info, env_context,
            user_action=user_action, is_first_turn=is_first_turn,
            conversation_history=conversation_history,
            word_limit=word_limit, structured=structured,
            choices_count=choices_count,
        )

        result = self._llm.chat(messages, stream=False, max_tokens=max_tokens)
        narrative = result.get("content", "")
        usage = result.get("usage")

        # 将叙述记入场景日志
        self._log_event(f"📖 剧情推进: {narrative[:80].replace(chr(10), ' ')}...")

        return narrative, {}, usage

    def narrate_stream(self, player_info: dict | None = None, env_context: str = "",
                       user_action: str = "", structured: bool = False,
                       max_tokens: int | None = None,
                       word_limit: int = 500,
                       choices_count: int = 0,
                       conversation_history: str = "",
                       is_first_turn: bool = True):
        """流式生成剧情叙述 — 生成器，逐 token yield。

        使用线程+队列桥接 LLM 的 on_token 回调和 SSE 生成器，
        使前端能在首个 token 到达时立即显示文字，而非等待完整响应。

        当 choices_count > 0 时使用全缓冲模式：LLM 内部不流式，
        完成后再逐 token 推送，确保 [CHOICES] 标记解析完整。

        Yields:
            ("token", str): 单个 LLM 输出 token
            ("reasoning", str): 思考推理 token（思考模型）
            ("done", (str, dict, dict|None, list|None)): 完成信号
                (narrative, env_updates, usage, choices_or_none)
        """
        messages = self._build_narration_messages(
            player_info, env_context,
            user_action=user_action, is_first_turn=is_first_turn,
            conversation_history=conversation_history,
            word_limit=word_limit, structured=structured,
            choices_count=choices_count,
        )

        # — 全缓冲模式（需提取 [CHOICES]）与真流式模式 —
        if choices_count > 0:
            # 全缓冲：非流式获取完整响应，解析 [CHOICES]，再逐 token 推送纯叙述
            result = self._llm.chat(messages, stream=False, max_tokens=max_tokens)
            narrative = result.get("content", "") if isinstance(result, dict) else str(result)
            usage = result.get("usage") if isinstance(result, dict) else None
            self._log_event(f"📖 剧情推进: {narrative[:80].replace(chr(10), ' ')}...")
            # 交给调用方处理 [CHOICES] 解析和逐 token 推送
            yield ("done", (narrative, {}, usage))
            return

        # — 真流式模式 —
        q = queue.Queue()
        cancel = threading.Event()

        def _llm_worker():
            try:
                def on_token(token: str):
                    if cancel.is_set():
                        raise RuntimeError("narrate_stream cancelled")
                    q.put(("token", token))

                def on_reasoning(token: str):
                    if cancel.is_set():
                        raise RuntimeError("narrate_stream cancelled")
                    q.put(("reasoning", token))

                result = self._llm.chat(messages, stream=True, on_token=on_token,
                                        on_reasoning=on_reasoning,
                                        max_tokens=max_tokens)
                q.put(("result", result))
            except Exception as e:
                q.put(("error", e))

        thread = threading.Thread(target=_llm_worker, daemon=True)
        thread.start()

        try:
            accumulated = ""
            while True:
                event_type, data = q.get()
                if event_type == "token":
                    accumulated += data
                    yield ("token", data)
                elif event_type == "reasoning":
                    yield ("reasoning", data)
                elif event_type == "result":
                    narrative = data.get("content", accumulated) if isinstance(data, dict) else accumulated
                    usage = data.get("usage") if isinstance(data, dict) else None
                    self._log_event(f"📖 剧情推进: {narrative[:80].replace(chr(10), ' ')}...")
                    yield ("done", (narrative, {}, usage))
                    return
                elif event_type == "error":
                    raise data
        finally:
            cancel.set()

    @staticmethod
    def _try_recover_json(text: str) -> list[dict] | None:
        """尝试恢复损坏的 JSON（LLM 在文本字段中使用了英文双引号标注对话）。

        策略：仅替换中文标点后/前的引号（明确是对话引号），不触碰 CJK 字符相邻的引号。
        如果仍失败，则用逐字段扫描的方式提取。
        """
        # 提取 JSON 数组区域
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        json_text = text[start:end + 1]

        # 尝试 1：直接解析
        try:
            segments = json.loads(json_text)
            if isinstance(segments, list) and len(segments) > 0:
                return segments
        except json.JSONDecodeError:
            pass

        # 尝试 2：仅替换中文标点相邻的引号（高置信度——标点+引号几乎总是对话标记）
        repaired = json_text
        repaired = re.sub(r'([：，。！？、；])\"', r'\1「', repaired)
        repaired = re.sub(r'\"([，。！？、；])', r'」\1', repaired)
        try:
            segments = json.loads(repaired)
            if isinstance(segments, list) and len(segments) > 0:
                logger.info("JSON 修复成功（标点相邻引号替换）")
                return segments
        except json.JSONDecodeError:
            pass

        # 尝试 3：逐字段扫描提取（绕过引号歧义）
        return SceneManager._scan_json_fields(json_text)

    @staticmethod
    def _scan_json_fields(json_text: str) -> list[dict] | None:
        """从损坏的 JSON 中逐字段扫描提取对象。

        不依赖 JSON 解析器判断字符串边界，而是利用已知的字段名
        (type, text, speaker) 作为锚点来定位值。
        """
        objects = []
        # 找到每个 {...} 对象
        depth = 0
        obj_start = -1
        for i, ch in enumerate(json_text):
            if ch == '{':
                if depth == 0:
                    obj_start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and obj_start >= 0:
                    obj_str = json_text[obj_start:i + 1]
                    obj = SceneManager._extract_object_fields(obj_str)
                    if obj:
                        objects.append(obj)
                    obj_start = -1

        return objects if objects else None

    @staticmethod
    def _extract_object_fields(obj_str: str) -> dict | None:
        """从单个 JSON 对象字符串中提取 type / text / speaker 字段。"""
        result = {}

        # type 字段
        m = re.search(r'\"type\"\s*:\s*\"(narration|dialogue)\"', obj_str)
        if not m:
            return None
        result["type"] = m.group(1)

        # text 字段：从 "text": " 之后，一直扫描到下一个 "speaker" 或 }
        text_match = re.search(r'\"text\"\s*:\s*\"', obj_str)
        if not text_match:
            return None
        text_start = text_match.end()
        text_chars = []
        i = text_start
        in_dialogue = False  # 跟踪 「/」 交替
        while i < len(obj_str):
            ch = obj_str[i]
            if ch == '\\':
                if i + 1 < len(obj_str):
                    text_chars.append(obj_str[i:i + 2])
                    i += 2
                else:
                    i += 1
                continue
            if ch == '"':
                # 判断是否是结束引号：后面紧跟 , 或 }（忽略空白）
                j = i + 1
                while j < len(obj_str) and obj_str[j] in ' \t\n\r':
                    j += 1
                if j >= len(obj_str) or obj_str[j] in ',}':
                    break
                # 嵌入的对话引号，交替替换为 「/」
                in_dialogue = not in_dialogue
                text_chars.append('「' if in_dialogue else '」')
                i += 1
                continue
            text_chars.append(ch)
            i += 1
        result["text"] = ''.join(text_chars).strip()

        # speaker 字段（可选）
        speaker_match = re.search(r'\"speaker\"\s*:\s*\"([^\"]*)\"', obj_str)
        if speaker_match:
            result["speaker"] = speaker_match.group(1)
        elif result["type"] == "dialogue":
            result["speaker"] = None

        return result

    @staticmethod
    def parse_structured(raw: str) -> tuple[list[dict], str]:
        """将 LLM 的结构化 JSON 输出解析为片段列表和纯文本。

        自动检测并处理 ```json 代码块，即使 LLM 未按要求输出纯文本格式。

        Returns:
            (segments, plain_text): 片段列表和拼接后的纯文本（用于 SSE 流式输出）。
            解析失败时返回空列表和原始文本。
        """
        text = raw.strip()

        # 移除 markdown 代码块包裹（```json 或 ```）
        if text.startswith("```"):
            lines = text.split("\n")
            # 跳过首行（可能是 ```json, ```JSON, 或 ```）
            if len(lines) > 1:
                text = "\n".join(lines[1:])
            # 移除末尾的 ```（可能在最后一行，也可能粘连在内容末尾）
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].strip()
            else:
                # 最后一行就是 ```
                last_newline = text.rfind("\n")
                if last_newline != -1 and text[last_newline:].strip() == "```":
                    text = text[:last_newline].strip()

        # 尝试直接解析（处理未被代码块包裹的情况）
        try:
            segments = json.loads(text)
        except json.JSONDecodeError:
            segments = SceneManager._try_recover_json(text)
            if segments is None:
                return [], raw

        if not isinstance(segments, list) or len(segments) == 0:
            return [], raw

        # 构建纯文本（用于流式输出和回退显示）
        parts = []
        for seg in segments:
            t = seg.get("text", "")
            if not isinstance(t, str) or not t.strip():
                continue
            if seg.get("type") == "dialogue" and seg.get("speaker"):
                parts.append(f"{seg['speaker']}：「{t}」")
            elif seg.get("type") == "dialogue":
                parts.append(f"「{t}」")
            else:
                parts.append(t)
        plain = "".join(parts) if parts else raw

        return segments, plain

    def restructure_dialogue(self, narrative: str) -> list[dict]:
        """将叙述文本重组为带说话人标签的对话片段。

        仅在 dialogue_bubble_mode 开启时调用，通过二次 LLM 推理
        识别叙述中「」内的对话及其说话人，返回结构化片段。

        Returns:
            list[dict]: [{"type": "narration"|"dialogue", "text": "...", "speaker": "..."}]
            失败时返回空列表，由前端回退到文本解析。
        """
        chars = self.get_scene_characters()
        if not chars:
            return []

        prompt = (
            f"【叙述文本】\n{narrative}\n\n"
            f"【场景角色】{', '.join(chars)}\n\n"
            "将以上叙述文本拆分为结构化的 JSON 数组。每个元素包含：\n"
            "- type: \"narration\"（叙述）或 \"dialogue\"（对话）\n"
            "- text: 原文片段\n"
            "- speaker: 说话人（仅 dialogue 需要；必须从【场景角色】中选择；"
            "无法确定时用 null）\n\n"
            "规则：\n"
            "1. 「」内的文字是 dialogue，其外的叙述文字是 narration\n"
            "2. 尽量从上下文中推断说话人（如\"XX说\"、\"XX道\"等提示）\n"
            "3. 保持原文不变，只做拆分\n"
            "4. 相邻的同类型片段应合并\n\n"
            "只输出 JSON 数组，不要任何其他内容。"
        )

        messages = [
            {"role": "system", "content": "你是文本结构化助手。只输出 JSON，不输出其他内容。"},
            {"role": "user", "content": prompt},
        ]

        try:
            result = self._llm.chat(messages, stream=False)
            text = result.get("content", "") if isinstance(result, dict) else str(result)
            # 提取 JSON 数组（LLM 可能包裹在 ```json ... ``` 中）
            text = text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:]) if len(lines) > 1 else text
                if text.endswith("```"):
                    text = text[:-3].strip()
            segments = json.loads(text)
            if isinstance(segments, list) and len(segments) > 0:
                return segments
        except Exception:
            logger.warning("对话重组失败，回退到前端解析", exc_info=True)

        return []

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
