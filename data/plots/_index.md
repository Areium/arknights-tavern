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
  # 示例剧情条目（实际使用时取消注释并替换）
  # chernobog_rescue:
  #   file: "chernobog_rescue.md"
  #   name: "切尔诺伯格救援"
  #   category: main
  #   priority: 10
  #   trigger_location: ["控制中枢"]
  #   trigger_character: ["阿米娅"]
  #   trigger_keywords: ["切尔诺伯格", "救援"]
  #   prerequisites: []
---
