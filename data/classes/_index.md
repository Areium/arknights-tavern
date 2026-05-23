---
# ==============================================================================
# 职业索引 (Class Index)
# ==============================================================================
# 本文件是职业体系的中央索引，系统启动时加载此文件建立 name→file 映射。
# 角色卡中的 class 字段值必须与此处某个 key 完全匹配，系统才能解析到详细条目。
#
# 明日方舟职业体系：八大门类，每类下有若干分支（子职业）。
#
# 格式说明：
#   每个条目一个顶级 key，包含：
#     file:         对应详细文件路径（相对于 data/classes/）
#     summary:      一句话概述，用于角色列表等不需要完整详情的场景
#     category:     所属大类
#     combat_role:  战斗中担任的角色
#     damage_type:  主要伤害类型（physical / arts / mixed / healing）
#     attack_range: 典型攻击范围（melee / short / medium / long / global）
#     subclasses:   子职业列表
# ==============================================================================
index:
  术师:
    file: "术师/index.md"
    summary: "远程源石技艺输出核心，对单体或群体造成高额法术伤害"
    category: "输出"
    combat_role: "远程法术输出"
    damage_type: arts
    attack_range: medium
    subclasses: ["中坚术师", "扩散术师", "轰击术师", "阵法术师", "秘术师"]

  近卫:
    file: "近卫/index.md"
    summary: "近战物理输出中坚，拥有多样的战斗风格和生存能力"
    category: "输出"
    combat_role: "近战物理输出"
    damage_type: physical
    attack_range: melee
    subclasses: ["剑豪", "强攻手", "收割者", "武者", "无畏者", "术战者", "领主"]

  狙击:
    file: "狙击/index.md"
    summary: "远程物理输出，优先攻击空中单位和远距离目标"
    category: "输出"
    combat_role: "远程物理输出"
    damage_type: physical
    attack_range: long
    subclasses: ["速射手", "炮手", "重射手", "散射手", "攻城手", "投掷手"]

  重装:
    file: "重装/index.md"
    summary: "前排防御核心，吸收伤害并保护队友，部分具备治疗能力"
    category: "防御"
    combat_role: "前排坦克/治疗"
    damage_type: mixed
    attack_range: melee
    subclasses: ["铁卫", "守护者", "不屈者", "决战者", "哨戒者"]

  先锋:
    file: "先锋/index.md"
    summary: "战场先头部队，快速部署并为后续单位提供部署资源"
    category: "支援"
    combat_role: "费用回复/前线侦查"
    damage_type: physical
    attack_range: melee
    subclasses: ["冲锋手", "尖兵", "情报官", "战术家", "攻城者"]

  医疗:
    file: "医疗/index.md"
    summary: "治疗与支援，为友方单位恢复生命值并解除异常状态"
    category: "治疗"
    combat_role: "治疗/驱散"
    damage_type: healing
    attack_range: medium
    subclasses: ["医师", "群愈师", "疗养师", "行医", "咒愈师", "链愈师"]

  辅助:
    file: "辅助/index.md"
    summary: "多功能支援，提供减速、增益、召唤等战术支持"
    category: "支援"
    combat_role: "控制/增益/召唤"
    damage_type: mixed
    attack_range: medium
    subclasses: ["凝滞师", "削弱者", "召唤师", "吟游者", "工匠", "护佑者"]

  特种:
    file: "特种/index.md"
    summary: "特殊战术单位，以非常规方式影响战局"
    category: "战术"
    combat_role: "特殊战术/位移"
    damage_type: mixed
    attack_range: short
    subclasses: ["处决者", "推击手", "钩索师", "伏击客", "行商", "傀儡师", "炼金师"]

  战术指挥:
    file: "战术指挥/index.md"
    summary: "战术指挥官，提供全局 buff/debuff 支援和远程火力协调，不直接接敌"
    category: "指挥"
    combat_role: "战术指挥/远程支援"
    damage_type: mixed
    attack_range: global
    subclasses: ["战术家", "策略官"]
---
