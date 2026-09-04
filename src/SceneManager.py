import json
import re
import time
import queue
import threading
import logging

from CharacterAgent import CharacterAgent

logger = logging.getLogger(__name__)


def _empty_extraction_result() -> dict:
    """返回空的标记提取结果。"""
    return {
        "beat_complete": False,
        "combat": None,
        "choices": None,
        "summary": None,
        "environment": None,
        "usage": None,
        "error": None,
    }


def _parse_extraction_json(text: str) -> dict:
    """从 LLM 响应中解析标记提取 JSON。

    处理 markdown 代码块包裹、JSON 对象定位和解析异常。
    失败时返回 _empty_extraction_result()。
    """
    text = text.strip()
    # 移除 markdown 代码块包裹
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].strip()
        else:
            # 可能代码块结尾在最后一行（包含换行）
            last_nl = text.rfind("\n")
            if last_nl != -1 and text[last_nl:].strip() == "```":
                text = text[:last_nl].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试从文本中定位 JSON 对象
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return _empty_extraction_result()
        else:
            return _empty_extraction_result()

    return {
        "beat_complete": bool(data.get("beat_complete", False)),
        "combat": _normalize_combat_field(data.get("combat_trigger")),
        "choices": _normalize_choices_field(data.get("choices")),
        "summary": _normalize_summary_field(data.get("summary")),
        "environment": _normalize_environment_field(data.get("environment")),
    }


def _normalize_combat_field(combat_data) -> dict | None:
    """验证并规范化 combat_trigger 字段。"""
    if not combat_data or not isinstance(combat_data, dict):
        return None
    encounter_id = combat_data.get("encounter_id", "")
    if not encounter_id or not isinstance(encounter_id, str) or not encounter_id.strip():
        return None
    params = combat_data.get("params")
    if params is not None and not isinstance(params, dict):
        params = None
    return {"encounter_id": encounter_id.strip(), "params": params}


def _normalize_environment_field(env_data) -> dict | None:
    """验证并规范化 environment 字段（只保留明确出现的场景变化）。"""
    if not env_data or not isinstance(env_data, dict):
        return None
    result = {}
    for key in ("location", "weather", "time"):
        val = env_data.get(key)
        if isinstance(val, str) and val.strip():
            result[key] = val.strip()
    atmosphere = env_data.get("atmosphere")
    if isinstance(atmosphere, str) and atmosphere.strip():
        result["atmosphere"] = [atmosphere.strip()]
    elif isinstance(atmosphere, list):
        items = [str(v).strip() for v in atmosphere if str(v).strip()]
        if items:
            result["atmosphere"] = items
    return result or None


def _normalize_choices_field(choices) -> list[str] | None:
    """验证并规范化 choices 字段。"""
    if not choices or not isinstance(choices, list):
        return None
    result = [str(c).strip() for c in choices if c and len(str(c).strip()) <= 30]
    return result if result else None


