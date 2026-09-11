---
encounter_id: "enc_festival_uprising"
name: "大典事变"
summary: "雪山大典骤然生变，冰原战士与冰原术师封锁会场，山雪鬼队长亲自带队镇压。"
category: "story"
difficulty: 4
encounter_type: "elite"
recommended_power_tier: "T2"
target_rounds: 3
threat_budget: 10.0
balance_version: 1
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "冰原战士"
        count: 3
        positions: [[3, 4], [4, 4], [5, 4]]
      - enemy: "冰原术师"
        count: 2
        positions: [[3, 6], [6, 6]]
      - enemy: "山雪鬼队长"
        count: 1
        positions: [[4, 5]]
conditions:
  max_rounds: 10
  escape_enabled: true
rewards:
  xp: 108
  items: ["源石碎片"]
  unlock: []
trigger_plot: ""
---
