---
# ==============================================================================
# 势力索引 (Faction Index)
# ==============================================================================
# 本文件是势力数据的中央索引，系统启动时加载此文件建立 name→file 映射。
# 角色卡中的 faction 字段值必须与此处某个 key 完全匹配，系统才能解析到详细条目。
#
# 格式说明：
#   每个条目一个顶级 key，包含：
#     file:       对应详细文件路径（相对于 data/factions/）
#     summary:    一句话概述
#     type:       势力类型：organization / nation / rebellion / cult / mercenary / research
#     scale:      势力规模：global / national / regional / city / small
#     alignment:  立场倾向（用于 AI 快速判断势力行为逻辑）
#     key_characters: 与该势力密切相关的已知角色
# ==============================================================================
index:
  罗德岛:
    file: "罗德岛/index.md"
    summary: "致力于矿石病治疗和感染者权益保护的医药公司，拥有武装力量"
    type: organization
    scale: regional
    alignment: neutral_good
    key_characters: ["阿米娅", "凯尔希", "博士"]

  整合运动:
    file: "整合运动/index.md"
    summary: "感染者激进组织，以暴力手段为感染者争取权益"
    type: rebellion
    scale: national
    alignment: chaotic_neutral
    key_characters: ["塔露拉", "霜星", "梅菲斯特"]

  龙门:
    file: "龙门/index.md"
    summary: "繁荣的移动城邦，商业中心，在各方势力间维持微妙平衡"
    type: nation
    scale: city
    alignment: lawful_neutral
    key_characters: ["陈", "魏彦吾"]

  乌萨斯帝国:
    file: "乌萨斯帝国/index.md"
    summary: "军国主义大国，对感染者实行高压政策，军事力量强大"
    type: nation
    scale: global
    alignment: lawful_evil
    key_characters: ["凛冬", "真理"]

  维多利亚:
    file: "维多利亚/index.md"
    summary: "蒸汽与工业之国，正在经历政治动荡，科技与贵族体制并存"
    type: nation
    scale: global
    alignment: true_neutral
    key_characters: ["推进之王", "风笛"]

  莱茵生命:
    file: "莱茵生命/index.md"
    summary: "大型科技研究机构，在前沿科技和源石应用领域领先"
    type: research
    scale: national
    alignment: true_neutral
    key_characters: ["赫默", "塞雷娅"]
---
