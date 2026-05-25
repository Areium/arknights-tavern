---
encounter_id: "enc_mixed_assault"
name: "混编突击"
summary: "混编突击：多兵种协同实施快速突袭的作战方式。"
category: "test"
difficulty: 3
grid_size: 7
deploy_zones:
  player: [[2, 0], [4, 1], [6, 0]]
  enemy: [[1, 4], [3, 5], [5, 4]]
  enemy_random_shift: true
waves:
  - enemies:
      - enemy: "整合运动士兵"
        count: 2
        positions: [[1, 4], [3, 5]]
      - enemy: "整合运动狙击手"
        count: 1
        positions: [[5, 4]]
  - enemies:
      - enemy: "整合运动术师"
        count: 2
        positions: [[2, 5], [4, 5]]
      - enemy: "整合运动士兵"
        count: 1
        positions: [[6, 4]]
conditions:
  max_rounds: 25
  escape_enabled: true
rewards:
  xp: 300
  items: ["战术徽记"]
  unlock: []
trigger_plot: ""
---
