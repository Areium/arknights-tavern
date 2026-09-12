# 战斗系统设计（架构总纲 · 已对齐当前实现）

> 本文是战斗系统的**架构与集成总纲**，内容已按当前代码校准（2026-08 审计）。
> 数值公式与平衡参数详见 [`combat-numerical-design.md`](combat-numerical-design.md)；
> 界面交互与布局详见 [`combat-ui-design.md`](combat-ui-design.md)；
> 背景图提示词规范见 [`combat-background-prompts.md`](combat-background-prompts.md)。
> 章节战斗化改造方案（战前简报/Approach 打法/敌人意图等）见 [`archive/combat-core-design.md`](archive/combat-core-design.md)（**已实现并归档**；其"7×7 网格明确不改"条款已作废）。
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

> **v1 规则（`balance_version = 1`，详见 §15）**：出牌只耗共享 AP，移动只耗个人 AP。

- **个人 AP**：`1 + floor((mobility - 3) / 3)`，钳制 **[1, 4]**（`entity.py`）；**只用于移动**。
- **共享 AP**：四人队基础 **4**；队伍中最高 `tactical_planning >= 8` 时 **5**（上限 5）（`engine.py:_recalc_shared_ap_max`）；**只用于出牌**。
  不允许共享 AP 补移动，也不允许个人 AP 补出牌。
- 移动：**1 个人 AP 可移动最多 `mobility // 2` 格**（切比雪夫距离，可斜走）。
- 出牌/移动都先经 `validate_card_play` / `validate_move` 预检（AP、回合、卡牌归属、职业限制、
  射程与合法目标）；拒绝时不消耗任何资源、不弃牌。
- 旧存档（无 `balance_version`）载入按 v1 迁移：AP 只做钳制（`min(存量, 新上限)`），不凭空增加剩余 AP。

## 5. 命中 / 伤害 / 治疗

公式详见 `combat-numerical-design.md` §7；代码在 `dice.py`：

- 命中：`d20 + HIT vs 6 + EVA`；**nat1 必失、未达 DC（dodge）也失手、nat20 暴击（伤害 ×2）**；伤害保底 1。
- **治疗完全无视抗性**（不按 min(DEF,RES) 减免）。

## 6. 属性 → 战斗数值

属性文档使用**中文 key**（如 `物理强度`），经 `entity.py` 的 `_ATTR_KEY_MAP` 映射为英文 key（`physical_strength` 等）；**没有旧英文 key（strength/agility）兼容映射**。数值派生公式（HP=END×12+STR×3 等）见 `combat-numerical-design.md` §3 与 `entity.py`。
角色卡 frontmatter 可选带 `combat_stats`（与敌人卡同格式），**声明即覆盖**对应派生数值，未声明的字段继续走属性派生。

## 7. 卡牌

- **9 职业 × 8 张（5 basic + 3 elite）= 72 张**；每角色起始卡组 7 张（5 basic + 2 elite）。
- **单一真相源（v1）**：运行时卡表只读 `data/classes/<职业>/cards.json`
  （`card_json_loader.py` 带缓存，`card_data.py` 为薄封装）。
  `blueprints/cards.py` 写盘后调用 `clear_cache()` 刷新；`perf_tests/test_card_json_roundtrip.py`
  验证 JSON 与迁移前硬编码表的结构等价，`perf_tests/cards_python_snapshot.json` 是迁移基线。
  （旧文档提到的 `card_loader.py` 三层回落为死代码，已在冗余清理中删除。）
- **v1 卡牌字段**：在 `damage_type/min_damage/max_damage/atk_scale/target/range/cost/tier/
  class_required/owner/effects/ignore_def/cleanse` 之外新增
  `rank`（R0–R3）、`upgrade_branch`（stable/burst/synergy/tactical）、`exhaust`（显式耗竭覆盖，
  null 表示按 tier：elite 用后进耗竭）、`power_tier`、`cv_budget`、`cv_estimated`、`balance_version`。
  `CardPool.play_card` 按 `Card.is_exhausted_on_play` 决定弃牌还是耗竭。
- 共享手牌 6 张，每轮补满；每轮每角色保底至少 1 张可用牌。
  **保底抽牌只从抽牌堆/弃牌堆检索，绝不从耗竭堆捞回精英卡**，也不会换掉其他存活角色的唯一手牌。
