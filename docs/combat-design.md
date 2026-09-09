# 战斗系统设计（架构总纲 · 已对齐当前实现）

> 本文是战斗系统的**架构与集成总纲**，内容已按当前代码校准（2026-08 审计）。
> 数值公式与平衡参数详见 [`combat-numerical-design.md`](combat-numerical-design.md)；
> 界面交互与布局详见 [`combat-ui-design.md`](combat-ui-design.md)；
> 背景图提示词规范见 [`combat-background-prompts.md`](combat-background-prompts.md)。
> 未实现的重构方向（战前简报/Approach 打法/敌人意图等）见 [`combat-core-design.md`](combat-core-design.md)（提案状态）。
> 代码权威源：`src/combat_engine/`、`src/combat_session.py`、`src/combat_data_loader.py`、`src/blueprints/combat.py`。

---

## 1. 架构组件

```
combat_session.py（会话包装：生命周期/玩家操作/奖励回写/SSE 推送）
        │
        ├── combat_engine/engine.py   —— 回合循环、状态机、AP/士气、敌人 AI
        │       ├── entity.py         —— CombatUnit（属性→战斗数值、个人 AP）
        │       ├── grid.py           —— 7×7 网格、寻路与范围（切比雪夫距离）
        │       ├── card.py           —— Card / CardPool（抽牌堆/手牌/弃牌/消耗）
        │       ├── card_data.py      —— 9 职业 × 8 张基础卡牌（5 basic + 3 elite）
        │       ├── card_loader.py    —— combat.json / cards.json → 卡牌实例
        │       └── dice.py           —— d20 命中/伤害/治疗判定
        │
        └── combat_data_loader.py —— 敌人/遭遇/背景加载（data/combat/）
```

数据源：
- 敌人：`data/combat/enemies/*.md`（frontmatter `name/class/combat_stats/drop_items/drop_rate/xp_reward`）
- 遭遇：`data/combat/encounters/*.md`（frontmatter `waves/background`）
- 背景：`data/combat/backgrounds/<bg_id>/index.md` + 图片
- 卡牌：`data/characters/<角色>/combat.json`（专属）+ `data/classes/<职业>/cards.json`（职业池）

## 2. 网格与站位

- **7×7 网格**（`grid.py`）；玩家部署列 0-2，敌方列 3-6。
- 距离：**切比雪夫距离**（8 方向，含斜走）。
- 遭遇战数据中的 `grid_size`/`deploy_zones` 字段当前**不被读取**。

## 3. 战斗流程（状态机）

```
INIT → ROUND_START → PLAYER_TURN → ENEMY_TURN → (round++, 回 ROUND_START) → … → END
```

- **无独立 ROUND_END 阶段**；胜负判定直接进入 `END` 相位。
- 玩家回合：出牌（选卡 + 目标）或移动单位；敌人回合：敌人 AI 逐个行动。

## 4. AP 系统（双池）

- **个人 AP**：`1 + floor((mobility - 3) / 3)`，钳制 **[1, 4]**（`entity.py`）。
  **玩家移动先耗个人 AP**；引擎层出牌也先耗个人 AP（不足部分以共享 AP 补足）。
- **共享 AP**：`2 + max(0, (最高 tactical_planning - 5) // 3)`，**上限 3**（`engine.py`）。
- 移动：**1 AP 可移动最多 `mobility // 2` 格**（切比雪夫距离，可斜走）。
- 会话层出牌校验共享 AP 余额（`combat_session.py`）。

## 5. 命中 / 伤害 / 治疗

公式详见 `combat-numerical-design.md` §7；代码在 `dice.py`：

- 命中：`d20 + HIT vs 6 + EVA`；**nat1 必失、未达 DC（dodge）也失手、nat20 暴击（伤害 ×2）**；伤害保底 1。
- **治疗完全无视抗性**（不按 min(DEF,RES) 减免）。

## 6. 属性 → 战斗数值

属性文档使用**中文 key**（如 `物理强度`），经 `entity.py` 的 `_ATTR_KEY_MAP` 映射为英文 key（`physical_strength` 等）；**没有旧英文 key（strength/agility）兼容映射**。数值派生公式（HP=END×12+STR×3 等）见 `combat-numerical-design.md` §3 与 `entity.py`。
角色卡 frontmatter 可选带 `combat_stats`（与敌人卡同格式），**声明即覆盖**对应派生数值，未声明的字段继续走属性派生。

## 7. 卡牌

- **9 职业 × 8 张（5 basic + 3 elite）= 72 张**（`card_data.py`）；每角色起始卡组 7 张（5 basic + 2 elite）。
- 共享手牌 6 张，每轮补满；每轮每角色保底至少 1 张可用牌。
- CardPool 三堆结构：抽牌堆 / 手牌 / 弃牌（+消耗）。
- 卡牌 JSON CRUD 走 `blueprints/cards.py`；加载器 `card_loader.py` 三层回落：
  `角色 combat.json → 职业 cards.json → 硬编码兜底`。

