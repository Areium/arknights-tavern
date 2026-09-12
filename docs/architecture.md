# 系统架构总览

> 状态：随代码演进 · 用途：本仓库的架构索引（模块职责、数据位置、关键约定）
> 仓库级协作规则（分支 / 并发防护）见根目录 `AGENTS.md`

---

## 1. 系统概述

明日方舟主题文字 RPG：

- **剧情模式** — LLM 驱动叙事 + 选项 + 记忆 + 环境
- **自由模式** — 沙盒角色交互
- **战斗** — 自由尺寸等距网格回合制（JSON 战斗节点 + 可扩展地形 + 统一曼哈顿度量；CSS 3D 网格 + PixiJS Spine 骨骼动画覆盖层）
- **世界书** — 酒馆 Lorebook 兼容的关键词触发式设定注入

运行链路：Electron 主进程管理窗口 + Python 子进程生命周期（`frontend/electron/`）→ React 渲染进程（`frontend/src/`，Vite 代理 `/api` → Flask `:5000`）→ Flask API（`src/app.py`，factory 模式组装 Manager + Blueprint）。

---

## 2. 后端（`src/`）

### 2.1 叙事与 LLM

| 模块 | 职责 |
|---|---|
| `app.py` | Flask factory `create_app()`，注册所有 Blueprint + 全局 Manager（含 WorldBookManager），入口 `main()` |
| `SceneManager.py` | 多角色场景编排，**两阶段叙述**：先 LLM 生成叙述文本流式推送，再 LLM 提取结构化标记（`[BEAT_COMPLETE]`、`[COMBAT]`、`[CHOICES]`、`[SUMMARY]`）。支持结构化对话输出（`parse_structured()`）用于气泡模式 |
| `CharacterAgent.py` | 单角色人设：角色卡 + 6 条行为规则 + Wiki 上下文 + 记忆注入 + function calling（wiki 查询工具，最多 3 轮） |
| `llm_backend_manager.py` | 多 Provider 编排，主/备自动降级（验证缓存 120s TTL + 真实失败 30s 冷却） |
| `load_llm.py` | Ollama / OpenAI 兼容 HTTP 客户端。**结构化错误（LLMError 系列，错误绝不伪装成模型回复）+ 连接/429/5xx 指数退避重试 + 请求指纹日志（前缀漂移标尺）+ `on_failure` 降级回调** |

### 2.2 会话与内容

| 模块 | 职责 |
|---|---|
| `session_manager.py` | 会话 CRUD、回滚、叙述变体。**`combat_mode`（`"narrative"` \| `"tactical"`）创建时选定，不可更改** |
| `session_overlay.py` | 职责聚合：角色/物品属性覆盖 + 剧情日志（保留最近 15 条）+ 节拍状态 + 任务系统 + 世界书绑定（`worldbook_id`） |
| `session_context.py` | 按会话缓存文档摘要 |
| `session_resources.py` / `session_export.py` | 会话级资源（背景/形象覆盖）与会话存档导出 |
| `environment_state.py` | 地点/天气/时间状态机，从 `data/environment/` 加载 |
| `wiki_manager.py` | 文档目录 + 三级深度提取（summary/core/full）+ `imports` 引用解析 |
| `document_manager.py` | 文件 CRUD + 哈希冲突检测 |
| `index_manager.py` | 基于 `imports` 字段的文档关系图，YAML 导出/导入 |
| `avatar_color.py` | 从角色 PNG 头像提取主导色（hex），用于 UI 主题配色 |
| `hooks/` | Hook 管道：`pipeline.py`（执行器）+ `attribute_roll.py` + `wiki_prefetch.py` |

### 2.3 世界书与记忆

- `world_book.py` — 世界书（酒馆 Lorebook 兼容）：4 源解析（v1/v2/卡内嵌/jsonl）+ 关键词触发匹配 + 注入格式化 + 回灌导出 + `WorldBookManager`（`data/worldbooks/`，gitignored）。
  **注入纪律：常驻 position-0 条目进稳定层，触发型条目一律进动态层（前缀缓存稳定）。**
