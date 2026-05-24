---
encounter_id: "enc_elite_hunt"
name: "精英讨伐"
category: "test"
difficulty: 5
grid_size: 7
deploy_zones:
  player: [[2, 0], [3, 1], [4, 0]]
  enemy: [[1, 6], [3, 5], [5, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "整合运动盾卫"
        count: 2
        positions: [[1, 5], [5, 5]]
      - enemy: "整合运动狙击手"
        count: 1
        positions: [[0, 4]]
  - enemies:
      - enemy: "整合运动术师"
        count: 2
        positions: [[2, 6], [4, 6]]
      - enemy: "整合运动士兵"
        count: 2
        positions: [[1, 4], [5, 4]]
  - enemies:
      - enemy: "整合运动盾卫"
        count: 1
        positions: [[3, 6]]
      - enemy: "整合运动术师"
        count: 1
        positions: [[6, 5]]
      - enemy: "整合运动狙击手"
        count: 1
        positions: [[3, 4]]
conditions:
  max_rounds: 35
  escape_enabled: false
rewards:
  xp: 500
  items: ["精英猎手勋章", "高级源石碎片"]
  unlock: []
trigger_plot: ""
---
