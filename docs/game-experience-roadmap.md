# 游戏体验优化路线图（Gap 分析与优先级）

> 面向目标：结合剧情完整流程，全面优化游戏体验（世界书/角色导入、角色与数值成长、战斗数值/难度/卡组、UI/动作/音效/背景、战斗×剧情结合、LLM 剧情自由开放型）。
> 参考：博德之门3（选择后果/检定）、杀戮尖塔（卡组构建）、SillyTavern（世界书）、AI Dungeon（开放叙事）。
> 本文档以「现状证据 + 目标态 + 优先级」的形式记录，随实现逐轮更新。

---

## 现状速览（2026-08 审计结论）

| 目标域 | 现状 | 缺口 |
|---|---|---|
| 世界书 / 角色导入 | ✅ 酒馆 Lorebook 兼容（4 源解析/触发/回灌，world_book.py）；✅ 角色卡 + Spine 导入（tools/import_spine.py） | 导入 onboarding 略繁琐 |
| 角色与数值成长 | ✅ 战斗奖励结算 + XP→等级→属性+1 + 掉落物品 + 战斗历史（combat.py:_settle_combat_rewards） | 成长不可见（无角色成长面板）；属性→战斗数值反馈不直观 |
| 战斗数值/难度/卡组 | ✅ 9 职业 × 8 卡组；✅ 数值公式（entity.py）；✅ 敌人意图 + SPD 行动顺序（本轮已落地） | 卡牌效果多为文案（状态效果未实装）；difficulty/level 未消费（无难度曲线）；max_rounds/escape 未消费；卡组无跨场成长 |
| UI/动作/音效/背景 | ✅ 3D 网格 + Spine 动画 + 音效 + 战斗背景 + 伤害数字/粒子 | 敌人意图头顶图标（暂为面板文字版） |
| 战斗×剧情结合 | ✅ LLM 触发战斗 + 结果写回 + 战后自动叙述 + 奖励结算；✅ 战前打法 + 剧情投点 + 战前简报流（剧情模式全闭环已落地） | 简报采用现有长叙述（brief_mode 短简报可后续精化） |
| LLM 剧情自由开放 | ✅ 两阶段叙述 + 选项 + 回退 + 变体 + 世界书注入 + 向量记忆 | 玩家选择的机制化后果（投点/失败向前）不足 |

---

## 优先级路线（对齐 docs/combat-core-design.md 的 Phase 划分）

### P0 · 已落地（本轮 feat/combat-intent-spd）
- 敌人意图（ROUND_START 计算，attack/heavy/aoe/move/defend，含目标 + 伤害估算）。
- 敌人按 SPD 降序行动；ai_behavior=defensive 的敌人离队坚守、aggressive 的追击。
- 意图通过 state.enemy_intents + round_start SSE 事件暴露；前端敌方面板显示「意图」行。

### P0.5 · 已落地（本轮 feat/combat-approaches）
- 战前打法（Approach）：encounters 新增 approaches（强攻/突袭/谈判/撤退）；src/combat_approaches.py 提供 resolve_approach（映射 enemy_scale/first_strike/player_effects/reward_mult）+ roll_check（d20 剧情投点，取小队最高属性，自然 20 必成 / 自然 1 必败）+ 兜底打法。
- CombatSession.start() 消费 enemy_scale / first_strike / reward_mult；/combat/start 支持 approach_id（combat/check/avoid 三态）；/combat/complete 应用 reward_mult。
- 修复 bug：同名敌人 count>1 共享 unit_id 互相覆盖（现在生成唯一 unit_id，遭遇战敌人数恢复为设计值，难度曲线修正）。
- 前端手动开战路径：打法卡片 + d20 检定结果 + 撤退提示（CombatView）。

### P1 · 战斗×剧情闭环 + 自由开放
1. ✅ 战前打法 + resolve_approach + roll_check + 战前简报流（feat/combat-approaches + feat/combat-briefing）：剧情模式标记提取后发 combat_briefing 事件（含打法列表），ChatPanel 弹简报面板选打法，不再自动开战。
2. ✅ 剧情投点（d20）：成功避免战斗 / 失败以 fail_combat 参数开战。
3. 敌人意图头顶图标：把面板文字版升级为 PixiJS 头顶图标（PixiCombatScene）。

### P2 · 战斗深度 + 难度曲线 + 卡组
4. 状态效果运行时：✅ 护盾/减速/束缚/虚弱/增幅 已实装（feat/status-effects：CombatUnit.status + Card.effects + play_card 施加 + 护盾吸伤 + 减速/束缚影响移动 + 虚弱/增幅 ±25% 伤害，前端 UnitStatusPanel 状态徽章）；⏳ 沉默/嘲讽/DoT/闪避 待做。
5. 卡组构建：✅ 战后 1 选 1（feat/deck-building：胜利后从小队卡池抽 3 张候选，选中卡持久化进 overlay.combat_deck，下场战斗以 bonus_cards 注入并按职业解析 owner）；⏳ 删卡/强化卡 待做。
6. 难度曲线：✅ conditions.max_rounds（回合超时判负，时间压力）+ escape_enabled（撤退 fail-forward，feat/combat-difficulty 已落地）；enemy.level 已由 combat_stats 内化（无需二次缩放），difficulty 作为关卡标签（难度曲线 = 遭遇战敌人构成 + 回合上限共同体现）。

### P3 · 成长可见性 + 高阶系统
7. 角色成长面板：显示 level/xp/属性，属性→战斗数值（HP/ATK/DEF…）即时换算预览。
8. 遗物 / 干员士气 / 指挥官模式（Phase 3 备选）。
9. ✅ 命中检定 bug 已修（feat/hit-fix）：dodge 现为 0 伤害（compute_damage 判 not hit），伤害/状态施加统一改为 hr.hit；DC 由 10+EVA 重平衡为 6+EVA（玩家 ~95% 命中 / 敌人 ~56%），HIT/EVA 属性真正生效。

---

## 关键文件（实现时参照）
- 战前打法：data/combat/encounters/*.md + 新 src/combat_approaches.py + src/combat_session.py:start()。
- 简报/投点：src/blueprints/chat.py（两段式战斗触发）+ src/SceneManager.py（brief_mode）。
- 状态效果：src/combat_engine/engine.py:play_card + card.py + data/classes/*/cards.json。
- 成长面板：src/blueprints/sessions.py（overlay progress）+ 前端新组件。
