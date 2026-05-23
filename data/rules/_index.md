---
# ==============================================================================
# 游戏推理规则索引 (Game Rules Index)
# ==============================================================================
# 本目录包含游戏机制相关的规则定义，与世界观设定（data/world/）分离。
# 包括 buff/debuff 抽取池、失败后果系统等推理规则。
# ==============================================================================
index:
  04-debuff-system:
    file: "04-debuff-system/index.md"
    name: "负面效果系统"
    category: rule
    priority: 4
    summary: "Debuff池定义、失败后roll点机制、以及对角色状态的影响规则"

  05-buff-pool:
    file: "05-buff-pool/index.md"
    name: "Buff & Debuff 抽取池"
    category: rule
    priority: 5
    summary: "六星稀有度体系的Buff/Debuff池、d20抽取规则、以及效果定义"

  06-deviation-states:
    file: "06-deviation-states/index.md"
    name: "剧情偏离状态系统"
    category: rule
    priority: 6
    summary: "三种剧情元状态（大纲之内/旁逸斜出/天高海阔）、状态转换规则、逃离主线处理流程"
---