def _normalize_summary_field(summary) -> str | None:
    """验证并规范化 summary 字段。"""
    if not summary or not isinstance(summary, str):
        return None
    s = summary.strip()
    return s if s else None


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
                 combat_mode: str = "narrative", worldbook_manager=None):
        self._llm = llm
        self._registry = registry
        self._overlay = overlay  # SessionOverlay instance
        self._wiki_manager = wiki_manager
        self._session_context = session_context
        self._combat_mode = combat_mode
        self._worldbook_manager = worldbook_manager  # WorldBookManager | None

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

    def _persist_scene(self):
        """持久化当前场景状态（角色/物品/当前目标）到会话覆盖层。"""
        if not self._overlay:
            return
        try:
            self._overlay.save_scene_state(
                list(self._agents.keys()),
                [{"id": item_id, **data} for item_id, data in self._scene_items.items()],
                self.active,
            )
        except Exception:
            logger.exception("保存场景状态失败")

    def add_item(self, item_id: str, item_data: dict) -> bool:
        """添加物品到场景。会自动合并会话覆盖。"""
        if item_id in self._scene_items:
            return False
        # Merge session overrides if available
        if self._overlay:
            item_data, _ = self._overlay.apply_item_overrides(item_id, item_data, "")
        self._scene_items[item_id] = item_data
        self._log_event(f"📦 {item_data.get('name', item_id)} 出现在场景中")
        self._persist_scene()
        return True

    def remove_item(self, item_id: str) -> bool:
        """从场景移除物品。"""
        if item_id not in self._scene_items:
            return False
        data = self._scene_items.pop(item_id)
        self._log_event(f"📦 {data.get('name', item_id)} 从场景中移除")
        self._persist_scene()
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

    # ── 世界书 ──

    def _resolve_worldbook(self):
        """解析当前会话生效的世界书（会话绑定 > 全局默认），无则返回 None。"""
        if not self._worldbook_manager:
            return None
        try:
            return self._worldbook_manager.resolve(self._overlay)
        except Exception:
            logger.exception("解析世界书失败")
            return None

    def _recent_scene_text(self, limit: int = 8) -> str:
        """构建世界书关键词扫描用的最近对话文本（场景事件日志尾部）。"""
        return "\n".join(self._scene_log[-limit:]) if self._scene_log else ""

    @staticmethod
    def _is_custom_worldbook(worldbook) -> bool:
        """用户导入/新建的世界书（source=imported）视为自定义世界观。"""
        return worldbook is not None and getattr(worldbook, "source", "") == "imported"


    def _build_worldbook_parts(self, worldbook, recent_text: str,
                               current_input: str, identity: str,
                               active_char: str | None = None) -> tuple[str, str]:
        """触发匹配 + 格式化，返回 (before, after) 注入文本。"""
        if worldbook is None:
            return "", ""
        try:
            matched = worldbook.collect_matches(recent_text, current_input)
            if matched:
                logger.debug("世界书命中 %d 条: %s",
                             len(matched), [e.uid for e in matched])
            return worldbook.format_injection(matched, identity=identity,
                                              active_char=active_char)
        except Exception:
            logger.exception("世界书注入失败，跳过本次注入")
            return "", ""

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
        self._persist_scene()
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
        self._persist_scene()
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
        self._persist_scene()
        return True

    def chat(self, user_input: str, player_info: dict | None = None,
             env_context: str = "", stream_callback=None,
             thinking: str | None = None,
             word_limit: int | None = None,
             max_tokens: int | None = None) -> tuple[str, dict, dict | None]:
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
        custom_prompt = self._overlay.get_custom_prompt() if self._overlay else None

        # 世界书：解析 + 扫描最近场景动态
        worldbook = self._resolve_worldbook()
        recent_text = self._recent_scene_text()

        # 路由到角色代理
        response, env_updates, usage = agent.chat(
            clean_input,
            player_info,
            env_context,
            thinking=thinking,
            scene_context=scene_context,
            stream_callback=stream_callback,
            custom_prompt=custom_prompt,
            worldbook=worldbook,
            recent_text=recent_text,
            word_limit=word_limit,
            max_tokens=max_tokens,
        )

        # 更新场景日志
        self._log_event(f"{identity} → {self.active}: {clean_input}")
        summary = response[:100].replace("\n", " ")
        self._log_event(f"{self.active}: {summary}")

        return response, env_updates, usage

    def group_chat(self, user_input: str, player_info: dict | None = None,
                   env_context: str = "", stream_callback=None,
                   thinking: str | None = None,
                   word_limit: int | None = None,
                   max_tokens: int | None = None):
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
        custom_prompt = self._overlay.get_custom_prompt() if self._overlay else None

        # 世界书：解析 + 扫描最近场景动态
        worldbook = self._resolve_worldbook()
        recent_text = self._recent_scene_text()

        results = []
        total_usage = None

        for name, agent in self._agents.items():
            try:
                response, env_updates, usage = agent.chat(
                    user_input,
                    player_info,
                    env_context,
                    thinking=thinking,
                    scene_context=scene_context,
                    stream_callback=stream_callback,
                    custom_prompt=custom_prompt,
                    worldbook=worldbook,
                    recent_text=recent_text,
                    word_limit=word_limit,
                    max_tokens=max_tokens,
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
你是文字冒险游戏的场景叙述者，负责推进剧情。
</role>

<core_rules>
- MUST：用第三人称叙述场景进展，描写环境、角色的动作和表情
- MUST：角色对话用「」标注，自然地融入叙述中
- MUST：叙述生动但克制，不代替玩家做决定，不替玩家说话
- MUST：每次叙述约 {word_limit} 字，在自然段落处收尾
- MUST：保持对话的连贯性，不重复已发生的事件
</core_rules>"""

    @staticmethod
    def _build_system_prompt(word_limit: int, structured: bool = False,
                             custom_prompt: str | None = None) -> str:
        """根据 word_limit 构建系统提示词。

        模板通过 .format() 注入 word_limit。
        """
        template = SceneManager._NARRATOR_SYSTEM_STRUCTURED if structured else SceneManager._NARRATOR_SYSTEM
        result = template.format(word_limit=word_limit)
        if custom_prompt:
            result += f"\n\n<custom_instruction>\n此外，请在整个对话过程中始终遵循以下用户自定义指示：\n{custom_prompt}\n</custom_instruction>"
        return result

    _NARRATOR_SYSTEM_STRUCTURED = """\
<role>
你是文字冒险游戏的场景叙述者，负责推进剧情。
</role>

<core_rules>
- MUST：用第三人称叙述场景进展，描写环境、角色的动作和表情
- MUST：角色有具体台词时，必须拆分为独立的 dialogue 段；narration 段只写叙述和描写，不包含角色的直接引语
- MUST：严禁在 JSON 文本值中使用英文双引号 "；dialogue 的 text 字段直接写台词原文，无需额外标注
- MUST：叙述生动但克制，不代替玩家做决定，不替玩家说话
- MUST：每次叙述约 {word_limit} 字，在自然段落处收尾
- MUST：保持对话的连贯性，不重复已发生的事件
</core_rules>

<output_format>
严格输出 JSON 数组，禁止其他文字：
[
  {{"type": "narration", "text": "叙述文字，描写环境、动作、神态等"}},
  {{"type": "dialogue", "text": "角色台词原文", "speaker": "角色名"}}
]
type 枚举：narration / dialogue，角色说的话一律用 dialogue
speaker 必须从场景角色列表选择，无法判断时用 null
相邻同类型元素合并
</output_format>"""

    _MARKER_EXTRACTOR_SYSTEM = """\
<role>
你是文本分析助手，负责从游戏叙述文本中提取结构化标记。
这是一个简单的分类和提取任务，不涉及创意写作。
</role>

<core_rules>
- MUST：只输出 JSON 对象，不要输出任何其他文字或解释
- MUST：只基于叙述文本中实际发生的内容进行判断，严禁虚构或推测
- MUST：只有叙述末尾场景明确达到段落结束点（角色离开、对话结束、行动完成等），才设置 beat_complete 为 true
- MUST：只有叙述中明确出现了敌对冲突/战斗场面时，才设置 combat_trigger
- MUST：选项必须基于叙述内容推导，每个选项不超过15个汉字
- MUST：只有叙述中明确出现了场景转移、天气/时段/氛围变化时，才填写 environment；没有变化时为 null
- 如果对某个字段没有把握，使用默认值（false / null / null / null / null）
</core_rules>

<output_format>
严格输出以下 JSON 对象，不要包含其他内容：
{
  "beat_complete": false,
  "combat_trigger": null,
  "choices": null,
  "summary": null,
  "environment": null
}

字段说明：
- beat_complete: boolean，场景是否自然结束
- combat_trigger: null 或 {"encounter_id": "遭遇ID", "params": null}
- choices: null 或字符串数组（每个选项不超过15个汉字）
- summary: null 或字符串（不超过50个汉字，只写事实不写评价）
- environment: null 或对象，可包含 location（地点名）、weather（天气）、time（时段）、atmosphere（氛围字符串或字符串数组）；只填写叙述中明确出现变化的内容
</output_format>"""

    def _build_extraction_messages(
        self, narrative: str, choices_count: int = 0,
        beat_state_active: bool = False,
    ) -> list[dict]:
        """构建标记提取的消息列表（Call 2）。

        根据条件动态构建 tasks 列表：仅当相关功能激活时才加入对应任务。
        """
        parts = [f"<narrative>\n{narrative}\n</narrative>"]

        tasks = [
            "- 判断叙述中是否发生了场景变化：地点转移、天气变化、时段变化、氛围变化。\n"
            "  如果有，将变化内容填入 environment 对象；没有则 environment 为 null。\n"
            "  只提取叙述中明确写出的内容，不要推测。"
        ]

        if beat_state_active:
            tasks.append(
                "- 判断叙述末尾的场景是否已自然推进到一个段落结束点。\n"
                "  段落结束点的特征：角色离开场景、重要对话结束、\n"
                "  关键行动完成、场景转换过渡等。\n"
                "  将判断结果填入 beat_complete 字段。"
            )

        if self._combat_mode == "tactical":
            encounters = self._list_encounters()
            tasks.append(
                f"- 判断叙述中是否出现了需要触发回合制战斗的明确的敌对冲突：\n"
                f"  袭击、交火、武装对峙（武器出鞘/即将动手）等场面。\n"
                f"  MUST：出现上述场面时 combat_trigger 必须填写遭遇ID，不得为 null；\n"
                f"  仅言语争吵或没有动手意图的对峙不算。\n"
                f"  从以下列表直接选择语义最接近的遭遇，不要过度分析匹配度：\n"
                f"  可用遭遇：{encounters}\n"
                f"  无法判断时使用默认遭遇（初遇整合运动）。\n"
                f"  将结果填入 combat_trigger 字段（格式：{{\"encounter_id\": \"遭遇ID\", \"params\": null}}）。\n"
                f"  可选：在 combat_trigger.params 中设置 status_effects，\n"
                f"  格式 {{\"角色名\": {{\"hp_penalty\": 0.0~1.0}}}}"
            )

        if choices_count > 0:
            tasks.append(
                f"- 基于叙述内容，推导恰好 {choices_count} 个合理的后续行动选项。\n"
                f"  每个选项不超过15个汉字，表达简洁直接，不编号。\n"
                f"  将选项填入 choices 数组。\n"
                f"- 用不超过50个汉字概括本章节叙述的剧情事实（只写事实，不写评价）。\n"
                f"  将摘要填入 summary 字段。"
            )

        if tasks:
            parts.append("<tasks>\n" + "\n".join(tasks) + "\n</tasks>")

        parts.append("MUST：只输出 JSON 对象，不要输出其他任何内容。")

        return [
            {"role": "system", "content": self._MARKER_EXTRACTOR_SYSTEM},
            {"role": "user", "content": "\n\n".join(parts)},
        ]

    def extract_markers(
        self, narrative: str, choices_count: int = 0,
        beat_state_active: bool = False,
    ) -> dict:
        """从叙述文本中提取结构化标记（Call 2）。

        这是一个简单的分类/提取任务，即使 flash 模型也能可靠处理。
        输入叙述文本，输出包含 beat_complete/combat/choices/summary 的字典。

        Returns:
            {
                "beat_complete": bool,
                "combat": {"encounter_id": str, "params": dict | None} | None,
                "choices": list[str] | None,
                "summary": str | None,
                "usage": dict | None,
                "error": str | None,
            }
        """
        if not narrative or not narrative.strip():
            return _empty_extraction_result()

        messages = self._build_extraction_messages(
            narrative, choices_count=choices_count,
            beat_state_active=beat_state_active,
        )

        try:
            _t0 = time.monotonic()
            # 输出预算：512 对会先消耗推理 token 的模型过小——实测战术模式（含战斗触发任务）
            # 空响应率约 8/11（finish_reason=length，预算耗尽于推理）；1024 后仍有约 40%
            # 案例耗尽（部分推理 >1000 tokens），继续上调至 2048 并保留 finish_reason 供诊断。
            # 分类/提取任务：显式关闭思考（实测 none 下无空响应/截断重试；
            # 思考预算 2048 下空/截断率 8%~42% ——见 results_extract_52.json）
            result = self._llm.chat(messages, stream=False, max_tokens=2048, thinking="none")
            logger.info("[TIMING] extract_markers LLM调用: %.0fms", (time.monotonic() - _t0) * 1000)
            text = result.get("content", "") if isinstance(result, dict) else str(result)
            usage = result.get("usage") if isinstance(result, dict) else None
            finish_reason = result.get("finish_reason") if isinstance(result, dict) else None
            parsed = _parse_extraction_json(text)

            # 空响应/截断重试一次：推理 token 消耗存在随机抖动（实测同一案例跨运行
            # 空/截断概率 8%~42% 不等），单次重试可吸收该随机性。
            retried = False
            if not (text or "").strip() or finish_reason == "length":
                logger.warning("Marker extraction 空/截断，重试一次 (empty=%s, finish=%s)",
                               not (text or "").strip(), finish_reason)
                result2 = self._llm.chat(messages, stream=False, max_tokens=2048, thinking="none")
                text2 = result2.get("content", "") if isinstance(result2, dict) else str(result2)
                if (text2 or "").strip():
                    text, parsed = text2, _parse_extraction_json(text2)
                    usage = result2.get("usage") if isinstance(result2, dict) else None
                    finish_reason = result2.get("finish_reason") if isinstance(result2, dict) else None
                    retried = True
            parsed["usage"] = usage
            parsed.setdefault("error", None)
            parsed["finish_reason"] = finish_reason
            # 显式降级标记：最终仍为空响应（预算截断/服务异常）与"模型判定无标记"区分开，
            # 避免静默默认值被误读为成功抽取。
            parsed["degraded"] = not (text or "").strip()
            parsed["retried"] = retried
            if parsed["degraded"]:
                logger.warning("Marker extraction: empty content (finish_reason=%s)", finish_reason)
            return parsed
        except Exception as e:
            logger.warning("Marker extraction failed: %s", e)
            return {**_empty_extraction_result(), "error": str(e),
                    "degraded": True, "finish_reason": None, "retried": False}

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
        """返回可用遭遇的缓存列表字符串（id（中文名），供战斗触发任务语义匹配）。

        实测：纯机器 ID 列表导致模型在多个候选间过度推理（单案例空响应耗尽 2048
        tokens），注入中文名后触发召回 +8pt 且推理明显收敛。
        """
        if cls._encounters_cache is None:
            import os

            import frontmatter as _fm

            encounters_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "combat", "encounters",
            )
            result = []
            if os.path.isdir(encounters_dir):
                for f in sorted(os.listdir(encounters_dir)):
                    if not f.endswith(".md"):
                        continue
                    entry_id = f[:-3]
                    name = ""
                    try:
                        with open(os.path.join(encounters_dir, f), "r", encoding="utf-8") as fh:
                            meta = _fm.load(fh).metadata
                        name = str(meta.get("name") or "")
                    except Exception:
                        name = ""
                    result.append(f"{entry_id}（{name}）" if name else entry_id)
            cls._encounters_cache = result
        return "、".join(cls._encounters_cache) if cls._encounters_cache else "初遇整合运动"

    def _build_narration_messages(
        self, player_info, env_context,
        user_action="", is_first_turn=True,
        conversation_history="",
        word_limit=500, structured=False,
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

        # 提前解析世界书：后续的目录注入、世界观标注、条目触发都依赖它
        worldbook = self._resolve_worldbook()

        # 先准备首轮的开场设定与玩家档案文本。
        # 它们在首轮同时用于世界书关键词扫描，这样自定义世界书（如魔法学院）
        # 不会因为首轮没有用户输入而完全无法触发。
        opening_setup_text = ""
        if is_first_turn:
            opening_parts = []
            for name, agent in self._agents.items():
                meta = getattr(agent, "metadata", None) or {}
                scenario = str(meta.get("scenario", "") or "").strip()
                first_mes = str(meta.get("first_mes", "") or "").strip()
                if not scenario and not first_mes:
                    continue
                first_mes = first_mes.replace("{{char}}", name).replace("{{user}}", identity)
                scenario = scenario.replace("{{char}}", name).replace("{{user}}", identity)
                block = [f"角色「{name}」的开场设定（故事开篇必须忠实呈现）："]
                if scenario:
                    block.append(f"场景设定：{scenario}")
                if first_mes:
                    block.append(f"角色开场白（开篇应自然呈现这段台词/场景）：{first_mes}")
                opening_parts.append("\n".join(block))
            if opening_parts:
                opening_setup_text = (
                    "<opening_setup>\n" + "\n\n".join(opening_parts) + "\n</opening_setup>")

        player_profile_text = ""
        try:
            from player_profile import load_player_profile
            player_profile = load_player_profile(identity)
            if player_profile:
                player_profile_text = f"<player_profile>\n{player_profile}\n</player_profile>"
        except Exception:
            logger.debug("玩家身份档案注入失败: %s", identity)

        # 世界书触发扫描文本：
        # - 首轮把开场设定/玩家档案/环境也纳入扫描，让“选中世界观”在开篇即生效；
        # - 后续轮次仍只扫描近期对话与当前输入，避免常驻内容重复触发。
        if is_first_turn:
            wb_scan_text = "\n".join(
                t for t in (
                    conversation_history,
                    self._recent_scene_text(),
                    player_profile_text,
                    opening_setup_text,
                    env_context,
                ) if t
            )
        else:
            wb_scan_text = (conversation_history or "") + "\n" + self._recent_scene_text()

        wb_before, wb_after = self._build_worldbook_parts(
            worldbook,
            recent_text=wb_scan_text,
            current_input=user_action,
            identity=identity,
        )

        # 构建用户消息，稳定内容在前（利用 API 前缀缓存），易变内容在后（recency 效应）
        context_parts = []

        # ── 模式提示（稳定，始终首位）──
        if self._combat_mode == "tactical":
            context_parts.append(
                "当前处于战术模式。如果场景中存在战斗/敌对冲突，"
                "请详细描述战斗局势。战斗触发将由系统自动处理。"
            )

        # ── 参考层：剧情结构、预加载资料、文档目录（稳定，放前面利用缓存）──
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
            retrieved_text = self._session_context.format_wiki_retrieved()
            if retrieved_text:
                ref_parts.append(retrieved_text)
        # 世界观标注：优先于文档目录，明确当前生效的世界书。
        if worldbook is not None:
            ref_parts.append(f"<worldview>\n当前世界观：{worldbook.name}\n</worldview>")
        # 内置文档目录只在非自定义世界书下注入，避免把方舟角色/地点/势力
        # 泄漏到用户导入的第三方世界观中。
        if self._wiki_manager and not self._is_custom_worldbook(worldbook):
            catalog = self._wiki_manager.format_catalog_summary(
                self._wiki_manager.NARRATIVE_CATALOG_CATS
            )
            if catalog:
                ref_parts.append(catalog)
        # 世界书（position=0 → 稳定参考层）
        if wb_before:
            ref_parts.append(wb_before)
        if opening_setup_text:
            ref_parts.append(opening_setup_text)
        if player_profile_text:
            ref_parts.append(player_profile_text)
        if ref_parts:
            context_parts.append("<reference>\n" + "\n\n".join(ref_parts) + "\n</reference>")

        # 场景角色 + 遭遇（稳定）
        chars = "\n".join(char_summaries) if char_summaries else "（无）"
        context_parts.append(f"<characters>\n{chars}\n</characters>")
        if self._combat_mode == "tactical":
            encounter_str = self._list_encounters()
            context_parts.append(
                f"<encounters>\n可用的战斗遭遇：{encounter_str}\n"
                f"</encounters>"
            )

        # ── 动态层：场景状态、历史、玩家动作（易变，放后面）──
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

        # 玩家
        player_lines = [f"身份：{identity}"]
        if user_action:
            player_lines.append(f"操作：{user_action}")
        context_parts.append(f"<player>\n" + "\n".join(player_lines) + "\n</player>")

        # 场景动态
        recent = self._scene_log[-8:]
        if recent:
            context_parts.append("<scene_events>\n" + "\n".join(recent) + "\n</scene_events>")

        # 世界书（position=1 → 动态层，紧贴收尾指令利用 recency）
        if wb_after:
            context_parts.append(f"<world_book>\n{wb_after}\n</world_book>")

        # 收尾指令（recency 效应）
        custom_prompt = self._overlay.get_custom_prompt() if self._overlay else None
        if structured:
            context_parts.append("MUST：只输出 JSON 数组，不要其他内容。")
            system_prompt = self._build_system_prompt(word_limit, structured=True,
                                                      custom_prompt=custom_prompt)
        else:
            context_parts.append(
                "请基于以上场景信息继续推进剧情。描写场景和角色的反应，"
                "角色对话用「」标注。保持剧情连贯、自然，结束时留出继续的空间。"
            )
            system_prompt = self._build_system_prompt(word_limit, structured=False,
                                                      custom_prompt=custom_prompt)
        # 末尾重申硬长度约束（对抗长上下文下的 Lost-in-the-Middle）
        context_parts.append(
            f"MUST：本轮所有正文内容（叙述 + 角色台词合计）控制在 {word_limit} 字以内，"
            "宁短勿长，不要为了凑字数堆砌描写。"
        )

        context = "\n\n".join(context_parts)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

    def narrate(self, player_info: dict | None = None, env_context: str = "",
                user_action: str = "", structured: bool = False,
                max_tokens: int | None = None,
                word_limit: int = 500,
                conversation_history: str = "",
                is_first_turn: bool = True,
                thinking: str | None = None) -> tuple[str, dict, dict | None]:
        """生成剧情叙述（非流式）。

        用于需要完整响应后再处理的场景（气泡模式、缓冲模式）。
        以场景叙述者的视角生成连贯的剧情文本，角色对话会自然嵌入叙述中。

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
        )

        _t0 = time.monotonic()
        result = self._llm.chat(messages, stream=False, max_tokens=max_tokens,
                                thinking=thinking)
        logger.info("[TIMING] narrate LLM调用: %.0fms (输出 %d 字符)", (time.monotonic() - _t0) * 1000, len(result.get("content", "")))
        narrative = result.get("content", "")
        usage = result.get("usage")

        # 将叙述记入场景日志
        self._log_event(f"📖 剧情推进: {narrative[:80].replace(chr(10), ' ')}...")

        return narrative, {}, usage

    def narrate_stream(self, player_info: dict | None = None, env_context: str = "",
                       user_action: str = "", structured: bool = False,
                       max_tokens: int | None = None,
                       word_limit: int = 500,
                       conversation_history: str = "",
                       is_first_turn: bool = True,
                       thinking: str | None = None):
        """流式生成剧情叙述 — 生成器，逐 token yield。

        使用线程+队列桥接 LLM 的 on_token 回调和 SSE 生成器，
        使前端能在首个 token 到达时立即显示文字，而非等待完整响应。

        Yields:
            ("token", str): 单个 LLM 输出 token
            ("reasoning", str): 思考推理 token（思考模型）
            ("done", (str, dict, dict|None)): 完成信号
                (narrative, env_updates, usage)
        """
        messages = self._build_narration_messages(
            player_info, env_context,
            user_action=user_action, is_first_turn=is_first_turn,
            conversation_history=conversation_history,
            word_limit=word_limit, structured=structured,
        )

        # 真流式模式
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
                                        max_tokens=max_tokens,
                                        thinking=thinking)
                q.put(("result", result))
            except Exception as e:
                q.put(("error", e))

        thread = threading.Thread(target=_llm_worker, daemon=True)
        thread.start()

        try:
            _t0 = time.monotonic()
            _ttft_logged = False
            accumulated = ""
            while True:
                event_type, data = q.get()
                if event_type == "token":
                    if not _ttft_logged:
                        _ttft_logged = True
                        logger.info("[TIMING] narrate_stream 首token延迟(TTFT): %.0fms", (time.monotonic() - _t0) * 1000)
                    accumulated += data
                    yield ("token", data)
                elif event_type == "reasoning":
                    yield ("reasoning", data)
                elif event_type == "result":
                    narrative = data.get("content", accumulated) if isinstance(data, dict) else accumulated
                    usage = data.get("usage") if isinstance(data, dict) else None
                    logger.info("[TIMING] narrate_stream 总耗时: %.0fms (输出 %d 字符)", (time.monotonic() - _t0) * 1000, len(narrative))
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
