---
encounter_id: "enc_snow_hunt"
name: "圣山猎场"
summary: "圣山圣猎途中，暴风雪中的雪原爪兽群疯狂扑来，冰原猎人在远处放冷箭。"
category: "story"
difficulty: 3
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "雪原爪兽"
        count: 6
        positions: [[3, 3], [4, 3], [5, 3], [6, 3], [4, 4], [5, 4]]
      - enemy: "冰原猎人"
        count: 2
        positions: [[3, 6], [6, 6]]
conditions:
  max_rounds: 30
  escape_enabled: true
rewards:
  xp: 200
  items: ["源石碎片"]
  unlock: []
trigger_plot: ""
---
