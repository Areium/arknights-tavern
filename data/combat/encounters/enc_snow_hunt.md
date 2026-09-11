---
encounter_id: "enc_snow_hunt"
name: "圣山猎场"
summary: "圣山圣猎途中，暴风雪中的雪原爪兽群疯狂扑来，冰原猎人在远处放冷箭。"
category: "story"
difficulty: 3
encounter_type: "normal"
recommended_power_tier: "T1"
target_rounds: 3
threat_budget: 6.2
balance_version: 1
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "雪原爪兽"
        count: 3
        positions: [[3, 3], [4, 3], [5, 3]]
      - enemy: "冰原猎人"
        count: 2
        positions: [[3, 6], [6, 6]]
conditions:
  max_rounds: 8
  escape_enabled: true
rewards:
  xp: 38
  items: ["源石碎片"]
  unlock: []
trigger_plot: ""
---
