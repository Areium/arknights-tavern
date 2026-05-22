# Data 目录说明

## 目录结构

```
data/
├── _INDEX.md              ← 总索引（机器可读注册表）
├── README.md              ← 本文件（人类可读说明）
├── attributes.md          ← 属性等级参考（1-10 级详解）
│
├── characters/            ← 角色定义
│   ├── _index.md          ← 角色索引
│   ├── TEMPLATE.md        ← 角色模板
│   └── *.md               ← 角色文件
│
├── races/                 ← 种族百科
│   ├── _index.md          ← 种族索引
│   ├── TEMPLATE.md        ← 种族模板
│   └── *.md               ← 种族文件
│
├── classes/               ← 职业体系
│   ├── _index.md          ← 职业索引
│   ├── TEMPLATE.md        ← 职业模板
│   └── *.md               ← 职业文件
│
├── factions/              ← 势力/组织
│   ├── _index.md          ← 势力索引
│   ├── TEMPLATE.md        ← 势力模板
│   └── *.md               ← 势力文件
│
├── items/                 ← 物品百科
│   ├── _index.md          ← 物品索引
│   ├── TEMPLATE.md        ← 物品模板
│   └── *.md               ← 物品文件
│
├── plots/                 ← 剧情节点
│   ├── _index.md          ← 剧情索引
│   ├── TEMPLATE.md        ← 剧情模板
│   └── *.md               ← 剧情文件
│
├── world/                 ← 世界观文档
│   ├── _index.md          ← 世界观索引
│   ├── TEMPLATE.md        ← 世界观模板
│   └── *.md               ← 世界观文件
│
└── memory/                ← ChromaDB 向量记忆（自动生成）
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
                           │ 引用 location / weather
              ┌────────────┴────────────┐
              ▼                         ▼
    environment/Location/    environment/weather/
    地点/场景                  天气类型
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
| `locations/` | 地点切换 | 当前场景上下文 | core |
| `weather/` | 天气切换 | 当前场景上下文 | core |
| `plots/` | 条件满足时触发 | 该剧情专用上下文 | full |

## 如何添加新条目

以添加一个新角色为例，按顺序检查：

1. **角色文件** → `data/characters/新角色.md`（必须）
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
   - 各等级含义参考 `data/attributes.md`

## 三级加载深度

系统通过 `RegistryManager` 控制注入 token 量：

| 深度 | 来源 | 典型 token | 触发时机 |
|-----|------|-----------|---------|
| **summary** | `_index.md` 的 summary 字段 | ~30 | 角色列表、场景物品一览 |
| **core** | 详细文件的特定章节（如 `## 生理特征` 前 3 段） | ~150 | 角色加载、地点/天气切换 |
| **full** | 完整 Markdown 文件 | ~400 | 玩家显式检视/询问时 |

RegistryManager 自动处理回退：文件不存在时，core/full → summary。
