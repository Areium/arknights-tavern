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

## 八、实施优先级建议

| 优先级 | 工作项 | 涉及文件 | 工作量 |
|--------|--------|---------|--------|
| 🔴 P0 | 属性 key 兼容层 | `entity.py` | 小（加映射表） |
| 🔴 P0 | 博士属性补全 | `博士/index.md` | 小（补 5 个属性值） |
| 🔴 P0 | 博士职业定义 | 新建 `classes/战术指挥/index.md` | 小 |
| 🔴 P0 | 敌人 markdown 模板 + 4 敌人 | 新建 5 个 .md | 中 |
| 🔴 P0 | 卡牌 markdown 模板 + 64 卡 | 新建 ~70 个 .md | 中 |
| 🟡 P1 | 职业卡池 markdown 化 | 新建 9 个子目录 | 中（可脚本迁移） |
| 🟡 P1 | Buff/Debuff 战斗映射 | 新文件 + 代码 | 中 |
| 🟡 P1 | 等级缩放 | `entity.py` + 新配置 | 小 |
| 🟡 P1 | 注册到 `_INDEX.md` | 编辑 index 文件 | 小 |
| 🟢 P2 | 角色专属卡牌 | 编辑各角色 .md | 中 |
| 🟢 P2 | 战斗遭遇模板 + 示例 | 新建 2-3 个 .md | 中 |
| 🟢 P2 | 物品/武器战斗效果 | 编辑 items + 代码 | 中 |
| 🟢 P2 | 天气战斗效果映射 | `environment_state.py` | 小 |
