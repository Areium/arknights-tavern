# Data 目录说明

## 目录结构

```
data/
├── categories.yaml          ← 类别注册表（类别 ID → 目录映射 + 层级定义）
├── README.md                ← 本文件（人类可读说明）
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
│   ├── encounters/        ← 遭遇战配置
│   └── backgrounds/       ← 战斗背景（提示词 index.md + 图片）
│
├── rules/                 ← 游戏机制规则定义
│   ├── combat-system/     ← 战斗系统规则（战术/叙事模式）
│   ├── rarity-system/     ← 稀有度分级
│   ├── debuff-system/     ← 负面效果规则
│   ├── buff-pool/         ← Buff/Debuff 抽取池
│   └── deviation-states/  ← 剧情偏离状态
│
├── worldbooks/            ← 世界书运行时数据（gitignored）
│
└── memory/                ← 向量记忆 + 会话持久化
    ├── chroma.sqlite3     ← ChromaDB 向量数据库
    └── sessions/          ← 会话状态（session.json / overrides.json）
```

> 战斗卡牌定义不在 `data/combat/` 下：专属卡牌在 `data/characters/<角色>/combat.json`，
> 职业卡池在 `data/classes/<职业>/cards.json`（`src/combat_engine/card_loader.py` 加载）。

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
                    │  environment/ │  ← 环境数据（经 categories.yaml 注册）
                    │  Location/   │      locations / weather 由 SceneManager 管理
                    │  weather/    │      位于 data/ 内，通过 categories.yaml 注册到系统
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

## 引用方式

所有文档通过在 frontmatter 中声明 `imports` 字段来引用其他文档：

```yaml
imports:
  - classes/术师
  - factions/罗德岛
  - characters/博士 | 博士
```

格式为 `类别/文档ID`，可选 ` | 显示名称`。系统据此自动构建全局引用图和索引树。

添加战斗数据：

1. **战斗敌人** → `data/combat/enemies/敌人名称.md`（使用 TEMPLATE_enemy.md）
2. **卡牌** → `data/combat/cards/职业名/卡牌名称.md`（使用 TEMPLATE_card.md）
3. **遭遇战** → `data/combat/encounters/遭遇id.md`（使用 TEMPLATE_encounter.md）
4. 添加后系统自动通过目录扫描发现新文档

## 三级加载深度

系统通过 `RegistryManager` 控制注入 token 量：

| 深度 | 来源 | 典型 token | 触发时机 |
|-----|------|-----------|---------|
| **summary** | 文档 frontmatter 的 summary 字段 | ~30 | 角色列表、场景物品一览 |
| **core** | 详细文件的特定章节（如 `## 生理特征` 前 3 段） | ~150 | 角色加载、地点/天气切换 |
| **full** | 完整 Markdown 文件 | ~400 | 玩家显式检视/询问时 |

RegistryManager 自动处理回退：文件不存在时，core/full → summary。
