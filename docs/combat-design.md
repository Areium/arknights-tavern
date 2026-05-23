# 战斗系统设计文档

> Arknights Text RPG — 回合制卡牌战斗的底层逻辑、数据结构、与项目集成方案
>
> demo 代码：`demo/combat/` | 当前版本：v0.1

---

## 目录

1. [概述](#概述)
2. [核心公式](#核心公式)
3. [属性映射（角色属性 → 战斗数值）](#属性映射)
4. [命中与伤害计算](#命中与伤害计算)
5. [卡牌系统](#卡牌系统)
6. [站位系统](#站位系统)
7. [回合制状态机](#回合制状态机)
8. [敌方 AI](#敌方-ai)
9. [数据结构定义](#数据结构定义)
10. [与项目集成的 markdown 数据模型](#与项目集成的-markdown-数据模型)
11. [集成路线图](#集成路线图)
12. [demo 文件索引](#demo-文件索引)

---

## 概述

战斗系统采用 **回合制卡牌** 模式，受 Slay the Spire 启发：

- **4 人小队**，站位在 3×3 玩家方阵，敌方 4×5 方阵
- 每个角色拥有基于 **职业** 的个人卡池，获取角色 / 升级时从卡池抽牌
- 卡牌伤害为 **范围值**，由掷骰（d20）和角色基础属性决定
- **AP（行动点）** 每回合恢复，卡牌消耗 AP，移动消耗 AP
- 回合顺序由 **SPD（速度）** 决定，速度高者先行动

整个战斗引擎在 `demo/combat/` 中以纯 Python 实现，不依赖任何前端框架。同时提供了基于 **Textual** 的鼠标交互界面（`demo/tui_app.py`）和简单的终端输入界面（`demo/run_demo.py`）。

---

## 核心公式

### 属性映射（角色属性 → 战斗数值）

角色的 RP 属性（1-10 级）按以下公式转换为战斗数值：

| 战斗数值 | 英文名 | 公式 | 说明 |
|---------|--------|------|------|
| 生命值 | HP | `endurance × 12 + strength × 3` | 耐久是主要 HP 来源 |
| 物理攻击 | PATK | `(strength + combat_skill) × 2` | 物理伤害卡牌使用 |
| 法术攻击 | MATK | `(originium_arts + intelligence) × 2` | 法术伤害卡牌使用 |
| 治疗量 | HEAL | `(originium_arts + intelligence) × 2` | 治疗卡牌使用 |
| 物理防御 | DEF | `round(endurance × 1.5 + strength × 0.5)` | 减免物理伤害 |
| 法术抗性 | RES | `round(emotional_stability × 1.5 + originium_arts × 0.5)` | 减免法术伤害 |
| 速度 | SPD | `agility × 2 + intelligence × 0.5` | 决定回合顺序 |
| 命中 | HIT | `combat_skill + agility` | 攻击命中判定加值 |
| 闪避 | EVA | `round(agility × 1.5)` | 闪避判定 DC |

> 代码位置：`demo/combat/entity.py` → `CombatUnit.from_character_metadata()`

### 混合攻击的处理

当卡牌的 `damage_type` 为 `"mixed"`（混合伤害）时：
- ATK 取 `(PATK + MATK) / 2`
- 防御取 `min(DEF, RES)`

### 命中和闪避

```
攻击掷骰 = d20 + attacker.HIT
目标 DC  = 10 + defender.EVA

if 攻击掷骰 >= 目标 DC → 命中 (hit)
if d20 == 20            → 暴击 (crit, 伤害 ×2)
if d20 == 1             → 未命中 (miss, 伤害 = 0)
```

> 代码位置：`demo/combat/dice.py` → `check_hit()`

### 伤害计算

```
base_damage = random(card.min_damage, card.max_damage)
atk_bonus   = attacker.ATK × card.atk_scale     (如 0.4 为轻击, 1.0 为重击)
resist      = defender.DEF (物理) or defender.RES (法术)
raw         = base_damage + atk_bonus - resist
final       = max(1, round(raw × 2)) if crit else max(1, round(raw))
```

- 治疗无视抗性，不暴击：`final = max(0, round(raw))`
- 伤害保底 1 点

> 代码位置：`demo/combat/dice.py` → `compute_damage()`

### AP 系统

- 每单位 **每回合 3 AP**（可在 `entity.py` 中调整 `MAX_AP`）
- 卡牌消耗 1-3 AP
- 移动消耗 1 AP 每格

---

## 卡牌系统

### 卡牌数据结构

```python
@dataclass
class Card:
    card_id: str        # 唯一标识，如 "caster_bolt"
    name: str           # 中文名
    description: str    # 描述文字
    damage_type: str    # "physical" | "arts" | "healing" | "mixed"
    min_damage: int     # 基础伤害下限
    max_damage: int     # 基础伤害上限
    atk_scale: float    # ATK 倍率 (0.2 ~ 1.5)
    target: str         # 目标模式，见下方表格
    range: int          # 最大射程（切比雪夫距离），-1 为全图
    cost: int           # AP 消耗 (1-3)
    tier: str           # "basic"（普通，循环利用）| "elite"（精英，战后移除）
    class_required: str # 职业限制，"any" 表示通用
```

> 代码位置：`demo/combat/card.py`

### 目标模式一览

| 模式 | 英文字段 | 范围 | 说明 |
|------|---------|------|------|
| 单体 | `SINGLE` | — | 一个单元格 |
| 自身 | `SELF` | — | 施法者自身 |
| 相邻 | `ADJACENT` | — | 目标 + 4 个正交邻格 |
| 十字 | `CROSS` | — | 目标 + 8 格十字（范围 2） |
| 直线 3 | `LINE_3` | — | 3 格直线（默认右向） |
| 整行 | `ROW` | — | 目标所在行全部 |
| 2×2 区域 | `AREA_2X2` | — | 2×2 方块 |
| 全体友军 | `ALL_ALLIES` | — | 所有友方单位 |
| 全体敌军 | `GLOBAL` | — | 所有敌方单位 |

> 代码位置：`demo/combat/grid.py` → `resolve_targets()`

### 卡牌生命周期

```
牌库(Deck) → 抽牌(draw_to_hand) → 手牌(Hand)
                                      ↓ 使用(play_card)
                                    普通卡 → 弃牌堆(Discard)
                                    精英卡 → 耗尽堆(Exhaust，不回收)
                                          ↓ 牌库空时
                                    弃牌堆 → 洗牌 → 牌库
```

- 每回合自动补满手牌至 7 张
- 精英卡（elite）使用后永久移除（本场战斗内）
- 普通卡（basic）循环利用

> 代码位置：`demo/combat/card.py` → `CardPool`

### 职业卡池

8 个职业，每个职业 **5 张基础卡 + 3 张精英卡** = 共 64 张卡牌定义。

| 职业 | 基础卡 | 精英卡 | 特色 |
|------|--------|--------|------|
| 术师 | 能量弹、法术冲击、冰霜新星、源石风暴、法力灼烧 | 奥术飞弹、虚空风暴、灵魂烈焰 | 高法术 AOE |
| 近卫 | 斩击、横斩、重击、剑刃风暴、破甲斩 | 真银斩、赤霄拔刀、不屈意志 | 高物理近战 |
| 狙击 | 精准射击、连射、穿甲弹、狙击要害、箭雨 | 超远狙击、爆裂箭、致命一击 | 远程精准 |
| 重装 | 盾击、嘲讽打击、重甲冲撞、防御阵线、震荡锤击 | 不破壁垒、地震锤、坚不可摧 | 坦克 + 辅助 |
| 先锋 | 突刺、冲锋、连续打击、迅捷斩、侦察标记 | 闪电突袭、先锋号令、横扫千军 | 快速低费 |
| 医疗 | 治疗术、群体治疗、净化术、守护之盾、生命恢复 | 奇迹之愈、圣域、源石惩戒 | 治疗 |
| 辅助 | 减速术、削弱、束缚术、领域展开、干扰术 | 源石沉默、增幅过载、精神操控 | 控制 |
| 特种 | 位移术、背刺、陷阱、暗影步、闪避姿态 | 处决、烟雾弹、伏击 | 混合特殊 |

> 代码位置：`demo/combat/card_data.py`

---

## 站位系统

### 网格布局

```
0   1   2       3   4   5   6   7
┌───┬───┬───┐ ┌───┬───┬───┬───┬───┐
│ 博 │ 阿 │ 闪 │ │ 士 │ 盾 │   │ 术 │   │   Row 0
├───┼───┼───┤ ├───┼───┼───┼───┼───┤
│   │ 银 │   │ │   │   │ 狙 │   │ 士 │   Row 1
├───┼───┼───┤ ├───┼───┼───┼───┼───┤
│   │   │   │ │   │   │   │   │   │       Row 2
└───┴───┴───┘ ├───┼───┼───┼───┼───┤
                │   │   │   │   │   │   Row 3
                └───┴───┴───┴───┴───┘
玩家方阵 3×3      敌方方阵 4×5
(列 0-2)          (列 3-7)
```

- **逻辑坐标**: `(row, col)`，左上角原点
- **距离计算**: 切比雪夫距离 `max(|dx|, |dy|)`
- 玩家只能在己方区域内移动（列 0-2）
- 敌人只能在敌方区域内移动（列 3-7）
- `(-1, -1)` 表示未放置

### 移动规则

- 曼哈顿距离内移动，消耗 AP
- 目标格必须在己方区域内
- 目标格不能被其他单位占据

> 代码位置：`demo/combat/grid.py`

---

## 回合制状态机

### 状态流转

```
INIT → ROUND_START → PLAYER_TURN ⇄ ENEMY_TURN (循环) → ROUND_END
         ↑                                                    │
         └────────────── (所有单位行动完毕) ←─────────────────┘
```

### 各阶段详解

| 阶段 | 英文 | 行为 |
|------|------|------|
| 初始化 | `INIT` | 放置单位、洗牌、掷先攻（SPD 排序） |
| 回合开始 | `ROUND_START` | 全体恢复 AP、补满手牌、更新回合顺序 |
| 玩家回合 | `PLAYER_TURN` | 等待玩家输入（选牌 / 移动 / 结束） |
| 敌方回合 | `ENEMY_TURN` | AI 自动行动（选牌 / 移动） |
| 回合结束 | `ROUND_END` | 检查胜负条件 |
| 结束 | `END` | 显示胜负结果 |

### 事件系统

引擎通过 `CombatEvent` 回调通知 UI：

| 事件类型 | 触发时机 | 关键字段 |
|---------|---------|---------|
| `battle_start` | 战斗开始 | `round` |
| `round_start` | 新回合开始 | `round` |
| `turn_start` | 单位获得行动权 | `unit_id`, `name`, `team`, `ap` |
| `damage` | 造成伤害 | `caster`, `target`, `damage`, `hit_result`, `card` |
| `heal` | 治疗 | `caster`, `target`, `amount`, `card` |
| `death` | 单位死亡 | `unit_id`, `name`, `team` |
| `battle_end` | 战斗结束 | `winner`, `reason` |
| `error` | 操作失败 | `unit_id`, `msg` |

> 代码位置：`demo/combat/engine.py` → `CombatEngine`

---

## 敌方 AI

简单贪心策略，每回合：

1. 找到距离最近的存活的玩家单位
2. 筛选可负担的卡牌（`cost <= AP`）
3. 如有可用的攻击卡且在射程内 → 打出伤害最高的那张
4. 如有 AP 但无法攻击 → 向最近玩家移动一步（切比雪夫方向）
5. 无法行动 → 跳过

> 代码位置：`demo/combat/engine.py` → `execute_enemy_turn()`

---

## 数据结构定义

### HitResult — 命中结果

```python
@dataclass
class HitResult:
    roll: int   # d20 投掷结果 (1-20)
    hit:  bool  # 是否命中
    crit: bool  # 是否暴击 (nat 20)
    miss: bool  # 是否未命中 (nat 1)
```

### DamageResult — 伤害结果

```python
@dataclass
class DamageResult:
    base_damage: int     # 骰子基础伤害
    atk_bonus:  float    # ATK × atk_scale
    resist:     int      # DEF 或 RES
    raw:        float    # 减免后伤害
    final:      int      # 最终伤害（取整，至少 1）
    damage_type: str     # 伤害类型
    hit:        HitResult
```

### CombatUnit — 战斗单位

```python
@dataclass
class CombatUnit:
    unit_id: str           # 唯一标识
    name: str              # 中文名称
    team: str              # "player" | "enemy"
    char_class: str        # 职业
    # 战斗数值
    max_hp: int
    hp: int
    PATK: float
    MATK: float
    HEAL: float
    DEF: int
    RES: int
    SPD: float
    HIT: int
    EVA: int
    # 行动
    AP: int
    MAX_AP: int
    # 来源
    attributes: dict       # 原始 RP 属性
    pos: tuple[int,int]    # 网格位置
```

### CardPool — 卡池

```python
@dataclass
class CardPool:
    deck: list[Card]       # 牌库（待抽）
    hand: list[Card]       # 手牌（最多 7 张）
    discard: list[Card]    # 弃牌堆（普通卡用后进入）
    exhaust: list[Card]    # 耗尽堆（精英卡用后永久移除）
    hand_size: int = 7
```

---

## 与项目集成的 markdown 数据模型

### 设计原则

遵循项目现有的 **YAML frontmatter + Markdown body** 数据存储模式：

1. 所有战斗相关数据以 `.md` 文件存储
2. 元数据在 `---` YAML frontmatter 中
3. 描述性文字在 Markdown body 中（`## ` 标题分段）
4. 注册在 `data/_INDEX.md` 和子 `_index.md` 中
5. 使用项目已有的 `frontmatter` 库加载
6. 字段 key 使用英文，显示用中文

### 建议新增的数据目录结构

```
data/
├── _INDEX.md                  ← 新增 "enemies", "combat_cards" 分类
├── combat/
│   ├── _index.md              ← 战斗系统总索引
│   ├── TEMPLATE_enemy.md      ← 敌人模板
│   ├── TEMPLATE_card.md       ← 卡牌模板
│   ├── enemies/
│   │   ├── _index.md          ← 敌人索引
│   │   ├── 整合运动士兵.md
│   │   ├── 整合运动术师.md
│   │   ├── 萨卡兹百夫长.md
│   │   └── ...
│   └── cards/
│       ├── _index.md          ← 卡牌索引（按职业分类）
│       ├── 术师/
│       │   └── ... (每张卡一个 .md)
│       └── ...
```

### 敌人 markdown 模板

文件路径示例：`data/combat/enemies/整合运动士兵.md`

```markdown
---
name: "整合运动士兵"
alias: "Reunion Soldier"
class: "近卫"              # 对应 data/classes/ 的职业
race: "未知"
faction: "整合运动"         # 对应 data/factions/
tags: ["基础敌人", "近战"]
level: 1                   # 等级（1-10，影响基础数值倍率）
combat_stats:
  hp: 90                   # 基础生命值
  patk: 12                 # 基础物理攻击
  matk: 8                  # 基础法术攻击
  defense: 5               # 基础物理防御
  resist: 4                # 基础法术抗性
  spd: 9                   # 速度（决定回合顺序）
  hit: 6                   # 命中加值
  eva: 5                   # 闪避值
  max_ap: 3                # 每回合最大行动点
ai_behavior: "aggressive"  # aggressive | defensive | support | balanced
ai_skills:                 # AI 可用的卡牌 ID 列表
  - "enemy_atk"
  - "enemy_heavy"
  - "enemy_aoe"
drop_items:                # 战利品
  - "基础源石碎片"
drop_rate: 0.3             # 掉落概率
xp_reward: 50              # 击败经验值
---

## 描述

整合运动的基础步兵单位，装备简陋但数量众多。

## 战斗特点

- 倾向于使用基础攻击卡
- 血量较低时可能会使用重击
- 周围有多个玩家单位时会使用横扫

## 战术建议

优先消灭术师后再处理士兵，避免被数量压制。
```

对应的 frontmatter 各字段含义：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 中文名 |
| `alias` | string | 英文名/ID |
| `class` | string | 职业（引用 `data/classes/`） |
| `race` | string | 种族（引用 `data/races/`） |
| `faction` | string | 阵营（引用 `data/factions/`） |
| `tags` | list | 标签 |
| `level` | int | 1-10 等级，影响基础数值倍率 |
| `combat_stats` | dict | 战斗数值（直接用数值，不映射 RP 属性） |
| `ai_behavior` | enum | AI 行为模式 |
| `ai_skills` | list | AI 技能卡 ID 列表 |
| `drop_items` | list | 可能掉落的物品 |
| `drop_rate` | float | 掉落概率 |
| `xp_reward` | int | 击败经验值 |

### 卡牌 markdown 模板

文件路径示例：`data/combat/cards/术师/能量弹.md`

```markdown
---
card_id: "caster_bolt"
name: "能量弹"
description: "发射一枚源石能量弹"
class_required: "术师"      # 职业限制，"any" 为通用
tier: "basic"               # basic | elite
damage_type: "arts"         # physical | arts | healing | mixed
min_damage: 4               # 基础伤害下限
max_damage: 8               # 基础伤害上限
atk_scale: 0.4              # ATK 倍率
target: "SINGLE"            # 目标模式
range: 3                    # 射程（切比雪夫距离），-1 为全图
cost: 1                     # AP 消耗
upgrade_to: "caster_bolt_2" # 可升级到的卡牌 ID（可选）
tags: ["源石技艺", "基础"]
---

## 效果描述

凝聚一颗高密度源石能量弹射向单个敌人，
造成法术伤害。是最基础的术师攻击手段。

## 使用建议

- 消耗低，适合作为常规输出手段
- 对高 RES 敌人效果较差，优先攻击低 RES 目标

## 升级路线

能量弹 → 强化能量弹（伤害 +2，倍率 +0.1）
```

### 角色属性扩展（加入到 data/characters/ 的 frontmatter）

角色现有的 `attributes` 字段已包含 8 个 1-10 属性，足以驱动战斗公式。无需额外字段。

但建议在角色 frontmatter 中新增可选字段，用于覆盖战斗系统默认行为：

```markdown
---
name: "阿米娅"
class: "术师"
attributes:
  strength: 6
  intelligence: 9
  # ...
combat_override:           # 可选：覆盖公式计算的战斗数值
  max_ap: 4                # 例：阿米娅每回合有 4 AP
starting_cards:            # 初始卡牌（覆盖默认随机抽取）
  - "caster_bolt"
  - "caster_shock"
  - "caster_nova"
  - "caster_burn"
elite_cards:               # 精英卡（升级时可选）
  - "caster_void"
---
```

### 战斗遭遇 markdown 模板（可选）

文件路径示例：`data/combat/encounters/初遇整合运动.md`

```markdown
---
encounter_id: "enc_first_reunion"
name: "初遇整合运动"
category: "story"           # story | random | boss
difficulty: 2               # 1-10 难度评级
waves:
  - enemies:
      - enemy: "整合运动士兵"
        count: 2
        positions: [[0, 4], [2, 5]]
      - enemy: "整合运动术师"
        count: 1
        positions: [[1, 4]]
conditions:
  max_rounds: 30            # 回合上限（0 = 无限制）
  escape_enabled: true      # 是否可以逃跑
rewards:
  xp: 200
  items: ["基础源石碎片"]
  unlock: []                # 解锁的剧情/地点
trigger_plot: "plot_first_encounter"  # 关联剧情
---

## 战斗描述

罗德岛小队首次遭遇整合运动巡逻队。
敌人数量不多，是测试战斗系统的入门战。

## 对话触发

- 回合 1 开始：博士 "准备迎战！"
- 首个敌人死亡：整合运动士兵 "撤退！请求支援！"
- 胜利：阿米娅 "这只是开始..."
```

### 集成到现有的数据加载管线

1. **注册新分类**：在 `data/_INDEX.md` 的 `index` 中添加：
```yaml
combat_enemies:
  directory: "data/combat/enemies"
  _index: "data/combat/_index.md"
combat_cards:
  directory: "data/combat/cards"
  _index: "data/combat/_index.md"
```

2. **注册子索引**：创建 `data/combat/_index.md`，包含 enemies 和 cards 的子索引

3. **扩展 RegistryManager**：在 `_CORE_SECTIONS` 中添加核心段落提取规则，并新增 `load_enemy()` / `load_card()` / `build_enemy_context()` 方法

4. **扩展 API**：在 `app.py` 中添加 REST 端点（可选，如不与前端交互则不需要）

5. **创建 EnemyFactory**：在引擎中新增 `EnemyFactory.from_markdown(path)` 替代当前的 `CombatUnit.create_enemy()` 硬编码

---

## 集成路线图

### Phase 1: 数据层（不修改引擎）

- [ ] 创建 `data/combat/` 目录结构
- [ ] 编写敌人模板 `TEMPLATE_enemy.md` 和卡牌模板 `TEMPLATE_card.md`
- [ ] 将现有的 4 个 demo 敌人转为 markdown 文件
- [ ] 将 64 张卡牌定义转为 markdown 文件（按职业分目录）
- [ ] 在 `data/_INDEX.md` 注册新分类
- [ ] 创建 `data/combat/_index.md`

### Phase 2: 加载管线

- [ ] 扩展 `RegistryManager`：
  - `load_enemy(enemy_key)` → 解析 markdown frontmatter
  - `load_cards_for_class(char_class)` → 从 markdown 加载卡池
  - `build_enemy_context(enemy)` → 为 LLM 场景描述提供敌人信息
- [ ] 创建 `CombatDataLoader` 类：
  - `from_enemy_md(path) → CombatUnit`
  - `from_card_md(path) → Card`
  - 处理属性映射公式

### Phase 3: 引擎集成

- [ ] 将 `demo/combat/` 提升为 `src/combat/`（或保持在 demo 中作为独立模块）
- [ ] 修改 `setup_battle()` 使用 `CombatDataLoader` 而不是硬编码数值
- [ ] 实现战斗遭遇系统（从 `data/combat/encounters/` 加载）
- [ ] 添加等级缩放：`final_stat = base_stat × level_multiplier(level)`

### Phase 4: 前端集成（远期）

- [ ] Flask 端点：`POST /api/combat/start` — 开始战斗
- [ ] WebSocket 战斗状态推送（替代 Textual 的事件回调）
- [ ] React 组件：战斗网格 + 手牌 UI（参考 Textual 的实现）
- [ ] 战斗动画和特效

---

## demo 文件索引

```
demo/
├── combat/
│   ├── __init__.py
│   ├── entity.py        # CombatUnit — 属性映射、伤害/治疗
│   ├── grid.py           # Grid — 4×8 网格、目标模式、距离
│   ├── card.py           # Card、CardPool — 卡牌生命周期
│   ├── card_data.py      # 64 张卡牌定义（8 职业 × 8 张）
│   ├── engine.py         # CombatEngine — 状态机、AI、事件
│   ├── dice.py           # 命中判定、伤害计算
│   └── renderer.py       # ASCII 终端渲染（已弃用，保留参考）
├── run_demo.py           # 终端键盘交互 demo（保留）
├── tui_app.py            # Textual 鼠标交互界面（当前推荐）
└── tui_widgets.py        # Textual 自定义控件
```

### 关键文件对应关系

| 需求 | 现有组件 | 集成后替代 |
|------|---------|-----------|
| 敌人数据 | `CombatUnit.create_enemy()` 硬编码 | `CombatDataLoader.from_enemy_md()` |
| 卡牌数据 | `card_data.py` 硬编码 | 从 `data/combat/cards/` markdown 加载 |
| 战斗遭遇 | `run_demo.py` 中的 `ENEMY_DEFS` | 从 `data/combat/encounters/` 加载 |
| 角色属性 | `CombatUnit.from_character_metadata()` | 直接从角色 `.md` 的 `attributes` 字段映射 |
| 职业卡池 | `get_starting_deck(char_class)` | 从 `data/combat/cards/<职业>/` 加载 |

---

*本文档随 `demo/combat/` 代码演进同步更新。最后一版代码验证：所有 30 场自动战斗测试通过，4v4 完整战斗在 4-13 回合内正常终结。*