- CardPool 三堆结构：抽牌堆 / 手牌 / 弃牌（+耗竭）。

## 8. 敌人与 AI

- 敌人卡组由 frontmatter `ai_skills` **数据驱动**（`engine.py` 的 `ENEMY_CARD_CATALOG` 目录解析 card_id，
  每实例深拷贝）；未声明/全部未知时回退职业默认（术师→arts、狙击→远程物理、其余→近战）。
  `ai_behavior` 的 defensive 姿态用于「坚守」意图判定。
- **行动槽（v1）**：`CombatUnit.action_slots`（默认 1；精英/Boss 为 2，由
  `combat_data_loader` 依 `role` 判定）。敌人每轮循环行动，直到用满 `action_slots`
  或 AP 耗尽；每个动作消耗卡牌 `cost`，移动消耗 1 AP。
- 敌人 AI（`engine.py`）：**意图驱动且预告 = 执行同一决策**——ROUND_START 用
  `_plan_enemy_actions()` 生成行动计划（`{action_slots, actions:[{type, label, card_id, target_id,
  damage_min/max}]}`，同时保留首段动作的扁平字段兼容旧前端），执行阶段
  `_execute_enemy_turn()` 按同一计划逐段执行；仅当控制（沉默/束缚）或目标失效导致计划动作
  无法执行时才重规划，**不虚报可行动数**。目标选择优先嘲讽单位，否则最近玩家。
- 敌人分层字段：`power_tier`（T0–T4）、`role`（minion/standard/strong/elite/boss）、
  `threat_points`、`expected_dpr`、`expected_effective_hp`、`balance_version`（见 §15）。
- 敌人 `level` 字段仍只作描述；`combat_stats` 为最终值。

## 9. 遭遇战与战斗触发

- 遭遇字段消费：`waves`（**逐波触发**：清空当前波后刷出下一波，全清才胜利）、`background`、
  `approaches`（打法）、`conditions`（`max_rounds` 超时判负 / `escape_enabled` 允许撤退）均被读取；
  `trigger_plot` **未读取**。
- **tactical 模式下**：LLM 叙述后 `extract_markers` 输出 `combat_trigger` → SSE
  `combat_briefing`（含打法列表）→ 玩家选打法后 POST `/combat/start` 开战（或谈判检定/撤退）。
  战斗目标优先级：节拍 `[COMBAT:enc_id]`（代码确定性解析）> LLM `combat_trigger` 提取。

## 10. 消耗品与奖励

- **已实现战斗消耗品**：物品 frontmatter `combat_effect: {type: heal}`，使用消耗 1 共享 AP（如 `data/items/急救包.md`）。
- **奖励结算（v1）**：
  `XP = (遭遇 rewards.xp + 0.35 × Σ 敌人 xp_reward) × 打法倍率`；
  打法倍率钳制在 **0.75–1.20**（突袭上限 1.20、谈判下限 0.75；撤退 ≤0.25 保留低倍率）。
  升级阈值 `XP_next(level) = 180 + 40 × (level - 1)`。
  经验分配：参与且存活 100%、阵亡 70%、未部署 30%；低于队伍最高等级 2 级以上（差距 ≥3 级）时 ×1.25 追赶。
- 战斗结束回写：角色 HP 变化/受伤/死亡状态写回会话。

## 10.1 战斗结算流程（`combat_settlement.py`）

- **触发**：引擎 `_check_battle_end()` 判定 `winner=player`（多波次只有最后一波清空才成立）→ SSE
  `battle_end` 下发前由 `_ensure_pending_settlement()` 自动生成并持久化待结算记录，
  随事件 `data.settlement` 推给前端；页面刷新/断线可用 `POST /combat/settlement` 补拉（幂等）。
- **数据源**：只读写剧情系统的会话覆盖层 `overrides.json`（`characters[name].progress` +
  `metadata.attributes`），不新建独立战斗数值副本；写回后 `SceneManager`/`CharacterAgent`/角色面板
  读到的即为新值。
- **结算 DTO**：每角色 `xp_gained`（含 `xp_base`/`xp_share`/`catchup_mult` 明细）、
  `level_before/after`、`xp_before/after`、`xp_needed`（进度条）、`level_ups`
  （**v1 起为 `{level, specialization_point, node_unlocked}`，不再携带属性提升**）、
  `attribute_changes`（v1 恒为空列表，属性只由剧情里程碑改变）、
  `specialization_points_*` / `nodes_unlocked_*`、`capped`（成长封顶）；
  奖励汇总含 XP/掉落/卡牌候选；无经验无奖励时给 `empty_message` 而不是空列表。
