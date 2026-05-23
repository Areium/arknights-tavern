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
6. [遗物系统（物品被动）](#遗物系统物品被动)
7. [站位系统](#站位系统)
8. [回合制状态机](#回合制状态机)
9. [敌方 AI](#敌方-ai)
10. [数据结构定义](#数据结构定义)
11. [与项目集成的 markdown 数据模型](#与项目集成的-markdown-数据模型)
12. [集成路线图](#集成路线图)
13. [Web 架构设计](#web-架构设计) ← 前后端集成方案
14. [demo 文件索引](#demo-文件索引)

---

## 概述

战斗系统采用 **回合制卡牌** 模式，受 Slay the Spire 启发：

- **4 人小队**，站位在 3×3 玩家方阵，敌方 4×5 方阵
- 每个角色拥有基于 **职业** 的个人卡池，获取角色 / 升级时从卡池抽牌
- 卡牌伤害为 **范围值**，由掷骰（d20）和角色基础属性决定
- **AP（行动点）** 每回合恢复，卡牌消耗 AP，移动消耗 AP
- 回合顺序由 **SPD（速度）** 决定，速度高者先行动

整个战斗引擎在 `demo/combat/` 中以纯 Python 实现，不依赖任何前端框架。同时提供了基于 **Textual** 的鼠标交互界面（`demo/tui_app.py`）和简单的终端输入界面（`demo/run_demo.py`）。

**目标架构**：将战斗引擎集成到项目的 **Flask 后端 + React 前端** 架构中。Flask 提供 REST + SSE 接口驱动战斗状态机，React 负责渲染网格、手牌和战斗事件。详见 [Web 架构设计](#web-架构设计) 章节。

---

## 核心公式

### 属性映射（角色属性 → 战斗数值）

角色的 RP 属性（1-10 级）按以下公式转换为战斗数值。

#### 属性 key 对照

项目属性已重命名为明日方舟正典术语。战斗系统需要同时兼容新旧 key 和中英文 key：

| 新 key（英文） | 新 key（中文） | 旧 key | 战斗用途 |
|---|---|---|---|
| `physical_strength` | `物理强度` | `strength` | PATK, DEF, HP |
| `mobility` | `战场机动` | `agility` | SPD, HIT, EVA |
| `physiological_tolerance` | `生理耐受` | `endurance` | HP, DEF |
| `tactical_planning` | `战术规划` | `intelligence` | MATK, HEAL, SPD |
| `originium_arts_assimilation` | `源石技艺适应性` | `originium_arts` | MATK, HEAL, RES |
| `combat_skill` | `战斗技巧` | — (不变) | PATK, HIT |
| `emotional_stability` | `情绪稳定性` | — (不变) | RES |
| `charisma` | `魅力` | — (不变) | RP 用途，暂无战斗映射 |

#### 战斗数值换算公式（使用新 key）

| 战斗数值 | 公式 |
|---------|------|
| HP | `physiological_tolerance × 12 + physical_strength × 3` |
| PATK | `(physical_strength + combat_skill) × 2` |
| MATK | `(originium_arts_assimilation + tactical_planning) × 2` |
| HEAL | `(originium_arts_assimilation + tactical_planning) × 2` |
| DEF | `round(physiological_tolerance × 1.5 + physical_strength × 0.5)` |
| RES | `round(emotional_stability × 1.5 + originium_arts_assimilation × 0.5)` |
| SPD | `mobility × 2 + tactical_planning × 0.5` |
| HIT | `combat_skill + mobility` |
| EVA | `round(mobility × 1.5)` |

缺失属性默认值：**5**（标准成人水平）。

> 代码位置：`demo/combat/entity.py` → `CombatUnit.from_character_metadata()`
> 
> 集成到后端时需加入属性 key 兼容层（见 [差距分析](./combat-integration-gap-analysis.md#一属性系统变化关键demo-公式需要更新)）。

#### d20 修正系统（可选集成）

远程数据为每个属性等级定义了 d20 修正值，可用于命中/暴击/技能检定的加值：

| 等级 | 评级 | d20 修正 |
|------|------|---------|
| 1-2 | 缺陷 | -3 ~ -2 |
| 3-4 | 普通 | -1 |
| 5-6 | 标准 | 0 ~ +1 |
| 7-8 | 优良 | +1 ~ +2 |
| 9-10 | 卓越 | +3 ~ +4 |

**建议**：保留当前的属性→战斗数值公式（需要 HP/ATK/DEF 做减法运算），但用 d20 修正取代当前的 HIT/EVA 判定，统一为 d20 + mod 体系。

### AP 系统（重设计）

#### 双 AP 池模型

战斗使用两套独立的 AP 池：

| AP 池 | 来源 | 用途 | 每轮重置 |
|-------|------|------|---------|
| **个人 AP** | 每个角色的 `mobility`（战场机动） | 打出该角色的**专属牌**和**职业牌** | 是 |
| **共用 AP** | 队伍中最高 `tactical_planning`（战术规划） | 打出**通用牌**（class_required="any"） | 是 |

共用 AP 消耗规则：先用共用 AP → 共用 AP 不足时，可用当前行动角色的个人 AP 补足 → 仍不足则无法打出。

#### 个人 AP 公式

```
个人 AP = 1 + floor((mobility - 3) / 3)

mobility 1-3   → 1 AP  (迟缓)
mobility 4-6   → 2 AP  (标准 — 阿米娅、霜星、闪灵)
mobility 7-9   → 3 AP  (迅捷 — 银灰、德克萨斯、陈)
mobility 10    → 4 AP  (极速)
```

#### 共用 AP 公式

```
共用 AP = 2 + floor((队伍最高 tactical_planning - 5) / 3)

队伍最高战术规划 = 5  → 共用 AP = 2
队伍最高战术规划 = 8  → 共用 AP = 3
队伍最高战术规划 = 10 → 共用 AP = 4
```

> 共用 AP 来源与具体角色解耦。无论玩家扮演谁，只要队伍中有人擅长战术规划，就能获得共用 AP。

#### SPD（mobility）的角色（重设计）

SPD **不再决定回合顺序**。改为三个用途：

| 用途 | 说明 |
|------|------|
| **初始 AP 值** | 高 mobility → 更多个人 AP（见上表） |
| **移动效率** | mobility ≥ 7 → 1 AP 可移动 2 格；mobility ≥ 10 → 3 格/AP；其余 1 格/AP |
| **拦截机会** | mobility ≥ 7 → 每轮 1 次主动拦截；mobility ≥ 9 → 2 次。敌方回合可选挡刀 |

#### 回合顺序（卡牌驱动）

回合顺序**不是由玩家自由选择角色**，而是**由卡牌决定谁行动**：

```
共享手牌(6张)
  ├─ 陈专属牌 → 陈的卡牌 → 陈行动（消耗陈的个人 AP）
  ├─ 术师职业牌 → 阿米娅/霜星可用的卡牌 → 选中者行动
  ├─ 通用牌 → 任何人可用 → 消耗共用 AP
  └─ ...

玩家点击一张卡牌 → 系统自动确定：
  ① 谁行动（专属牌=固定，职业牌=同职业中选，通用牌=任意人）
  ② AP 消耗来源（个人 vs 共用）
  ③ 若 AP 不足 → 卡牌灰显，无法选择
```

**结果**：手牌本身就是"行动菜单"。可打出的牌亮起，打不出的灰显。玩家不需要先选角色再找牌，流程更自然。同一角色有多张可打出的牌时，玩家可以连续打多张，直到该角色个人 AP 耗尽或无可用的牌。

#### 重装挡刀被动

重装职业角色拥有独立于 SPD 的被动挡刀能力：

```
触发条件（全部满足）：
  ① 敌人使用单体攻击（非 AOE）指向友方单位
  ② 重装存活且非攻击目标本身
  ③ 从敌人到目标的 Bresenham 线段经过重装所在格或其邻格
  ④ 重装与目标切比雪夫距离 ≤ 2

挡刀成功率 = 30%（基础） + 5% × 重装的 physiological_tolerance
  physiological_tolerance = 5  → 55%
  physiological_tolerance = 8  → 70%
  physiological_tolerance = 10 → 80%

成功：伤害重定向到重装，使用重装的 DEF/RES 计算减免
失败：伤害正常结算
```

主动拦截（高 SPD）与被动挡刀（重装）形成互补：前者可靠但消耗资源，后者自动但看概率。

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
atk_bonus   = attacker.ATK × card.atk_scale
resist      = defender.DEF (物理) or defender.RES (法术)
raw         = base_damage + atk_bonus - resist
final       = max(1, round(raw × 2)) if crit else max(1, round(raw))
```

- 治疗无视抗性，不暴击：`final = max(0, round(raw))`
- 伤害保底 1 点

> 代码位置：`demo/combat/dice.py` → `compute_damage()`

---

## 卡牌系统（重设计）

### 三种卡牌类别

| 类别 | 标识 | 谁能用 | 消耗 | 示例 |
|------|------|--------|------|------|
| **专属牌** | `owner: "陈"` | 仅指定角色 | 该角色个人 AP | 赤霄拔刀（陈专属） |
| **职业牌** | `class_required: "术师"` | 该职业任意角色 | 打出者个人 AP | 能量弹（术师通用） |
| **通用牌** | `class_required: "any"` | 任何角色 | 共用 AP（不足时个人补） | 治疗药剂、防御姿态 |

专属牌相比同类职业牌 ATK 倍率高 20-30%，体现角色专属的价值。

### 共享手牌 + 牌库模型

```
共享牌库 (28张 = 4角色 × 7张)
       │
       ▼ 每轮补满至 6 张
共享手牌 (6张)
       │
       ▼ 玩家选择角色行动
角色A(个人AP) 打专属牌/职业牌
角色B(个人AP) 打专属牌/职业牌
任意角色     打通用牌(消耗共用AP)
```

| 参数 | 值 | 说明 |
|------|-----|------|
| 每位角色携带牌数 | 7 张 | 组成共享牌库 |
| 共享牌库总量 | 28 张（4 人） | |
| 共享手牌上限 | **6 张** | 始终可见，支持提前规划 |
| 每轮抽牌 | 补满至 6 张 | 手牌跨轮保留 |
| 每轮手牌刷新率 | ~70%（4-5 张新牌） | 保留 1-2 张未用的旧牌 |
| 完整牌库循环 | ~6-7 轮 | 匹配 4-13 轮典型战斗长度 |
| 角色保底 | 若某存活角色手牌中无可用牌，强制换入 1 张该角色随机牌 | 避免"全程没牌可出" |

### 卡牌数据结构

```python
@dataclass
class Card:
    card_id: str          # 唯一标识
    name: str             # 中文名
    description: str      # 描述文字
    damage_type: str      # "physical" | "arts" | "healing" | "mixed"
    min_damage: int       # 基础伤害下限
    max_damage: int       # 基础伤害上限
    atk_scale: float      # ATK 倍率 (0.2 ~ 1.5)
    target: str           # 目标模式
    range: int            # 最大射程（切比雪夫距离），-1 为全图
    cost: int             # AP 消耗 (1-3)
    tier: str             # "basic"（循环利用）| "elite"（战后移除）
    class_required: str   # 职业限制，"any" 表示通用牌
    owner: str | None     # 角色专属标识，null 表示非专属
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

### 卡牌生命周期（共享牌库版）

```
共享牌库(28张) → 抽牌(补满至6) → 共享手牌(6张)
                                      ↓ 使用(play_card)
                                    基本牌 → 弃牌堆(Discard)
                                    精英牌 → 耗尽堆(Exhaust)
                                          ↓ 牌库 + 手牌总计不足6张时
                                    弃牌堆 → 洗牌 → 牌库
```

- 每回合补满共享手牌至 **6 张**（不是每个角色单独抽）
- 精英卡（elite）使用后永久移除（本场战斗内）
- 基本卡（basic）循环利用
- 角色保底：补牌时若某存活角色在手牌中无任何可用牌，强制替换一张手牌为该角色的随机牌

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

## 遗物系统（物品被动）

物品在战斗中作为**被动遗物**生效，类似于 Slay the Spire 的遗物机制——战前配置，战斗全程自动生效，不需要主动使用。

### 设计原则

- **不设计战斗专属消耗品**。方舟 8 个职业已覆盖治疗（医疗）、增益（辅助）、控制（辅助/特种）、 debuff（辅助）等所有战术需求，无需物品来填补
- 物品只提供**被动效果**，不进入手牌、不消耗 AP、不需要快捷栏
- 每个角色可携带 **1-2 件**遗物进入战斗
- 遗物效果在 `data/items/` 的 frontmatter 中定义，复用现有物品数据

### 现有物品的遗物映射

| 物品 | 携带者 | 遗物效果 |
|------|--------|---------|
| 博士的战术终端 | 博士 / 玩家角色 | 共用 AP +1（指挥能力加成） |
| 抑制戒指 | 阿米娅 | RES +3，免疫"源石技艺失控"类 debuff |
| 战术地图 | 任意角色 | 战斗开始时，揭示敌方 4×5 部署区中随机 3 格已占位（情报优势） |
| 源石结晶 | 术师角色 | MATK +3（施法媒介加成） |
| 罗德岛干员证 | — | 无战斗效果（纯剧情物品） |

### 物品 frontmatter 扩展

在现有物品 markdown 中新增 `combat_passive` 字段：

```yaml
# data/items/抑制戒指/index.md（现有字段保留，新增以下）
combat_passive:
  stats:
    res: +3
  immunity: ["originium_overload", "fear"]
  condition: "wearer_class=术师"    # 生效条件（可选），不填则无条件生效
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `stats` | dict | 战斗数值加成（patk/matk/def/res/hp/eva/hit/spd/max_ap） |
| `immunity` | list | 免疫的 debuff ID 列表 |
| `condition` | str | 生效条件表达式（如 "wearer_class=术师"、"hp_below_50%"） |
| `aura` | dict | 光环效果（影响相邻友军），如 `{range: 2, stat: def, value: 2}` |

### 与卡牌/职业的分工

```
职业体系 ─→ 战斗中的主动能力（卡牌 = 治疗/伤害/控制/增益）
遗物系统 ─→ 战斗中的被动加成（属性提升/免疫/情报/光环）
```

这套分工让物品系统保持轻量——不需要设计消耗品的使用时机、AP 成本、快捷栏 UI。物品就是"你带了就有"的被动加成，和 Slay the Spire 遗物一样简单。

---

## 站位系统（重设计）

### n×n 网格

战场为 n×n 的正方形网格，大小由遭遇类型决定：

| 遭遇规模 | 网格 | 适用场景 |
|---------|------|---------|
| 小型 | 6×6 | 狭路相逢、室内战斗 |
| 标准 | 8×8 | 大多数遭遇 |
| 大型 | 10×10 | Boss 战、大规模冲突 |

### 部署区

玩家部署区固定为**左侧正中间 3×3**，敌方部署区为**右侧正中间 4×5**（横向位置随机微调）：

```yaml
# 遭遇 markdown 示例
grid_size: 8
deploy_zones:
  player: [[2, 0], [4, 2]]          # 左中 3×3（rows 2-4, cols 0-2）
  enemy:  [[2, 3], [5, 7]]          # 右中 4×5（rows 2-5, cols 3-7）
  enemy_random_shift: true           # 敌方 4×5 横向可在 ±1 列范围内随机偏移
```

```
8×8 网格示意:
  0 1 2 3 4 5 6 7
0 . . . . . . . .
1 . . . . . . . .
2 █ █ █ . ▓ ▓ ▓ ▓ ▓     █ = 玩家部署区 (3×3) — 固定左中
3 █ █ █ . ▓ ▓ ▓ ▓ ▓     ▓ = 敌方部署区 (4×5) — 右中，横向随机 ±1
4 █ █ █ . ▓ ▓ ▓ ▓ ▓
5 . . . . ▓ ▓ ▓ ▓ ▓
6 . . . . . . . .
7 . . . . . . . .
```

- **玩家**：始终 3×3，左侧正中间（8×8 下为 rows 2-4, cols 0-2）
- **敌方**：4 行 × 5 列，右侧正中间（8×8 下为 rows 2-5, cols 3-7），`enemy_random_shift` 控制起点的 ±1 随机偏移
- col 2-3 之间为天然分界线，两方初始距离最近仅 1 列

### 移动规则

- 移动消耗 **1 AP 每格**（基础）
- **移动效率加成**：mobility ≥ 7 → 1 AP 移动 2 格；mobility ≥ 10 → 3 格/AP
- 移动使用**曼哈顿距离**（上下左右，不可斜走）
- 目标格不能有其他单位占据
- 移动范围不受阵营限制——角色可以移动到棋盘上任何空位
- 经过敌方单位邻格时无惩罚（无"借机攻击"概念）

### 距离计算

距离使用**切比雪夫距离**：`max(|row_diff|, |col_diff|)`

这对应"王棋移动"——斜走与直走等价，攻击范围判定以此为基准。

> 代码位置：`demo/combat/grid.py`

---

## 回合制状态机

### 状态流转

```
INIT → ROUND_START → PLAYER_PHASE (卡牌驱动) → ENEMY_TURN → ROUND_END
         ↑                │                          │            │
         │    共享手牌→点击卡牌→自动确定角色              │            │
         │    专属牌→该角色  职业牌→同职业选一              │            │
         │    通用牌→任意人(扣共用AP)                    │            │
         │         全部角色AP耗尽或手动结束 ←───────────┘            │
         │    敌方攻击时触发拦截判定 ←──────────────────────────────┘
         └─────────────────────────────────────────────────────────┘
```

### 各阶段详解

| 阶段 | 行为 |
|------|------|
| `INIT` | 读入遭遇数据 → 创建 n×n 网格 → 部署单位 → 组建共享牌库(28张) → 洗牌 |
| `ROUND_START` | 全体重置个人AP + 共用AP → 共享手牌补满至6张 |
| `PLAYER_PHASE` | 共享手牌展示可打出的牌（AP不足者灰显）；玩家**点击卡牌**→ 自动确定行动角色→ 打出；全部角色AP耗尽或手动结束 |
| `ENEMY_TURN` | AI 依次行动，每次攻击前检查拦截条件（重装被动挡刀 + 高SPD主动拦截提示） |
| `ROUND_END` | 检查胜负条件 |
| `END` | 结算画面 |

### 事件系统

引擎通过 `CombatEvent` 回调通知 UI，新增拦截相关事件：

| 事件类型 | 触发时机 | 关键字段 |
|---------|---------|---------|
| `battle_start` | 战斗开始 | `round` |
| `round_start` | 新回合开始 | `round` |
| `turn_start` | 角色被激活行动 | `unit_id`, `name`, `team`, `personal_ap`, `shared_ap` |
| `damage` | 造成伤害 | `caster`, `target`, `damage`, `hit_result`, `card` |
| `heal` | 治疗 | `caster`, `target`, `amount`, `card` |
| `block_attempt` | 挡刀判定触发 | `defender`, `target`, `attacker` |
| `block_success` | 挡刀成功 | `defender`, `redirected_damage` |
| `block_fail` | 挡刀失败 | `defender` |
| `intercept_prompt` | 主动拦截机会 | `available_units` (可拦截的角色列表) |
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

### 战斗遭遇 markdown 模板

文件路径示例：`data/combat/encounters/初遇整合运动.md`

```markdown
---
encounter_id: "enc_first_reunion"
name: "初遇整合运动"
category: "story"              # story | random | boss
difficulty: 2                  # 1-10 难度评级
grid_size: 8                   # n×n 网格大小
deploy_zones:
  player: [[0, 0], [2, 2]]    # 玩家部署区（左上角 3×3）
  enemy:  [[5, 5], [7, 7]]    # 敌方部署区（右下角 3×3）
waves:
  - enemies:
      - enemy: "整合运动士兵"
        count: 2
        positions: [[5, 5], [6, 6]]
      - enemy: "整合运动术师"
        count: 1
        positions: [[7, 6]]
conditions:
  max_rounds: 30               # 回合上限（0 = 无限制）
  escape_enabled: true         # 是否可以逃跑
rewards:
  xp: 200
  items: ["基础源石碎片"]
  unlock: []                   # 解锁的剧情/地点
trigger_plot: "plot_first_encounter"
---
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

### Phase 1: 数据层（P0 — 不修改引擎）

- [ ] 创建 `data/combat/` 目录结构（`enemies/`、`cards/`、`encounters/`）
- [ ] 编写敌人模板 `TEMPLATE_enemy.md` 和卡牌模板 `TEMPLATE_card.md`
- [ ] 将现有的 4 个 demo 敌人转为 markdown 文件
- [ ] 将 64 张卡牌定义转为 markdown 文件（按职业分目录）
- [ ] 创建 `data/classes/战术指挥/index.md` 职业定义
- [ ] 补全博士的 8 属性
- [ ] 在 `data/_INDEX.md` 注册新分类
- [ ] 创建 `data/combat/_index.md`

### Phase 2: 属性兼容 + 加载管线（P0/P1）

- [ ] 更新 `entity.py` 的属性 key 映射表：
  - 旧 key → 新 key（`strength` → `physical_strength` 等）
  - 中文 key → 英文 key（`物理强度` → `physical_strength` 等）
  - 缺失属性默认值 5
- [ ] 创建 `CombatDataLoader` 类：
  - `from_enemy_md(path) → CombatUnit`
  - `from_card_md(path) → Card`
  - `from_encounter_md(path) → encounter_config`
- [ ] 扩展 `RegistryManager` 以支持战斗数据类型
- [ ] 将 `demo/combat/` 从 demo 目录提升/导入到 `src/` 后端可引用的位置

### Phase 3: 后端 API 层

- [ ] 实现 `CombatSession` 类（服务端战斗会话管理）
- [ ] 实现 `CombatDataLoader`（从 markdown 加载敌人/卡牌/遭遇）
- [ ] 在 `app.py` 中添加战斗 API 端点：
  - `POST /api/sessions/<id>/combat/start`
  - `GET /api/sessions/<id>/combat/state`
  - `POST /api/sessions/<id>/combat/action`
  - `POST /api/sessions/<id>/combat/end-turn`
  - `GET /api/sessions/<id>/combat/events` (SSE)
- [ ] 在 `Session` 类中集成 `CombatSession`
- [ ] 实现战斗状态的序列化/反序列化（存档/读档）
- [ ] 添加等级缩放：`final_stat = base_stat × level_multiplier(level)`
- [ ] Buff/Debuff 战斗效果映射（利用 `data/rules/04-debuff-system/` 和 `05-buff-pool/` 的数据）

### Phase 4: 前端 React 组件

- [ ] 创建 `CombatView` 页面组件（挂载在会话的 combat 路由下）
- [ ] 实现 `CombatGrid` + `GridCell` 组件（4×8 网格，点击交互）
- [ ] 实现 `CombatCard` + `CombatHand` 组件（手牌展示、选择、AP 不足灰显）
- [ ] 实现 `UnitStatusPanel`（所有单位 HP/AP 状态条）
- [ ] 实现 `CombatEventLog`（SSE 事件实时滚动展示）
- [ ] 实现 `TargetingOverlay`（目标高亮、范围预览）
- [ ] 在 Zustand store 中新增 `combatSlice`
- [ ] 键盘快捷键支持（`1-7` 选牌、`F` 结束回合、`Esc` 取消）
- [ ] CSS 动画（伤害数字、单位移动、卡牌打出效果）
- [ ] 战斗结算画面（胜利/失败 + 奖励展示）

### Phase 5: 剧情集成 + 遭遇系统（远期）

- [ ] 战斗遭遇绑定到剧情回合（`data/plots/` 中的 `scenes.md`）
- [ ] 战斗胜负影响剧情分支
- [ ] 战斗后的 buff/debuff 延续到后续场景
- [ ] 角色升级与经验系统集成
- [ ] 物品/武器对战斗数值的加成
- [ ] 天气/环境对战斗的影响

---

## Web 架构设计

> 将 demo 战斗引擎嵌入现有的 React + Flask 架构中。

### 总体架构

```
┌─────────────────────────────────────────────────────────┐
│                    Electron Shell                        │
│  ┌──────────────────────┐  ┌─────────────────────────┐  │
│  │   React Frontend     │  │   Flask Backend         │  │
│  │   (Vite + TS)        │  │   (127.0.0.1:5000)      │  │
│  │                      │  │                         │  │
│  │  CombatGrid  CardHand│  │  /api/combat/start      │  │
│  │  StatusPanel EventLog│  │  /api/combat/action     │  │
│  │  TargetingOverlay    │  │  /api/combat/state      │  │
│  │                      │  │  /api/combat/events (SSE)│  │
│  │         ▲            │  │         │               │  │
│  │         │ REST+SSE   │  │         ▼               │  │
│  │         ▼            │  │  CombatSession          │  │
│  │  Zustand Store       │  │   └─ CombatEngine       │  │
│  │  (combatSlice)       │  │   └─ CombatDataLoader   │  │
│  └──────────────────────┘  │   └─ SessionOverlay      │  │
│                            └─────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**关键决策**：
- 战斗状态机 **完全在服务端** 运行（Flask 持有 `CombatEngine` 实例），前端只负责渲染和用户输入
- 前端通过 **REST** 提交操作（选牌、移动、结束回合），通过 **SSE** 接收实时事件（伤害、治疗、死亡）
- 战斗数据（敌人、卡牌）从 `data/combat/` markdown 文件加载，复用项目现有的 `DocumentManager` 管线
- 战斗会话绑定到项目的 `Session` 系统，支持存档/读档

### 后端 API 设计

所有战斗 API 挂载在 `/api/sessions/<session_id>/combat/` 下。

#### REST 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/combat/start` | 开始一场战斗。请求体：`{ "encounter_id": "enc_first_reunion" }` 或自定义敌人配置 |
| `GET` | `/combat/state` | 获取当前战斗的完整状态快照（JSON） |
| `POST` | `/combat/action` | 提交玩家操作。请求体见下方 |
| `POST` | `/combat/end-turn` | 结束当前单位回合 |
| `GET` | `/combat/events` | **SSE 流**：订阅战斗事件推送 |

#### 操作请求体（`POST /combat/action`）

```json
{
  "unit_id": "amiya_001",       // 当前行动的角色
  "action": "play_card",
  "card_index": 2,              // 共享手牌中的索引 (0-based)
  "target": [3, 5]              // 目标格子 [row, col]
}
```

```json
{
  "unit_id": "silverash_001",
  "action": "move",
  "target": [1, 3]
}
```

```json
{
  "unit_id": "chen_001",
  "action": "intercept",        // 主动拦截
  "target_unit": "amiya_001"    // 被攻击的友方单位
}
```

#### 状态快照响应（`GET /combat/state`）

```json
{
  "round_num": 3,
  "phase": "PLAYER_PHASE",
  "grid_size": 8,
  "winner": null,
  "shared_ap": 3, "max_shared_ap": 4,
  "available_units": ["chen_001", "silverash_001", "amiya_001"],  // 尚未行动
  "acted_units": ["shining_001"],                                   // 已行动
  "units": [
    {
      "unit_id": "amiya_001", "name": "阿米娅",
      "team": "player", "char_class": "术师",
      "hp": 85, "max_hp": 110,
      "personal_ap": 2, "max_personal_ap": 2,
      "patk": 22, "matk": 38, "def": 8, "res": 12,
      "pos": [1, 1], "mobility": 5
    }
  ],
  "grid": { /* n×n 网格，每格 unit_id | null */ },
  "shared_hand": [ /* 共享手牌 (6张) */ ],
  "valid_targets": [],
  "valid_moves": [],
  "can_intercept": ["silverash_001"]  // 有拦截机会的角色
}
```

#### SSE 事件流

```
event: round_start
data: {"round":3,"shared_ap":4,"personal_ap":{"chen_001":3,...}}

event: turn_start
data: {"unit_id":"amiya_001","name":"阿米娅","personal_ap":2}

event: damage
data: {"caster":"阿米娅","target":"整合运动士兵","damage":18,"hit_result":"hit","card":"能量弹"}

event: intercept_prompt
data: {"attacker":"整合运动术师","target":"闪灵","available_interceptors":["银灰","陈"]}

event: block_attempt
data: {"defender":"闪灵(重装)","target":"阿米娅","attacker":"整合运动士兵","chance":0.7}

event: block_success
data: {"defender":"闪灵","redirected_damage":3}

event: battle_end
data: {"winner":"player","reason":"all enemies dead"}
```

#### 选择方案：REST+SSE vs WebSocket

| 方案 | 优势 | 劣势 |
|------|------|------|
| **REST + SSE**（推荐） | 复用现有 SSE 管线；单向事件流足够（前端→后端只需 POST action）；实现简单 | 需要两次请求（action POST + SSE 接收结果） |
| WebSocket | 双向实时；单连接 | 需要新增 WebSocket 基础设施；Flask 支持较弱 |

**推荐 REST + SSE**：回合制战斗不需要毫秒级实时性，SSE 可以完美覆盖"后端推送事件"的场景，且项目已在 `ChatPanel` 和 `narrate` 中大量使用 SSE。

### 前端组件架构

#### 组件树

```
CombatView
├── CombatHeader           — 回合数、共用AP池、阶段
├── CombatGrid             — n×n 网格（动态尺寸）
│   └── GridCell × n²     — 单格（单位/空位/部署区/高亮）
├── UnitStatusBar          — 4 角色头像 + 个人AP条 + 已行动标记
├── CombatHand             — 共享手牌（6 张横向，可打出亮起/灰显）
│   └── CombatCard × 6    — 卡牌含：类别标记(专属/职业/通用)、AP消耗来源
├── CombatEventLog         — 滚动战斗事件日志
└── InterceptModal         — 拦截提示弹窗（敌方回合弹出）
```

#### 关键交互流程

1. **看手牌**：6 张共享手牌横向展示，AP 足够的牌高亮，不足的灰显
2. **点击卡牌**：
   - 专属牌 → 自动激活 owner 角色
   - 职业牌 → 若有多个同职业角色，弹窗简选或自动选 AP 充足者
   - 通用牌 → 检查共用 AP，不足时检查当前激活角色个人 AP 能否补足
3. **目标选择**：卡牌选中后进入 TARGETING 模式，网格高亮有效目标 → 点击格子确认
4. **移动**：点击 UnitStatusBar 中角色 → 点击"移动"按钮 → 高亮可达范围（考虑 mobility 效率）→ 点击目标格
5. **连续出牌**：同一角色有多张可打出的牌时连续打出，直到 AP 耗尽或无可用的牌
6. **敌方回合**：禁用交互，SSE 推送敌方行动。攻击前：
   - 重装被动挡刀自动判定 → `block_attempt/success/fail`
   - 高 SPD 角色拦截机会 → 弹出 `InterceptModal`
7. **键盘快捷键**：`1-6` 选牌，`F` 结束阶段，`Esc` 取消选择

#### 状态管理（Zustand Store）

```typescript
interface CombatState {
  inCombat: boolean;
  encounterId: string | null;
  gridSize: number;

  roundNum: number;
  phase: 'INIT' | 'ROUND_START' | 'PLAYER_PHASE' | 'ENEMY_TURN' | 'END';
  winner: 'player' | 'enemy' | null;

  // 双 AP 池
  sharedAp: number;  maxSharedAp: number;
  units: CombatUnitDTO[];                // 含 personal_ap, mobility

  // 卡牌决定谁行动 — 角色 AP 用尽则其专属/职业牌自动灰显
  unitsWithAp: string[];                 // 尚有个人AP的角色

  // 共享手牌 + 网格
  sharedHand: CardDTO[];
  grid: (string | null)[][];
  validTargets: [number, number][];
  validMoves: [number, number][];

  // 拦截
  interceptPrompt: { attacker: string; target: string; available: string[] } | null;

  // UI
  selectedCardIndex: number | null;
  uiMode: 'VIEWING' | 'TARGETING' | 'MOVING' | 'INTERCEPT';

  // 操作 — 无需 activateUnit，card 自身携带 owner/class_required
  selectCard: (index: number) => void;          // 点击卡牌 → 自动确定角色+AP来源
  submitAction: (action: CombatAction) => Promise<void>;
  respondIntercept: (unitId: string | null) => Promise<void>;
  endPhase: () => Promise<void>;
}
```

#### 渲染性能

最大网格 10×10 = 100 格，共享手牌 6 张，单位 ≤ 8 个。数据量极小，React 默认渲染足够，无需虚拟滚动。

### 服务端会话管理

#### CombatSession

`CombatSession` 是持有 `CombatEngine` 的服务端对象：

```python
class CombatSession:
    """绑定到项目的 Session，管理一场战斗的完整生命周期。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.engine: CombatEngine | None = None
        self.data_loader: CombatDataLoader
        self.event_queue: queue.Queue  # SSE 消费者从此读取

    def start(self, encounter_id: str) -> dict:
        """从 data/combat/encounters/ 加载遭遇，初始化 CombatEngine。"""
        ...

    def handle_action(self, action: dict) -> list[CombatEvent]:
        """执行一个玩家操作，返回产生的事件列表。"""
        ...

    def end_turn(self) -> list[CombatEvent]:
        """结束当前回合，推进状态机。"""
        ...

    def get_state_snapshot(self) -> dict:
        """生成前端需要的完整状态快照。"""
        ...

    def to_dict(self) -> dict:
        """序列化整个战斗状态，用于存档。"""
        ...

    @classmethod
    def from_dict(cls, data: dict) -> "CombatSession":
        """从存档恢复。"""
        ...
```

#### 与现有 Session 系统的集成

```
Session (session_manager.py)
  ├── SceneManager     — 角色/聊天管理
  ├── EnvironmentState — 位置/天气/时间
  ├── SessionOverlay   — 临时修改
  ├── VectorMemory     — 记忆系统
  └── CombatSession    — 战斗状态 (新增)
```

在项目的 `Session` 类中添加 `combat: CombatSession | None` 字段。当 `combat` 不为 None 时表示当前正在进行战斗。

#### API 挂载方式

在 `app.py` 中按如下方式组织路由：

```python
@app.route("/api/sessions/<session_id>/combat/start", methods=["POST"])
def combat_start(session_id):
    session = session_manager.get(session_id)
    data = request.get_json()
    combat = CombatSession(session_id)
    # 从 CombatDataLoader 加载遭遇数据
    snapshot = combat.start(data.get("encounter_id"))
    session.combat = combat
    return jsonify(snapshot)

@app.route("/api/sessions/<session_id>/combat/action", methods=["POST"])
def combat_action(session_id):
    session = session_manager.get(session_id)
    action = request.get_json()
    events = session.combat.handle_action(action)
    # 将事件推入 SSE 队列
    for ev in events:
        session.combat.event_queue.put(ev)
    return jsonify({"ok": True})

@app.route("/api/sessions/<session_id>/combat/events")
def combat_events(session_id):
    """SSE 端点：流式推送战斗事件。"""
    session = session_manager.get(session_id)
    def generate():
        while session.combat and not session.combat.engine.is_battle_over():
            try:
                ev = session.combat.event_queue.get(timeout=30)
                yield f"event: {ev.type}\ndata: {json.dumps(ev.data)}\n\n"
                if ev.type == "battle_end":
                    break
            except queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
    return Response(generate(), mimetype="text/event-stream")
```

### 数据序列化格式

#### 战斗单位 DTO

```typescript
interface CombatUnitDTO {
  unit_id: string;
  name: string;
  team: "player" | "enemy";
  char_class: string;
  hp: number;  max_hp: number;
  personal_ap: number;  max_personal_ap: number;
  mobility: number;
  patk: number;  matk: number;
  def: number;  res: number;
  pos: [number, number];
  can_intercept: boolean;          // mobility ≥ 7
  is_defender: boolean;            // 重装职业 → 挡刀被动
  is_alive: boolean;
}
```

#### 卡牌 DTO

```typescript
interface CardDTO {
  card_id: string;
  name: string;
  damage_type: "physical" | "arts" | "healing" | "mixed";
  min_damage: number;  max_damage: number;
  atk_scale: number;
  target: string;                   // SINGLE | SELF | ADJACENT | CROSS | ...
  range: number;
  cost: number;
  tier: "basic" | "elite";
  class_required: string;           // "any" = 通用牌
  owner: string | null;             // "陈" = 专属牌, null = 非专属
  category: "exclusive" | "class" | "universal";  // 前端计算: owner非空→exclusive, class_required="any"→universal
}
```

#### 战斗事件 DTO

```typescript
type CombatEventDTO =
  | { type: "round_start"; data: { round: number; shared_ap: number; personal_ap: Record<string,number> } }
  | { type: "turn_start"; data: { unit_id: string; name: string; personal_ap: number } }
  | { type: "damage"; data: { caster: string; target: string; damage: number; hit_result: string; card: string } }
  | { type: "heal"; data: { caster: string; target: string; amount: number; card: string } }
  | { type: "block_attempt"; data: { defender: string; target: string; attacker: string; chance: number } }
  | { type: "block_success"; data: { defender: string; redirected_damage: number } }
  | { type: "block_fail"; data: { defender: string } }
  | { type: "intercept_prompt"; data: { attacker: string; target: string; available_interceptors: string[] } }
  | { type: "intercept_result"; data: { interceptor: string; damage_taken: number } }
  | { type: "death"; data: { unit_id: string; name: string; team: string } }
  | { type: "move"; data: { unit_id: string; from: [number,number]; to: [number,number] } }
  | { type: "battle_end"; data: { winner: "player" | "enemy"; reason: string } }
  | { type: "error"; data: { msg: string } };
```

### 博士在战斗中的定位

当前问题：博士只有 3/8 属性，职业 `战术指挥` 不在 8 个有效职业中。

**方案 A — 指挥官模式（推荐）**：博士不直接上场，而是提供全局战术 buff。例如每回合可以选择一个 buff 施加给队友（ATK + 2、DEF + 2、SPD + 2）。博士的 `tactical_planning: 10` 驱动 buff 强度。

**方案 B — 补全属性**：给博士补全 8 属性，让博士作为普通单位上场。

**方案 C — 特殊卡池**：博士上场但使用 `战术指挥` 专属卡池（buff/debuff 为主，少量直接伤害，全局射程）。

在 Web 架构中，方案 A 最容易实现且最适合博士的角色设定。实现方式：
- 在 CombatEngine 的 `_start_round()` 中，如果玩家方包含博士，额外触发一个"战术指挥"阶段
- 前端显示 buff 选择面板

---

## demo 文件索引

### 现有 demo 文件

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

### 集成后的目标文件结构

```
src/
├── combat/                      # 从 demo/combat/ 提升的后端战斗模块
│   ├── __init__.py
│   ├── entity.py                # CombatUnit（含属性 key 兼容层）
│   ├── grid.py                  # Grid + resolve_targets
│   ├── card.py                  # Card + CardPool
│   ├── dice.py                  # check_hit + compute_damage
│   ├── engine.py                # CombatEngine 状态机
│   ├── data_loader.py           # NEW: CombatDataLoader（读取 markdown 数据）
│   └── combat_session.py        # NEW: CombatSession（服务端会话管理）
├── app.py                       # 新增 combat API 端点

frontend/src/
├── components/
│   └── combat/                  # NEW: 战斗 UI 组件
│       ├── CombatView.tsx        # 战斗主视图
│       ├── CombatGrid.tsx        # 4×8 网格
│       ├── GridCell.tsx          # 单格
│       ├── CombatCard.tsx        # 卡牌组件
│       ├── CombatHand.tsx        # 手牌栏
│       ├── UnitStatusPanel.tsx   # 单位状态面板
│       ├── CombatEventLog.tsx    # 事件日志（SSE 消费）
│       └── CombatResult.tsx      # 结算画面
├── stores/
│   └── combatSlice.ts           # NEW: Zustand combat state
└── hooks/
    └── useCombatSSE.ts          # NEW: SSE hook for combat events

data/combat/                     # NEW: 战斗数据（markdown）
├── _index.md
├── TEMPLATE_enemy.md
├── TEMPLATE_card.md
├── TEMPLATE_encounter.md
├── enemies/
│   └── *.md                     # 敌人数据
├── cards/
│   ├── 术师/*.md
│   ├── 近卫/*.md
│   └── ...
└── encounters/
    └── *.md                     # 战斗遭遇
```

### 关键文件对应关系

| 需求 | 现有组件 | 集成后替代 |
|------|---------|-----------|
| 敌人数据 | `CombatUnit.create_enemy()` 硬编码 | `CombatDataLoader.from_enemy_md()` |
| 卡牌数据 | `card_data.py` 硬编码 | 从 `data/combat/cards/` markdown 加载 |
| 战斗遭遇 | `run_demo.py` 中的 `ENEMY_DEFS` | 从 `data/combat/encounters/` 加载 |
| 角色属性 | `CombatUnit.from_character_metadata()` | 使用属性 key 兼容层 + 角色 `.md` 的 `attributes` |
| 职业卡池 | `get_starting_deck(char_class)` | 从 `data/combat/cards/<职业>/` 加载 |
| 用户界面 | Textual `tui_app.py` / `run_demo.py` | React `CombatView.tsx` 组件树 |
| 事件系统 | `engine.on_event` 回调 | SSE `/combat/events` 端点 |
| 状态管理 | 本地 CombatScreen 对象 | 服务端 `CombatSession` + 前端 Zustand store |
---

*本文档随 `demo/combat/` 代码演进同步更新。最后一版代码验证：所有 30 场自动战斗测试通过，4v4 完整战斗在 4-13 回合内正常终结。*
