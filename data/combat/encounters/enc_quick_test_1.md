---
encounter_id: "enc_quick_test_1"
name: "快速测试·第一波"
summary: "战斗测试——第一波：单个整合运动士兵，简单快速。"
category: "test"
difficulty: 1
grid_size: 7
deploy_zones:
  player: [[3, 0], [5, 1]]
  enemy: [[4, 5]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "整合运动士兵"
        count: 1
        positions: [[4, 5]]
conditions:
  max_rounds: 10
  escape_enabled: false
rewards:
  xp: 50
  items: []
  unlock: []
trigger_plot: ""
---
