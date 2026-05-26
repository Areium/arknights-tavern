---
encounter_id: "enc_quick_test_3"
name: "快速测试·第三波"
summary: "战斗测试——第三波：士兵与术师混编，检验法术应对。"
category: "test"
difficulty: 2
grid_size: 7
deploy_zones:
  player: [[3, 0], [5, 1]]
  enemy: [[4, 4], [5, 5]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "整合运动士兵"
        count: 1
        positions: [[4, 4]]
      - enemy: "整合运动术师"
        count: 1
        positions: [[5, 5]]
conditions:
  max_rounds: 12
  escape_enabled: false
rewards:
  xp: 120
  items: []
  unlock: []
trigger_plot: ""
---
