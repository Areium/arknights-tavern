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

    def __init__(self, llm, registry, overlay=None, wiki_manager=None, session_context=None):
        self._llm = llm
        self._registry = registry
        self._overlay = overlay  # SessionOverlay instance
        self._wiki_manager = wiki_manager
        self._session_context = session_context

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

    _NARRATOR_SYSTEM = """你是明日方舟文字冒险游戏的【场景叙述者】，负责推进剧情。

规则：
1. 用第三人称叙述场景的进展，描写环境、角色的动作和表情
2. 角色对话用「」标注，自然地融入叙述中
3. 叙述生动但克制，不代替玩家做决定，不替玩家说话
4. 每次叙述控制在 150-250 字之间，保留悬念和继续的空间
5. 如果是继续之前的对话，保持对话的连贯性

请开始叙述当前场景的下一步发展。"""

    _NARRATOR_SYSTEM_STRUCTURED = """你是明日方舟文字冒险游戏的【场景叙述者】，负责推进剧情。

规则：
1. 用第三人称叙述场景的进展，描写环境、角色的动作和表情
2. 叙述中的角色对话必须使用「」标注，严禁在 JSON 文本值中使用英文双引号 " 标注对话，因为这会破坏 JSON 结构
3. 叙述生动但克制，不代替玩家做决定，不替玩家说话
4. 每次叙述控制在 150-250 字之间，保留悬念和继续的空间
5. 如果是继续之前的对话，保持对话的连贯性

请以 JSON 数组格式输出剧情。每个元素为叙述段落或角色对话：
- 叙述：{"type": "narration", "text": "叙述文字（其中对话用「」标注）"}
- 对话：{"type": "dialogue", "text": "对话内容", "speaker": "角色名"}
speaker 必须从【场景角色】列表中选择。无法判断说话人时用 null。
相邻的同类型片段应合并为一个元素。
只输出 JSON 数组，不要 markdown 代码块或其他文字。"""

    def narrate(self, player_info: dict | None = None, env_context: str = "",
                user_action: str = "", structured: bool = False) -> tuple[str, dict, dict | None]:
        """生成剧情叙述。

        用于【继续推进剧情】模式。以场景叙述者的视角生成连贯的剧情文本，
        角色对话会自然嵌入叙述中。

        Args:
            player_info: 玩家信息
            env_context: 环境上下文
            user_action: 用户最近的操作（如有），用于衔接剧情
            structured: True 时要求 LLM 直接输出 JSON 片段数组

        Returns:
            tuple[str, dict, dict|None]: (叙述文本, 环境更新字典, token使用量)
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

        # 注入剧情开场上下文（仅首次叙述，注入后清除）
        if self._overlay and self._overlay.has_plot_context():
            opening = self._overlay.get_plot_context()
            if opening:
                context_parts.append(f"\n【开场场景】\n{opening}")
                logger.info("已注入开场上下文到首次叙述")
            self._overlay.clear_plot_context()

        # 注入预加载文档（沿 imports 链展开的角色/种族/职业/势力等）
        if self._session_context:
            preloaded_text = self._session_context.format_preloaded()
            if preloaded_text:
                context_parts.append(preloaded_text)

        # Wiki 目录摘要
        if self._wiki_manager:
            catalog = self._wiki_manager.format_catalog_summary()
            if catalog:
                context_parts.append(catalog)

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

        if structured:
            context_parts.append(
                "\n---\n请基于以上场景信息，以 JSON 格式继续推进剧情。"
            )
            system_prompt = self._NARRATOR_SYSTEM_STRUCTURED
        else:
            context_parts.append(
                "\n---\n请基于以上场景信息，继续推进剧情。"
                "描写场景和角色的反应，角色对话用「」标注。"
                "保持剧情连贯、自然，结束时留出继续的空间。"
            )
            system_prompt = self._NARRATOR_SYSTEM

        context = "\n".join(context_parts)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        result = self._llm.chat(messages, stream=False)
        narrative = result.get("content", "")
        usage = result.get("usage")

        # 将叙述记入场景日志
        self._log_event(f"📖 剧情推进: {narrative[:80].replace(chr(10), ' ')}...")

        return narrative, {}, usage

    def narrate_stream(self, player_info: dict | None = None, env_context: str = "",
                       user_action: str = "", structured: bool = False):
        """流式生成剧情叙述 — 生成器，逐 token yield。

        使用线程+队列桥接 LLM 的 on_token 回调和 SSE 生成器，
        使前端能在首个 token 到达时立即显示文字，而非等待完整响应。

        Yields:
            ("token", str): 单个 LLM 输出 token
            ("done", (str, dict, dict|None)): 完成信号 (narrative, env_updates, usage)
        """
        identity = (player_info or {}).get("identity", "博士") if player_info else "博士"

        # — 构建 messages（与 narrate() 完全一致）—
        char_summaries = []
        for name, agent in self._agents.items():
            meta = agent.metadata if hasattr(agent, 'metadata') else {}
            tags = meta.get("tags", [])
            tag_str = f"（{' '.join(tags[:3])}）" if tags else ""
            active_mark = " ← 对话中" if name == self.active else ""
            char_summaries.append(f"- {name}{tag_str}{active_mark}")

        context_parts = ["【场景状态】", env_context or "当前场景"]

        if self._overlay and self._overlay.has_plot_context():
            opening = self._overlay.get_plot_context()
            if opening:
                context_parts.append(f"\n【开场场景】\n{opening}")
                logger.info("已注入开场上下文到首次叙述")
            self._overlay.clear_plot_context()

        if self._session_context:
            preloaded_text = self._session_context.format_preloaded()
            if preloaded_text:
                context_parts.append(preloaded_text)

        if self._wiki_manager:
            catalog = self._wiki_manager.format_catalog_summary()
            if catalog:
                context_parts.append(catalog)

        context_parts.append("\n【场景角色】")
        context_parts.extend(char_summaries)
        context_parts.append(f"\n【玩家身份】{identity}")

        if user_action:
            context_parts.append(f"\n【玩家操作】{user_action}")

        recent = self._scene_log[-8:]
        if recent:
            context_parts.append("\n【场景动态】")
            context_parts.extend(recent)

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

        if structured:
            context_parts.append(
                "\n---\n请基于以上场景信息，以 JSON 格式继续推进剧情。"
            )
            system_prompt = self._NARRATOR_SYSTEM_STRUCTURED
        else:
            context_parts.append(
                "\n---\n请基于以上场景信息，继续推进剧情。"
                "描写场景和角色的反应，角色对话用「」标注。"
                "保持剧情连贯、自然，结束时留出继续的空间。"
            )
            system_prompt = self._NARRATOR_SYSTEM

        context = "\n".join(context_parts)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        # — 线程+队列桥接 LLM streaming —
        q = queue.Queue()
        cancel = threading.Event()

        def _llm_worker():
            try:
                def on_token(token: str):
                    if cancel.is_set():
                        raise RuntimeError("narrate_stream cancelled")
                    q.put(("token", token))

                result = self._llm.chat(messages, stream=True, on_token=on_token)
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
