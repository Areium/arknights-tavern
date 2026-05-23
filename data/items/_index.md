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
    file: "抑制戒指/index.md"
    summary: "阿米娅佩戴的源石技艺抑制装置，用于控制其强大的法术力量"
    category: accessory
    portable: true
    rarity: epic
    related_characters: ["阿米娅"]

  博士的战术终端:
    file: "博士的战术终端/index.md"
    summary: "博士使用的便携式战术指挥设备，连接PRTS系统"
    category: equipment
    portable: true
    rarity: rare
    related_characters: ["博士"]

  罗德岛干员证:
    file: "罗德岛干员证/index.md"
    summary: "罗德岛正式干员的身份证明，集成门禁、通讯和紧急定位功能"
    category: key_item
    portable: true
    rarity: common
    related_characters: []

  源石结晶:
    file: "源石结晶/index.md"
    summary: "泰拉世界的核心能源物质，也是矿石病的病原体"
    category: material
    portable: true
    rarity: common
    related_characters: []

  战术地图:
    file: "战术地图/index.md"
    summary: "标注了行动路线和关键节点的纸质或电子地图"
    category: document
    portable: true
    rarity: common
    related_characters: []

  指挥官护甲:
    file: "指挥官护甲.md"
    summary: "瑕光为博士亲手改装的战术护甲，左肩嵌有临光家族手工徽章"
    category: equipment
    portable: true
    rarity: epic
    related_characters: ["瑕光", "博士"]

  感染者合同数据:
    file: "感染者合同数据.md"
    summary: "焰尾从商业联合会窃取的感染者骑士合同加密数据，揭露商业联合会利用感染者骑士进行源石实验"
    category: document
    portable: true
    rarity: epic
    related_characters: ["焰尾"]

  临光的旧铠甲:
    file: "临光的旧铠甲.md"
    summary: "临光上一届特锦赛夺冠时的骑士铠甲，由瑕光暗中修复保留"
    category: equipment
    portable: false
    rarity: rare
    related_characters: ["临光", "瑕光"]

  托兰的雇佣证明:
    file: "托兰的雇佣证明.md"
    summary: "玛恩纳以一枚旧银币雇佣托兰暗中保护临光姐妹的证据"
    category: document
    portable: true
    rarity: uncommon
    related_characters: ["玛恩纳·临光", "托兰"]

  瑕光工坊外的监视照片:
    file: "瑕光工坊外的监视照片.md"
    summary: "砾在博士不知情时拍摄的无胄盟监视瑕光工坊的证据照片"
    category: document
    portable: true
    rarity: uncommon
    related_characters: ["砾", "瑕光", "白金"]

  商业联合会内部清洗的证据:
    file: "商业联合会内部清洗的证据.md"
    summary: "商业联合会对内部不配合董事进行清洗的计划文件，由玄铁大位秘密保留"
    category: document
    portable: true
    rarity: epic
    related_characters: ["玄铁大位"]

  商业联合会内部会议纪要:
    file: "商业联合会内部会议纪要.md"
    summary: "商业联合会针对临光回归的应对策略会议记录"
    category: document
    portable: true
    rarity: rare
    related_characters: []

  焰尾的感染者合同数据:
    file: "焰尾的感染者合同数据.md"
    summary: "焰尾本人的感染者合同，包含将她的源石结晶用于科研的秘密附加条款"
    category: document
    portable: true
    rarity: epic
    related_characters: ["焰尾"]
---