- **幂等与兜底**：待结算记录内 `applied.characters` / `applied.inventory` 逐项标记，
  写回失败返回 500 并保留战斗与记录（前端可「重试结算」），重试不重复发放；
  `overrides.json` 采用临时文件 + `os.replace` 原子落盘。
- **成长规则（v1）**：等级只发放专精点（每级 1 点），每 3 级解锁一个职业节点；
  属性不再随等级自动提升；无硬等级上限（`MAX_LEVEL=None` 可改）；
  遭遇 `rewards.unlock` 尚未接入（结算面板会提示）。

## 11. SSE 事件

事件统一包装为 `{"type": "<事件名>", "data": {...}}`（`blueprints/combat.py`）。引擎发出的事件：

`battle_start` / `round_start`（含 `round` 与 `intents`）/ `card_played` / `damage` / `heal` /
`move` / `death` / `status`（状态效果）/ `cleanse`（净化）/ `wave_start`（新一波敌人入场）/
`turn_end`（回合切换，无 round_end）/ `battle_end` / `error`

状态快照由 `combat_session.py` 输出；`valid_moves` 恒为 `[]`（客户端计算）。

## 12. API（`src/blueprints/combat.py`）

`/api/sessions/<id>/combat/start|action|state|complete|events|card-pick|abandon|settlement` 及战斗测试会话对应端点；
`start` 支持 `approach_id`（打法），`settlement` 生成/读取待结算数据（幂等），
`complete` 写回结算（角色成长/掉落/战斗历史）并清理战斗；
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

## 15. 平衡版本（`balance_version = 1`）

数值成长曲线方案的落地版本。改动集中在运行时语义与数值两端：

| 面 | v0（旧） | v1（现） |
|---|---|---|
| 出牌支付 | 个人 AP 优先、共享 AP 补足 | **只花共享 AP** |
| 移动支付 | 个人 AP 优先、共享 AP 补足 | **只花个人 AP** |
| 共享 AP | `2 + (战术规划-5)//3`，上限 3 | 基础 **4**；最高战术规划 ≥8 时 **5**（上限 5） |
| 敌人行动 | 名义 `max_ap=3`，实际每轮 1 次 | **行动槽**：普通 1、精英/Boss 2；循环至槽满或 AP 耗尽 |
| 保底抽牌 | 可从耗竭堆捞回精英卡 | **绝不取耗竭卡**，也不夺走他人唯一手牌 |
| 卡表来源 | `card_data.py` 硬编码 + cards.json 双源 | **cards.json 单一真相源**（含 effects/ignore_def/cleanse 等全字段） |
| 卡牌预算 | 无统一口径 | **24 CV/AP**（`combat_engine/cv.py`）；68/72 卡落带、4 卡带文档化例外 |
| 升级收益 | +1 最低未满属性 | **专精点**（每级 1 点，每 3 级解锁职业节点），属性只由剧情里程碑改变 |
| 升级阈值 | `level × 100` | `180 + 40 × (level - 1)` |
| 敌人 XP | 与遭遇基础 XP 全额叠加 | `遭遇 XP + 0.35 × 敌人 XP`，倍率钳制 0.75–1.20 |
| 遭遇难度 | `difficulty` 自由整数 | `encounter_type`/`recommended_power_tier`/`threat_budget`/`target_rounds` + 威胁带重排 |
| 存档 | 字段级重建（无版本） | `CombatEngine.to_dict/from_dict` 全量快照 + v0→v1 迁移（AP 只钳制不增加） |

机器生成的审计与模拟报告（每次数值变更后重跑）：

- `perf_tests/cv_audit_report.md` — 全卡 CV 审计与例外清单（`scripts/cv_audit.py`）
- `perf_tests/balance_migration_report.md` — 敌人分层与遭遇预算（`scripts/migrate_balance_v1.py`）
- `perf_tests/encounter_tuning_report.md` — 遭遇威胁重排（`scripts/tune_encounters_v1.py`）
- `perf_tests/progression_report.md` — 固定种子模拟与验收偏差（`perf_tests/simulate_combat.py`）
