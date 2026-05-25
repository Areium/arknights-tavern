---
encounter_id: "enc_training"
name: "基础训练"
summary: "战斗遭遇的基础训练方法及要点。"
category: "test"
difficulty: 1
grid_size: 7
deploy_zones:
  player: [[3, 0], [5, 1]]
  enemy: [[3, 5], [5, 5]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "整合运动士兵"
        count: 2
        positions: [[3, 5], [5, 5]]
conditions:
  max_rounds: 20
  escape_enabled: true
rewards:
  xp: 100
  items: ["基础训练勋章"]
  unlock: []
trigger_plot: ""
---
