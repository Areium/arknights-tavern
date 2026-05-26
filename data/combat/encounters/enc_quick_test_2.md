---
encounter_id: "enc_quick_test_2"
name: "快速测试·第二波"
summary: "战斗测试——第二波：两名整合运动士兵，近战配合。"
category: "test"
difficulty: 1
grid_size: 7
deploy_zones:
  player: [[3, 0], [5, 1]]
  enemy: [[3, 4], [5, 5]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "整合运动士兵"
        count: 2
        positions: [[3, 4], [5, 5]]
conditions:
  max_rounds: 10
  escape_enabled: false
rewards:
  xp: 80
  items: []
  unlock: []
trigger_plot: ""
---