## 8. 敌人与 AI

- 敌人卡组由 frontmatter `ai_skills` **数据驱动**（`engine.py` 的 `ENEMY_CARD_CATALOG` 目录解析 card_id，
  每实例深拷贝）；未声明/全部未知时回退职业默认（术师→arts、狙击→远程物理、其余→近战）。
  `ai_behavior` 的 defensive 姿态用于「坚守」意图判定。
- 敌人 AI（`engine.py`）：**意图驱动**——ROUND_START 计算每个敌人意图
  `{type: 攻击/重击/范围攻击/移动/坚守, target, 强度范围}` 推送前端；执行按 **SPD 降序**
  逐个行动，优先消费意图卡牌（精英卡消耗后本场不可再用），无法攻击时向最近玩家移动。
  目标选择优先嘲讽单位，否则最近玩家；无撤退阈值（撤退为玩家主动 `escape_enabled`）。
- 敌人 `level` 字段不读取，`combat_stats` 直接作为最终值。

## 9. 遭遇战与战斗触发

- 遭遇字段消费：`waves`（**逐波触发**：清空当前波后刷出下一波，全清才胜利）、`background`、
  `approaches`（打法）、`conditions`（`max_rounds` 超时判负 / `escape_enabled` 允许撤退）均被读取；
  `trigger_plot` **未读取**。
- **tactical 模式下**：LLM 叙述后 `extract_markers` 输出 `combat_trigger` → SSE
  `combat_briefing`（含打法列表）→ 玩家选打法后 POST `/combat/start` 开战（或谈判检定/撤退）。
  战斗目标优先级：节拍 `[COMBAT:enc_id]`（代码确定性解析）> LLM `combat_trigger` 提取。

## 10. 消耗品与奖励

- **已实现战斗消耗品**：物品 frontmatter `combat_effect: {type: heal}`，使用消耗 1 共享 AP（如 `data/items/急救包.md`）。
- 奖励结算：XP = 遭遇 `rewards.xp` + Σ 敌人 `xp_reward`；物品 = 遭遇 `rewards.items` + 按 `drop_rate` roll 敌人 `drop_items`；升级阈值 `level×100`，+1 最低战斗属性。
- 战斗结束回写：角色 HP 变化/受伤/死亡状态写回会话。

## 11. SSE 事件

事件统一包装为 `{"type": "<事件名>", "data": {...}}`（`blueprints/combat.py`）。引擎发出的事件：

`battle_start` / `round_start`（含 `round` 与 `intents`）/ `card_played` / `damage` / `heal` /
`move` / `death` / `status`（状态效果）/ `cleanse`（净化）/ `wave_start`（新一波敌人入场）/
`turn_end`（回合切换，无 round_end）/ `battle_end` / `error`

状态快照由 `combat_session.py` 输出；`valid_moves` 恒为 `[]`（客户端计算）。

## 12. API（`src/blueprints/combat.py`）

`/api/sessions/<id>/combat/start|action|state|complete|events|card-pick|abandon` 及战斗测试会话对应端点；
`start` 支持 `approach_id`（打法），`complete` 结算奖励（XP/物品/卡组候选）并回写；
战斗回写（HP/受伤/死亡）在 `combat_complete` 处理。

## 13. 前端

- `CombatView.tsx`（主控）+ `CombatGrid.tsx`（CSS 3D 网格，`rotateX(33deg)`）+ `PixiCombatScene.tsx`（Spine 覆盖层，runtime-3.8）+ `CombatHand/DeckViewer/CardEditor` + `audioManager.ts`（音效）。
- 战前简报/打法卡片在 `ChatPanel.tsx`（`pendingBriefing` + `combat_briefing` SSE）与 `CombatView.tsx`（`approaches`）中渲染。
- 格子/卡牌双模式尺寸、快捷键（1-5 选牌、F 结束回合、Esc 取消）详见 `combat-ui-design.md`。

## 14. 路线图（现状）

**已实现**：7×7 网格 + Spine 覆盖 + 拖卡/点选操作、共享手牌 6 张、双 AP 池、d20 判定、
消耗品、XP/物品奖励与升级、战斗结算画面（含奖励展示 + 战后自动叙述）、卡牌 JSON CRUD、
战斗背景图（含会话级覆盖、AI 生成工作流）、音效、战前简报与打法选择（Approach）、
敌人意图系统、SPD 行动顺序、max_rounds/逃跑条件、战斗内状态效果（护盾/减速/束缚/
虚弱/增幅/沉默/灼烧/嘲讽/闪避/致盲 + 净化/破甲）、战后卡牌 1 选 1、剧情分支投点接入战斗、
节拍 `[COMBAT:enc_id]` 代码级解析、波次逐波触发、敌人 `ai_skills` 数据驱动。

**未实现**：部署区 `deploy_zones`/`grid_size` 字段（当前玩家/敌人用默认站位）、`trigger_plot` 结算联动。
