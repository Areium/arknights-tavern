---
# ==============================================================================
# 物品索引 (Item Index)
# ==============================================================================
# 本文件是物品百科的中央索引，系统启动时加载此文件建立 name→file 映射。
# 角色卡、场景物品、剧情脚本中的物品名称均可通过此索引解析到详细条目。
#
# 格式说明：
#   每个条目一个顶级 key，包含：
#     file:       对应详细文件路径（相对于 data/items/）
#     summary:    一句话概述
#     category:   物品分类
#                 - "equipment"   → 装备/武器
#                 - "consumable"  → 消耗品/药品
#                 - "key_item"    → 关键剧情物品
#                 - "accessory"   → 饰品/个人物品
#                 - "document"    → 文书/资料
#                 - "material"    → 材料/资源
#     portable:   是否可携带（true / false）
#     rarity:     稀有度：common / uncommon / rare / epic / legendary
#     related_characters: 与该物品密切相关的角色
# ==============================================================================
index:
  抑制戒指:
    file: "抑制戒指.md"
    summary: "阿米娅佩戴的源石技艺抑制装置，用于控制其强大的法术力量"
    category: accessory
    portable: true
    rarity: epic
    related_characters: ["阿米娅"]

  博士的战术终端:
    file: "博士的战术终端.md"
    summary: "博士使用的便携式战术指挥设备，连接PRTS系统"
    category: equipment
    portable: true
    rarity: rare
    related_characters: ["博士"]

  罗德岛干员证:
    file: "罗德岛干员证.md"
    summary: "罗德岛正式干员的身份证明，集成门禁、通讯和紧急定位功能"
    category: key_item
    portable: true
    rarity: common
    related_characters: []

  源石结晶:
    file: "源石结晶.md"
    summary: "泰拉世界的核心能源物质，也是矿石病的病原体"
    category: material
    portable: true
    rarity: common
    related_characters: []

  战术地图:
    file: "战术地图.md"
    summary: "标注了行动路线和关键节点的纸质或电子地图"
    category: document
    portable: true
    rarity: common
    related_characters: []
---
