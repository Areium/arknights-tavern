---
# ==============================================================================
# 游戏推理规则索引 (Game Rules Index)
# ==============================================================================
# 本目录包含游戏机制相关的规则定义，与世界观设定（data/world/）分离。
# 包括 buff/debuff 抽取池、失败后果系统等推理规则。
# ==============================================================================
index:
  rarity-system:
    file: "rarity-system/index.md"
    name: "稀有度分级体系"
    category: rule
    priority: 3
    summary: "统一的六星稀有度分级标准，定义各级别的颜色、力量上限、卡牌公式参数、剧情权重，适用于角色/卡牌/物品/Buff全系统"

  debuff-system:
    file: "debuff-system/index.md"
    name: "负面效果系统"
    category: rule
    priority: 4
    summary: "Debuff池定义、失败后roll点机制、以及对角色状态的影响规则"

  buff-pool:
    file: "buff-pool/index.md"
    name: "Buff & Debuff 抽取池"
    category: rule
    priority: 5
    summary: "六星稀有度体系的Buff/Debuff池、d20抽取规则、以及效果定义"

  deviation-states:
    file: "deviation-states/index.md"
    name: "剧情偏离状态系统"
    category: rule
    priority: 6
    summary: "三种剧情元状态（大纲之内/旁逸斜出/天高海阔）、状态转换规则、逃离主线处理流程"
---
