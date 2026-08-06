---
encounter_id: "enc_final_showdown"
name: "圣山决战"
summary: "圣山巅的最终决战——山雪鬼队长与冰原狂战士倾巢而出，冰原术师在后方压阵，决定谢拉格命运的一战。"
category: "story"
difficulty: 5
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "山雪鬼队长"
        count: 2
        positions: [[3, 4], [6, 4]]
      - enemy: "冰原狂战士"
        count: 2
        positions: [[4, 5], [5, 5]]
      - enemy: "冰原术师"
        count: 2
        positions: [[3, 6], [6, 6]]
conditions:
  max_rounds: 30
  escape_enabled: true
rewards:
  xp: 500
  items: ["基础源石碎片"]
  unlock: []
trigger_plot: ""
---
