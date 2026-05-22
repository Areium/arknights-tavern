---
# ==============================================================================
# 属性索引 (Attribute Index)
# ==============================================================================
# 本文件是属性体系的中央索引，系统启动时加载此文件建立 name→file 映射。
# 角色卡中的 attributes 字典（如 {strength: 7, intelligence: 5}）通过此索引
# 解析到对应属性文件和等级描述。
#
# 格式说明：
#   每个条目一个顶级 key（中文名），包含：
#     file:    对应详细文件路径（相对于 data/attributes/）
#     eng:     英文标识，与角色卡 attributes 字典的 key 一致
#     summary: 一句话概述
#     related_classes: 该属性重要的职业
# ==============================================================================
index:
  力量:
    file: "力量.md"
    eng: strength
    summary: "物理力量、近战威力、负重能力"
    related_classes: ["近卫", "重装", "先锋"]

  智力:
    file: "智力.md"
    eng: intelligence
    summary: "知识储备、分析能力、策略思维"
    related_classes: ["术师", "辅助", "医疗"]

  情绪稳定性:
    file: "情绪稳定性.md"
    eng: emotional_stability
    summary: "抗压能力、情绪控制、精神韧性"
    related_classes: ["重装", "医疗", "术师"]

  战斗技巧:
    file: "战斗技巧.md"
    eng: combat_skill
    summary: "武器掌握、格斗技术、实战经验"
    related_classes: ["近卫", "狙击", "特种"]

  源石技艺:
    file: "源石技艺.md"
    eng: originium_arts
    summary: "源石亲和度、法术威力、施法控制力"
    related_classes: ["术师", "医疗", "辅助"]

  魅力:
    file: "魅力.md"
    eng: charisma
    summary: "领导力、说服力、社交影响力"
    related_classes: ["辅助", "先锋"]

  耐力:
    file: "耐力.md"
    eng: endurance
    summary: "体力续航、抗打击能力、持久作战能力"
    related_classes: ["重装", "近卫", "先锋"]

  敏捷:
    file: "敏捷.md"
    eng: agility
    summary: "速度、灵活性、反应能力、协调性"
    related_classes: ["特种", "狙击", "先锋"]
---
