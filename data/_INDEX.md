---
# ==============================================================================
# Data 总索引 (Data Master Index)
# ==============================================================================
# 本文件是 data/ 目录的入口注册表。
# 系统启动时仅加载此文件，然后按需加载各子索引。
#
# 字段说明：
#   index:  子索引文件路径（相对于项目根目录）
#   dir:    详细条目存放目录（相对于项目根目录）
#   ref_by: 哪些其他类别引用了此类别
#   refs:   此类别引用了哪些其他类别（在子索引的条目中具体定义）
#
# 添加新数据类别时，在此注册并创建对应的子 _index.md 即可。
# 详细的使用说明见 data/README.md。
# ==============================================================================
index:
  characters:
    index: "data/characters/_index.md"
    dir: "data/characters/"
    ref_by: ["plots"]
    refs: ["races", "classes", "factions", "items"]

  races:
    index: "data/races/_index.md"
    dir: "data/races/"
    ref_by: ["characters"]
    refs: []

  classes:
    index: "data/classes/_index.md"
    dir: "data/classes/"
    ref_by: ["characters"]
    refs: []

  factions:
    index: "data/factions/_index.md"
    dir: "data/factions/"
    ref_by: ["characters", "plots", "world"]
    refs: []

  items:
    index: "data/items/_index.md"
    dir: "data/items/"
    ref_by: ["characters", "plots", "locations"]
    refs: []

  locations:
    index: "environment/Location/_index.md"
    dir: "environment/Location/"
    ref_by: ["plots", "environment_state"]
    refs: ["items"]

  weather:
    index: "environment/weather/_index.md"
    dir: "environment/weather/"
    ref_by: ["plots", "environment_state"]
    refs: []

  plots:
    index: "data/plots/_index.md"
    dir: "data/plots/"
    ref_by: []
    refs: ["characters", "locations", "weather", "factions", "items"]

  world:
    index: "data/world/_index.md"
    dir: "data/world/"
    ref_by: []
    refs: ["factions"]

  attributes:
    index: "data/attributes/_index.md"
    dir: "data/attributes/"
    ref_by: ["characters"]
    refs: []

  enemies:
    index: "data/enemies/_index.md"
    dir: "data/enemies/"
    ref_by: ["plots"]
    refs: ["races", "factions"]
---
