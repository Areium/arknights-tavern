---
encounter_id: "enc_festival_eve"
name: "大典前夜冲突"
summary: "雪山大典前夜，圣山脚下的广场陷入混战，山雪鬼成队涌入，冰原战士稳住防线。"
category: "story"
difficulty: 3
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
      - enemy: "冰原战士"
        count: 2
        positions: [[4, 5], [5, 5]]
conditions:
  max_rounds: 8
  escape_enabled: true
rewards:
  xp: 38
  items: ["源石碎片"]
  unlock: []
trigger_plot: ""
---
