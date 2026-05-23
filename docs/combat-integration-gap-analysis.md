# 战斗系统集成分析 —— 差距与所需补充

> 基于远程最新 `data/` 结构分析。2026-05-23。

---

## 一、属性系统变化（关键：demo 公式需要更新）

### 1-1. 属性 key 映射（旧 → 新）

项目已将属性重命名为明日方舟正典术语。demo 中 `combat/entity.py` 的 `from_character_metadata()` 使用的是旧 key，**必须更新**：

| 旧 key（demo 使用） | 新 key（远程最新） | 新中文名 | 战斗用途 |
|---|---|---|---|
| `strength` | `physical_strength` | 物理强度 | PATK, DEF, HP |
| `agility` | `mobility` | 战场机动 | SPD, HIT, EVA |
| `endurance` | `physiological_tolerance` | 生理耐受 | HP, DEF |
| `intelligence` | `tactical_planning` | 战术规划 | MATK, HEAL, SPD |
| `originium_arts` | `originium_arts_assimilation` | 源石技艺适应性 | MATK, HEAL, RES |
| `combat_skill` | `combat_skill` (不变) | 战斗技巧 | PATK, HIT |
| `emotional_stability` | `emotional_stability` (不变) | 情绪稳定性 | RES |
| `charisma` | `charisma` (不变) | 魅力 | (RP 用途，暂无战斗映射) |

### 1-2. 新增的 d20 修正系统

远程每个属性等级现在都带有 d20 修正值：

| 等级 | 评级 | 修正 |
|------|------|------|
| 1-2 | 缺陷 | -3 ~ -2 |
| 3-4 | 普通 | -1 |
| 5-6 | 标准 | 0 ~ +1 |
| 7-8 | 优良 | +1 ~ +2 |
| 9-10 | 卓越 | +3 ~ +4 |

**需要决策**：战斗伤害公式是继续用当前 demo 的属性→战斗数值换算，还是改用 d20 修正系统？当前 demo 的公式是对属性的线性映射（如 `PATK = (strength + combat_skill) × 2`）。两条路线：

- **路线 A**：保持 demo 公式（属性→战斗数值→伤害计算），将 d20 修正作为额外的命中/暴击加值
- **路线 B**：简化为统一的 d20 修正系统（属性→修正值→所有判定使用同一套 d20 + mod 体系）

**建议**：路线 A 更适合卡牌战斗（需要 HP/ATK/DEF 等数值做减法运算），但 d20 修正可以取代当前的 HIT/EVA 判定。

### 1-3. 属性 key 语言不一致

- 模板 `TEMPLATE.md` 要求中文 key（`物理强度`、`战场机动`…）
- **只有阿米娅用了中文 key**
- **其他 6 个角色全部用了英文 key**（`physical_strength`、`mobility`…）

`CombatUnit.from_character_metadata()` 需要同时兼容两种 key。

---

## 二、角色数据缺口

### 2-1. 博士属性不完整（阻塞）

博士只有 **3/8** 属性：

```yaml
attributes:
  tactical_planning: 10
  physical_strength: 5
  emotional_stability: 8
```

缺少：`mobility`、`physiological_tolerance`、`combat_skill`、`originium_arts_assimilation`、`charisma`。

如果强制使用战斗公式，博士的 HP/DEF/SPD/HIT/EVA 将全为 0 或异常值。

**需要补充**：
1. 给博士补全 8 属性，或
2. 在战斗系统中定义缺省值规则（缺失属性默认 5），或
3. 博士作为"指挥官"角色不直接参与战斗，而是提供战术 buff

### 2-2. 博士的职业不存在

博士的 `class: "战术指挥"` 不在 8 个有效职业中。需要：
- 新建 `data/classes/战术指挥/index.md`，定义其 `damage_type`/`attack_range`/`core_attributes`，或
- 在战斗系统中为 `战术指挥` 创建专属卡池

### 2-3. 各角色无卡牌内容

