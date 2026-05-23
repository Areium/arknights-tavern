---
# ==============================================================================
# 世界观文档索引 (World View Index)
# ==============================================================================
# 本文件是世界观文档的中央索引，系统启动时加载此文件建立 id→file 映射。
# 各文档按 category 分时注入到角色 system prompt。
#
# 格式说明：
#   每个条目一个顶级 key（文档 ID），包含：
#     file:     对应详细文件路径（相对于 data/world/）
#     name:     文档中文名
#     category: 注入时机：global / faction / region / event
#     priority: 注入优先级（1-10），数字越大越靠前
#     trigger:  触发条件（category 非 global 时必填）
#     summary:  一句话概述
# ==============================================================================
index:
  01-basic-setting:
    file: "01-basic-setting/index.md"
    name: "泰拉世界基础设定"
    category: global
    priority: 1
    summary: "源石、天灾、矿石病、移动城邦等核心概念"

  # 注：势力、种族详细信息参见 data/factions/ 和 data/races/。
  # 游戏推理规则（buff/debuff 池、失败后果系统）参见 data/rules/。
---
