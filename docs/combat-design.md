# 战斗系统设计文档

> Arknights Tavern — 回合制卡牌战斗的底层逻辑、数据结构、与项目集成方案
>
> 引擎代码：`src/combat_engine/` | 当前版本：v1.0
>
> **状态说明**：本文档包含已实现功能和未来规划设计两部分。章节标题旁标注
> ✅ = 已实现，📐 = 设计中/未实现。代码以 `src/combat_engine/` 和 `frontend/src/components/combat/` 为准。

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

✅ **已实现**：
- **4 人小队**，站位在 7×7 网格（玩家区左侧 3 列，敌方区右侧 4 列）
- 每个角色拥有基于 **职业** 的卡池（每职业 5 基础 + 3 精英 = 8 张）
- 全队 **共享卡池**（28 张 = 4 角色 × 7 张），每轮补满至 6 张共享手牌
- **共享回合制**（全队同时行动，玩家自由选择角色出牌）
- **共享 AP** 池，由队伍最高战术规划属性决定上限
- 卡牌伤害为 **范围值**，由掷骰（d20）和角色基础属性决定
- 角色 **个人 AP** 由 mobility 属性决定（当前仅供敌方使用）
- **角色保底** 机制（每轮每角色至少 1 张可用牌）

📐 **设计中的扩展**：
- 个人 AP 出牌消耗（当前统一消耗共享 AP）
- 移动效率与 mobility 挂钩
- 拦截/挡刀系统
- 遗物/物品被动效果

整个战斗引擎在 `src/combat_engine/` 中以纯 Python 实现，前端使用 React + TypeScript 的 Web 界面。

