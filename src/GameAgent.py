import os
import json
import re
import random
import logging

import frontmatter

from load_llm import ApiLLM
from CharacterAgent import CharacterAgent
from environment_state import EnvironmentState
from registry_manager import RegistryManager
from SceneManager import SceneManager

logger = logging.getLogger(__name__)


class GameAgent:
    """游戏代理，实现角色扮演和环境加载"""

    # 路径常量（基于 __file__ 绝对路径，不依赖 CWD）
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _CHARACTERS_DIR = os.path.join(_ROOT, "data", "characters")
    _ENV_DIR = os.path.join(_ROOT, "environment")

    def __init__(self):
        self.llm = ApiLLM()

        # 层级索引管理器：解析种族/职业/势力/物品引用
        self.registry = RegistryManager()
        self.registry.validate()  # 启动时报告引用断裂

        # 场景角色管理器：支持多角色同场
        self.scene_manager = SceneManager(self.llm, self.registry)

        # 玩家信息管理
        self.player_info = {}
        self.player_loaded = False

        # 环境状态管理
        self.environment = EnvironmentState()
        self.environment.load_default()

        # 对话模式: "system" = 系统操作, "story" = 剧情模式
        self.dialogue_mode = "system"

        # 战斗模式: "narrative" = 叙事驱动(默认), "tactical" = 战术回合制
        self.combat_mode = "narrative"

        # 缓存：字符列表 + 已知地点（避免每次调用都扫描文件系统）
        self._character_list = self._scan_characters()
        self._known_locations = self._scan_locations()

        self.system_prompt = self._build_system_prompt()

    # ── 属性（兼容旧接口，实际委托给 scene_manager）──

    @property
    def current_character_name(self) -> str | None:
        """当前活跃角色名，委托给 SceneManager。"""
        return self.scene_manager.active if self.scene_manager else None

    @current_character_name.setter
    def current_character_name(self, value: str | None):
        """兼容旧代码中直接设值的写法。"""
        if self.scene_manager and value:
            self.scene_manager.active = value

    @property
    def current_character_agent(self) -> CharacterAgent | None:
        """当前活跃角色的 CharacterAgent，委托给 SceneManager。"""
        return self.scene_manager.get_active_agent() if self.scene_manager else None

    @current_character_agent.setter
    def current_character_agent(self, value: CharacterAgent | None):
        """兼容旧代码（SceneManager 接管后此 setter 极少使用）。"""
        pass

    # ── 系统 prompt 构建 ──

    def _build_system_prompt(self) -> str:
        """构建系统提示（不含工具定义，工具操作由前端/API 直调）。"""
        current_status = ""
        scene_chars = self.scene_manager.get_scene_characters() if self.scene_manager else []
        if scene_chars:
            chars_str = "、".join(scene_chars)
            current_status = f"当前场景角色: {chars_str}"
            if self.scene_manager.active:
                current_status += f"\n对话中: {self.scene_manager.active}"
        else:
            current_status = "当前无活跃角色"

        if self.player_loaded:
            current_status += f"\n当前玩家: {self.player_info.get('identity', '博士')}"
        else:
            current_status += "\n玩家信息: 未加载"

        env_info = self.environment.build_context() if hasattr(self, 'environment') else ""
        if env_info:
            current_status += f"\n{env_info}"

        combat_mode_info = ""
        if self.combat_mode == "narrative":
            combat_mode_info = """
## ⚔️ 当前战斗模式：叙事模式（默认）
战斗通过剧情描述和关键判定来推进，不需要管理 HP/SP/回合。
玩家使用 `/combat tactical` 可切换为战术回合制模式。"""
        else:
            combat_mode_info = """
## ⚔️ 当前战斗模式：战术模式
战斗使用 d20 回合制系统，包含 HP/SP/防御 DC/先攻等完整数值结算。
玩家使用 `/combat narrative` 可切换为叙事模式。"""

        return f"""# 明日方舟 游戏代理 (Game Agent)

你是明日方舟文字冒险游戏的**游戏代理**，负责协调游戏中的各种系统。

## 🎯 核心职责

1. **角色管理**: 引导用户选择角色、告知可用角色
2. **玩家管理**: 引导用户设置玩家身份
3. **游戏引导**: 在无角色状态下引导用户开始游戏
4. **战斗管理**: 根据当前战斗模式（叙事/战术）处理战斗场景

## 🎮 可用角色
{', '.join(self._character_list)}

## 🎲 骰子工具
用户可以使用掷骰命令进行 d20 判定：
  /roll         → 掷 d20
  /roll dc15    → 掷 d20，对抗 DC 15
  /roll 3 dc15  → 掷 d20 + 3，对抗 DC 15
  投骰子 / 判定 dc15 → 同上

## 🎁 Buff/Debuff 抽取
用户可以从 Buff/Debuff 池中随机抽取：
  抽buff        → 从 Buff 池抽取（d20 决定稀有度）
  抽debuff      → 从 Debuff 池抽取（d20 决定稀有度）
  抽buff +2     → 带修正抽取（+2 提高稀有度档位）
{combat_mode_info}

## 📊 当前状态
{current_status}

## 🎭 行为准则
- 以友好、专业的游戏代理身份与用户交互
- 帮助用户在明日方舟的世界中获得最佳体验
- 当有活跃角色时，除非用户明确发出系统命令，否则将对话路由给角色代理
- 保持游戏世界的沉浸感和连贯性
- 在叙事战斗模式下：战斗是剧情的延伸——用关键选择和 d20 判定推进冲突，不使用机械的回合制结算
- 在战术战斗模式下：严格遵循 combat-system/index.md 中的回合制规则

请开始你的游戏代理工作！"""

    def load_character(self, character_name: str) -> str:
        """
        加载角色并加入当前场景。

        Args:
            character_name (str): 角色名称，对应的文件名（不含扩展名）。

        Returns:
            str: 加载结果信息。
        """
        ok = self.scene_manager.load_character(character_name)
        if ok:
            self.dialogue_mode = "story"
            return f"成功加载角色: {character_name}"
        return f"错误: 无法加载角色 {character_name}"

    def switch_character(self, character_name: str) -> str:
        """
        快速切换到场景中的另一个角色。

        Args:
            character_name (str): 要切换到的角色名称

        Returns:
            str: 切换结果信息
        """
        if character_name == self.scene_manager.active:
            return f"当前已经在与 {character_name} 对话"

        ok = self.scene_manager.switch_active(character_name)
        if ok:
            self.dialogue_mode = "story"
            return f"已切换到角色: {character_name}"
        else:
            # 不在场景中时，尝试加载
            return self.load_character(character_name)

    def exit_conversation(self) -> str:
        """
        退出对话。

        Returns:
            str: 退出信息
        """
        return "conversation_ended"

    def toggle_mode(self) -> str:
        """切换对话模式：系统模式 ↔ 剧情模式。"""
        if self.dialogue_mode == "system":
            if not self.scene_manager.get_active_agent():
                return "当前没有活跃角色，无法切换到剧情模式"
            self.dialogue_mode = "story"
            chars = "、".join(self.scene_manager.get_scene_characters())
            return f"已切换到剧情模式，当前场景角色：{chars}。按 Tab 返回系统模式。"
        else:
            self.dialogue_mode = "system"
            return "已切换到系统模式。按 Tab 进入剧情模式。"

    def toggle_combat_mode(self) -> str:
        """切换战斗模式：叙事模式 ↔ 战术模式。"""
        if self.combat_mode == "narrative":
            self.combat_mode = "tactical"
            self.system_prompt = self._build_system_prompt()  # 重建系统提示
            return (
                "⚔️ 已切换为**战术模式**。\n\n"
                "战斗将使用完整的 d20 回合制系统：HP、SP、防御 DC、先攻顺序、卡牌消耗。\n"
                "如需回到叙事模式，输入 `/combat narrative`。"
            )
        else:
            self.combat_mode = "narrative"
            self.system_prompt = self._build_system_prompt()
            return (
                "📖 已切换为**叙事模式**。\n\n"
                "战斗将通过剧情描述和关键判定来推进，不需要管理数值。\n"
                "适合只想体验剧情的玩家。如需回到战术模式，输入 `/combat tactical`。"
            )

    # ── 玩家管理工具 ──

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

    # ── Buff/Debuff 抽取池 ──

    # 稀有度映射：d20 结果 → (星级, 稀有度名)
    _RARITY_TABLE = [
        (range(1, 6), 1, "★ 普通"),
        (range(6, 11), 2, "★★ 稀有"),
        (range(11, 15), 3, "★★★ 精良"),
        (range(15, 18), 4, "★★★★ 史诗"),
        (range(18, 20), 5, "★★★★★ 传说"),
        (range(20, 21), 6, "★★★★★★ 神话"),
    ]

    @staticmethod
    def _rarity_for_roll(roll: int) -> tuple[int, str]:
        """根据 d20 结果返回 (星级, 稀有度名)。"""
        for rng, stars, name in GameAgent._RARITY_TABLE:
            if roll in rng:
                return stars, name
        return 1, "★ 普通"

    def _load_pool(self, filename: str) -> dict[int, list[dict]]:
        """解析 buff/debuff 池 markdown 文件，返回 {星级: [条目列表]}。"""
        path = os.path.join(self._ROOT, "data", "rules", "buff-pool", filename)
        pool: dict[int, list[dict]] = {s: [] for s in range(1, 7)}
        if not os.path.isfile(path):
            return pool

        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        # 匹配每个条目块：### ID: 名称 ... 直到下一个 ### 或文件尾
        entries = re.split(r"\n(?=### [A-Z]+-\d+:)", text)
        for block in entries:
            m = re.match(r"### ([A-Z]+-\d+): (.+?)(?:\((.+?)\))?\s*$", block, re.MULTILINE)
            if not m:
                continue
            entry_id = m.group(1).strip()
            name = m.group(2).strip()

            def _extract(key: str) -> str:
                mm = re.search(rf"- \*\*{key}\*\*[:：](.+?)$", block, re.MULTILINE)
                return mm.group(1).strip() if mm else ""

            category = _extract("类别")
            effect = _extract("效果")
            duration = _extract("持续")
            narrative = _extract("叙事")
            if narrative.startswith('"') and narrative.endswith('"'):
                narrative = narrative[1:-1]

            entry = {
                "id": entry_id, "name": name, "category": category,
                "effect": effect, "duration": duration, "narrative": narrative,
            }

            # 判断星级：通过所在章节的 ## 标题
            section_match = re.search(
                r"## ★+(?:★)\s*([^(\n]+?)(?:\s*\([^)]+\))?\s*(?:—.*?)?$",
                block, re.MULTILINE
            )
            # 回退：从整个 block 之前的章节标题推断
            # 简单方法：按 block 在全文中的位置，向前查找最近的 ## ★ 标题
            block_start = text.find(block)
            if block_start > 0:
                before = text[:block_start]
                stars_match = re.findall(r"## (★+)\s*(?:[^(\n]+?)(?:\s*\([^)]*d20: (\d+)-?(\d+)?\))", before)
                if stars_match:
                    last = stars_match[-1]
                    star_count = len(last[0])
                    if star_count in pool:
                        pool[star_count].append(entry)
                    continue

            # 最终回退：从 block 内容中找
            for star_count in range(6, 0, -1):
                stars_str = "★" * star_count
                if stars_str in block[:200]:
                    pool[star_count].append(entry)
                    break

        return pool

    def _draw_from_pool(self, pool_name: str, modifier: int = 0) -> str:
        """从指定池中抽取一个 buff/debuff，返回格式化的结果。"""
        filename = "buffs.md" if pool_name == "buff" else "debuffs.md"
        pool = self._load_pool(filename)

        roll = random.randint(1, 20)
        adjusted = min(20, max(1, roll + modifier))
        stars, rarity_name = self._rarity_for_roll(adjusted)

        if modifier != 0 and adjusted != roll:
            mod_str = f"+{modifier}" if modifier > 0 else str(modifier)
            roll_info = f"d20 = {roll} (修正 {mod_str} → {adjusted})"
        else:
            roll_info = f"d20 = {roll}"

        available = pool.get(stars, [])
        if not available:
            # 降级查找
            for s in range(stars - 1, 0, -1):
                if pool.get(s):
                    available = pool[s]
                    stars = s
                    rarity_name = self._rarity_for_roll(
                        {1: 3, 2: 8, 3: 12, 4: 16, 5: 18, 6: 20}[s]
                    )[1]
                    break

        if not available:
            return f"🎲 {roll_info} → {rarity_name}\n该档位暂无可用条目。"

        entry = random.choice(available)
        lines = [
            f"🎲 {roll_info}",
            f"📦 稀有度：{rarity_name} ({'★' * stars})",
            f"📛 {entry['id']}: {entry['name']}",
            f"📂 类别：{entry['category']}",
            f"📐 效果：{entry['effect']}",
            f"⏱ 持续：{entry['duration']}",
            f"💬 {entry['narrative']}",
        ]
        return "\n".join(lines)

    def draw_buff(self, modifier: int = 0) -> str:
        """抽取一个 Buff。"""
        return self._draw_from_pool("buff", modifier)

    def draw_debuff(self, modifier: int = 0) -> str:
        """抽取一个 Debuff。"""
        return self._draw_from_pool("debuff", modifier)

    @staticmethod
    def _is_draw_request(text: str) -> bool:
        """检测是否为 buff/debuff 抽取请求。"""
        keywords = [
            "抽buff", "抽debuff", "抽取buff", "抽取debuff",
            "抽个buff", "抽个debuff", "抽一个buff", "抽一个debuff",
            "buff池", "debuff池", "抽奖", "抽卡",
            "draw buff", "draw debuff",
        ]
        text_lower = text.lower().strip()
        return any(kw in text_lower for kw in keywords)

    def _handle_draw(self, text: str) -> str:
        """解析抽取请求并执行。支持格式：抽buff / 抽debuff / 抽buff +2。"""
        is_debuff = any(kw in text.lower() for kw in ["debuff", "debuff池"])
        modifier = 0
        mod_match = re.search(r"\+(\d+)", text)
        if mod_match:
            modifier = int(mod_match.group(1))
        mod_match_neg = re.search(r"\-(\d+)", text)
        if mod_match_neg:
            modifier = -int(mod_match_neg.group(1))

        if is_debuff:
            return self.draw_debuff(modifier)
        return self.draw_buff(modifier)

    # ── Roll 点工具 ──

    def roll_d20(self, modifier: int = 0, difficulty: int | None = None) -> str:
        """掷 20 面骰子，返回格式化的结果。

        Args:
            modifier: 属性加成（正值有利，负值不利）
            difficulty: 难度等级（DC），若提供则判定成功/失败

        Returns:
            str: 格式化的掷骰结果
        """
        roll = random.randint(1, 20)
        total = roll + modifier

        parts = [f"🎲 掷出 d20: **{roll}**"]
        if modifier != 0:
            sign = "+" if modifier > 0 else ""
            parts.append(f" (修正 {sign}{modifier})")
        if modifier != 0:
            parts.append(f" = **{total}**")

        if difficulty is not None:
            success = total >= difficulty
            if success:
                parts.append(f"  ✅ 成功 (DC {difficulty})")
            else:
                parts.append(f"  ❌ 失败 (DC {difficulty})")
        elif roll == 20:
            parts.append("  🌟 大成功！")
        elif roll == 1:
            parts.append("  💀 大失败！")

        return "".join(parts)

    @staticmethod
    def _is_roll_request(text: str) -> bool:
        """检测用户输入是否为掷骰请求。"""
        keywords = [
            "/roll", "/r", "roll点", "roll d20", "roll d",
            "投骰子", "掷骰", "掷骰子", "roll一下", "roll 一下",
            "投个骰子", "扔骰子", "丢骰子",
            "判定", "过个判定",
        ]
        text_lower = text.lower().strip()
        return any(kw in text_lower for kw in keywords)

    def _handle_roll(self, text: str) -> str:
        """解析掷骰请求并执行，返回格式化的结果。

        支持格式：
          /roll           → d20
          /roll 3         → d20 + 3
          /roll dc15      → d20 vs DC 15
          /roll 3 dc15    → d20 + 3 vs DC 15
          判定 dc15       → d20 vs DC 15
        """
        modifier = 0
        difficulty = None

        # 提取 DC（难度等级）
        dc_match = re.search(r"dc\s*(\d+)", text, re.IGNORECASE)
        if dc_match:
            difficulty = int(dc_match.group(1))

        # 提取修正值：紧邻 dc 前的数字
        mod_match = re.search(r"(\d+)\s*dc", text, re.IGNORECASE)
        if mod_match:
            modifier = int(mod_match.group(1))
        else:
            # 无 dc 时的独立数字
            cleaned = re.sub(r"dc\s*\d+", "", text, flags=re.IGNORECASE)
            mod_match = re.search(r"(\d+)", cleaned)
            if mod_match:
                modifier = int(mod_match.group(1))

        return self.roll_d20(modifier=modifier, difficulty=difficulty)

    # ── 选项生成 ──

    def generate_options(self) -> list[str] | None:
        """基于当前模式和上下文生成选项。

        剧情模式 → 继续推进剧情 + 对话选项
        系统模式 → 系统操作选项（角色管理、环境设置等）
        """
        if self.dialogue_mode == "story" and self.scene_manager.get_active_agent():
            return self._generate_story_options()
        return self._generate_system_options()

    def _generate_story_options(self) -> list[str] | None:
        """生成剧情模式选项：【继续推进剧情】+ 对话选项。

        对话选项最多 2 条，由 LLM 根据当前场景生成。
        无近期对话时只返回【继续推进剧情】。
        """
        env_context = self.environment.build_context()
        player_identity = self.player_info.get("identity", "博士") if self.player_loaded else "博士"
        active = self.scene_manager.active or ""

        scene_chars = self.scene_manager.get_scene_characters()
        chars_context = f"当前场景角色：{'、'.join(scene_chars)}"

        agent = self.scene_manager.get_active_agent()
        recent = agent.memory.recent_buffer if agent else []
        dialogue_lines = []
        for msg in recent[-4:]:
            speaker = "用户" if msg["role"] == "user" else active
            dialogue_lines.append(f"{speaker}: {msg['content']}")
        dialogue = "\n".join(dialogue_lines)

        # 无近期对话 → 只有继续推进剧情
        if not dialogue_lines:
            return ["继续推进剧情"]

        prompt = f"""根据以下明日方舟角色扮演上下文，从玩家「{player_identity}」的视角，
生成 2 句可以向角色「{active}」说的话。

【当前场景】
{env_context}

{chars_context}
对话中：{active}

{'【近期对话】\n' + dialogue if dialogue else ''}

要求：
1. 选项以「{player_identity}」对「{active}」说话的口吻
2. 自然衔接近期对话
3. 展现不同的意图（问候、追问、转移话题、行动请求等）
4. 口语化、自然

直接输出 JSON 数组，例如：["选项 1", "选项 2"]
不要包含其他文字。"""

        try:
            messages = [{"role": "user", "content": prompt}]
            response = self.llm.chat(messages).strip()
            opts = self._parse_options(response)
            if opts and len(opts) >= 2:
                return ["继续推进剧情"] + opts[:2]
            return ["继续推进剧情"]
        except Exception as e:
            logger.error("选项生成失败: %s", e)
            return ["继续推进剧情"]

    def _generate_system_options(self) -> list[str] | None:
        """生成系统操作选项（系统模式）。"""
        env_context = self.environment.build_context()
        player_identity = self.player_info.get("identity", "博士") if self.player_loaded else "博士"

        status_parts = []
        if self.player_loaded:
            status_parts.append(f"玩家: {self.player_info.get('identity', '博士')}")
        else:
            status_parts.append("玩家未加载")
        status_parts.append(env_context)

        scene_chars = self.scene_manager.get_scene_characters()
        if scene_chars:
            status_parts.append(f"场景中: {'、'.join(scene_chars)}")

        prompt = f"""你正在协助用户进行明日方舟文字冒险游戏。
用户当前处于系统主菜单。

【当前状态】
{' | '.join(p for p in status_parts if p)}

【可用操作】
- 加载角色开始对话（可选角色：{'、'.join(self._character_list)}）
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

    def _scan_characters(self) -> list[str]:
        """扫描 data/characters/ 目录，返回角色名列表。

        支持实体文件夹（{name}/index.md）和传统文件（{name}.md）两种模式。
        """
        chars = []
        if not os.path.isdir(self._CHARACTERS_DIR):
            return chars
        for entry in os.listdir(self._CHARACTERS_DIR):
            entry_path = os.path.join(self._CHARACTERS_DIR, entry)
            # 实体文件夹：目录含 index.md
            if os.path.isdir(entry_path):
                if os.path.isfile(os.path.join(entry_path, "index.md")):
                    chars.append(entry)
            # 传统文件（向后兼容）
            elif entry.endswith(".md"):
                stem = os.path.splitext(entry)[0]
                if stem not in ("_index", "TEMPLATE"):
                    chars.append(stem)
        return chars

    def _scan_locations(self) -> dict[str, str]:
        """扫描 environment/Location/ 目录，构建 {关键词 → 文件名} 映射（仅在 __init__ 调用一次）。

        支持实体文件夹和传统 .md 文件两种模式。
        """
        known = {}
        base = os.path.join(self._ENV_DIR, "Location")
        if not os.path.isdir(base):
            return known
        for root, dirs, files in os.walk(base):
            # 实体文件夹
            for d in dirs:
                d_full = os.path.join(root, d)
                index_md = os.path.join(d_full, "index.md")
                if os.path.isfile(index_md):
                    known[d] = d
                    try:
                        with open(index_md, "r", encoding="utf-8") as fh:
                            meta = frontmatter.load(fh).metadata
                        if meta.get("name"):
                            known[meta["name"]] = d
                        if meta.get("alias"):
                            known[meta["alias"]] = d
                    except Exception:
                        continue
            # 传统 .md 文件（向后兼容）
            for f in files:
                if not f.endswith(".md"):
                    continue
                stem = os.path.splitext(f)[0]
                if stem in ("_index", "TEMPLATE", "index"):
                    continue
                known[stem] = stem
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8") as fh:
                        meta = frontmatter.load(fh).metadata
                    if meta.get("name"):
                        known[meta["name"]] = stem
                    if meta.get("alias"):
                        known[meta["alias"]] = stem
                except Exception:
                    continue
        return known

    def _check_env_keywords(self, text: str) -> bool:
        """从用户输入中检测环境关键词，自动更新环境状态。"""
        move_verbs = ["去", "到", "回", "进入", "来", "前往", "返回"]
        for loc_key, loc_file in self._known_locations.items():
            if loc_key in text:
                for verb in move_verbs:
                    idx = text.find(loc_key)
                    start = max(0, idx - 5)
                    if verb in text[start:idx + len(loc_key)]:
                        self.environment.set_location(loc_file)
                        logger.info("检测到位置变化: →%s", loc_key)
                        return True
                    break
        return False

    def _check_character_load_intent(self, text: str) -> str | None:
        """检测用户输入中的角色加入意图，匹配成功则加载角色并返回提示。

        触发句式：让/叫/把/请/找 [角色名] 来/过来/加入/进来/加入对话
        """
        # 构建角色名查找表：原名 + 中文名（通过 metadata 中的 name 字段）
        name_map = {}
        for cn in self._character_list:
            name_map[cn] = cn
        for cn in self.scene_manager.get_scene_characters():
            agent = self.scene_manager.get_active_agent()
            if agent:
                meta = getattr(agent, 'metadata', {})
                if meta.get('name'):
                    name_map[meta['name']] = cn

        load_patterns = [
            r"(?:让|叫|把|请|找)(.{2,4})(?:来|过来|加入|进来|加入对话)",
            r"(?:将|把)(.{2,4})(?:加入对话|加入场景|叫过来|请过来)",
            r"(.{2,4})(?:加入对话|加入场景|来一下|在吗)",
        ]
        for pattern in load_patterns:
            m = re.search(pattern, text)
            if m:
                target = m.group(1).strip()
                for key, filename in name_map.items():
                    if target in key or key in target:
                        scene_chars = self.scene_manager.get_scene_characters()
                        if filename in scene_chars:
                            return f"{filename} 已经在场景中了。"
                        ok = self.scene_manager.load_character(filename)
                        if ok:
                            self.dialogue_mode = "story"
                            return f"{filename} 来到了场景中。"
        return None

    def run(self, user_input: str, max_turns: int = 10, stream: bool = False) -> str:
        """
        运行游戏代理，处理用户输入。

        Args:
            user_input (str): 用户输入
            max_turns (int): 最大处理轮次，防止无限循环

        Returns:
            str: 最终的回复内容
        """
        # 环境关键词预检测（所有模式下都更新环境）
        self._check_env_keywords(user_input)

        # 角色加载意图检测（所有模式下）
        load_msg = self._check_character_load_intent(user_input)
        if load_msg:
            return load_msg

        # Roll 点检测（所有模式下）
        if self._is_roll_request(user_input):
            return self._handle_roll(user_input)

        # Buff/Debuff 抽取检测（所有模式下）
        if self._is_draw_request(user_input):
            return self._handle_draw(user_input)

        # ── 剧情模式：通过 SceneManager 路由 ──
        if self.dialogue_mode == "story" and self.scene_manager.get_active_agent():
            logger.info("剧情模式 → 场景角色: %s", self.scene_manager.get_scene_characters())
            try:
                player_info = self.player_info if self.player_loaded else None
                env_context = self.environment.build_context()

                if user_input == "__CONTINUE__":
                    narrative, env_updates = self.scene_manager.narrate(
                        player_info, env_context
                    )
                    self.environment.apply_update(env_updates)
                    result = self._refine_response(narrative)
                    if stream:
                        for ch in result:
                            print(ch, end="", flush=True)
                        print()
                    return result
                else:
                    # 用户主动对话 → 路由到角色
                    stream_cb = (lambda t: print(t, end="", flush=True)) if stream else None
                    character_response, env_updates = self.scene_manager.chat(
                        user_input, player_info, env_context, stream_callback=stream_cb
                    )
                    if stream:
                        print()
                    self.environment.apply_update(env_updates)
                    return self._refine_response(character_response)

            except Exception as e:
                logger.error("剧情模式出错: %s", e)
                return "抱歉，剧情处理遇到了一些问题，请稍后再试。"

        # ── 系统模式：单轮 LLM 调用（无需工具循环，工具操作由前端/API 直调）──
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]
        response_text = self.llm.chat(messages, stream=False)
        return self._refine_response(response_text)


    def _refine_response(self, raw_response: str) -> str:
        """清理响应中的工具调用标签。"""
        return re.sub(
            r"<tool_call>.*?</tool_call>", "", raw_response, flags=re.DOTALL
        ).strip()
