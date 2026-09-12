---
encounter_id: "enc_snow_convoy"
name: "商会车队遇袭"
summary: "喀兰贸易商队在雪道上遭遇山雪鬼武装与雪原爪兽的伏击，博士初次见识谢拉格的武力冲突。"
category: "story"
difficulty: 1
encounter_type: "teaching"
recommended_power_tier: "T0"
target_rounds: 2
threat_budget: 2.6
balance_version: 1
grid_size: 7
background: "snow_mountain"
deploy_zones:
  player: [[0, 0], [2, 2]]
  enemy: [[3, 3], [6, 6]]
  enemy_random_shift: false
approaches:
  - id: assault
    label: "正面强攻"
    hint: "以绝对火力压制车队伏击者，敌人不会增援，但会全力迎战。"
    combat:
      enemy_scale: 1.0
      first_strike: false
      player_effects: {}
      reward_mult: 1.2
  - id: ambush
    label: "雪坡突袭"
    hint: "抢占雪坡制高点先手突击，减少敌人数；若被察觉将陷入苦战。"
    combat:
      enemy_scale: 0.8
      first_strike: true
      player_effects: {}
      reward_mult: 1.0
  - id: negotiate
    label: "尝试交涉"
    hint: "以交涉化解冲突，魅力检定决定成败。"
    check:
      attr: "魅力"
      dc: 12
    fail_combat:
      enemy_scale: 1.2
      player_effects:
        博士:
          hp_penalty: 0.1
      reward_mult: 0.7
    reward_mult: 0.5
  - id: retreat
    label: "撤退"
    hint: "保全队伍撤退，放弃本次战利品。"
    avoid: true
    reward_mult: 0.0
waves:
  - enemies:
      - enemy: "山雪鬼"
        count: 1
        positions: [[3, 3]]
      - enemy: "雪原爪兽"
        count: 1
        positions: [[3, 4]]
conditions:
  max_rounds: 6
  escape_enabled: true
rewards:
  xp: 16
  items: ["源石碎片"]
  unlock: []
trigger_plot: ""
---
