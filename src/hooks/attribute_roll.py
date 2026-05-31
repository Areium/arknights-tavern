"""
属性检定 Hook：自动检测用户动作 → 掷 d20 → 注入 prompt + 推送前端。
"""

from __future__ import annotations

import logging
import re

from .base import HookContext, NarrativeHook
from services.dice import DiceSystem
from services.attribute_loader import AttributeLoader

logger = logging.getLogger(__name__)

# 动作关键词 → 属性名映射
ACTION_ATTRIBUTE_MAP: dict[str, list[str]] = {
    "物理强度": [
        "推开", "举起", "搬动", "砸", "撞", "破门", "撬开", "掰开",
        "撕裂", "压倒", "制服", "擒拿", "拖", "扛", "冲撞", "击碎",
        "砸开", "猛击", "砸碎", "推倒", "压制", "摔", "扔", "投掷",
        "打破", "撞开", "举起", "搬运", "推开", "拉倒",
    ],
    "战场机动": [
        "闪避", "躲避", "潜入", "潜行", "翻越", "攀爬", "跳下",
        "冲刺", "疾跑", "悄悄", "无声", "翻过", "爬", "跳过",
        "绕后", "伏击", "先手", "翻窗", "跳跃", "翻滚", "侧身",
        "挤过", "钻过", "溜进", "摸进", "潜入",
    ],
    "生理耐受": [
        "忍耐", "承受", "硬抗", "扛住", "坚持", "支撑",
        "强撑", "硬撑", "顶住", "保持清醒", "保持意识",
        "抵抗", "抵御", "免疫", "忍受", "撑住", "扛",
        "抗住", "咬牙", "挺住", "硬接",
    ],
    "战术规划": [
        "分析", "计划", "策略", "指挥", "判断", "推理", "侦查",
        "观察地形", "评估", "预判", "解读", "破解", "部署",
        "调度", "协调", "谋划", "推演", "计算", "侦察",
    ],
    "战斗技巧": [
        "格挡", "招架", "还击", "反击", "瞄准", "狙击",
        "精准", "缴械", "连击", "剑术", "射击", "刺杀",
        "偷袭", "暗杀", "劈砍", "刺击", "射击", "开火",
    ],
    "源石技艺适应性": [
        "施法", "咏唱", "吟唱", "导能", "汇聚", "术式",
        "驱动", "释放源石技艺", "激活法阵", "注入能量",
        "施放", "咏唱", "引导源石", "催动", "激活",
    ],
    "情绪稳定性": [
        "保持冷静", "镇定", "压抑", "控制情绪",
        "面不改色", "不露声色", "稳住心态", "沉住气",
        "克制", "忍住", "不动声色", "冷静",
    ],
    "魅力": [
        "说服", "劝", "谈判", "交涉", "请求", "打动", "鼓舞",
        "激励", "安抚", "套话", "诱导", "迷惑", "忽悠",
        "哄", "骗", "游说", "劝说", "恳求", "争取",
    ],
}

# 动作修饰词 → DC 调整
HARD_MODIFIERS: dict[str, int] = {
    "强行": 3, "极限": 4, "极速": 3, "精准": 2,
    "完美": 3, "绝境": 5, "危急": 2, "拼死": 4,
    "死命": 3, "拼命": 3, "竭尽": 2, "孤注": 4,
}

EASY_ACTIONS: set[str] = {
    "观察", "查看", "阅读", "寻找", "拾起", "捡起",
    "倾听", "闻", "触摸", "闲聊", "询问",
}

DEFAULT_DC = 12
EASY_DC = 8