- `memory.py` — `VectorMemory`：最近轮次滑动窗口 + ChromaDB 语义搜索，持久化于 `data/memory/`（gitignored）。

### 2.4 战斗后端

| 模块 | 职责 |
|---|---|
| `combat_session.py` | 战斗会话包装器：组装 CombatEngine + CombatDataLoader，管理生命周期、玩家操作、敌人 AI、SSE 推送 |
| `combat_data_loader.py` | 加载战斗节点 `data/combat/nodes/*.json`、敌人 `data/enemies/*.md`（叙事 attributes + 战斗 combat_stats，缺 combat_stats 时按 attributes 派生）与 `backgrounds/` |
| `combat_map.py` | 战斗地图 JSON：尺寸/格子类型注册表/部署区解析与校验（行列定位错误、软锁警告、上限 40×40） |
| `combat_nodes.py` | 战斗节点注册表：JSON 读写 + `_hash` 冲突检测 + 校验 + 剧情节拍绑定/进度 + 世界书归属（节点 `worldbook_id`，剧情/资产/卡牌同约定）+ 剧情流程解析 `plot_flows`（章节/节拍/`[COMBAT:]` 引用，只收剧情叙述区）+ 节点图数据 `node_graph`（`shared/json_hash.py` 与卡牌共用哈希） |
| `combat_balance.py` | 威胁模型（五类模板/威胁点/阶段带推荐/预算对照），校验器、编辑器与生成工具共用 |
| `combat_rules.py` | 战斗配置加载：`data/combat/rules/{growth,difficulty}.json`（升级属性点、阶段带缩放与威胁容差，按 mtime 热加载） |

战斗引擎（`src/combat_engine/`）：

- `engine.py` — 回合循环 / AP / 士气 / 地形效果 / 寻路移动
- `entity.py` — `CombatUnit`
- `grid.py` — 自由尺寸网格、Dijkstra 寻路、视线、统一曼哈顿度量与目标形状
- `card.py` / `card_data.py` — 卡牌 / CardPool；职业基础卡牌以 JSON 为单一真相源
- `dice.py` — 命中/伤害，含 `terrain_mods` 地形修正

### 2.5 API 层（`src/blueprints/`，Flask Blueprint）

`chat.py`（对话/叙述/SSE/战斗触发）、`combat.py`（战斗 SSE + 敌人/格子目录）、`combat_nodes.py`（战斗节点 CRUD/校验/按世界书过滤/节点图 graph/节拍进度）、`cards.py`（卡牌 JSON CRUD + 所属世界书标注树）、`documents.py`（文档读写，剧情节点图编辑 plots 用）、`sessions.py`、`scene.py`、`environment.py`、`index.py`、`wiki.py`、`llm.py`、`assets.py`（图片资产 + 实体来源世界书标注）、`memories.py`、`status.py`、`worldbook.py`（书 CRUD/导入/条目/默认书/会话绑定）。

### 2.6 服务 / 共享 / Provider

- 服务层（`src/services/`）：`dice.py`、`attribute_loader.py`
- 共享工具（`src/shared/`）：`helpers.py`（SSE 响应工厂、记忆注入）、`cache.py`
- Provider（`src/providers/`）：`openai.py`、`deepseek.py`

### 2.7 测试

`tests/`（已纳入版本控制，含黄金基线 `tests/golden/`）+ `perf_tests/test_*_v1.py`（无外部依赖的战斗/结算子集）。统一入口 `bash scripts/run_tests.sh`（内含 pytest 与 `tests/legacy/` 脚本式检查）。

---

## 3. 前端（`frontend/src/`）

### 3.1 入口与外壳

