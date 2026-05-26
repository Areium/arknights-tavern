import os
import json
import logging
import re

import frontmatter
import yaml

from memory import VectorMemory

logger = logging.getLogger(__name__)


_WIKI_TOOL = {
    "type": "function",
    "function": {
        "name": "wiki_query",
        "description": (
            "查询明日方舟世界文档库，获取角色、种族、职业、势力、物品、地点、天气、"
            "敌人或剧情设定的详细信息。当对话触及'预加载资料'和'延伸参考'未覆盖的细节时使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "查询关键词：实体名称（如'临光'、'库兰塔'）、文档路径（如'characters/临光'）或简短描述"
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
            embed_fn=self.llm.embed if hasattr(self.llm, "embed") else None,
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
            char_card = yaml.dump(metadata, allow_unicode=True, default_flow_style=False, sort_keys=False)

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
             stream_callback=None) -> tuple[str, dict, dict | None]:
        """
        与角色进行对话。

        Args:
            user_input: 用户输入的对话内容。
            player_info: 玩家信息，注入到角色上下文中。
            environment_context: 当前环境上下文文本，由 GameAgent 传入。
            scene_context: 场景上下文（同场角色、场景动态），由 SceneManager 传入。

        Returns:
            tuple[str, dict, dict|None]: (角色的回复, 环境更新字典, token使用量)。
        """
        memory_context = self.memory.build_context(user_input)

        player_section = ""
        if player_info:
            identity = player_info.get("identity", "博士")
            player_section = f"\n当前玩家身份: {identity}\n"

        # 构建 system prompt 各部分，按三层结构排列
        system_parts = [self.character]

        # ── Identity：Registry 上下文（仅在无预加载时作为 fallback）──
        if not (self._session_context and self._session_context.preloaded):
            if self.registry and self.metadata:
                registry_context = self.registry.build_character_context(
                    self.metadata, self._entity_whitelist)
                if registry_context:
                    system_parts.append(registry_context)

        # ── Situation：当前情境 ──
        if player_section:
            system_parts.append(player_section)
        if environment_context:
            system_parts.append(environment_context)
        if scene_context:
            system_parts.append(scene_context)

        # ── Context：记忆与历史 ──
        system_parts.append(memory_context)

        # ── Reference：参考资料（供按需查阅）──
        if self._session_context and self._session_context.preloaded:
            preloaded_text = self._session_context.format_preloaded()
            if preloaded_text:
                system_parts.append(preloaded_text)
        if self._wiki_manager:
            catalog = self._wiki_manager.format_catalog_summary()
            if catalog:
                system_parts.append(catalog)

        system_content = "\n\n".join(system_parts)

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_input},
        ]

        tools = [_WIKI_TOOL] if self._wiki_manager else None

        # 工具调用循环 (max 3 rounds)
        total_usage = None
        for _round in range(3):
            result = self.llm.chat(messages, stream=False, tools=tools)

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
