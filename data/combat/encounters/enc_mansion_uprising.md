---
encounter_id: "enc_mansion_uprising"
name: "希瓦艾什家宴事变"
summary: "希瓦艾什庄园家宴上爆发冲突，冰原战士与冰原术师破门而入，山雪鬼趁乱突袭。"
category: "story"
difficulty: 3
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "冰原战士"
        count: 2
        positions: [[4, 4], [5, 4]]
      - enemy: "冰原术师"
        count: 2
        positions: [[3, 6], [6, 6]]
      - enemy: "山雪鬼"
        count: 2
        positions: [[3, 3], [6, 3]]
conditions:
  max_rounds: 30
  escape_enabled: true
rewards:
  xp: 200
  items: ["源石碎片"]
  unlock: []
trigger_plot: ""
---
