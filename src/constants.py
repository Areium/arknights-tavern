"""
共享常量 — 供 wiki_manager 等模块使用。
"""

# ── 核心章节提取规则 ──
# 每个类别定义一组 (章节名, 段落数) 规则，None 表示取该章节全文。
# 优先级从高到低：先匹配到的先提取。
CORE_SECTIONS: dict[str, list[tuple[str, int | None]]] = {
    "races": [
        ("## 生理特征", 3),
        ("## 角色扮演提示", None),
    ],
    "classes": [
        ("## 战斗定位", 3),
        ("## 子职业一览", 1),
        ("## 角色扮演提示", None),
    ],
    "factions": [
        ("## 组织概述", 2),
    ],
    "items": [
        ("## 物品描述", 3),
        ("## 功能与效果", 2),
    ],
    "locations": [
        ("# 描述", 2),
    ],
    "weather": [
        ("## 天气概述", 2),
        ("## 视觉特征", 2),
    ],
    "enemies": [
        ("## 战斗信息", 3),
        ("## 行为模式", None),
        ("## 外貌描写", 2),
    ],
}

# ── 属性名 → 中文名映射（兼容英文旧格式和中文新格式）──
ATTR_ENG_TO_CN: dict[str, str] = {
    "physical_strength": "物理强度",
    "tactical_planning": "战术规划",
    "emotional_stability": "情绪稳定性",
    "combat_skill": "战斗技巧",
    "originium_arts_assimilation": "源石技艺适应性",
    "charisma": "魅力",
    "physiological_tolerance": "生理耐受",
    "mobility": "战场机动",
    # v4.0 角色文件直接使用中文属性名，中文→中文直通
    "物理强度": "物理强度",
    "战术规划": "战术规划",
    "情绪稳定性": "情绪稳定性",
    "战斗技巧": "战斗技巧",
    "源石技艺适应性": "源石技艺适应性",
    "魅力": "魅力",
    "生理耐受": "生理耐受",
    "战场机动": "战场机动",
}
