"""
属性数据加载器：等级→roll修正映射 + 环境DC修正表。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 所有 8 个属性共享同一修正映射（已验证 data/attributes/*/index.md 一致）
LEVEL_MODIFIER_MAP: dict[int, int] = {
    1: -3,
    2: -2,
    3: -1,
    4: -1,
    5: 0,
    6: +1,
    7: +1,
    8: +2,
    9: +3,
    10: +4,
}

# 属性英文 key → 中文名
ATTRIBUTE_EN_TO_CN: dict[str, str] = {
    "physical_strength": "物理强度",
    "mobility": "战场机动",
    "physiological_tolerance": "生理耐受",
    "tactical_planning": "战术规划",
    "combat_skill": "战斗技巧",
    "originium_arts_assimilation": "源石技艺适应性",
    "emotional_stability": "情绪稳定性",
    "charisma": "魅力",
}

# 天气 → 属性 DC 修正（仅列有影响的天气）
WEATHER_DC_MODIFIERS: dict[str, dict[str, int]] = {
    "大雨":     {"战场机动": 1, "生理耐受": 1, "源石技艺适应性": 1},
    "雷暴":     {"战场机动": 2, "生理耐受": 1, "源石技艺适应性": 2, "情绪稳定性": 1},
    "暴风雨":   {"战场机动": 2, "生理耐受": 1, "源石技艺适应性": 1},
    "暴雪":     {"战场机动": 2, "生理耐受": 2, "战术规划": 1},
    "雾":       {"战场机动": 1, "战术规划": 1},
    "浓雾":     {"战场机动": 2, "战术规划": 2},
    "小雪":     {"战场机动": 1, "生理耐受": 1},
    "小雨":     {"战场机动": 0},
    "多云":     {},
    "晴天":     {},
    "沙暴":     {"生理耐受": 2, "战场机动": 2, "战术规划": 1},
}

# 时段 → 属性 DC 修正
TIME_DC_MODIFIERS: dict[str, dict[str, int]] = {
    "夜晚": {"战术规划": 1, "战场机动": -1},
    "深夜": {"战术规划": 2, "战场机动": -2},
    "黄昏": {"战场机动": -1},
    "清晨": {"战术规划": 0},
    "上午": {},
    "下午": {},
}


class AttributeLoader:
    """属性数据加载器。"""

    @staticmethod
    def get_modifier(attribute_name: str, level: int) -> int:
        """返回指定属性等级的 roll 修正值（-3 ~ +4）。"""
        clamped = max(1, min(10, level))
        return LEVEL_MODIFIER_MAP.get(clamped, 0)

    @staticmethod
    def get_env_dc_modifier(
        weather: str, time_of_day: str, attribute: str
    ) -> int:
        """汇总天气 + 时段对该属性的 DC 修正值。

        环境修正影响 DC（目标难度），而非角色掷骰修正。
        """
        total = 0
        for table in [WEATHER_DC_MODIFIERS, TIME_DC_MODIFIERS]:
            for key, modifiers in table.items():
                if key in weather or key in time_of_day:
                    total += modifiers.get(attribute, 0)
        return total

    @staticmethod
    def cn_to_eng(attribute_cn: str) -> str | None:
        """中文属性名 → 英文 key。"""
        for eng, cn in ATTRIBUTE_EN_TO_CN.items():
            if cn == attribute_cn:
                return eng
        return None
