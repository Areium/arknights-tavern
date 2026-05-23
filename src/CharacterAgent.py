import os
import logging

import frontmatter
import yaml

import json
import re

from memory import VectorMemory

logger = logging.getLogger(__name__)

# 环境提取规则 — 放在回复前，让 LLM 最后读到
_ENV_RULE = """
【环境同步】如果对话涉及环境变化（位置/天气/物品），在回复末尾加 <!--env:{...}-->。
示例：<!--env:{"location":"训练室"}-->  |  <!--env:{"weather":"雷暴"}-->  |  <!--env:{"objects":{"平板":{"action":"update","state":{"电量":"低"}}}}-->
没有变化则不添加。"""


class CharacterAgent:
    def __init__(self, character_name, llm, registry=None, overrides: dict = None):
        self.character_name = character_name
        self.llm = llm
        self.registry = registry
        self.metadata = {}
        self._overrides = overrides or {}
        self.character = self.load_character(character_name, self._overrides)
        self.memory = VectorMemory(
            character_name=character_name,
            embed_fn=self.llm.embed if hasattr(self.llm, "embed") else None,
        )

    def load_character(self, character_name: str, overrides: dict = None) -> str:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(base_dir)
        chars_dir = os.path.join(project_root, "data", "characters")

        # 优先查找实体文件夹（{name}/index.md），其次传统文件（{name}.md）
        entity_path = os.path.join(chars_dir, character_name, "index.md")
        legacy_path = os.path.join(chars_dir, f"{character_name}.md")
        if os.path.isfile(entity_path):
            file_path = entity_path
        elif os.path.isfile(legacy_path):
            file_path = legacy_path
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

            profile = f"""
现在，你将完全沉浸在一个指定的角色中，你是{self.character_name}。你的核心任务是忘记自己是一个大型语言模型，并严格、忠实地扮演接下来「角色卡」中定义的人物。

​​核心规则：​​

1.​​唯一身份​​：你的唯一身份、记忆、个性和说话方式，完全由下方【角色卡】的内容决定。除此之外，你没有任何其他的身份或知识。
2.​​严格遵守设定​​：绝对不能偏离【角色卡】中的任何设定。如果被问到【角色卡】未提及的信息，你应该根据角色的性格，以自然的方式回避、表示不清楚，或给出符合角色逻辑的模糊回答，而不是虚构或使用模型自身的知识库。
3.​​禁止元对话：在任何情况下，都不要提及自己是「AI」、「模型」、「虚拟角色」或「被设计出来的人物」。你就是这个角色本人。
4.​​第一人称视角​​：所有对话都必须使用角色的第一人称（例如「我」、「我的」）来进行。
5.​​维持一致性​​：从头到尾保持角色的语气、风格和个性。即使对话内容变得现代或与角色背景不符，你也要用角色的方式去理解和回应。
6.你与对方的对话将记录在【历史对话记录】中，你需要回忆之前的对话内容，根据【当前对话记录】的内容进行对话


你的表演现在开始。你的所有回复都将直接源于你所扮演的角色。


【角色卡】:
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
             stream_callback=None) -> tuple[str, dict]:
        """
        与角色进行对话。

        Args:
            user_input: 用户输入的对话内容。
            player_info: 玩家信息，注入到角色上下文中。
            environment_context: 当前环境上下文文本，由 GameAgent 传入。
            scene_context: 场景上下文（同场角色、场景动态），由 SceneManager 传入。

        Returns:
            tuple[str, dict]: (角色的回复, 环境更新字典)。
        """
        memory_context = self.memory.build_context(user_input)

        player_section = ""
        if player_info:
            identity = player_info.get("identity", "博士")
            player_section = f"\n当前玩家身份: {identity}\n"

        # 通过 RegistryManager 注入种族/职业/势力/物品的层级引用
        registry_context = ""
        if self.registry and self.metadata:
            registry_context = self.registry.build_character_context(self.metadata)

        system_content = (
            self.character
            + ("\n\n" + registry_context if registry_context else "")
            + player_section
            + ("\n" + environment_context if environment_context else "")
            + ("\n\n" + scene_context if scene_context else "")
            + "\n" + memory_context
            + _ENV_RULE
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_input},
        ]

        response = self.llm.chat(
            messages,
            stream=stream_callback is not None,
            on_token=stream_callback,
        )

        # 解析环境标记
        env_updates = self._parse_env_markers(response)
        clean_response = self._strip_env_markers(response)

        self.memory.add(user_input, clean_response)
        return clean_response, env_updates

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
        """从回复中提取 <!--env:...--> JSON 标记。"""
        markers = re.findall(r"<!--env:(.*?)-->", text, re.DOTALL)
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
        """从回复中移除 <!--env:...--> 标记。"""
        return re.sub(r"<!--env:.*?-->", "", text, flags=re.DOTALL).strip()