**只有阿米娅** 的 markdown body 中有 `# 卡牌` 段落（4 专属 + 6 职业通用）。其他 6 个角色均无卡牌定义。

**需要补充**：为每个角色的 markdown 文件添加 `# 卡牌` 段落，或由战斗系统根据职业自动生成初始卡组（当前 demo 的做法）。

### 2-4. 角色数据汇总

| 角色 | 职业 | 属性数 | Key 语言 | 有卡牌 | 问题 |
|------|------|--------|----------|--------|------|
| 博士 | 战术指挥(无效) | 3/8 | EN | 无 | 缺 5 属性 + 无职业 + 无卡牌 |
| 阿米娅 | 术师 | 8/8 | CN | 有 | race 含括号额外文本 |
| 银灰 | 近卫 | 8/8 | EN | 无 | — |
| 闪灵 | 医疗 | 8/8 | EN | 无 | — |
| 德克萨斯 | 先锋 | 8/8 | EN | 无 | faction 有误 |
| 陈 | 近卫 | 8/8 | EN | 无 | race 应为龙非鲁珀 |
| 霜星 | 术师 | 8/8 | EN | 无 | — |

---

## 三、职业战斗数据（已完备，可直接使用）

8 个职业的 `damage_type` / `attack_range` / `core_attributes` 已定义完整：

| 职业 | 伤害类型 | 射程 | 核心属性 |
|------|---------|------|---------|
| 术师 | arts | medium | originium_arts_assimilation, tactical_planning |
| 近卫 | physical | melee | physical_strength, combat_skill, physiological_tolerance |
| 狙击 | physical | long | mobility, combat_skill |
| 重装 | mixed | melee | physical_strength, physiological_tolerance, emotional_stability |
| 先锋 | physical | melee | mobility, charisma, tactical_planning |
| 医疗 | healing | medium | tactical_planning, emotional_stability, originium_arts_assimilation |
| 辅助 | mixed | medium | tactical_planning, originium_arts_assimilation, charisma |
| 特种 | mixed | short | mobility, combat_skill, tactical_planning |

**用途**：`core_attributes` 可以用于计算卡牌伤害加成（如在核心属性上有高分则伤害更高），或用于属性校验（某卡牌要求某属性≥X 才能打出）。

---

## 四、现有的规则系统与战斗的交互点

### 4-1. Debuff 系统（data/rules/04-debuff-system/）

已有 **17 种 debuff** 分布在 4 类（身体/心理/环境/物质），每类都有明确的属性修正值。**可直接映射到战斗效果**：

| Debuff ID | 名称 | 战斗效果建议 |
|-----------|------|------------|
| PH-001 轻伤 | 物理 -2 | DEF -2, 物理伤害 -2 |
| PH-002 重伤 | 物理 -3 | DEF -4, 行动速度减半 |
| PH-003 中毒 | STR -3 | 每回合 CON 判定, 失败扣 HP |
| PH-004 疲惫 | 全体 -1 | 全卡牌 AP 消耗 +1 |
| ME-001 惊吓 | 下个判定 -1 | 下张卡伤害 -25% |
| ME-002 恐惧 | 社交 -2 | 无法攻击, 移动方向反转 |
| EN-001 被困 | 逃脱 DC +2 | 移动范围减半或不能移动 |
| MA-002 被拖累 | 移动 -2 | 速度 -2, 闪避 -2 |

### 4-2. Buff/Debuff 池（data/rules/05-buff-pool/）

已有 **20+ buff** 和 **15+ debuff**，带稀有度（1-6 星）、d20 范围、持续时间。战斗中可以触发的效果：