`main.tsx`（React 18 createRoot）→ `App.tsx`：GameTopBar（管理页顶栏：返回主菜单 + 管理页导航，返回入口全站唯一）+ StatusBar（状态栏）+ 内容区（HomeMenu / ChatView / CombatView / SessionManagerView / CharacterManager / WorldBookManager / ContentHub / DocsView / SettingsPanel）。轮询后端状态 5s、LLM 状态 10s、会话列表 15s。

### 3.2 聊天

- `components/ChatView.tsx` — 对话页容器：会话列表 + 场景面板（角色/物品/环境/记忆/任务）+ `ChatPanel.tsx`（消息流/流式输出/选项/变体/回滚/对话气泡）
- `components/chat/` — 气泡渲染子组件（DialogueBubble、NarrationText、AvatarPlaceholder 等）
- `components/MarkdownRenderer.tsx` — 统一 Markdown 渲染
- `utils/dialogueParser.ts` — 解析 `「」` 对话为 `DialogueSegment[]`，前文叙述匹配场景角色名确定说话人
- `utils/baseUrl.ts` — 后端地址解析（Electron/浏览器）

### 3.3 战斗

- `components/combat/CombatView.tsx` — 战斗主控（50k+ LOC，最大组件）
- `components/combat/NodeFlowEditor.tsx` — 节点流编辑器（内容中心「节点图」Tab）：先选世界书再编辑，横向可展开节点图同屏呈现剧情节点（plot 章节/节拍）与战斗节点（`[COMBAT:]` 引用连线），点击节点开右侧抽屉编辑、支持增删
- `components/combat/BattleNodeForm.tsx` — 单个战斗节点编辑表单（抽屉内挂载：地图绘制 BattleMapCanvas + 敌人编成与血量覆盖 + 服务端校验 + 试打）
- `components/combat/StoryBeatEditor.tsx` — 剧情节拍编辑抽屉（对 `data/plots/<id>/index.md` 做节拍增删改，配合 `utils/plotBeatEditor.ts` 的 Markdown 手术）
- `components/combat/` 其余 — CSS 网格（CombatGrid：行列自由尺寸 + 地形着色 + 部署区标识）+ PixiJS Spine 覆盖层（PixiCombatScene，runtime-3.8）+ 手牌（CombatHand）+ 卡组查看（DeckViewer）+ 卡牌编辑（CardEditor）+ 状态/事件面板 + Spine 动画规格（`spineAnimSpecs.ts`）
- `audio/audioManager.ts` — 战斗音效管理

### 3.4 管理页

- `components/ContentHub.tsx` — 内容中心（Tab：索引/资产/卡牌/节点图；文档管理已移除——世界观语料经 `scripts/generate_builtin_worldbook.py` 整理为世界书整合包 `data/packs/arknights.json`，浏览与编辑走世界书模块）
- `components/AssetManager.tsx` — 资产目录：图片上传/裁剪/默认图，实体显示上级目录与来源世界书（frontmatter `worldbook_id`），按书筛选与归类
- `components/CardManager.tsx` — 卡牌管理：角色/职业卡牌编辑（CardEditor），条目显示所属世界书，按书筛选
- `components/WorldBookManager.tsx` — 世界书管理：导入（文件/粘贴，支持角色卡 PNG/JSON 连带导入角色 + 内嵌世界书）、条目编辑器、会话绑定、酒馆格式导出
- `components/SettingsPanel.tsx` — LLM 配置/主题/叙述选项

### 3.5 状态与数据获取

- `stores/appStore.ts`（Zustand 4）
  - **Key 刷新模式** — 多个自增整数 key（`envRefreshKey`、`memoryRefreshKey`、`chatRefreshKey`、`characterRefreshKey`、`sceneSwitchKey`），组件比较 key 检测数据过期
  - **按会话存储** — 消息/流式/发送状态按 `sessionId` 隔离，切换会话不丢失
  - 关键状态：`combatContext`（VIEWING/TARGETING + 选中卡牌/单位）、`pendingAutoNarrate`（战后自动叙述）、`dialogueBubbleMode`（气泡/纯文本切换）
