# 系统更新设计与维护文档

> 记录战斗系统的架构演进、关键修改与未来规划方向
> 最后更新：2026-05-25

---

## 目录

1. [更新记录](#更新记录)
2. [当前系统状态](#当前系统状态)
3. [未来修改计划](#未来修改计划)
4. [系统整体架构](#系统整体架构)

---

## 更新记录

### 2026-05-25 — 角色卡牌扩展：临光 / 佐菲娅 / 博士

- 临光新增 3 张卡牌：盾牌格挡(★)、骑士的号令(★★)、耀骑士之名(★★★)
- 佐菲娅(新角色)新增 4 张卡牌：基础剑术(★)、社交之眼(★★)、临光的家徽(★★★★★)、家族的脊梁(★★★★★★)
- 博士新增 4 张卡牌：战术指令·前进(★)、战场评估(★★)、博士的计策(★★★)、石棺的记忆(★★★★★★)
- 6★ 卡牌均包含详细剧情影响段落，与角色弧线和世界观设定深度绑定

### 2026-05-25 — 会话级 Token 累计统计 + 聊天面板标题栏

- Session 新增 `total_usage` 累计字段，持久化到会话 JSON
- 所有 LLM 调用路径（chat/group-chat/narrate/narrate-continue/narrate-variant）接入 `accumulate_usage()`
- ChatPanel 新增标题栏：会话名、当前轮数、累计 token 消耗（入/出）
- Session 类型定义扩展 `narration_count` 和 `total_usage`

### 2026-05-25 — Phase 2 后端重构：Blueprint 架构 + Wiki 工具调用 + 结构化对话

**修改动机**：原有 `app.py` 2569 行单体路由难以维护，缺乏工具调用和结构化输出能力，registry_manager 设计过时。

**核心变更**：

| 模块 | 变更 |
|------|------|
| `src/app.py` | 从 2569 行单体重构为 115 行 Flask factory（`create_app()`），路由拆分为 13 个 Blueprint |
| `src/blueprints/` | 新增 13 个功能域 Blueprint（sessions, chat, scene, combat, documents, index, llm, wiki, environment, assets, legacy, memories, status） |
| `src/wiki_manager.py` | 新增 WikiManager：全量目录索引、imports 链 BFS 展开（depth 0/1/2）、模糊查询、目录摘要注入、LLM 摘要回填 |
| `src/session_context.py` | 新增会话文档缓存：角色变化时沿 imports 链预加载 |
| `src/CharacterAgent.py` | 新增 `wiki_query` 工具调用（最多 3 轮），会话文档上下文注入，token 用量追踪 |
| `src/SceneManager.py` | 新增结构化叙述模式（JSON 片段数组：narration/dialogue）、3 级 JSON 修复回退、`narrate_stream()` 线程+队列流式生成 |
| `src/load_llm.py` | `chat()` 返回值从 `str` 改为 `dict`（`{type, content, usage, tool_calls}`），新增工具调用解析（Ollama/OpenAI），`chat_text()` 向后兼容辅助 |
| `src/session_manager.py` | RegistryManager → WikiManager 迁移，Session 集成 WikiManager/SessionContext |
| `src/constants.py` | 新增核心章节提取规则、属性名中英文映射 |
| `src/avatar_color.py` | 从头像提取主题色，自动写入角色 frontmatter |
| `src/services/` | 新增 buff 池抽取系统和 d20 骰子系统 |
| `src/shared/` | 抽取公共辅助（SSE 响应、JSON 错误、缓存失效） |
| `src/combat_session.py` | 新增 `CombatTestSessionManager` 替代全局 dict |
| 删除文件 | `GameAgent.py`（840 行）、`registry_manager.py`（489 行）、`logging_setup.py`、`main.py`、`ui.py` — 均为死代码 |
| 前端 | 对话气泡模式（DialogueBubble/AvatarPlaceholder/NarrationText/LoadingIndicator/TokenUsage）、角色立绘组件（CharacterIllustration）、对话解析器（dialogueParser）、SSE 事件扩展（dialogue_segments/token_usage） |
| 数据模板 | v4.0→v5.0：imports 依赖链替代可检索条目章节，新增 summary 字段 |
| 资产 | 12 个角色 + 1 个新角色（佐菲娅）的 avatar/skin PNG 资产 |
| 依赖 | 移除 `readchar`，新增 `Pillow`（头像取色） |

### 2026-05-24 — 代码与数据冗余清理

- 移除未使用的 npm 依赖（react-markdown、d3-force、@types/d3-force）
- 删除前端死代码：`getCellSize`/`getCardSize`（combatConfig）、`getIndexGraph`/`getOverrides`/`listDocuments`（useApi）、`"MOVING"` UI 模式（appStore）
- 删除 CombatGrid 未使用的 props（`grid`、`validTargets`、`validMoves`）
- 删除后端死代码：`combat_data_loader.py` 中未使用的卡牌加载方法、`engine.py` 中 3 个未使用方法（`get_unit_hand`/`get_active_unit`/`to_dict`）、`index_manager.py` 中未使用的会话配置函数
- 清理死数据：删除 `data/combat/cards/` 下 55 个卡牌 markdown 文件（卡牌数据已由 `card_data.py` 硬编码管理）
- `engine.py` 中 `execute_enemy_turn` 重命名为 `_execute_enemy_turn`（仅内部调用）
- 修复 `app.py` 中 `_project_root` 变量名遮蔽导致战斗测试 500 错误
- 战斗错误提示增加 5 秒自动消失

### 2026-05-24 — 全局索引管理系统 + 等距网格优化

**修改动机**：原有索引分散在文档 frontmatter 中，缺乏全局管理视图和可视化引用树。战斗网格需要等距 3D 效果和小精灵覆盖层优化。

**修改内容（本地）**：

| 模块 | 变更 |
|------|------|
| `src/index_manager.py` | 新增全局索引配置管理器：CRUD、反向引用树构建、会话级配置、YAML 导入/导出、全量树合并（含未配置文档） |
| `frontend/src/components/IndexManager.tsx` | 新增索引管理组件：三栏布局（配置文件列表 + 文档树 \| 详情引用编辑 \| 实体选择添加）、引用树全屏视图、类别筛选、YAML 导入/导出、会话配置切换 |
| `frontend/src/components/DocumentManager.tsx` | 移除逐文档索引编辑面板，索引管理统一由 IndexManager 处理 |
| `frontend/src/components/Sidebar.tsx` | 新增"🔗 索引"导航项 |
| `frontend/src/App.tsx` | 注册索引视图路由 |
| `frontend/src/stores/appStore.ts` | `currentView` 类型扩展 `"index"` |
| `frontend/src/types/index.ts` | 新增索引配置树类型定义 |
| `frontend/src/hooks/useApi.ts` | 新增索引配置 API 方法（全量树、添加/移除文档、来源列表） |
| `src/app.py` | 新增索引配置 REST 路由 |

**修改内容（远程）**：

| 模块 | 变更 |
|------|------|
| `CombatGrid.tsx` | 等距 3D 网格渲染、小精灵覆盖层叠加 |
| `GridCell.tsx` | 单元格交互优化、反选支持 |
| `CombatView.tsx` | 交互逻辑重构、状态管理优化 |
| `AttackArrow.tsx` | 攻击箭头简化重构 |
| `CombatParticles.tsx` | 粒子特效优化 |
| `gridUtils.ts` | 新增网格工具模块 |

### 2026-05-23 — 角色悬浮提示 + 会话覆盖战斗集成

- 新增 `CombatUnitTooltip` 组件（Portal 浮层，展示属性/数值）
- 战斗启动时应用会话 overrides（角色编辑后的属性流入战斗）
- 新增 `POST /combat/complete` 战斗结算写回端点
- 新增 DeckViewer 卡组查看组件（按角色分组，手牌/抽牌堆/弃牌堆/消耗堆）

### 2026-05-23 — 战斗 UI 合并与优化

- 拖拽出牌支持，3D 透视网格，CSS 粒子特效
- GridCell 按钮嵌套修复（ChibiSprite 改为 pointer-events-none）
- 选中/活跃单位视觉区分（分别使用不同边框样式）
- 卡牌攻击范围高亮

---

## 当前系统状态

### 已实现功能

- [x] 共享卡池系统（全队共用抽牌堆/手牌/弃牌堆/消耗堆）
- [x] 共享回合制（全队同时行动，自由选择角色出牌）
- [x] 双 AP 池（共享 AP + 个人 AP）
- [x] 角色保底机制（每轮每角色至少 1 张可用牌）
- [x] 敌方 AI（寻敌→出牌→移动）
- [x] 命中/伤害计算（d20 体系）
- [x] 网格站位（9×8，Chebyshev 距离）
- [x] 卡牌目标模式（SINGLE/ADJACENT/CROSS/LINE_3/ROW/ALL_ALLIES/GLOBAL）
- [x] 角色属性→战斗数值映射
- [x] 会话 overrides 战斗集成
- [x] 战斗结算写回
- [x] SSE 事件流（伤害/治疗/死亡/回合/战斗结束）
- [x] 浮动伤害数字 + 粒子特效
- [x] 角色悬浮工具提示（属性+数值）
- [x] 卡组查看器
- [x] 战斗测试模式（无需会话）
- [x] 战斗存档/读档
- [x] Blueprint 模块化路由架构（13 个功能域）
- [x] Wiki 文档目录索引 + imports 链预加载
- [x] LLM 工具调用（wiki_query）
- [x] 结构化对话输出（JSON narration/dialogue 片段）
- [x] SSE 流式叙述（Token 级渐进显示）
- [x] 对话气泡模式（角色主题色）
- [x] 角色立绘展示（战斗选中时）
- [x] 会话级 token 累计统计
- [x] Buff/Debuff 抽取池系统
- [x] d20 独立掷骰服务

### 已知限制

- [ ] 敌方 AI 简单（仅攻击最近目标，无策略）
- [ ] 无角色死亡后的卡组清理
- [ ] 精英牌消耗后无法回收
- [ ] 无 buff/debuff 系统
- [ ] 网格移动无碰撞检测（单位不可重叠但可穿越）

---

## 未来修改计划

### 短期（下一阶段）

1. **个人 AP 系统完善**
   - 当前个人 AP 在回合开始时重置，但未在前端展示
   - 移动消耗个人 AP 而非共享 AP
   - 角色专属牌消耗个人 AP，通用牌消耗共享 AP

2. **敌方 AI 增强**
   - 引入行为模式（攻击型/防守型/支援型）
   - 优先攻击低血量/高威胁目标
   - 敌方治疗单位 AI

3. **buff/debuff 系统**
   - 状态效果（眩晕、中毒、脆弱、加固等）
   - 持续时间与层数
   - 与卡牌/遗物系统的交互

4. **战斗 UI 打磨**
   - 攻击动画（弹道/冲击）
   - 单位受伤/死亡动画
   - 音效系统接口

### 中期

5. **遗物/物品系统**
   - 战斗中被动效果（属性加成、触发效果）
   - 主动物品（一次性/冷却制）
   - 物品数据从 markdown 加载

6. **多波次遭遇战**
   - 波次间增援
   - 波次过渡动画
   - 波次奖励/回复

7. **战斗回放**
   - 记录全部行动序列
   - 回放渲染（步进/自动播放）

### 长期

8. **PvP 框架**
   - 双方轮流操作的异步对战
   - 匹配与排行

9. **模组化遭遇战编辑器**
   - 可视化编辑遭遇配置
   - 预览敌方站位

---

## 系统整体架构

### 技术栈

```
┌─────────────────────────────────────────────────┐
│                   Frontend                       │
│  React 18 + TypeScript + Zustand + Tailwind     │
│  Vite 构建  ·  Electron 桌面壳（可选）           │
├─────────────────────────────────────────────────┤
│                   Backend                        │
│  Flask (Python 3.12) + REST + SSE               │
│  Blueprint 架构  ·  WikiManager  ·  SceneManager │
│  SessionManager  ·  SessionContext  ·  Overlay   │
├─────────────────────────────────────────────────┤
│                Combat Engine                     │
│  纯 Python  ·  独立于 Flask                      │
│  engine.py  ·  entity.py  ·  card.py            │
│  grid.py  ·  dice.py  ·  card_data.py           │
├─────────────────────────────────────────────────┤
│                   Data                           │
│  Markdown + YAML Frontmatter                     │
│  data/characters/  ·  data/combat/              │
│  Wiki 目录索引  ·  imports 依赖链               │
│  overrides.json（会话层持久化）                  │
└─────────────────────────────────────────────────┘
```

### 前端架构

```
frontend/src/
├── components/
│   ├── ChatPanel.tsx            — 对话面板（SSE 流式、气泡模式、token 统计）
│   ├── Sidebar.tsx              — 主导航栏
│   ├── DocumentManager.tsx      — 文档管理（树/内容编辑器）
│   ├── IndexManager.tsx         — 全局索引配置管理（三栏布局 + 引用树）
│   ├── SettingsPanel.tsx        — 设置面板
│   ├── SessionList.tsx          — 会话列表（自动命名、去重）
│   ├── CharacterPanel.tsx       — 角色面板
│   ├── chat/                    — 对话气泡组件
│   │   ├── DialogueBubble.tsx   — 角色对话气泡（主题色边框/背景）
│   │   ├── AvatarPlaceholder.tsx — 角色头像占位图
│   │   ├── NarrationText.tsx    — 叙述文本
│   │   ├── LoadingIndicator.tsx — 等待加载指示器
│   │   └── TokenUsage.tsx       — 单次响应 token 消耗展示
│   └── combat/
│       ├── CombatView.tsx          — 战斗主视图（状态管理、事件中枢）
│       ├── CombatGrid.tsx          — 网格渲染（等距 3D、拖放、单元格）
│       ├── GridCell.tsx            — 单个单元格（单位显示、小精灵、高亮）
│       ├── ChibiSprite.tsx         — 角色小精灵（纯展示，pointer-events-none）
│       ├── CombatHand.tsx          — 手牌扇形布局
│       ├── CombatCard.tsx          — 单张卡牌（拖拽源、渐变、AP 消耗）
│       ├── UnitStatusPanel.tsx     — 角色状态面板（HP/AP/属性摘要）
│       ├── CombatUnitTooltip.tsx   — 角色悬浮提示（Portal，属性+数值）
│       ├── CombatEventLog.tsx      — 战斗事件日志
│       ├── CombatParticles.tsx     — Canvas 粒子特效
│       ├── CharacterIllustration.tsx — 角色立绘展示（选中时显示）
│       ├── gridUtils.tsx           — 网格工具函数
│       └── DeckViewer.tsx          — 卡组查看器（按角色/牌堆分组）
├── hooks/
│   └── useApi.ts               — API 客户端（REST + SSE）
├── utils/
│   └── dialogueParser.ts       — 对话解析器（「」→ 气泡片段，说话人推断）
├── stores/
│   └── appStore.ts             — Zustand 全局状态
├── types/
│   └── index.ts                — TypeScript 类型定义
└── style.css                   — 战斗样式（粒子动画、网格 3D、手牌扇形）
```

### 后端架构

```
src/
├── app.py                      — Flask 应用入口（create_app 工厂模式）
├── constants.py                — 共享常量（核心章节规则、属性映射）
├── session_manager.py          — 会话生命周期管理 + token 累计
├── SceneManager.py             — 场景管理：多角色对话、结构化叙述、SSE 流式生成
├── CharacterAgent.py           — 角色代理：角色扮演 + wiki_query 工具调用 + 记忆
├── session_overlay.py          — 会话层数据覆盖（overrides.json）
├── session_context.py          — 会话文档缓存（imports 链预加载）
├── wiki_manager.py             — Wiki 文档索引与查询（目录构建、imports 链展开、模糊查询、摘要回填）
├── index_manager.py            — 全局索引配置管理（CRUD、反向引用树、会话级配置）
├── avatar_color.py             — 从头像提取主题色，写入角色 frontmatter
├── combat_session.py           — 战斗会话封装（CombatEngine → REST/SSE）
├── combat_data_loader.py       — 战斗数据加载（遭遇/敌人）
├── document_manager.py         — 文档 CRUD + 冲突检测
├── llm_backend_manager.py      — LLM 多后端检测与自动降级
├── load_llm.py                 — LLM 加载器（Ollama/API），支持工具调用和 token 追踪
├── environment_state.py        — 环境状态追踪
├── memory.py                   — 向量记忆系统（ChromaDB）
├── blueprints/                  — Flask Blueprints（功能域路由拆分）
│   ├── sessions.py             — 会话 CRUD + 剧情列表
│   ├── chat.py                 — 对话/叙述 API（SSE 流式、变体生成）
│   ├── scene.py                — 场景角色/物品/覆盖管理 + 角色头像/立绘
│   ├── combat.py               — 会话战斗 + 战斗测试
│   ├── documents.py            — 文档 CRUD + 冲突检测
│   ├── index.py                — 索引配置管理
│   ├── llm.py                  — LLM 后端配置
│   ├── wiki.py                 — Wiki 目录查询 + 摘要回填
│   ├── environment.py          — 环境状态
│   ├── assets.py               — 静态资源
│   ├── legacy.py               — 旧版路由兼容
│   ├── memories.py             — 回忆系统
│   └── status.py               — 健康检查
├── services/                    — 服务层
│   ├── dice.py                 — d20 掷骰系统（关键词检测、文本解析）
│   └── buff_pool.py            — Buff/Debuff 随机抽取池（稀有度分层）
├── shared/                      — 共享工具
│   ├── helpers.py              — JSON 错误、SSE 响应、记忆上下文注入
│   └── cache.py                — 文档变更后缓存失效
└── combat_engine/
    ├── __init__.py             — 公开 API 导出
    ├── engine.py               — 战斗状态机、回合管理、敌方 AI
    ├── entity.py               — 战斗单位（属性映射、数值换算）
    ├── card.py                 — 卡牌、卡池（抽牌/弃牌/消耗）
    ├── card_data.py            — 卡牌数据定义、职业卡池、起始卡组
    ├── grid.py                 — 网格系统（站位、移动、距离、目标解析）
    └── dice.py                 — d20 掷骰、命中判定、伤害计算
```

### 数据流

```
Markdown 数据 ──→ CombatDataLoader ──→ CombatEngine
                                          │
会话 overrides ──→ SessionOverlay ──→ character_metas
                                          │
                    ┌─────────────────────┘
                    ▼
              CombatSession
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   REST API    SSE Stream   状态快照
   (action)    (events)    (get_state)
        │           │           │
        ▼           ▼           ▼
   CombatView ◄── React State ◄── JSON
```


### 战斗状态机

```
INIT ──→ ROUND_START ──→ PLAYER_TURN ──（玩家结束回合）──→ ENEMY_TURN
  ↑                                            │                │
  │                              轮次+1，抽牌，重置 AP            │
  │                                            │                │
  └────────────────────────────────────────────┘                │
                                                    所有敌方行动完成
                                                           │
                                                    检查胜负 ──→ END
```

### 核心数据模型

```
CombatUnit                    Card                      CardPool
├─ unit_id                   ├─ card_id                ├─ deck: list[Card]
├─ name                      ├─ name                   ├─ hand: list[Card]
├─ team (player/enemy)       ├─ damage_type            ├─ discard: list[Card]
├─ char_class                ├─ min/max_damage         ├─ exhaust: list[Card]
├─ HP / PATK / MATK / ...    ├─ atk_scale              └─ hand_size: int
├─ AP (personal)             ├─ target (SINGLE/...)
├─ pos [row, col]            ├─ range
├─ attributes (raw 1-10)     ├─ cost
└─ is_alive                  ├─ tier (basic/elite)
                             ├─ class_required
                             └─ owner (character name)
```

### 共享 AP 计算

```
SHARED_AP_MAX = 2 + max(0, (highest_tactical_planning - 5) // 3)
                 ───   ──────────────────────────────────────
                 基础               战术规划加成
                                   (6-7: +0, 8-10: +1, ...)
```

### 卡牌保底机制

每轮抽牌后，检测每位存活角色在共享手牌中是否至少有一张归属卡牌。如果没有，从抽牌堆/弃牌堆/消耗堆中随机找一张该角色的卡牌，替换手牌中随机一张。此机制保证每位角色都有可用的行动选择。