| Buff ID | 名称 | 星 | 战斗效果建议 |
|---------|------|---|------------|
| BF-001 | 肾上腺素 | 1 | PATK +2, 持续 1 回合 |
| BF-101 | 战斗准备 | 2 | 全体 combat +2, 持续 2 回合 |
| BF-201 | 战术指挥 | 3 | 全体 ATK +3, 持续 3 回合 |
| BF-304 | 不屈 | 4 | 承受一次致死伤害(HP=1) |
| BF-401 | 光辉骑士之盾 | 5 | 全队 DEF/RES +5, 首次伤害免疫 |
| BF-502 | 凯尔希的沉默 | 6 | ATK +6, 额外行动次数 |

### 4-3. 偏差状态系统（data/rules/06-deviation-states/）

三个叙事层级影响规则严格度：
- **大纲之内**：全部战斗 DC 正常
- **旁逸斜出**：战斗 DC 降低 1-2
- **天高海阔**：无强制战斗触发, 自由沙盒

**用途**：战斗遭遇的触发条件需要检查当前偏差状态。

---

## 五、缺失的内容清单（按优先级排序）

### 🔴 P0 — 阻塞战斗集成

#### 5-1. 属性兼容层
`entity.py` 需更新以处理：
- 新旧 key 映射（`strength` → `physical_strength` 等）
- 中英文 key 并存（`物理强度` 和 `physical_strength`）
- 缺失属性的默认值（建议默认 5）

#### 5-2. 博士数据补全
- 创建 `data/classes/战术指挥/index.md` 职业定义
- 补全博士的 8 属性
- 决定博士在战斗中的角色（上场作战 vs 战术指挥 buff）

#### 5-3. 敌人 markdown 数据
`data/combat/enemies/` 目录 + 模板 + 至少 4 个敌人文件（demo 中的士兵/术师/盾卫/狙击手）

#### 5-4. 卡牌 markdown 数据
- `data/combat/cards/` 目录结构（按职业分子目录）
- 每张卡一个 `.md` 文件，用 frontmatter 存储 `card_id`/`damage_type`/`min_damage`/`target` 等
- 将 demo 的 64 张卡片定义（`card_data.py`）迁移为 markdown

### 🟡 P1 — 需要但可用兜底方案

#### 5-5. 角色专属卡牌
- 为每个角色添加 `# 卡牌` 段落到 markdown body（目前仅阿米娅有）
- 或在代码中根据职业自动分配初始卡组（当前 demo 做法）

#### 5-6. 战斗遭遇数据
`data/combat/encounters/` — 每个遭遇一个 `.md`：
- `encounter_id` / `waves`（敌人组合+站位）
- `conditions`（回合限制/逃跑）
- `rewards`（经验/物品）
- `trigger_plot`（关联剧情）

#### 5-7. Buff/Debuff 战斗映射
将现有的 17+ 种 debuff 和 20+ 种 buff 映射到具体战斗数值效果（ATK/DEF/SPD 修正、持续回合数等）

#### 5-8. 等级缩放表
角色等级（1-10）→ 战斗数值倍率。当前 demo 无等级概念，所有单位用固定数值。

### 🟢 P2 — 增强体验

#### 5-9. 武器/物品对战斗的加成
`data/items/` 中的物品有 `effects` 字段（叙事文本），可扩展为战斗效果

#### 5-10. 环境对战斗的影响
`environment/weather/` 中的天气效果（visibility_range、movement_speed）可映射为战斗修正

#### 5-11. 子职业专属卡牌
当前卡池按职业划分（8 职业各 8 张）。远期可按子职业（如剑豪/强攻手/收割者）进一步细分

---

## 六、需要新增的数据目录

