import os
import json
import time
import logging
import re

import frontmatter
import yaml

from memory import VectorMemory, resolve_embed_fn

logger = logging.getLogger(__name__)


_WIKI_TOOL = {
    "type": "function",
    "function": {
        "name": "wiki_query",
        "description": (
            "查询当前世界文档库，获取角色、种族、职业、势力、物品、地点、天气、"
            "敌人或剧情设定的详细信息。当对话触及'预加载资料'和'延伸参考'未覆盖的细节时使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "查询关键词：实体名称、文档路径（如'characters/角色名'）或简短描述"
                }
            },
            "required": ["query"]
        }
    }
}


class CharacterAgent:
    def __init__(self, character_name, llm, registry=None, overrides: dict = None,
                 entity_whitelist: dict = None, wiki_manager=None, session_context=None):
        self.character_name = character_name
        self.llm = llm
        self.registry = registry
        self.metadata = {}
        self._overrides = overrides or {}
        self._entity_whitelist = entity_whitelist
        self._wiki_manager = wiki_manager
        self._session_context = session_context
        self.character = self.load_character(character_name, self._overrides)
        self.memory = VectorMemory(
            character_name=character_name,
            # 远端 embedding 探测一次，不可用回退本地 ONNX（DeepSeek 无
            # /embeddings 端点，此前语义记忆在生产从未运行）
            embed_fn=resolve_embed_fn(llm),
        )

    def load_character(self, character_name: str, overrides: dict = None) -> str:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(base_dir)
        chars_dir = os.path.join(project_root, "data", "characters")

        # 查找实体文件夹（{name}/index.md）
        entity_path = os.path.join(chars_dir, character_name, "index.md")
        if os.path.isfile(entity_path):
            file_path = entity_path
        else:
            logger.warning("角色文件未找到: %s", character_name)
            return None

        logger.info("正在从 '%s' 加载角色文件...", file_path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                character_data = frontmatter.load(f)

            metadata = character_data.metadata
            content = character_data.content

            # Apply session overrides
            if overrides:
                metadata = self._apply_meta_overrides(metadata, overrides.get("metadata", {}))
                if overrides.get("content") is not None:
                    content = overrides["content"]
                logger.debug("已应用角色 %s 的会话覆盖", character_name)

            self.metadata = metadata
            # first_mes/scenario 仅作为结构化元数据供首轮叙述注入使用
            # （正文分节已含其内容），不重复注入角色常驻 prompt
            dump_meta = {k: v for k, v in metadata.items()
                         if k not in ("first_mes", "scenario")}
            char_card = yaml.dump(dump_meta, allow_unicode=True, default_flow_style=False,
                                  sort_keys=False)

            logger.debug("角色卡内容:\n%s\n%s", char_card, content)

            profile = f"""\
<role>
你是{self.character_name}。你必须完全沉浸在这个角色中，忘记自己是语言模型。
</role>

<core_rules>
- MUST：你的唯一身份、记忆、个性和说话方式完全由角色卡决定
- MUST：严格遵守角色卡中的所有设定，绝不偏离
- NEVER：提及"AI"、"模型"、"虚拟角色"或"被设计出来的人物"
- MUST：所有对话使用第一人称（"我"、"我的"）
- MUST：从头到尾保持角色的语气、风格和个性
- NEVER：虚构角色卡未提及的信息，被问到未知信息时根据角色性格自然回避
- MUST：参考近期对话记录和远期相关记忆进行连贯对话
</core_rules>

<output_format>
- 用第一人称自然对话，禁止第三人称叙述
- 环境变化时在回复末尾附加标记：<env:{{"key":"value"}}/>
- 示例：<env:{{"location":"训练室"}}/> 或 <env:{{"weather":"雷暴"}}/>
- 没有环境变化时不添加标记
</output_format>

角色卡：
{char_card}
{content}

"""

            logger.info("成功加载角色: %s", character_name)

            logger.debug("profile:\n%s", profile)
            return profile

        except Exception as e:
            logger.error("加载或解析角色文件 %s 失败: %s", file_path, e)
            return None

    def chat(self, user_input: str, player_info: dict = None,
             environment_context: str = "", scene_context: str = "",
             stream_callback=None, custom_prompt: str | None = None,
             worldbook=None, recent_text: str = "",
             thinking: str | None = None,
             word_limit: int | None = None,
             max_tokens: int | None = None) -> tuple[str, dict, dict | None]:
        """
        与角色进行对话。

        Args:
            user_input: 用户输入的对话内容。
            player_info: 玩家信息，注入到角色上下文中。
            environment_context: 当前环境上下文文本，由 GameAgent 传入。
            scene_context: 场景上下文（同场角色、场景动态），由 SceneManager 传入。
            worldbook: WorldBook 实例（可空），触发命中的条目按 position 注入。
            recent_text: 最近的对话文本，供世界书关键词扫描。
            word_limit: 可选，本轮回复期望字数上限。
            max_tokens: 可选，传给 LLM 的 token 硬上限。

        Returns:
            tuple[str, dict, dict|None]: (角色的回复, 环境更新字典, token使用量)。
        """
        _t0 = time.monotonic()
        memory_context = self.memory.build_context(user_input)

        player_section = ""
        identity = "博士"
        if player_info:
            identity = player_info.get("identity", "博士")
            player_section = f"\n当前玩家身份: {identity}\n"
            try:
                from player_profile import load_player_profile
                profile = load_player_profile(identity)
                if profile:
                    player_section += "\n" + profile + "\n"
            except Exception:
                logger.debug("玩家身份档案注入失败: %s", identity)

        # ── 世界书触发匹配（position=0 卡前 / position=1 卡后）──
        is_custom_worldbook = worldbook is not None and getattr(worldbook, "source", "") == "imported"
        wb_before, wb_after = "", ""
        if worldbook is not None:
            try:
                eligible_uids = worldbook.eligible_uids_for(getattr(self._session_context, "overlay", None))
                logger.debug("世界书候选 %s 条（钉入 %d 条）",
                             len(eligible_uids) if eligible_uids is not None else "全量",
                             len(getattr(eligible_uids, "forced_uids", None) or ()))
                matched = worldbook.collect_matches(recent_text, user_input, eligible_uids=eligible_uids)
                wb_before, wb_after = worldbook.format_injection(
                    matched, identity=identity, active_char=self.character_name)
            except Exception:
                logger.exception("世界书注入失败，跳过本次注入")

        # 构建 system prompt，稳定内容在前（利用 API 前缀缓存），易变内容在后（recency 效应）
        system_parts = [self.character]

        # ── 世界书（position=0，紧跟角色卡，稳定层）──
        if wb_before:
            system_parts.append(wb_before)
        # 世界观标注：明确当前生效的世界书，自定义世界书不再跟随方舟默认。
        if worldbook is not None:
            system_parts.append(f"<worldview>\n当前世界观：{worldbook.name}\n</worldview>")

        # ── Identity：Registry 上下文（仅在无预加载时作为 fallback）──
        if not (self._session_context and self._session_context.preloaded):
            if self.registry and self.metadata:
                registry_context = self.registry.build_character_context(
                    self.metadata, self._entity_whitelist)
                if registry_context:
                    system_parts.append(registry_context)

        # ── Knowledge：参考资料（稳定，放前面利用缓存）──
        if self._session_context and self._session_context.preloaded:
            preloaded_text = self._session_context.format_preloaded()
            if preloaded_text:
                system_parts.append(preloaded_text)
        # 内置文档目录只在非自定义世界书下注入，避免把方舟角色/势力/地点
        # 泄漏到用户导入的第三方世界观中。
        if self._wiki_manager and not is_custom_worldbook:
            catalog = self._wiki_manager.format_catalog_summary(
                self._wiki_manager.CHARACTER_CATALOG_CATS
            )
            if catalog:
                system_parts.append(catalog)

        # ── 自定义指令 ──
        if custom_prompt:
            system_parts.append(
                f"<custom_instruction>\n"
                f"此外，请在整个对话过程中始终遵循以下用户自定义指示：\n"
                f"{custom_prompt}\n"
                f"</custom_instruction>"
            )

        # ── 回复长度控制 ──
        if word_limit:
            system_parts.append(
                f"<length_rule>\n"
                f"- MUST：本轮回复控制在 {word_limit} 字以内，只表达当前最必要的反应与台词，"
                "不要超长、不要连续输出大段背景说明。\n"
                f"</length_rule>"
            )

        # ── Situation：当前情境 ──
        if player_section:
            system_parts.append(player_section)
        if environment_context:
            system_parts.append(environment_context)
        if scene_context:
            system_parts.append(scene_context)

        # ── 世界书（position=1，卡后，紧贴记忆上下文利用 recency）──
        if wb_after:
            system_parts.append(wb_after)

        # ── Context：记忆与历史（易变，放最后利用 recency 效应）──
        system_parts.append(memory_context)

        system_content = "\n\n".join(system_parts)

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_input},
        ]

        # 自定义世界书不使用内置 wiki 工具，避免查询结果把方舟设定带回来
        tools = [_WIKI_TOOL] if (self._wiki_manager and not is_custom_worldbook) else None

        # 工具调用循环 (max 3 rounds)
        total_usage = None
        for _round in range(3):
            result = self.llm.chat(messages, stream=False, tools=tools, thinking=thinking,
                                   max_tokens=max_tokens)

            # Accumulate token usage
            call_usage = result.get("usage")
            if call_usage:
                if total_usage is None:
                    total_usage = dict(call_usage)
                else:
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        total_usage[k] = total_usage.get(k, 0) + call_usage.get(k, 0)

            if result.get("type") == "tool_call":
                tool_calls = result.get("tool_calls", [])
                # 追加助手消息（含 tool_calls）
                assistant_msg: dict = {"role": "assistant", "content": result.get("content") or ""}
                tc_list = []
                for tc in tool_calls:
                    tc_list.append({
                        "id": tc.get("id", "wiki_0"),
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)},
                    })
                if tc_list:
                    assistant_msg["tool_calls"] = tc_list
                messages.append(assistant_msg)

                # 执行工具调用
                for tc in tool_calls:
                    if tc["name"] == "wiki_query":
                        query_str = tc["arguments"].get("query", "")
                        logger.info("wiki_query: %s → %s", self.character_name, query_str[:80])
                        wiki_result = self._wiki_manager.query(query_str)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", "wiki_0"),
                            "content": wiki_result,
                        })
                        if self._session_context:
                            self._session_context.add_wiki_result(query_str, wiki_result)
                continue

            # 文本回复
            response_text = result.get("content", "")
            if stream_callback and response_text:
                for ch in response_text:
                    stream_callback(ch)

            env_updates = self._parse_env_markers(response_text)
            clean_response = self._strip_env_markers(response_text)
            logger.info("[TIMING] CharacterAgent.chat %s: 总耗时 %.0fms (LLM调用%d次, 含embedding)",
                        self.character_name, (time.monotonic() - _t0) * 1000, _round + 1)
            self.memory.add(user_input, clean_response)
            return clean_response, env_updates, total_usage

        # 所有轮次都是 tool_call 的极端情况
        return "（抱歉，我暂时无法回答这个问题。）", {}, total_usage

    @staticmethod
    def _apply_meta_overrides(base: dict, overrides: dict) -> dict:
        """深度合并覆盖到基础 metadata。"""
        import copy
        result = copy.deepcopy(base)
        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = CharacterAgent._apply_meta_overrides(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    # ── 环境标记解析 ──

    @staticmethod
    def _parse_env_markers(text: str) -> dict:
        """从回复中提取 <env:.../> 标记。"""
        markers = re.findall(r"<env:(.*?)/>", text, re.DOTALL)
        if not markers:
            return {}
        for raw in markers:
            try:
                return json.loads(raw.strip())
            except json.JSONDecodeError:
                continue
        return {}

    @staticmethod
    def _strip_env_markers(text: str) -> str:
        """从回复中移除 <env:.../> 标记。"""
        return re.sub(r"<env:.*?/>", "", text, flags=re.DOTALL).strip()
