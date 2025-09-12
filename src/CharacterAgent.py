import os

import frontmatter
import yaml


class CharacterAgent:
    def __init__(self, character_name, llm):
        self.character_name = character_name
        self.llm = llm
        self.character = self.load_character(character_name)
        self.memory = []

    def load_character(self, character_name: str, data_path: str = "../data/characters") -> str:
        """
        从文件加载角色设置并构建提示。

        Args:
            character_name (str): 角色名称，对应的文件名（不含扩展名）。

        Returns:
            str: 角色的提示prompt，如果加载失败则返回 None。
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.abspath(os.path.join(base_dir, data_path, f"{character_name}.md"))

        if not os.path.isfile(file_path):
            print(f"⚠️ 警告: 角色文件未找到: {file_path}")
            return None

        print(f"🔍 正在从 '{file_path}' 加载角色文件...")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                character_data = frontmatter.load(f)

            metadata = character_data.metadata
            content = character_data.content
            char_card = yaml.dump(metadata, allow_unicode=True, default_flow_style=False, sort_keys=False)

            print("角色卡内容:", char_card, content)

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

            print(f"✅ 成功加载角色: {character_name}")

            print("profile:", profile)
            return profile

        except Exception as e:
            print(f"❌ 错误: 加载或解析角色文件 {file_path} 失败: {e}")
            return None

    def chat(self, user_input: str) -> str:
        """
        与角色进行对话。

        Args:
            user_input (str): 用户输入的对话内容。

        Returns:
            str: 角色的回复。
        """

        # 构建记忆字符串
        # 历史对话记录
        history_log = "\n".join(
            [f"{'user' if msg['role'] == 'user' else self.character_name}: {msg['content']}" for msg in self.memory]
        )

        memory = f"""

【历史对话记录】:
{history_log}
"""

        # 构建发送给 LLM 的消息列表
        messages = [{"role": "system", "content": self.character + memory},
                    {"role": "user", "content": user_input}]

        # 调用 LLM 生成回复
        response = self.llm.chat(messages)

        # 将当前用户输入添加到记忆中
        self.memory.append({"role": "user", "content": user_input})
        # 将 LLM 的回复添加到记忆中
        self.memory.append({"role": "character", "content": response})

        return response