```
data/
├── _INDEX.md                      ← 新增 combat 分类注册
├── classes/
│   └── 战术指挥/index.md           ← 新建（博士的职业）
├── combat/
│   ├── _index.md                   ← 战斗系统总索引
│   ├── TEMPLATE_enemy.md           ← 敌人模板
│   ├── TEMPLATE_card.md            ← 卡牌模板
│   ├── TEMPLATE_encounter.md       ← 遭遇模板
│   ├── enemies/
│   │   ├── _index.md
│   │   ├── 整合运动士兵.md
│   │   ├── 整合运动术师.md
│   │   ├── 整合运动盾卫.md
│   │   └── 整合运动狙击手.md
│   ├── cards/
│   │   ├── _index.md
│   │   ├── 术师/   (8 张卡)
│   │   ├── 近卫/   (8 张)
│   │   ├── 狙击/   (8 张)
│   │   ├── 重装/   (8 张)
│   │   ├── 先锋/   (8 张)
│   │   ├── 医疗/   (8 张)
│   │   ├── 辅助/   (8 张)
│   │   ├── 特种/   (8 张)
│   │   └── 战术指挥/ (8 张，新建)
│   └── encounters/
│       ├── _index.md
│       └── 初遇整合运动.md
```

---

## 七、`entity.py` 需要修改的具体内容

### 7-1. 属性 key 映射表

```python
# 旧 demo 属性 → 新项目属性
_ATTR_KEY_MAP = {
    # 新正典 key（英文）
    "physical_strength": "physical_strength",
    "mobility": "mobility",
    "physiological_tolerance": "physiological_tolerance",
    "tactical_planning": "tactical_planning",
    "combat_skill": "combat_skill",
    "originium_arts_assimilation": "originium_arts_assimilation",
    "emotional_stability": "emotional_stability",
    "charisma": "charisma",
    # 新正典 key（中文）
    "物理强度": "physical_strength",
    "战场机动": "mobility",
    "生理耐受": "physiological_tolerance",
    "战术规划": "tactical_planning",
    "战斗技巧": "combat_skill",
    "源石技艺适应性": "originium_arts_assimilation",
    "情绪稳定性": "emotional_stability",
    "魅力": "charisma",
    # 旧 demo key → 新 key
    "strength": "physical_strength",
    "agility": "mobility",
    "endurance": "physiological_tolerance",
    "intelligence": "tactical_planning",
    "originium_arts": "originium_arts_assimilation",
}
```

### 7-2. 属性默认值

缺失属性默认 5（标准成人水平），博士的 5 个缺失属性会自动填为 5。

### 7-3. 更新后的战斗数值映射公式

```python
def from_character_metadata(cls, meta: dict, **kwargs) -> "CombatUnit":
    attrs = _normalize_attributes(meta.get("attributes", {}))
    
    HP  = attrs["physiological_tolerance"] * 12 + attrs["physical_strength"] * 3
    PATK = (attrs["physical_strength"] + attrs["combat_skill"]) * 2
    MATK = (attrs["originium_arts_assimilation"] + attrs["tactical_planning"]) * 2
    HEAL = (attrs["originium_arts_assimilation"] + attrs["tactical_planning"]) * 2
    DEF  = round(attrs["physiological_tolerance"] * 1.5 + attrs["physical_strength"] * 0.5)
    RES  = round(attrs["emotional_stability"] * 1.5 + attrs["originium_arts_assimilation"] * 0.5)
    SPD  = attrs["mobility"] * 2 + attrs["tactical_planning"] * 0.5
    HIT  = attrs["combat_skill"] + attrs["mobility"]
    EVA  = round(attrs["mobility"] * 1.5)
```

### 7-4. 博士的战术指挥职业

新建 `data/classes/战术指挥/index.md`，建议：
```yaml
damage_type: "mixed"
attack_range: "global"
core_attributes: ["tactical_planning", "charisma", "emotional_stability"]
combat_role: "战术指挥/远程支援"
```

博士的卡池特色：buff/debuff 为主，少量直接伤害，全局射程。

---

## 八、Demo 引擎代码级差距

> 以下差距来自对 `demo/combat/` 代码的逐文件审计，与设计文档对照。

### 8-1. `card.py` — Card 缺少关键字段

当前 Card dataclass 缺少设计文档已定义的字段：

| 缺失字段 | 用途 | 影响 |
|---------|------|------|
| `owner: str \| None` | 角色专属标识（专属牌锁定使用者） | 无法实现专属牌类别 |
| `class_required` 无默认值逻辑 | 设计文档要求 `"any"` = 通用牌 | 当前代码有该字段但 to_dict() 未序列化，from_dict() 未反序列化 |

