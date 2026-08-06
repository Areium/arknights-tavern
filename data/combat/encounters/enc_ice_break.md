---
encounter_id: "enc_ice_break"
name: "破冰巷战"
summary: "三族摊牌前的破冰之战，山雪鬼在街巷中层层堵截，冰原狂战士作为压阵杀器冲出。"
category: "story"
difficulty: 4
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "山雪鬼"
        count: 4
        positions: [[3, 3], [4, 3], [5, 3], [6, 3]]
      - enemy: "冰原狂战士"
        count: 1
        positions: [[4, 5]]
conditions:
  max_rounds: 30
  escape_enabled: true
rewards:
  xp: 300
  items: ["基础源石碎片"]
  unlock: []
trigger_plot: ""
---
