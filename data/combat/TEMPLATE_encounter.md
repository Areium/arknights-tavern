---
# ==============================================================================
# 战斗遭遇模板 (Encounter Template)
# ==============================================================================
encounter_id: "enc_template"
name: "遭遇名称"
category: "story"
difficulty: 2
grid_size: 7
deploy_zones:
  player: [[2, 0], [4, 2]]
  enemy: [[2, 3], [5, 6]]
  enemy_random_shift: true
waves:
  - enemies:
      - enemy: "整合运动士兵"
        count: 2
        positions: [[2, 5], [4, 6]]
      - enemy: "整合运动术师"
        count: 1
        positions: [[3, 5]]
conditions:
  max_rounds: 30
  escape_enabled: true
rewards:
  xp: 200
  items: []
  unlock: []
trigger_plot: ""
---
