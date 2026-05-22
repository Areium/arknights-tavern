import os
import json
import re
import logging

import frontmatter

from load_llm import LocalLLM, ModelConfig, ApiLLM
from CharacterAgent import CharacterAgent
from environment_state import EnvironmentState

logger = logging.getLogger(__name__)


class GameAgent:
    """游戏代理，实现角色扮演和环境加载"""

    def __init__(self):
        """
        初始化游戏代理。
        """
        self.llm = ApiLLM()

        # 角色管理
        self.character_agents = {}  # 缓存已创建的角色代理
        self.current_character_agent = None  # 当前活跃的角色代理
        self.current_character_name = None  # 当前角色名称

        # 玩家信息管理
        self.player_info = {}  # 存储玩家信息
        self.player_loaded = False  # 玩家信息是否已加载

        # 环境状态管理
        self.environment = EnvironmentState()
        self.environment.load_default()

        available_tools = {
            "load_character": self.load_character,
            "switch_character": self.switch_character,
            "load_player": self.load_player,
            "exit_conversation": self.exit_conversation,
            "set_environment": self.set_environment,
        }

        self.tools = available_tools
        self.system_prompt = self._build_system_prompt()
        self.history = []

    def _build_system_prompt(self) -> str:
        """构建游戏代理的系统提示"""
        tool_definitions = []
        for name, func in self.tools.items():
            if not func.__doc__:
                logger.warning("工具 '%s' 缺少文档字符串 (docstring)，模型可能无法理解其功能。", name)
            tool_definitions.append(
                {
                    "name": name,
                    "description": func.__doc__.strip() if func.__doc__ else "无可用描述",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            param: {"type": "string"} for param in func.__annotations__ if param != "return"
                        },
                        "required": list(func.__annotations__.keys() - {"return"}),
                    },
                }
            )

        character_list = [
            name.replace(".md", "")
            for name in os.listdir("data/characters")
            if name.endswith(".md")
        ]

        current_status = ""
        if self.current_character_name:
            current_status = f"当前活跃角色: {self.current_character_name}"
        else:
            current_status = "当前无活跃角色"

        if self.player_loaded:
            player_identity = self.player_info.get('identity', '博士')
            current_status += f"\n当前玩家: {player_identity}"
        else:
            current_status += "\n玩家信息: 未加载"

        env_info = self.environment.build_context() if hasattr(self, 'environment') else ""
        if env_info:
            current_status += f"\n{env_info}"

        prompt = f"""# 明日方舟 游戏代理 (Game Agent)

你是明日方舟文字冒险游戏的**游戏代理**，负责协调游戏中的各种系统，包括角色管理、故事推进等。

## 🎯 核心职责

### 角色管理
1. **角色切换**: 当用户想要与特定角色对话时，调用相应工具,并且请用中文名称
2. **角色列表**: 当用户想了解可用角色时，提供角色信息
3. **退出对话**: 当用户想要退出当前角色对话时，处理退出逻辑

### 玩家管理
1. **玩家信息**: 当用户想要设置或查看玩家信息时，调用load_player工具
2. **身份设定**: 玩家默认身份为博士
3. **信息整合**: 将玩家信息整合到游戏体验中

### 游戏协调
1. **系统命令识别**: 识别用户的系统级命令（如切换角色、退出等）
2. **游戏引导**: 在游戏代理模式下，引导用户选择角色或使用游戏功能
3. **流程管理**: 管理游戏的开始、进行和结束

## 🛠️ 可用工具
{json.dumps(tool_definitions, indent=2, ensure_ascii=False)}

## 📋 交互规则

1. **角色对话模式**: 当用户选择角色后，后续对话将直接路由给角色代理
2. **系统命令优先**: 识别并处理系统级命令（如切换角色、退出等）
3. **游戏引导**: 在无角色状态下，引导用户选择角色或使用游戏功能

## 🎮 可用角色
{', '.join(character_list)}

## 📊 当前状态
{current_status}

## 🔧 工具调用格式
当你需要调用工具时，请在前后加上<tool_call>，严格按照以下格式回复，不要有任何多余的文字：
<tool_call>
{{"name": "工具名称", "arguments": {{"参数名": "参数值"}}}}
</tool_call>
```

## 🎭 行为准则
- 以友好、专业的游戏代理身份与用户交互
- 帮助用户在明日方舟的世界中获得最佳体验
- 当有活跃角色时，除非用户明确发出系统命令，否则将对话路由给角色代理
- 保持游戏世界的沉浸感和连贯性

请开始你的游戏代理工作！"""
        return prompt

    def load_character(self, character_name: str) -> str:
        """
        加载角色并创建角色代理。

        Args:
            character_name (str): 角色名称，对应的文件名（不含扩展名）。

        Returns:
            str: 加载结果信息。
        """
        try:
            # 检查角色是否已经缓存
            if character_name in self.character_agents:
                logger.info("从缓存切换到角色: %s", character_name)
                self.current_character_agent = self.character_agents[character_name]
                self.current_character_name = character_name
                return f"成功切换到已缓存的角色: {character_name}"

            # 创建新的角色代理
            logger.info("正在创建角色代理: %s", character_name)
            character_agent = CharacterAgent(character_name, self.llm)

            if character_agent.character is None:
                return f"错误: 无法加载角色 {character_name}"

            # 缓存角色代理
            self.character_agents[character_name] = character_agent
            self.current_character_agent = character_agent
            self.current_character_name = character_name

            logger.info("成功加载并缓存角色: %s", character_name)
            return f"成功加载角色: {character_name}"

        except Exception as e:
            logger.error("加载角色 %s 失败: %s", character_name, e)
            return f"错误: 加载角色 {character_name} 失败: {str(e)}"

    def switch_character(self, character_name: str) -> str:
        """
        快速切换到已缓存的角色，如果角色未缓存则自动加载。

        Args:
            character_name (str): 要切换到的角色名称

        Returns:
            str: 切换结果信息
        """
        if character_name == self.current_character_name:
            return f"当前已经是角色 {character_name}，无需切换"

        if character_name in self.character_agents:
            logger.info("快速切换到角色: %s", character_name)
            self.current_character_agent = self.character_agents[character_name]
            self.current_character_name = character_name
            return f"已切换到角色: {character_name}"
        else:
            logger.info("角色 %s 未缓存，正在加载...", character_name)
            return self.load_character(character_name)

    def exit_conversation(self) -> str:
        """
        退出对话。

        Returns:
            str: 退出信息
        """
        return "conversation_ended"

    def load_player(self, identity: str = "博士") -> str:
        """
        加载玩家身份信息。

        Args:
            identity (str): 玩家身份标识。

        Returns:
            str: 加载结果信息。
        """
        self.player_info = {"identity": identity}
        self.player_loaded = True
        return f"成功加载玩家: {identity}"

    def set_environment(self, **kwargs) -> str:
        """
        设置当前环境。
        支持参数:
            location (str): 地点名称
            weather (str): 天气名称
            time (str): 时间段

        Returns:
            str: 设置结果
        """
        changes = []
        if "location" in kwargs:
            self.environment.set_location(kwargs["location"])
            changes.append(f"位置→{self.environment.location}")
        if "weather" in kwargs:
            self.environment.set_weather(kwargs["weather"])
            changes.append(f"天气→{kwargs['weather']}")
        if "time" in kwargs:
            self.environment.time_of_day = kwargs["time"]
            changes.append(f"时段→{kwargs['time']}")
        if changes:
            return f"环境已更新: {'、'.join(changes)}"
        return "未指定任何环境参数"

    def generate_options(self) -> list[str] | None:
        """基于当前上下文生成 3 个对话选项。

        支持两种模式：
        - 有活跃角色 → 从玩家视角生成角色对话选项
        - 无活跃角色 → 从 GameAgent 系统命令视角生成菜单操作选项
        """
        env_context = self.environment.build_context()
        player_identity = self.player_info.get("identity", "博士") if self.player_loaded else "博士"

        if self.current_character_agent:
            recent = self.current_character_agent.memory.recent_buffer
            dialogue_lines = []
            for msg in recent[-6:]:
                speaker = "用户" if msg["role"] == "user" else self.current_character_name
                dialogue_lines.append(f"{speaker}: {msg['content']}")
            dialogue = "\n".join(dialogue_lines)

            prompt = f"""根据以下明日方舟角色扮演上下文，从玩家「{player_identity}」的视角，
生成 3 句可以向角色「{self.current_character_name}」说的话。

【当前场景】
{env_context}

{'【近期对话】\n' + dialogue if dialogue else ''}

要求：
1. 选项以「{player_identity}」对「{self.current_character_name}」说话的口吻
2. 自然衔接近期对话
3. 三个选项展现不同的意图（问候、追问、转移话题、行动请求等）
4. 口语化、自然

直接输出 JSON 数组，例如：["选项 1", "选项 2", "选项 3"]
不要包含其他文字。"""
        else:
            character_list = [
                name.replace(".md", "")
                for name in os.listdir("data/characters")
                if name.endswith(".md")
            ]
            status_parts = []
            if self.player_loaded:
                status_parts.append(f"玩家: {self.player_info.get('identity', '博士')}")
            else:
                status_parts.append("玩家未加载")
            status_parts.append(env_context)

            prompt = f"""你正在协助用户进行明日方舟文字冒险游戏。
当前没有活跃角色，用户处于游戏主菜单。

【当前状态】
{' | '.join(p for p in status_parts if p)}

【可用操作】
- 加载角色开始对话（可选角色：{'、'.join(character_list)}）
- 设置玩家身份
- 查看环境信息
- 查看可用角色列表

根据以上状态，生成 3 个用户可以说的下一步操作选项。
每个选项都必须像是用户自然说出的一句话。
选项间应有不同的意图（选角色、设身份、看环境等）。

直接输出 JSON 数组，例如：["选项 1", "选项 2", "选项 3"]
不要包含其他文字。"""

        try:
            messages = [{"role": "user", "content": prompt}]
            response = self.llm.chat(messages).strip()
            return self._parse_options(response)
        except Exception as e:
            logger.error("选项生成失败: %s", e)
            return None

    @staticmethod
    def _parse_options(text: str) -> list[str] | None:
        """解析 LLM 返回的选项文本，多层回退。"""
        # 1. 提取最外层 [...] 并尝试 json.loads
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                options = json.loads(candidate)
                if isinstance(options, list) and len(options) >= 2 and all(
                    isinstance(o, str) for o in options
                ):
                    return options[:3]
            except json.JSONDecodeError:
                pass

        # 2. 按编号行提取
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        options = []
        for line in lines:
            m = re.match(r"^\d+[.、\)]\s*(.+)", line)
            if m:
                txt = m.group(1).strip().strip("\"'").strip("“”")
                options.append(txt)
        if len(options) >= 2:
            return options[:3]

        return None

    def _check_env_keywords(self, text: str) -> bool:
        """从用户输入中检测环境关键词，自动更新环境状态。"""
        changed = False

        # 位置检测：定向动词 + 已知地点
        base = os.path.join("environment", "Location")
        known_locations = {}
        if os.path.isdir(base):
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if f.endswith(".md"):
                        name = os.path.splitext(f)[0]
                        known_locations[name] = name
                        try:
                            with open(os.path.join(root, f), "r", encoding="utf-8") as fh:
                                meta = frontmatter.load(fh).metadata
                            known_locations[meta.get("name")] = name
                            if meta.get("alias"):
                                known_locations[meta["alias"]] = name
                        except Exception:
                            continue

        move_verbs = ["去", "到", "回", "进入", "来", "前往", "返回"]
        for loc_key, loc_file in known_locations.items():
            if loc_key in text:
                for verb in move_verbs:
                    idx = text.find(loc_key)
                    # 检查地点名前是否有关键词（前后5字符内）
                    start = max(0, idx - 5)
                    context = text[start:idx + len(loc_key)]
                    if verb in context:
                        self.environment.set_location(loc_file)
                        changed = True
                        logger.info("检测到位置变化: →%s", loc_key)
                        break
                if changed:
                    break

        return changed

    def run(self, user_input: str, max_turns: int = 10) -> str:
        """
        运行游戏代理，处理用户输入，支持工具调用和角色对话。

        Args:
            user_input (str): 用户输入
            max_turns (int): 最大处理轮次，防止无限循环

        Returns:
            str: 最终的回复内容
        """
        # 环境关键词预检测（在路由到角色前更新环境）
        self._check_env_keywords(user_input)

        # 如果有活跃角色，让大模型判断是否路由
        if self.current_character_agent:
            should_route = self._should_route_to_character(user_input)
            if should_route:
                logger.info("路由对话给角色: %s", self.current_character_name)
                try:
                    # 传递玩家信息和环境上下文给角色代理
                    player_info = self.player_info if self.player_loaded else None
                    env_context = self.environment.build_context()
                    character_response, env_updates = self.current_character_agent.chat(
                        user_input, player_info, env_context
                    )
                    # 应用环境更新
                    self.environment.apply_update(env_updates)
                    return self._refine_response(character_response)
                except Exception as e:
                    logger.error("角色对话出错: %s", e)
                    return "抱歉，角色遇到了一些问题，请稍后再试。"
            else:
                logger.info("模型判断: 作为系统命令处理")

        # 将用户输入添加到历史记录
        self.history.append({"role": "user", "content": user_input})

        # 构建消息列表：系统提示 + 历史对话
        messages = [
            {"role": "system", "content": self.system_prompt},
        ] + self.history

        for i in range(max_turns):
            logger.debug("--- [游戏代理 - 第 %d 轮] ---", i + 1)

            response_text = self.llm.chat(messages, stream=False)
            logger.debug("模型响应: %s", response_text)

            tool_call_match = re.search(r"<tool_call>(.*?)</tool_call>", response_text, re.DOTALL)

            if tool_call_match:
                logger.debug("检测到工具调用")
                tool_call_str = tool_call_match.group(1).strip()

                try:
                    tool_call = json.loads(tool_call_str)
                    tool_name = tool_call.get("name")
                    tool_args = tool_call.get("arguments", {})

                    if tool_name in self.tools:
                        logger.debug("执行工具: %s，参数: %s", tool_name, tool_args)
                        tool_func = self.tools[tool_name]
                        tool_result = tool_func(**tool_args)
                        messages.append({"role": "assistant", "content": tool_result})
                        logger.debug("工具结果: %s", tool_result)


                        # 处理特殊工具调用
                        if tool_name == "exit_conversation":
                            # 退出对话工具被调用，结束游戏
                            final_response = response_text.replace(tool_call_match.group(0), "").strip()
                            return final_response or "再见！感谢你的陪伴。"


                    else:
                        error_message = f"错误: 尝试调用未知工具 '{tool_name}'"
                        logger.error(error_message)

                except (json.JSONDecodeError, TypeError) as e:
                    error_message = f"错误: 解析工具调用失败: {e}\n原始字符串: {tool_call_str}"
                    logger.error(error_message)

            else:
                # 没有工具调用，直接返回回复
                logger.debug("游戏代理直接回复")
                return self._refine_response(response_text)

        # 如果达到最大轮次，也进行内容整理
        error_msg = "系统提示: 处理过程过于复杂，请重新尝试。"
        return self._refine_response(error_msg)

    def _should_route_to_character(self, user_input: str) -> bool:
        """
        使用大模型判断用户输入是否应路由给角色。

        Args:
            user_input (str): 用户输入

        Returns:
            bool: 如果应路由给角色，返回 True，否则返回 False。
        """
        prompt = f"""# 路由决策

当前有一个活跃的角色扮演对话正在进行中，角色是 {self.current_character_name}。
你需要判断用户的最新输入是针对该角色的，还是一个希望与游戏代理交互的系统命令。

## 用户输入
"{user_input}"

## 你的判断
- 如果输入是针对 **{self.current_character_name}** 的对话内容（例如：打招呼、提问、互动），请只回答 "CHARACTER"。
- 如果输入是希望与 **游戏代理** 交互的系统命令（例如：切换角色、退出游戏、询问游戏规则等），请只回答 "AGENT"。

请严格按照要求，直接给出你的判断，不要包含任何其他文字。"""

        try:
            messages = [{"role": "system", "content": prompt}]
            response = self.llm.chat(messages, stream=False).strip().upper()
            logger.debug("路由决策模型响应: '%s'", response)
            return "CHARACTER" in response
        except Exception as e:
            logger.warning("路由决策失败: %s", e)
            # 失败时，默认为非系统命令，继续与角色对话
            return True

    def _refine_response(self, raw_response: str) -> str:
        """
        使用大模型整理和优化响应内容

        Args:
            raw_response (str): 原始响应内容

        Returns:
            str: 整理后的响应内容
        """
        refine_system_prompt = f"""你是一个内容整理专家，请优化以下角色扮演游戏中的回复内容。

## 🎯 优化目标
1. **移除技术痕迹**: 删除任何工具调用标签、系统提示或元信息
2. **保持角色一致性**: 确保回复完全符合角色的性格和说话风格
3. **提升自然度**: 让对话更自然流畅，增强沉浸感
4. **优化表达**: 改善语言表达，但保持原意不变

## 📋 处理规则
- 如果内容包含工具调用标签，完全移除它们
- 保持角色的第一人称视角
- 确保语言风格与角色设定一致
- 如果内容过于简短，可适当丰富表达
- 如果内容有语法错误，进行修正
- 保持原始情感和语气

## 整理后的内容
请直接输出整理后的内容，不要添加任何说明或注释。"""

        try:
            # 构建整理消息，包含 system 和 user 角色
            refine_messages = [
                {"role": "system", "content": refine_system_prompt},
                {"role": "user", "content": raw_response},
            ]

            # 调用大模型进行内容整理
            refined_response = self.llm.chat(refine_messages)

            return refined_response.strip()

        except Exception as e:
            logger.warning("内容整理失败: %s", e)
            # 如果整理失败，返回原始内容（但移除工具调用标签）
            cleaned_response = re.sub(r"<tool_call>.*?</tool_call>", "", raw_response, flags=re.DOTALL)
            return cleaned_response.strip()
