---
# ==============================================================================
# 天气索引 (Weather Index)
# ==============================================================================
# 本文件是天气数据的中央索引，系统启动时加载此文件建立 name→file 映射。
# EnvironmentState 使用此索引解析天气引用。
# 剧情脚本中的 trigger_weather 字段通过此索引解析到天气文件。
#
# 格式说明：
#   每个条目一个顶级 key（中文名），包含：
#     file:     对应详细文件路径（相对于 environment/weather/）
#     summary:  一句话概述
#     category: 天气大类：clear / precipitation / overcast / atmospheric / severe_weather
#     intensity: 强度等级：light / normal / heavy / extreme
#     icon:     显示图标（emoji）
# ==============================================================================
index:
  晴天:
    file: "sunny.md"
    summary: "万里无云，阳光明媚，视野开阔，心情愉悦"
    category: clear
    intensity: normal
    icon: "☀️"

  多云:
    file: "cloudy.md"
    summary: "云层遮蔽天空，光线柔和，偶有阳光穿透云隙"
    category: overcast
    intensity: normal
    icon: "⛅"

  小雨:
    file: "light_rain.md"
    summary: "细细的雨丝飘落，空气中弥漫着湿润的泥土气息"
    category: precipitation
    intensity: light
    icon: "🌧️"

  大雨:
    file: "heavy_rain.md"
    summary: "倾盆大雨，视野受限，道路泥泞，行动受阻"
    category: precipitation
    intensity: heavy
    icon: "🌧️"

  雷暴:
    file: "thunderstorm.md"
    summary: "狂风暴雨，雷电交加，视野和移动受限，极度危险"
    category: severe_weather
    intensity: extreme
    icon: "⛈️"

  雪:
    file: "snow.md"
    summary: "白雪纷飞，世界银装素裹，行动痕迹容易被掩盖"
    category: precipitation
    intensity: normal
    icon: "❄️"

  雾:
    file: "fog.md"
    summary: "浓雾弥漫，能见度极低，适合潜行但也容易迷失方向"
    category: atmospheric
    intensity: normal
    icon: "🌫️"
---
