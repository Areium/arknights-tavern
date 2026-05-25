---
encounter_id: "enc_defense"
name: "坚守阵地"
summary: "战斗中的坚守阵地，强调防御与不屈意志。"
category: "test"
difficulty: 4
grid_size: 7
deploy_zones:
  player: [[2, 0], [3, 1], [4, 0], [5, 1]]
  enemy: [[0, 4], [1, 5], [2, 6], [4, 6], [5, 5], [6, 4]]
  enemy_random_shift: true
waves:
  - enemies:
      - enemy: "整合运动盾卫"
        count: 2
        positions: [[1, 5], [5, 5]]
      - enemy: "整合运动士兵"
        count: 2
        positions: [[0, 4], [6, 4]]
  - enemies:
      - enemy: "整合运动术师"
        count: 2
        positions: [[2, 6], [4, 6]]
      - enemy: "整合运动狙击手"
        count: 1
        positions: [[3, 5]]
conditions:
  max_rounds: 30
  escape_enabled: false
rewards:
  xp: 400
  items: ["坚守勋章", "重装凭证"]
  unlock: []
trigger_plot: ""
---
