---
encounter_id: "enc_final_showdown"
name: "圣山决战"
summary: "圣山巅的最终决战——山雪鬼队长与冰原狂战士倾巢而出，冰原术师在后方压阵，决定谢拉格命运的一战。"
category: "story"
difficulty: 5
encounter_type: "boss"
recommended_power_tier: "T3"
target_rounds: 4
threat_budget: 12.8
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
    hint: "在圣山之巅与山雪鬼倾力一战，敌人全力迎战。"
    combat:
      enemy_scale: 1.0
      first_strike: false
      player_effects: {}
      reward_mult: 1.3
  - id: negotiate
    label: "最后的交涉"
    hint: "以言辞动摇山雪鬼队长，魅力检定决定能否避免决战。"
    check:
      attr: "魅力"
      dc: 15
    fail_combat:
      enemy_scale: 1.2
      player_effects: {}
      reward_mult: 0.8
    reward_mult: 0.5
  - id: retreat
    label: "撤退"
    hint: "承认失败撤退，放弃最终决战的战利品。"
    avoid: true
    reward_mult: 0.0
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
  max_rounds: 12
  escape_enabled: true
rewards:
  xp: 301
  items: ["源石碎片"]
  unlock: []
trigger_plot: ""
---
