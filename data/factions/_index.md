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

  独立势力:
    file: "独立势力/index.md"
    summary: "不属于任何主要阵营的个体与小型团体，包括雇佣兵、黑市商人、情报贩子"
    type: mercenary
    scale: small
    alignment: true_neutral
    key_characters: ["灰狐"]

  乌萨斯军方:
    file: "乌萨斯军方/index.md"
    summary: "泰拉大陆规模最大的军事力量之一，以严酷纪律和压倒性火力著称"
    type: nation
    scale: global
    alignment: lawful_evil
    key_characters: []

  野生:
    file: "野生/index.md"
    summary: "泰拉荒野中的非智慧生物，包括源石虫、变异野兽等受本能驱动的生物"
    type: organization
    scale: small
    alignment: true_neutral
    key_characters: []

  商业联合会:
    file: "商业联合会/index.md"
    summary: "卡西米尔的实际统治者，通过资本控制骑士竞技、媒体和城市建设"
    type: organization
    scale: national
    alignment: lawful_evil
    key_characters: []

  监证会:
    file: "监证会/index.md"
    summary: "卡西米尔骑士传统的守护者，在资本侵蚀中寻找反击时机"
    type: organization
    scale: national
    alignment: lawful_neutral
    key_characters: ["罗素"]

  无胄盟:
    file: "无胄盟/index.md"
    summary: "商业联合会资助的暗杀组织，执行不能公开的清除任务"
    type: mercenary
    scale: regional
    alignment: neutral_evil
    key_characters: ["白金", "青金罗伊", "青金莫妮克", "玄铁大位"]

  红松骑士团:
    file: "红松骑士团/index.md"
    summary: "由感染者骑士组成的反抗组织，为感染者的生存权利而战"
    type: rebellion
    scale: small
    alignment: chaotic_good
    key_characters: ["焰尾", "灰毫", "野鬃"]

  临光家族:
    file: "临光家族/index.md"
    summary: "没落的骑士贵族，耀骑士的归来点燃了家族复兴的希望"
    type: organization
    scale: small
    alignment: lawful_good
    key_characters: ["临光", "瑕光", "玛恩纳·临光"]

  银枪天马:
    file: "银枪天马/index.md"
    summary: "监证会直属精英骑士团，卡西米尔最后的非商业化武装力量"
    type: organization
    scale: national
    alignment: lawful_neutral
    key_characters: []

  卡西米尔:
    file: "卡西米尔/index.md"
    summary: "以骑士文化闻名的国度，骑士竞技被资本全面渗透"
    type: nation
    scale: global
    alignment: true_neutral
    key_characters: ["罗素"]
---