此外 `Card.to_dict()` 未输出 `class_required`，`Card.from_dict()` 未接收 `class_required`。

### 8-2. `card.py` — CardPool 是每单位独立卡池，非共享

设计文档定义的是**共享牌库 + 共享手牌**模型（28 张牌库 → 6 张共享手牌），但当前 `CardPool` 绑定在单个 `CombatUnit` 上：

```python
# engine.py — 每个单位独立 CardPool
self._pools: dict[str, CardPool] = {}  # unit_id → CardPool
```

`CardPool.hand_size = 7`（每单位），但设计文档定义共享手牌为 **6 张**。

**需要**：重写为 `SharedDeck` 模型 — 单一牌库(28张) → 单一手牌(6张) → 单一弃牌堆。

### 8-3. `engine.py:323` — 敌方 AI 射程判定 bug

```python
playable = [c for c in pool.hand if c.cost <= unit.AP]
if playable and dist <= 1:  # BUG: 硬编码 dist <= 1
```

`dist <= 1` 导致敌方**只能近战攻击**。即使敌人有射程 3 的远程卡牌（如术师），也只有当目标在相邻格时才尝试使用。正确的逻辑应该是：先筛选 `playable`，再对每张卡检查 `dist <= card.range`。当前代码的 `dist <= 1` 是一个过早的门槛，把所有远程攻击都过滤掉了。

设计文档（§敌方 AI）的描述是正确的——"如有可用的攻击卡且在射程内 → 打出"——但代码实现有 bug。

### 8-4. `engine.py:329` — 全局射程 sentinel 不一致

```python
real_range = card.range if card.range >= 0 else 999
```

设计文档和 `card.py` 约定 `-1` = 全图射程。但 engine.py 用 `999` 作为 sentinel。虽功能等价，但应该统一为 `-1`。

### 8-5. `grid.py` — 网格尺寸硬编码

```python
TOTAL_ROWS = 4
TOTAL_COLS = 8
PLAYER_ROWS = 3
PLAYER_COLS = 3
ENEMY_ROWS = 4
ENEMY_COLS = 5
```

设计文档要求 n×n 可配置网格（6×6 / 8×8 / 10×10）。`Grid` 类需要接受构造参数而非模块级常量。

### 8-6. `grid.py` — 无部署区抽象

当前单位位置通过绝对坐标硬编码（`run_demo.py` 和 `tui_app.py` 中的 `PLAYER_SETUP` 和 `ENEMY_POSITIONS`）。设计文档定义了 `deploy_zones` 概念（玩家 3×3 左中、敌方 4×5 右中 + 随机偏移）。`Grid` 类需要新增 `set_deploy_zone(team, rect)` 方法。

### 8-7. 无拦截/挡刀机制

设计文档 §AP 系统定义了：
- **重装被动挡刀**：Bresenham 路径检查 + 概率公式
- **高 SPD 主动拦截**：mobility ≥ 7 每轮 1 次

当前 demo 代码中完全不存在这些逻辑。`CombatEngine` 没有 `check_intercept()`、`check_block()` 方法，也没有 `intercept_prompt` / `block_attempt` 事件。

### 8-8. 无等级缩放

设计文档在敌人模板中定义了 `level: 1-10` 字段。当前 demo 所有单位使用固定数值，`entity.py` 没有 `level_multiplier` 映射。

### 8-9. `tui_app.py` / `run_demo.py` — 硬编码的战斗设置

两个入口文件各自硬编码了相同的 `PLAYER_SETUP`、`ENEMY_DEFS`、`ENEMY_POSITIONS`。这些数据应该从 markdown 遭遇文件加载。

---

## 九、Session / API 集成差距

> 以下差距来自对 `src/` 后端代码的审计。

### 9-1. `Session` 无战斗状态字段