class AttributeRollHook(NarrativeHook):
    """属性检定 Hook：自动检测动作 → d20 掷骰 → 结果注入。

    优先级设为 50（较早执行，让其他 hook 可以使用检定结果）。
    """

    @property
    def priority(self) -> int:
        return 50

    def __init__(self, attribute_loader: AttributeLoader | None = None):
        self._loader = attribute_loader or AttributeLoader()
        self._last_result: dict | None = None

    # ── 主入口 ──

    def on_before_narration(self, ctx: HookContext) -> list[dict]:
        """分析用户动作，如需检定则执行掷骰并返回 SSE 事件。"""
        self._last_result = None
        if not ctx.user_action:
            return []

        result = self._execute_check(ctx)
        if result is None:
            return []

        self._last_result = result
        return [self._build_sse_event(result, ctx.stream_id)]

    def on_between_phases(self, ctx: HookContext) -> list[dict]:
        """Phase 1 后补充检定：扫描 narrative 中是否触发了新的检定需求。"""
        # 当前版本：不做 Phase 2 补充检定，仅依赖 before_narration 的结果
        return []

    def get_prompt_injection(self, ctx: HookContext) -> str | None:
        """构建注入到 Phase 1 prompt 的系统消息。"""
        if self._last_result is None:
            return None
        return self._build_injection(self._last_result)

    # ── 检定执行 ──

    def _execute_check(self, ctx: HookContext) -> dict | None:
        """完整的检定流程：确定属性 → 计算修正 → 掷 d20 → 记录结果。"""
        session = ctx.session
        overlay = session.overlay if hasattr(session, "overlay") else None
        scene = session.scene_manager if hasattr(session, "scene_manager") else None

        # 1. 确定属性和目标 DC
        attr_name, base_dc, source = self._determine_check(ctx)
        if attr_name is None:
            return None

        # 2. 获取活跃角色及其属性值
        char_name = scene.active if scene else None
        if not char_name:
            return None
        agent = scene._agents.get(char_name) if scene else None
        if not agent or not hasattr(agent, "metadata"):
            return None

        attributes = agent.metadata.get("attributes", {})
        attr_level = attributes.get(attr_name)
        if attr_level is None:
            logger.debug("角色 %s 没有属性 %s", char_name, attr_name)
            return None

        # 3. 计算修正值
        base_mod = self._loader.get_modifier(attr_name, attr_level)
        cond_mod = overlay.get_condition_modifier(char_name, attr_name) if overlay else 0
        total_modifier = base_mod + cond_mod

        # 4. 计算最终 DC
        env = session.environment if hasattr(session, "environment") else None
        weather = env.weather if env else ""
        time_of_day = env.time_of_day if env else ""
        env_mod = self._loader.get_env_dc_modifier(weather, time_of_day, attr_name)
        final_dc = base_dc + env_mod

        # 5. 掷骰
        result = DiceSystem.roll_d20_structured(total_modifier, final_dc)
        result["attribute"] = attr_name
        result["character"] = char_name
        result["source"] = source
        result["base_modifier"] = base_mod
        result["condition_modifier"] = cond_mod
        result["env_modifier"] = env_mod
        result["base_dc"] = base_dc

        # 6. 记录结果
        if overlay:
            overlay.record_check(char_name, result)
            # 严重失败 → 添加负面状态
            if result["success"] is False and result["roll"] <= 5:
                round_num = overlay._data.get("narration_round", 0)
                overlay.add_condition(char_name, {
                    "name": _failure_condition_name(attr_name),
                    "modifier": -1,
                    "applies_to": attr_name,
                    "round": round_num,
                })
            # 大成功 → 移除最严重的负面状态
            if result["roll"] == 20 and result["success"]:
                state = overlay.get_character_state(char_name)
                conds = state.get("conditions", [])
                if conds:
                    worst = min(conds, key=lambda c: c.get("modifier", 0))
                    overlay.remove_condition(char_name, worst["name"])

        logger.info(
            "检定: %s %s d20=%d+%d=%d vs DC%d → %s",
            char_name, attr_name,
            result["roll"], total_modifier, result["total"],
            final_dc, "成功" if result["success"] else "失败",
        )
        return result

    # ── 检定参数确定 ──

    def _determine_check(self, ctx: HookContext) -> tuple[str | None, int, str]:
        """三层优先级确定检定属性和 DC。

        Returns:
            (attribute_name, dc, source) 或 (None, 0, "")
        """
        session = ctx.session
        overlay = session.overlay if hasattr(session, "overlay") else None

        # 层1：剧情节拍 stat_check
        if overlay:
            # 先查当前 beat
            current_beat = overlay.get_current_beat()
            if current_beat and current_beat.get("stat_check"):
                beat_check = current_beat["stat_check"]
                attr, dc = _pick_attribute(beat_check)
                if attr:
                    return (attr, dc, "beat")

            # 再查偏离点 stat_check
            dp_check = overlay.get_stat_check_for_context(ctx.user_action)
            if dp_check:
                attr, dc = _pick_attribute(dp_check)
                if attr:
                    return (attr, dc, "stat_check")

        # 层2：关键词自动检测
        attr, dc = _detect_by_keywords(ctx.user_action)
        if attr:
            return (attr, dc, "keyword")

        return (None, 0, "")

    # ── SSE 与 Prompt 生成 ──

    @staticmethod
    def _build_sse_event(result: dict, stream_id: str) -> dict:
        """构建 attribute_roll SSE 事件。"""
        return {
            "type": "attribute_roll",
            "data": {
                "attribute": result["attribute"],
                "character": result["character"],
                "roll": result["roll"],
                "modifier": result["modifier"],
                "total": result["total"],
                "dc": result["difficulty"],
                "success": result["success"],
                "text": _build_roll_text(result),
                "source": result.get("source", "keyword"),
                "stream_id": stream_id,
            },
        }

    @staticmethod
    def _build_injection(result: dict) -> str:
        """构建注入到 LLM prompt 的系统消息。"""
        return (
            "<system_note>\n"
            + _build_roll_text(result)
            + "\n" + _narrative_guidance(result)
            + "\n</system_note>"
        )


