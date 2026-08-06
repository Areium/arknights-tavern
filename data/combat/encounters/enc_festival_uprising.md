---
encounter_id: "enc_festival_uprising"
name: "大典事变"
summary: "雪山大典骤然生变，冰原战士与冰原术师封锁会场，山雪鬼队长亲自带队镇压。"
category: "story"
difficulty: 4
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
  max_rounds: 30
  escape_enabled: true
rewards:
  xp: 300
  items: ["基础源石碎片"]
  unlock: []
trigger_plot: ""
---