战斗引擎已集成到项目的 **Flask 后端 + React 前端** 架构中。Flask 提供 REST + SSE 接口驱动战斗状态机，React 负责渲染网格、手牌和战斗事件。详见 [Web 架构设计](#web-架构设计) 章节。

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

> 代码位置：`src/combat_engine/entity.py` → `CombatUnit.from_character_metadata()`

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
| **个人 AP** | 每个角色的 `mobility`（战场机动） | 敌方单位使用，玩家角色个人 AP 暂未使用 | 是 |
| **共用 AP** | 队伍中最高 `tactical_planning`（战术规划） | 所有玩家行动（出牌 + 移动） | 是 |

> **当前实现（2026-05-24）**：所有玩家行动统一消耗共享 AP。个人 AP 已在 `CombatUnit` 中计算并存储，但仅用于敌方单位的消耗。后续将实现"专属/职业牌消耗个人 AP，通用牌消耗共享 AP"的完整模型。

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

#### SPD（mobility）的角色

SPD **不再决定回合顺序**。改为以下用途：

| 用途 | 说明 | 状态 |
|------|------|------|
| **个人 AP 值** | 高 mobility → 更多个人 AP（见上表） | ✅ 已实现 |
| **移动效率** | mobility ≥ 7 → 1 AP 可移动 2 格；mobility ≥ 10 → 3 格/AP | 📐 未实现 |
| **拦截机会** | mobility ≥ 7 → 每轮 1 次主动拦截；mobility ≥ 9 → 2 次 | 📐 未实现 |

> 当前移动统一消耗 1 AP/格，无 mobility 效率加成。

#### 回合顺序（共享回合制 ✅）

当前实现使用**共享回合模型**，而非卡牌驱动：

```
共享手牌(6张) → 所有角色共享
  ├─ 玩家自由选择任意卡牌打出
  ├─ 专属牌 → 查找 owner 对应角色（自动绑定）
  ├─ 所有行动消耗共享 AP
  └─ 点击"结束回合"进入敌方阶段

玩家连续出牌/移动，直到共享 AP 耗尽或手动结束回合。


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

> 代码位置：`src/combat_engine/dice.py` → `check_hit()`

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

> 代码位置：`src/combat_engine/dice.py` → `compute_damage()`

---

## 卡牌系统（重设计）

### 三种卡牌类别

| 类别 | 标识 | 谁能用 | 消耗 | 示例 |
|------|------|--------|------|------|
| **专属牌** | `owner: "陈"` | 仅指定角色 | 该角色个人 AP | 赤霄拔刀（陈专属） |
| **职业牌** | `class_required: "术师"` | 该职业任意角色 | 打出者个人 AP | 能量弹（术师通用） |
| **通用牌** | `class_required: "any"` | 任何角色 | 共用 AP（不足时个人补） | 治疗药剂、防御姿态 |

专属牌相比同类职业牌 ATK 倍率高 20-30%，体现角色专属的价值。

### 共享手牌 + 牌库模型（✅ 已实现）

```
共享牌库 (28张 = 4角色 × 7张)
       │
       ▼ 每轮弃手牌 → 补满至 6 张
共享手牌 (6张)
       │
       ▼ 玩家选择出牌（所有行动消耗共享 AP）
```

| 参数 | 值 | 说明 |
|------|-----|------|
| 每位角色携带牌数 | 7 张 | 组成共享牌库 |
| 共享牌库总量 | 28 张（4 人） | |
| 共享手牌上限 | **6 张** | `CombatEngine.SHARED_HAND_SIZE = 6` |
| 每轮抽牌 | 弃旧手牌 → 补满至 6 张 | 不跨轮保留 |
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

> 代码位置：`src/combat_engine/card.py`

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

> 代码位置：`src/combat_engine/grid.py` → `resolve_targets()`

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

> 代码位置：`src/combat_engine/card.py` → `CardPool`

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

> 代码位置：`src/combat_engine/card_data.py`

---

## 遗物系统（物品被动）📐 设计中 — 尚未实现

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

战场为固定 **7×7** 网格（7 行 × 7 列）。

#### 部署区

玩家部署区为左侧 **3 列**（cols 0-2），敌方部署区为右侧 **4 列**（cols 3-6）：

```
7×7 网格示意:
  0 1 2 3 4 5 6
0 █ . . ▓ ▓ ▓ ▓     █ = 玩家区 (cols 0-2) — 左侧 3 列
1 █ . . ▓ ▓ ▓ ▓     ▓ = 敌方区 (cols 3-6) — 右侧 4 列
2 █ . . ▓ ▓ ▓ ▓
3 █ . . ▓ ▓ ▓ ▓
4 █ . . ▓ ▓ ▓ ▓
5 █ . . ▓ ▓ ▓ ▓
6 █ . . ▓ ▓ ▓ ▓
```

- **玩家**：可部署在 cols 0-2 任意行（当前默认位置为 rows 3-5, cols 0-2 的 4 个位置）
- **敌方**：可部署在 cols 3-6 任意行，支持自动随机放置
- col 2-3 之间为天然分界线

#### 移动规则（✅ / 📐）

- 移动消耗 **1 AP 每格**（当前实现，无 mobility 效率加成）
- 📐 移动效率加成（mobility ≥ 7 → 2 格/AP）为规划中
- 移动使用**曼哈顿距离**（上下左右，不可斜走）
- 目标格不能有其他单位占据
- 移动范围不受阵营限制——角色可以移动到棋盘上任何空位
- 经过敌方单位邻格时无惩罚（无"借机攻击"概念）

#### 距离计算

距离使用**切比雪夫距离**：`max(|row_diff|, |col_diff|)`

这对应"王棋移动"——斜走与直走等价，攻击范围判定以此为基准。

> 代码位置：`src/combat_engine/grid.py`

---

## 回合制状态机

### 状态流转（✅ 已实现）

```
INIT → ROUND_START → PLAYER_TURN → ENEMY_TURN → (round++) → ROUND_START
         ↑                                                  │
         └──────────────────────────────────────────────────┘
                                       │
                                    ROUND_END → END
```

### 各阶段详解

| 阶段 | 行为 |
|------|------|
| `INIT` | 读入遭遇数据 → 创建 7×7 网格 → 部署单位 → 组建共享牌库(28张) → 洗牌 |
| `ROUND_START` | 弃掉手牌 → 从抽牌堆抽6张 → 角色保底检测 → 重置个人AP + 共用AP → 进入 Player Turn |
| `PLAYER_TURN` | 玩家自由行动（出牌/移动），所有行动消耗共享 AP；点击"结束回合"进入 Enemy Turn |
| `ENEMY_TURN` | 所有存活敌方依次行动（每单位抽1张牌 → 判断能否出牌 → 不能则向最近玩家移动） |
| `ROUND_END` | 检查胜负条件（循环内自动执行）→ 未结束则轮次+1 → 进入 ROUND_START |
| `END` | 战斗结束，记录 winner |

### 事件系统 ✅

引擎通过 `CombatEvent` 回调通知：

| 事件类型 | 触发时机 | 关键字段 | 状态 |
|---------|---------|---------|------|
| `battle_start` | 战斗开始 | `round` | ✅ |
| `round_start` | 新回合开始 | `round` | ✅ |
| `card_played` | 打出卡牌 | `unit_id`, `caster`, `card`, `target`, `results` | ✅ |
| `damage` | 造成伤害 | `caster`, `target`, `damage`, `hit_result`, `card` | ✅ |
| `heal` | 治疗 | `caster`, `target`, `amount`, `card` | ✅ |
| `move` | 单位移动 | `unit_id`, `name`, `from_pos`, `to_pos` | ✅ |
| `death` | 单位死亡 | `unit_id`, `name`, `team` | ✅ |
| `battle_end` | 战斗结束 | `winner`, `reason` | ✅ |
| `error` | 操作失败 | `unit_id`, `msg` | ✅ |
| `block_attempt` | 挡刀判定触发 | 📐 未实现 | 📐 |
| `block_success` | 挡刀成功 | 📐 未实现 | 📐 |
| `intercept_prompt` | 主动拦截机会 | 📐 未实现 | 📐 |

> 代码位置：`src/combat_engine/engine.py` → `CombatEngine`

---

## 敌方 AI

简单贪心策略，每回合：

1. 找到距离最近的存活的玩家单位
2. 筛选可负担的卡牌（`cost <= AP`）
3. 如有可用的攻击卡且在射程内 → 打出伤害最高的那张
4. 如有 AP 但无法攻击 → 向最近玩家移动一步（切比雪夫方向）
5. 无法行动 → 跳过

> 代码位置：`src/combat_engine/engine.py` → `execute_enemy_turn()`

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
    hand: list[Card]       # 手牌
    discard: list[Card]    # 弃牌堆（普通卡用后进入）
    exhaust: list[Card]    # 耗尽堆（精英卡用后永久移除）
    hand_size: int = 7     # 默认值 7，引擎中共享手牌设为 6
```

> 注意：`CardPool.hand_size` 默认值为 7，但 `CombatEngine.SHARED_HAND_SIZE = 6`。
> 创建共享卡池时引擎显式传入 `hand_size=6`。敌方可使用独立手牌容量（默认 5）。

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

### 当前数据目录结构

卡牌数据已由 `src/combat_engine/card_data.py` 硬编码管理（按职业定义卡牌池 + `get_starting_deck()`），不再使用 markdown 文件存储卡牌。

```
data/
├── combat/
│   ├── TEMPLATE_enemy.md      ← 敌人模板
│   ├── TEMPLATE_encounter.md  ← 遭遇模板
│   ├── TEMPLATE_card.md       ← 卡牌模板（归档，实际数据在 card_data.py）
│   ├── enemies/
│   │   ├── 整合运动士兵.md
│   │   ├── 整合运动狙击手.md
│   │   ├── 整合运动术师.md
│   │   ├── 整合运动盾卫.md
│   │   └── ...
│   └── encounters/
│       ├── 初遇整合运动.md
│       ├── enc_defense.md
│       ├── enc_elite_hunt.md
│       ├── enc_mixed_assault.md
│       └── enc_training.md
├── enemies/                   ← 叙事敌人（RP 场景用）
├── rules/                     ← 规则定义
├── attributes/                ← 属性详解（每属性独立文件）
└── memory/sessions/           ← 会话持久化数据
```
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

### 卡牌数据定义

卡牌数据在 `src/combat_engine/card_data.py` 中以硬编码字典定义，按职业组织。模板文件 `TEMPLATE_card.md` 保留作为字段参考。

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

### 集成到现有的数据加载管线 ✅

已完成以下集成步骤：

1. **注册新分类**：在 `data/_INDEX.md` 中添加了 `combat_enemies`、`combat_cards`、`combat_encounters`、`enemies`、`attributes`、`rules` 等分类
2. **注册子索引**：创建了 `data/combat/_index.md`，包含 enemies、cards、encounters 的子索引
3. **扩展 API**：在 `app.py` 中添加了战斗 REST + SSE 端点
4. **创建 CombatDataLoader**：提供 `load_enemy()`、`load_card()`、`load_encounter()`、`build_starting_deck()` 等方法

---

## 集成路线图

### Phase 1: 数据层（P0 — 不修改引擎）

- [x] 创建 `data/combat/` 目录结构（`enemies/`、`encounters/`）
- [x] 编写敌人模板 `TEMPLATE_enemy.md` 和卡牌模板 `TEMPLATE_card.md`
- [x] 将现有的敌人转为 markdown 文件（4 个战斗敌人）
- [x] 卡牌数据迁移至 `card_data.py` 硬编码（更灵活、可编程生成）
- [x] 创建 `data/classes/战术指挥/index.md` 职业定义
- [ ] 补全博士的 8 属性
- [x] 在 `data/_INDEX.md` 注册新分类（combat_enemies, combat_cards, combat_encounters, enemies, attributes, rules）
- [x] 创建 `data/combat/_index.md`
- [x] 创建 `encounters/初遇整合运动.md` 首个遭遇配置

### Phase 2: 属性兼容 + 加载管线（P0/P1）

- [x] 更新 `entity.py` 的属性 key 映射表：
  - 旧 key → 新 key（`strength` → `physical_strength` 等）
  - 中文 key → 英文 key（`物理强度` → `physical_strength` 等）
  - 缺失属性默认值 5
- [x] 创建 `CombatDataLoader` 类：
  - `load_enemy(name) → CombatUnit`
  - `load_card(class, name) → Card`
  - `load_encounter(id) → encounter_config`
- [x] 将 `combat_engine/` 从 demo 目录迁移到 `src/` 后端可引用的位置

### Phase 3: 后端 API 层

- [x] 实现 `CombatSession` 类（服务端战斗会话管理）
- [x] 实现 `CombatDataLoader`（从 markdown 加载敌人/卡牌/遭遇）
- [x] 在 `app.py` 中添加战斗 API 端点：
  - `POST /api/sessions/<id>/combat/start`
  - `GET /api/sessions/<id>/combat/state`
  - `POST /api/sessions/<id>/combat/action`
  - `POST /api/sessions/<id>/combat/end-turn`
  - `GET /api/sessions/<id>/combat/events` (SSE)
  - `POST /api/sessions/<id>/combat/complete`
- [x] 在 `Session` 类中集成 `CombatSession`
- [x] 实现战斗状态的序列化/反序列化（存档/读档）
- [ ] 添加等级缩放：`final_stat = base_stat × level_multiplier(level)`
- [ ] Buff/Debuff 战斗效果映射（利用 `data/rules/` 的数据）

### Phase 4: 前端 React 组件

- [x] 创建 `CombatView` 页面组件（挂载在 combat 路由下）
- [x] 实现 `CombatGrid` + `GridCell` 组件（7×7 网格，3D 透视，拖放）
- [x] 实现 `CombatCard` + `CombatHand` 组件（手牌扇形布局，拖拽出牌，AP 不足灰显）
- [x] 实现 `UnitStatusPanel`（HP/AP/属性/职业标签）
- [x] 实现 `CombatEventLog`（Timeline 风格 SSE 事件展示）
- [x] 实现 `DeckViewer`（卡组查看器，按角色/牌堆分组）
- [x] 实现 `CombatUnitTooltip`（Portal 悬浮属性面板）
- [x] 实现 `CombatParticles`（Canvas 粒子特效）
- [x] 在 Zustand store 中集成 combat state
- [x] 键盘快捷键支持（`1-6` 选牌、`F` 结束回合、`Esc` 取消）
- [x] CSS 动画（伤害数字、浮动粒子、卡牌打出、受击震动）
- [ ] 战斗结算画面（胜利/失败 + 奖励展示）
- [ ] 攻击弹道/冲击动画

### Phase 5: 剧情集成 + 遭遇系统（远期）

- [ ] 战斗遭遇绑定到剧情回合（`data/plots/` 中的 `scenes.md`）
- [ ] 战斗胜负影响剧情分支
- [ ] 战斗后的 buff/debuff 延续到后续场景
- [ ] 角色升级与经验系统集成
- [ ] 物品/武器对战斗数值的加成（遗物系统）
- [ ] 天气/环境对战斗的影响

---

## Web 架构设计

> 战斗引擎已嵌入现有的 React + Flask 架构中。

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
| `POST` | `/combat/start` | 开始一场战斗。请求体：`{ "encounter_id": "...", "character_names": ["阿米娅",...] }` |
| `GET` | `/combat/state` | 获取当前战斗的完整状态快照（JSON） |
| `POST` | `/combat/action` | 提交玩家操作。请求体见下方 |
| `POST` | `/combat/end-turn` | 结束玩家回合，进入敌方阶段 |
| `POST` | `/combat/complete` | 战斗结算，结果写回到会话覆盖层 |
| `GET` | `/combat/events` | **SSE 流**：订阅战斗事件推送 |

#### 操作请求体（`POST /combat/action`）

```json
{
  "action": "play_card",
  "card_index": 2,              // 共享手牌中的索引 (0-based)
  "target": [3, 5]              // 目标格子 [row, col]
}
```

```json
{
  "action": "move",
  "unit_id": "银灰",            // 移动角色的 unit_id
  "target": [1, 3]
}
```

#### 状态快照响应（`GET /combat/state`）

```json
{
  "round_num": 3,
  "phase": "PLAYER_TURN",
  "grid_size": 9,
  "winner": null,
  "shared_ap": 3, "shared_ap_max": 4,
  "units": [
    {
      "unit_id": "阿米娅", "name": "阿米娅",
      "team": "player", "char_class": "术师",
      "hp": 85, "max_hp": 110,
      "personal_ap": 2, "max_personal_ap": 2,
      "patk": 22, "matk": 38, "def": 8, "res": 12,
      "spd": 16, "hit": 14, "eva": 8,
      "pos": [3, 0], "mobility": 5,
      "is_alive": true,
      "attributes": { "physical_strength": 6, ... }
    }
  ],
  "grid": { "3,0": "阿米娅", "4,0": "银灰", ... },
  "shared_hand": [ /* 共享手牌 (6张) */ ],
  "player_hands": { "阿米娅": [ /* 该角色拥有的手牌子集 */ ] },
  "shared_pool": { "deck": [...], "discard": [...], "exhaust": [...] },
  "valid_targets": [[3,5], [4,6]],
  "valid_moves": [],
  "active_unit_id": "阿米娅",
  "battle_over": false
}
```

#### SSE 事件流

```
event: round_start
data: {"round":3,"shared_ap":4,"personal_ap":{"chen_001":3,...}}

event: damage
data: {"caster":"阿米娅","target":"整合运动士兵","damage":18,"hit_result":"hit","card":"能量弹"}

event: heal
data: {"caster":"闪灵","target":"银灰","amount":12,"card":"治疗术"}

event: move
data: {"unit_id":"chen","name":"陈","from_pos":[3,0],"to_pos":[3,1]}

event: card_played
data: {"unit_id":"amiya","caster":"阿米娅","card":"能量弹","target":[3,5]}

event: death
data: {"unit_id":"rebel_01","name":"整合运动士兵","team":"enemy"}

event: battle_end
data: {"winner":"player","reason":"所有敌人已消灭"}

<!-- 📐 以下事件尚未实现（规划中）：
event: intercept_prompt
event: block_attempt
event: block_success
-->
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
6. **敌方回合**：禁用交互，SSE 推送敌方行动。攻击前检查胜负条件。拦截/挡刀系统为规划中功能。
7. **键盘快捷键**：`1-6` 选牌，`F` 结束阶段，`Esc` 取消选择

#### 状态管理（Zustand Store）

```typescript
interface CombatState {
  inCombat: boolean;
  encounterId: string | null;
  gridSize: number;

  roundNum: number;
  phase: 'INIT' | 'ROUND_START' | 'PLAYER_TURN' | 'ENEMY_TURN' | 'END';
  winner: 'player' | 'enemy' | null;

  // 共享 AP
  sharedAp: number;  maxSharedAp: number;
  units: CombatUnitDTO[];

  // 共享手牌 + 网格
  sharedHand: CardDTO[];
  playerHands: Record<string, CardDTO[]>;     // 按角色分组的手牌
  grid: Record<string, string>;                // "row,col" → unit_id
  validTargets: [number, number][];
  validMoves: [number, number][];

  // UI
  selectedCardIndex: number | null;
  uiMode: 'VIEWING' | 'TARGETING';

  selectCard: (index: number) => void;
  submitAction: (action: CombatAction) => Promise<void>;
  endTurn: () => Promise<void>;
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
  spd: number;  hit: number;  eva: number;
  pos: [number, number];
  is_alive: boolean;
  attributes: Record<string, number>;
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
  | { type: "round_start"; data: { round: number; shared_ap: number } }
  | { type: "card_played"; data: { unit_id: string; caster: string; card: string; target: number[]; results: number[] } }
  | { type: "damage"; data: { caster: string; target: string; damage: number; hit_result: string; card: string } }
  | { type: "heal"; data: { caster: string; target: string; amount: number; card: string } }
  | { type: "move"; data: { unit_id: string; from_pos: number[]; to_pos: number[] } }
  | { type: "death"; data: { unit_id: string; name: string; team: string } }
  | { type: "battle_end"; data: { winner: string; reason: string } }
  | { type: "error"; data: { msg: string } }
  // 📐 以下为规划中事件类型：
  // | { type: "block_attempt"; data: { defender, target, attacker, chance } }
  // | { type: "block_success"; data: { defender, redirected_damage } }
  // | { type: "intercept_prompt"; data: { attacker, target, available_interceptors } };
```

### 博士在战斗中的定位

当前，博士的 `class` 设置为 `战术指挥`，拥有独立的 8 张卡牌（5 基础 + 3 精英）。战术指挥职业的卡牌特色：全局射程、支援 + 打击混合、战术指令。

当前存在两个问题：
1. 博士缺少完整的 8 属性数据（只有 3/8），战斗数值使用默认值 5
2. 博士作为普通单位上场但缺少剧情上的合理解释

**推荐方案 — 指挥官模式（规划中）**：博士不直接上场，而是提供全局战术 buff。每回合可选择 buff 施加给队友。博士的 `tactical_planning: 10` 驱动 buff 强度。此方案需实现 buff/debuff 系统后才能完整落地。

---

## 文件索引

### 战斗引擎（后端）

```
src/
├── combat_engine/
│   ├── __init__.py
│   ├── entity.py                # CombatUnit — 属性映射、伤害/治疗
│   ├── grid.py                  # Grid — 4×8 网格、目标模式、距离
│   ├── card.py                  # Card、CardPool — 卡牌生命周期
│   ├── card_data.py             # 72 张卡牌定义（9 职业 × 8 张）
│   ├── engine.py                # CombatEngine — 状态机、AI、事件
│   └── dice.py                  # 命中判定、伤害计算
├── combat_session.py            # CombatSession — 服务端会话管理
├── combat_data_loader.py        # CombatDataLoader — 从 markdown 加载数据
└── app.py                       # combat API 端点

frontend/src/
├── components/combat/
│   ├── CombatView.tsx          — 战斗主视图（状态管理、事件中枢）
│   ├── CombatGrid.tsx          — 网格渲染（3D 透视、拖放、单元格）
│   ├── GridCell.tsx            — 单个单元格（单位显示、小精灵、高亮）
│   ├── ChibiSprite.tsx         — 角色小精灵（纯展示，pointer-events-none）
│   ├── CombatHand.tsx          — 手牌扇形布局
│   ├── CombatCard.tsx          — 单张卡牌（拖拽源、渐变、AP 消耗）
│   ├── UnitStatusPanel.tsx     — 角色状态面板（HP/AP/属性摘要）
│   ├── CombatUnitTooltip.tsx   — 角色悬浮提示（Portal，属性+数值）
│   ├── CombatEventLog.tsx      — 战斗事件日志
│   ├── CombatParticles.tsx     — Canvas 粒子特效
│   └── DeckViewer.tsx          — 卡组查看器（按角色/牌堆分组）
├── hooks/
│   └── useApi.ts               — API 客户端（REST + SSE）
├── stores/
│   └── appStore.ts             — Zustand 全局状态（含 combat state）
├── types/
│   └── index.ts                — TypeScript 类型定义
└── style.css                   — 战斗样式（粒子动画、网格 3D、手牌扇形）

data/combat/
├── TEMPLATE_enemy.md
├── TEMPLATE_card.md              ← 字段参考（实际卡牌数据在 card_data.py）
├── TEMPLATE_encounter.md
├── enemies/
│   └── *.md                     # 敌人数据
└── encounters/
    └── *.md                     # 战斗遭遇
```

### 关键组件对应关系

| 需求 | 实现 |
|------|------|
| 敌人数据 | `CombatDataLoader.load_enemy()` → `data/combat/enemies/` |
| 卡牌数据 | `get_starting_deck(class)` → `src/combat_engine/card_data.py` |
| 战斗遭遇 | `CombatDataLoader.load_encounter()` → `data/combat/encounters/` |
| 角色属性 | `CombatUnit.from_character_metadata()` + `_ATTR_KEY_MAP` 兼容层 |
| 用户界面 | React `CombatView.tsx` 组件树 |
| 事件系统 | `engine.on_event` 回调 → SSE `/combat/events` 端点 |
| 状态管理 | `CombatSession`（服务端）+ Zustand `appStore`（前端） |
---

*本文档随 `src/combat_engine/` 代码演进同步更新。最后一版代码验证：所有 30 场自动战斗测试通过，4v4 完整战斗在 4-13 回合内正常终结。*