- `hooks/useApi.ts` — REST + SSE 客户端（`connectSSE` 支持 GET/POST 事件流），自动检测 Electron/浏览器环境

### 3.6 UI 皮肤系统

- `appStore.skin: SkinId = "default" | "prts" | "tavern"`，持久化在后端 `config/llm_config.json` 的 `skin` 字段（`src/llm_backend_manager.py` 白名单校验，非法值回落 `default`）。
- `App.tsx` 按 `skin` 在 `<html>` 上切换 `skin-prts` / `skin-tavern` / `light` 三个 class —— 皮肤激活时 `light` 被抑制（仅 `skin === "default" && theme === "light"` 才加），设置页的明暗开关同步置灰。
- 两套皮肤是纯覆盖层 CSS（`src/styles/skin-prts.css`、`src/styles/skin-tavern.css`），沿用 `style.css` 中 `html.light` 的既有模式，**不做 CSS 变量重构**。
- 颜色工具类覆盖块（两个文件里由「工具类覆盖（由 scripts/gen_skin_utils.py 生成，勿手改）」标记界定的区段）由 `scripts/gen_skin_utils.py` 按色板生成 —— 前端实际用到 243 个颜色工具类（含 `hover:` / `placeholder:` 等变体与自定义 `surface-*` 色板），手写必漏，**改配色请改脚本里的色板后重跑**（`python scripts/gen_skin_utils.py`），不要手改该区段。
- 氛围仅静态（PRTS 扫描线、Tavern 烛光渐变），无动画，各带 `prefers-reduced-motion` 兜底。
- 作用域用 `@scope (html.skin-*) to (.bg-combat-bg)` 界定，**战斗页不换肤**（否则它复用的大量 `bg-gray-*` / `text-gray-*` 工具类会被污染）。覆盖范围：外壳 + 会话大厅 + 管理页 + 聊天页；视觉蓝本见 `ui-styles/02-prts-holo-terminal.html`、`ui-styles/03-tavern-journal.html`。

---

## 4. 内容工具与脚本

战斗内容工具（`tools/`）：

| 工具 | 用途 |
|---|---|
| `validate_battle_spec.py` | 候选规格校验，退出码门禁 |
| `simulate_battle.py` | 固定种子试跑 + 阈值判定 |
| `generate_battle_spec.py` | 按阶段带程序化生成合法战斗 |
| `balance_audit.py` | 敌人分层/XP 单调性/节点预算审计 |
| `metric_migration_report.py` | 度量迁移前后对照 |

生成流程与硬性约束见 skill `combat-designer`，规格说明见 `docs/battle-spec.md`。

其他脚本：`scripts/generate_builtin_worldbook.py`（世界书整合包）、`scripts/gen_skin_utils.py`（皮肤颜色工具类生成）、`scripts/run_tests.sh`（统一测试入口）。

---

## 5. 设计文档地图（`docs/`）

| 文档 | 内容 |
|---|---|
| `architecture.md` | 本文件：架构索引 |
| `combat-design.md` | 战斗引擎架构与机制设计 |
| `combat-numerical-design.md` | 战斗数值公式与平衡参数 |
| `combat-ui-design.md` | 战斗界面交互与布局设计 |
| `battle-spec.md` | 战斗规格（节点 JSON 全字段/地形效果/威胁与阶段带/校验规则/生成闭环），LLM 与设计者共用 |
| `combat-background-prompts.md` | 战斗背景图生成提示词规范 |
| `content-hub-design.md` | 内容中心整合设计 |
| `tutorial.md`、`game-experience-roadmap.md`、`perf-round-latency.md` | 教程、体验路线、性能记录 |
| `prompt.md` | Prompt 工程策略与模板设计 |
| `system-update-log.md` | 系统更新日志 |
| `archive/combat-core-design.md` | 章节战斗化改造方案（**已实现**，2026-08，已归档）。其中「7×7 网格明确不改」的骨架条款**已作废**，现状以代码与 `combat-design.md` 为准 |
