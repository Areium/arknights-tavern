---
# ==============================================================================
# 敌人模板 (Enemy Template)
# ==============================================================================
# 使用方法：复制此文件，填入具体数据，删除本注释块。
#
# 必填字段：name, class, level, combat_stats, ai_behavior
# 可选字段：alias, race, faction, tags, ai_skills, drop_items, drop_rate, xp_reward
# ==============================================================================
name: "敌人名称"
alias: "enemy_id"
class: "近卫"
race: "未知"
faction: "整合运动"
tags: ["基础敌人"]
level: 1
combat_stats:
  hp: 100
  patk: 10
  matk: 5
  defense: 5
  resist: 4
  spd: 8
  hit: 5
  eva: 4
  max_ap: 3
ai_behavior: "aggressive"
ai_skills:
  - "enemy_atk"
  - "enemy_heavy"
drop_items: []
drop_rate: 0.3
xp_reward: 50
---

# 描述

敌人的基本描述。

## 战斗特点

- 特点1
- 特点2

## 战术建议

应对建议。
