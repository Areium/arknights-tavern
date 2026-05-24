---
# ==============================================================================
# 剧情索引 (Plot Index)
# ==============================================================================
# 本文件是剧情节点的中央索引，系统启动时加载此文件建立 id→file 映射。
# 当触发条件满足时，系统查此索引加载对应剧情脚本。
#
# 格式说明：
#   每个条目一个顶级 key（剧情唯一 ID），包含：
#     file:              对应详细文件路径（相对于 data/plots/）
#     name:              剧情中文名
#     category:          剧情类型：main / side / character / random / world
#     priority:          优先级（1-10），同时满足多个剧情时高优先级优先触发
#     trigger_location:  触发地点列表（可选）
#     trigger_character: 触发角色列表（可选）
#     trigger_keywords:  触发关键词列表（可选）
#     prerequisites:     前置剧情 ID 列表（可选）
# ==============================================================================
index:
  near_light:
    file: "near-light/index.md"
    name: "长夜临光"
    category: main
    priority: 9
    trigger_location: ["大骑士领卡瓦莱利亚基"]
    trigger_character: ["瑕光", "临光"]
    trigger_keywords: ["特锦赛", "骑士竞技", "卡西米尔", "感染者骑士"]
---
