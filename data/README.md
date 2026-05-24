# Data 目录说明

## 目录结构

```
data/
├── _INDEX.md              ← 总索引（机器可读注册表）
├── README.md              ← 本文件（人类可读说明）
│
├── attributes/            ← 属性等级参考（1-10 级详解，每属性一个文件）
├── characters/            ← 角色定义
├── races/                 ← 种族百科
├── classes/               ← 职业体系
├── factions/              ← 势力/组织
├── items/                 ← 物品百科
├── enemies/               ← 叙事脚本敌人（RP 向数据）
├── plots/                 ← 剧情节点
├── world/                 ← 世界观文档
│
├── combat/                ← 战斗系统数据
│   ├── enemies/           ← 战斗敌人定义（带 combat_stats）
│   ├── cards/             ← 卡牌定义（按职业分目录）
│   └── encounters/        ← 遭遇战配置
│
├── rules/                 ← 游戏机制规则定义
│   ├── combat-system/     ← 战斗系统规则（战术/叙事模式）
│   ├── rarity-system/     ← 稀有度分级
│   ├── debuff-system/     ← 负面效果规则
│   ├── buff-pool/         ← Buff/Debuff 抽取池
│   └── deviation-states/  ← 剧情偏离状态
│
└── memory/                ← 向量记忆 + 会话持久化
    ├── chroma.sqlite3     ← ChromaDB 向量数据库
    └── sessions/          ← 会话状态（session.json / overrides.json）
```

## 引用关系图

```
                    ┌──────────────┐
                    │  world/      │  ← 始终注入（全局背景知识）
                    └──────┬───────┘
                           │ 引用
                    ┌──────▼───────┐
                    │  factions/   │  ← 势力详解
                    └──────▲───────┘
                           │ faction 字段引用
                    ┌──────┴───────┐
    races/  ←──────│  characters/  │──────→  classes/
    种族详解  race   │  角色定义     │  class  职业详解
                    └──┬────────┬──┘
                       │ key_items │ relationships
                       ▼           ▼
                  items/      characters/
                  物品百科       （自引用：其他角色）

                    ┌──────────────┐
                    │  plots/      │  ← 条件触发，引用 ↑ 所有类型
                    └──────────────┘
                           │ 地理位置
                           ▼
                    ┌──────────────┐
                    │  attributes/ │  ← 属性系统定义（被角色/敌人引用）
                    └──────────────┘

                    ┌──────────────┐
                    │  environment/ │  ← 项目根目录下的环境数据（经 _INDEX.md 注册）
                    │  Location/   │      locations / weather 由 SceneManager 管理
                    │  weather/    │      不在 data/ 内但通过 _INDEX.md 注册到系统
                    └──────────────┘

                    ┌──────────────┐
                    │  rules/      │  ← 规则定义（被所有系统引用）
                    │  combat-system/  debuff-system/
                    │  rarity-system/  buff-pool/
                    │  deviation-states/
                    └──────────────┘

                    ┌──────────────┐
                    │  combat/     │  ← 加载到战斗引擎的数据
                    │  enemies/    │     由 CombatDataLoader 加载
                    │  cards/      │
                    │  encounters/ │
                    └──────────────┘

                    ┌──────────────┐
                    │  enemies/    │  ← 叙事脚本敌人（RP 场景中使用）
                    │  (非战斗)    │
                    └──────────────┘
```

## 解析时点一览

| 数据类别 | 加载时点 | 注入范围 | 默认深度 |
|---------|---------|---------|---------|
| `world/` (global) | 系统启动 | 所有角色共享 | summary |
| `world/` (faction) | 角色加载 | 该势力相关上下文 | core |
| `world/` (region) | 地点切换 | 当前场景上下文 | core |
| `world/` (event) | 剧情触发 | 该剧情上下文 | full |
| `races/` | 角色加载 | 当前角色 system prompt | core |
| `classes/` | 角色加载 | 当前角色 system prompt | core |
| `factions/` | 角色加载 | 当前角色 system prompt | summary |
| `items/` (角色物品) | 角色加载 | 当前角色 system prompt | core |
| `items/` (场景物品) | 地点切换 | 场景上下文 | summary |
| `items/` (检视) | 玩家交互 | 当前对话轮次 | full |
| `attributes/` | 角色加载 | 当前角色数值参考 | core |
| `locations/` | 地点切换 | 当前场景上下文 | core |
| `weather/` | 天气切换 | 当前场景上下文 | core |
| `plots/` | 条件满足时触发 | 该剧情专用上下文 | full |
| `enemies/` (叙事) | 遭遇时加载 | 当前场景上下文 | core |
| `combat/enemies/` | 战斗启动 | CombatEngine 初始化 | full |
| `combat/cards/` | 战斗启动 | 按职业加载到卡池 | full |
| `combat/encounters/` | 战斗启动 | 遭遇配置 | full |
| `rules/` | 按需加载 | 系统规则参考 | summary |

## 如何添加新条目

以添加一个新角色为例，按顺序检查：

1. **角色文件** → `data/characters/新角色/index.md`（必须）
2. **角色索引** → 在 `data/characters/_index.md` 中注册
3. **种族引用** → 确认 `race` 值在 `data/races/_index.md` 的 keys 中已存在
   - 若不存在 → 需先创建对应种族文件和索引条目
4. **职业引用** → 确认 `class` 值在 `data/classes/_index.md` 的 keys 中已存在
   - 若不存在 → 需先创建对应职业文件和索引条目
5. **势力引用** → 确认 `faction` 值在 `data/factions/_index.md` 的 keys 中已存在
   - 若不存在 → 需先创建对应势力文件和索引条目
6. **物品引用** → 确认 `key_items` 中每个值在 `data/items/_index.md` 中已存在
   - 若不存在 → 需先创建对应物品文件和索引条目
7. **属性数值** → 确认 attributes 字段值在 1-10 范围内
   - 各等级含义参考 `data/attributes/` 中各属性定义

添加战斗数据：

1. **战斗敌人** → `data/combat/enemies/敌人名称.md`（使用 TEMPLATE_enemy.md）
2. **卡牌** → `data/combat/cards/职业名/卡牌名称.md`（使用 TEMPLATE_card.md）
3. **遭遇战** → `data/combat/encounters/遭遇id.md`（使用 TEMPLATE_encounter.md）
4. 所有战斗文件在 `data/combat/_index.md` 中自动注册

## 三级加载深度

系统通过 `RegistryManager` 控制注入 token 量：

| 深度 | 来源 | 典型 token | 触发时机 |
|-----|------|-----------|---------|
| **summary** | `_index.md` 的 summary 字段 | ~30 | 角色列表、场景物品一览 |
| **core** | 详细文件的特定章节（如 `## 生理特征` 前 3 段） | ~150 | 角色加载、地点/天气切换 |
| **full** | 完整 Markdown 文件 | ~400 | 玩家显式检视/询问时 |

RegistryManager 自动处理回退：文件不存在时，core/full → summary。
