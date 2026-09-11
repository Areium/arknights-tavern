---
encounter_id: "enc_snow_ambush"
name: "矿道伏击"
summary: "博士与银灰一行在追击刺客追入的旧矿道上遭遇山雪鬼主力与冰原猎人的交叉伏击。"
category: "story"
difficulty: 2
encounter_type: "normal"
recommended_power_tier: "T1"
target_rounds: 3
threat_budget: 6.4
balance_version: 1
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
waves:
  - enemies:
      - enemy: "山雪鬼"
        count: 2
        positions: [[3, 3], [4, 3]]
      - enemy: "冰原猎人"
        count: 2
        positions: [[3, 5], [5, 5]]
conditions:
  max_rounds: 8
  escape_enabled: true
rewards:
  xp: 38
  items: ["源石碎片"]
  unlock: []
trigger_plot: ""
---
