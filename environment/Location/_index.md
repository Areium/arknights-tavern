---
# ==============================================================================
# 地点索引 (Location Index)
# ==============================================================================
# 本文件是地点/场景数据的中央索引，系统启动时加载此文件建立 name→file 映射。
# EnvironmentState 使用此索引解析地点引用。
# 剧情脚本中的 trigger_location 字段通过此索引解析到地点文件。
#
# 地点文件按区域分子目录管理（如 Rhode_Island/、Lungmen/）。
#
# 格式说明：
#   每个条目一个顶级 key（中文名），包含：
#     file:    对应详细文件路径（相对于 environment/Location/）
#     region:  所属区域
#     summary: 一句话概述
#     tags:    地点标签，用于关键词匹配和分类
# ==============================================================================
index:
  控制中枢:
    file: "Rhode_Island/Control_Center/index.md"
    region: "罗德岛"
    summary: "罗德岛舰船的神经中枢，全息投影和战术数据屏环绕的战略指挥中心"
    tags: ["罗德岛", "指挥", "舰桥"]

  宿舍:
    file: "Rhode_Island/Dormitories/index.md"
    region: "罗德岛"
    summary: "干员们日常休息和生活的私人空间，温馨而放松"
    tags: ["罗德岛", "生活区", "休息"]

  制造站:
    file: "Rhode_Island/Manufacturing_Station/index.md"
    region: "罗德岛"
    summary: "罗德岛的工业制造中心，生产作战物资和药品"
    tags: ["罗德岛", "生产", "工业"]

  医疗部:
    file: "Rhode_Island/Medical_Department/index.md"
    region: "罗德岛"
    summary: "罗德岛的医疗核心，矿石病研究和干员治疗的主要场所"
    tags: ["罗德岛", "医疗", "后勤"]

  训练室:
    file: "Rhode_Island/Training Room/index.md"
    region: "罗德岛"
    summary: "干员们进行战斗训练和模拟演习的场所"
    tags: ["罗德岛", "训练", "战斗"]

  会客室:
    file: "Rhode_Island/Reception_Room/index.md"
    region: "罗德岛"
    summary: "罗德岛接待访客和进行外交会谈的正式场所"
    tags: ["罗德岛", "外交", "接待"]
---