`session_manager.py` 的 `Session.__init__()` 创建了 `SceneManager`、`EnvironmentState`、`SessionOverlay`、`VectorMemory`，但**没有 `combat` 属性**。

设计文档要求在 `Session` 中添加 `self.combat: CombatSession | None = None`。

### 9-2. `SessionOverlay` 无战斗覆盖通道

`session_overlay.py` 支持 4 个覆盖通道：
- `characters` — 角色属性覆盖
- `items` — 物品效果覆盖
- `environment` — 天气/时间/气氛覆盖
- `quest_states` — 任务状态

**缺少** `combat` 通道。战斗系统需要覆盖通道来支持：
- 角色在战斗中获得的临时 buff/debuff 延续到后续场景
- 战斗结果修改角色状态（受伤、经验等）

### 9-3. `RegistryManager` 不支持战斗数据类型

`registry_manager.py` 的 `_CORE_SECTIONS` 定义了 6 个类别的提取规则（races/classes/factions/items/locations/weather），**不含 combat 相关类别**。

`build_character_context()` 方法不提取战斗数值（ATK/DEF/HP 等），因为设计上这些值由公式从 `attributes` 计算。但如果角色有 `combat_override`，需要在此处提取。

`_load()` 方法只读取 `data/_INDEX.md` 中注册的类别。需要新增 `combat_enemies`、`combat_cards`、`combat_encounters` 三个类别。

### 9-4. `data/_INDEX.md` 未注册战斗和规则类别

当前 `_INDEX.md` 注册了 9 个类别（characters/races/classes/factions/items/locations/weather/plots/world/attributes），缺失：

| 缺失类别 | 数据目录 | 影响 |
|---------|---------|------|
| `combat` | `data/combat/` | 战斗数据对 RegistryManager 不可见 |
| `rules` | `data/rules/` | 现有的 buff/debuff/偏差状态系统不可见 |

`data/rules/` 下的 `04-debuff-system/`、`05-buff-pool/`、`06-deviation-states/` 包含已经定义好的 17 种 debuff + 20+ buff，但因为没有注册到索引，`RegistryManager` 无法加载它们。

### 9-5. `data/combat/` 目录不存在

设计文档 §与项目集成的 markdown 数据模型 定义了完整的 `data/combat/` 目录树（~80+ markdown 文件），但**当前数据目录中完全不存在**。

---

## 十、数据层不一致

### 10-1. 职业索引字段命名不一致

`data/classes/_index.md` 的 `index` 条目使用 `range`：

```yaml
术师:
  damage_type: arts
  range: medium        # ← 注意：_index.md 用 range
```

但各职业的独立 `.md` 文件使用 `attack_range`：

```yaml
# data/classes/术师/index.md
damage_type: arts
attack_range: medium   # ← 注意：独立文件用 attack_range
```

`TEMPLATE.md` 也使用 `attack_range`。代码中加载职业数据时需要同时兼容两种 key，或统一为一个。

### 10-2. 属性 key 语言不一致（再次强调）

- TEMPLATE.md 要求中文 key
- 只有阿米娅用了中文 key
- 其他 6 个角色用了英文 key

这个在 §1-3 已提及，但它会影响 `RegistryManager.build_character_context()` 的输出——如果角色属性是英文 key，LLM 看到的 prompt 中属性名和中文解说不一致。

### 10-3. 阿米娅 race 字段含额外文本

阿米娅的 `race: "卡特斯/奇美拉"`，用 `/` 分隔两个种族值。`RegistryManager.resolve("races", "卡特斯/奇美拉")` 无法匹配。需要将 race 拆分为 `["卡特斯", "奇美拉"]` 或只保留主种族。

---

## 十一、设计文档自身的待补充项

> 设计文档 `combat-design.md` 已相当完整，以下是审计中发现的少量缺口。

### 11-1. 缺少明确的"共享牌库管理"章节