# ── 辅助函数 ──

def _pick_attribute(stat_check: dict) -> tuple[str | None, int]:
    """从 stat_check 字典中选一个属性（取第一个）。"""
    if not stat_check:
        return (None, 0)
    for attr, dc in stat_check.items():
        return (attr, int(dc))
    return (None, 0)


def _detect_by_keywords(user_action: str) -> tuple[str | None, int]:
    """基于关键词匹配检测需要检定的属性和 DC。

    Returns:
        (attribute_name, dc) 或 (None, 0)
    """
    best_attr = None
    best_count = 0

    for attr, keywords in ACTION_ATTRIBUTE_MAP.items():
        count = sum(1 for kw in keywords if kw in user_action)
        if count > best_count:
            best_count = count
            best_attr = attr

    if best_attr is None or best_count == 0:
        return (None, 0)

    # 计算 DC
    dc = _determine_action_dc(user_action)
    return (best_attr, dc)


def _determine_action_dc(user_action: str) -> int:
    """基于动作描述确定 DC。"""
    # 简单动作
    for easy in EASY_ACTIONS:
        if easy in user_action:
            return EASY_DC

    dc = DEFAULT_DC

    # 高难度修饰词
    for modifier, adjustment in HARD_MODIFIERS.items():
        if modifier in user_action:
            dc += adjustment

    return dc


def _failure_condition_name(attr_name: str) -> str:
    """根据属性名生成失败的负面状态名称。"""
    mapping = {
        "物理强度": "肌肉拉伤",
        "战场机动": "扭伤",
        "生理耐受": "轻伤",
        "战术规划": "判断失误",
        "战斗技巧": "失误阴影",
        "源石技艺适应性": "源石反噬",
        "情绪稳定性": "情绪波动",
        "魅力": "威信受损",
    }
    return mapping.get(attr_name, "轻微负面状态")


def _build_roll_text(result: dict) -> str:
    """构建人类可读的检定结果文本。"""
    attr = result["attribute"]
    char = result["character"]
    roll = result["roll"]
    mod = result["modifier"]
    total = result["total"]
    dc = result["difficulty"]
    success = result["success"]

    base_mod = result.get("base_modifier", 0)
    cond_mod = result.get("condition_modifier", 0)
    env_mod = result.get("env_modifier", 0)

    # d20 + 修正 = 总值
    text = f"🎲 {attr}检定 — {char}掷出 {roll}"
    if mod != 0:
        sign = "+" if mod > 0 else ""
        text += f" {sign}{mod}"
    text += f" = {total}"

    # DC 分解
    dc_parts = []
    base_dc = result.get("base_dc", dc)
    if base_dc != dc or env_mod != 0:
        dc_parts.append(f"基础{base_dc}")
    if env_mod > 0:
        dc_parts.append(f"环境+{env_mod}")
    elif env_mod < 0:
        dc_parts.append(f"环境{env_mod}")
    if dc_parts:
        text += f" vs DC {dc}（{' + '.join(dc_parts)}）"
    else:
        text += f" vs DC {dc}"

    # 修正明细
    detail_parts = []
    if base_mod != 0:
        detail_parts.append(f"属性{base_mod:+d}")
    if cond_mod != 0:
        detail_parts.append(f"状态{cond_mod:+d}")
    if detail_parts:
        text += f"  [修正: {', '.join(detail_parts)}]"

    # 结果
    if success is True:
        if roll == 20:
            text += " → 🌟 大成功！"
        elif total - dc <= 2:
            text += " → ✅ 勉强成功"
        else:
            text += " → ✅ 成功"
    elif success is False:
        if roll == 1:
            text += " → 💀 大失败！"
        elif dc - total <= 2:
            text += " → ❌ 惜败"
        else:
            text += " → ❌ 失败"

    return text


def _narrative_guidance(result: dict) -> str:
    """生成给 LLM 的叙述引导。"""
    success = result["success"]
    roll = result["roll"]
    char = result["character"]

    if success is True and roll == 20:
        return f"大成功！请在叙述中体现{char}以超乎预期的方式完美完成了动作，产生额外的正面效果。"
    elif success is True:
        return f"请在叙述中体现{char}成功完成了该动作。"
    elif success is False and roll == 1:
        return f"大失败！请在叙述中体现{char}的动作以最糟糕的方式失败，产生了严重的负面后果。请结合场景推进剧情，不要卡住。"
    elif success is False:
        return f"请在叙述中体现{char}未能完成该动作，但剧情应继续推进（fail-forward），以更复杂的方式展开后续发展。"
    return ""
