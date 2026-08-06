---
encounter_id: "enc_snow_convoy"
name: "商会车队遇袭"
summary: "喀兰贸易商队在雪道上遭遇山雪鬼武装与雪原爪兽的伏击，博士初次见识谢拉格的武力冲突。"
category: "story"
difficulty: 1
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "山雪鬼"
        count: 3
        positions: [[3, 3], [4, 3], [5, 3]]
      - enemy: "雪原爪兽"
        count: 2
        positions: [[3, 4], [4, 4]]
conditions:
  max_rounds: 30
  escape_enabled: true
rewards:
  xp: 100
  items: ["基础源石碎片"]
  unlock: []
trigger_plot: ""
---