设计文档 §卡牌系统 定义了共享手牌模型，但缺少：
- 牌库抽空后弃牌堆洗牌的触发时机（补牌时 vs 回合开始时）
- 角色死亡后其 7 张牌是否从牌库移除（当前未定义）
- 替换角色（如 4 人中 1 人撤退换人）时牌库如何更新

### 11-2. 缺少卡牌升级/获取系统说明

当前设计文档没有定义：
- 角色升级时如何获得新卡牌（从职业卡池随机抽？从预定义升级路径选？）
- 精英卡获取条件
- 卡牌是否可以交易/替换

### 11-3. 缺少多人协作考虑

当前设计为单人控制 4 角色。如果未来支持多人（如 GM 模式），共享手牌模型需要调整。

### 11-4. AP 消耗的边界情况

- 通用牌消耗共用 AP + 个人 AP 补足时，如果多个角色都有个人 AP，优先消耗谁的？（当前未定义）
- 角色个人 AP 耗尽后，其专属牌是否仍显示在手牌中（灰显）？

### 11-5. 拦截与挡刀的交互优先级

当敌方攻击时，如果同时满足：
- 重装被动挡刀（自动判定，概率性）
- 高 SPD 主动拦截（玩家选择，确定性）

哪个先判定？如果重装挡刀成功，是否还触发主动拦截提示？当前设计文档未明确。

---

## 十二、实施优先级建议（更新）

| 优先级 | 工作项 | 涉及文件 | 工作量 |
|--------|--------|---------|--------|
| 🔴 P0 | 属性 key 兼容层 | `entity.py` | 小 |
| 🔴 P0 | 博士属性补全 | `博士/index.md` | 小 |
| 🔴 P0 | 博士职业定义 | 新建 `classes/战术指挥/index.md` | 小 |
| 🔴 P0 | 修复敌方 AI 射程 bug | `engine.py:323` | 小 |
| 🔴 P0 | Card 添加 `owner` 字段 | `card.py` | 小 |
| 🔴 P0 | 敌人 markdown 模板 + 4 敌人 | 新建 5 个 .md | 中 |
| 🔴 P0 | 卡牌 markdown 模板 + 64 卡 | 新建 ~70 个 .md | 中 |
| 🔴 P0 | 创建 `data/combat/` 目录结构 | 新建目录 + _index.md | 小 |
| 🟡 P1 | 共享牌库重写（CardPool → SharedDeck） | `card.py` + `engine.py` | 中 |
| 🟡 P1 | Grid n×n 可配置化 + 部署区 | `grid.py` | 中 |
| 🟡 P1 | Session 添加 combat 属性 | `session_manager.py` | 小 |
| 🟡 P1 | SessionOverlay 添加 combat 通道 | `session_overlay.py` | 小 |
| 🟡 P1 | RegistryManager 支持 combat 类别 | `registry_manager.py` | 中 |
| 🟡 P1 | `data/_INDEX.md` 注册 combat + rules | 编辑 index | 小 |
| 🟡 P1 | 统一 class _index.md `range` → `attack_range` | `_index.md` + 代码 | 小 |
| 🟡 P1 | Buff/Debuff 战斗数值映射 | 新文件 + 代码 | 中 |
| 🟡 P1 | 等级缩放表 | `entity.py` + 新配置 | 小 |
| 🟢 P2 | 拦截/挡刀机制实现 | `engine.py` | 中 |
| 🟢 P2 | 角色专属卡牌 | 编辑各角色 .md | 中 |
| 🟢 P2 | 战斗遭遇模板 + 示例 | 新建 2-3 个 .md | 中 |
| 🟢 P2 | 物品 combat_passive 字段 | 编辑 items + 代码 | 中 |
| 🟢 P2 | 天气战斗效果映射 | `environment_state.py` | 小 |
| 🟢 P2 | 全局射程 sentinel 统一 (999→-1) | `engine.py` | 小 |
| 🟢 P2 | 设计文档补充 §11.1-11.5 | `combat-design.md` | 小 |
