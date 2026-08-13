# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在本仓库中工作时提供指导。

## Git 工作流
MUST 实现和修改功能前，遵循以下分支工作流：
1. 使用git从 `main` 创建 **feature 分支**，使用描述性名称（如 `feat/combat-ai`、`fix/memory-leak`）
2. 在 feature 分支上 **完成所有修改**
3. **充分测试**，确保正确性
4. 测试通过后 **合并回 `main`**
5. 合并成功后 **删除 feature 分支**
禁止将大型功能变更直接提交到 `main`。


## 项目架构

### 系统概述

明日方舟主题文字 RPG：剧情模式（LLM 驱动叙事 + 选项 + 记忆 + 环境）、自由模式（沙盒角色交互）、7×7 等距网格回合制战斗（CSS 3D 网格 + PixiJS Spine 骨骼动画覆盖层）、世界书（酒馆 Lorebook 兼容的关键词触发式设定注入）。

Electron 主进程管理窗口 + Python 子进程生命周期（`frontend/electron/`）→ React 渲染进程（`frontend/src/`，Vite 代理 `/api` → Flask `:5000`）→ Flask API（`src/app.py`，factory 模式组装 Manager + Blueprint）。

### 核心后端（`src/`）
- `app.py` — Flask factory `create_app()`，注册所有 Blueprint + 全局 Manager（含 WorldBookManager），入口 `main()`
- `SceneManager.py` — 多角色场景编排，**两阶段叙述**：先 LLM 生成叙述文本流式推送，再 LLM 提取结构化标记（`[BEAT_COMPLETE]`、`[COMBAT]`、`[CHOICES]`、`[SUMMARY]`）。支持结构化对话输出（`parse_structured()`）用于气泡模式
- `CharacterAgent.py` — 单角色人设：角色卡 + 6 条行为规则 + Wiki 上下文 + 记忆注入 + function calling（wiki 查询工具，最多 3 轮）
- `session_manager.py` — 会话 CRUD、回滚、叙述变体。**`combat_mode`（`"narrative"` | `"tactical"`）创建时选定，不可更改**
- `session_overlay.py` — 职责聚合：角色/物品属性覆盖 + 剧情日志（保留最近 15 条）+ 节拍状态 + 任务系统 + 世界书绑定（`worldbook_id`）
- `session_context.py` — 按会话缓存文档摘要
- `session_resources.py` / `session_export.py` — 会话级资源（背景/形象覆盖）与会话存档导出
- `environment_state.py` — 地点/天气/时间状态机，从 `data/environment/` 加载
- `wiki_manager.py` — 文档目录 + 三级深度提取（summary/core/full）+ `imports` 引用解析
- `document_manager.py` — 文件 CRUD + 哈希冲突检测
- `world_book.py` — 世界书（酒馆 Lorebook 兼容）：4 源解析（v1/v2/卡内嵌/jsonl）+ 关键词触发匹配 + 注入格式化 + 回灌导出 + `WorldBookManager`（`data/worldbooks/`，gitignored）。**注入纪律：常驻 position-0 条目进稳定层，触发型条目一律进动态层（前缀缓存稳定）**
- `memory.py` — `VectorMemory`：最近轮次滑动窗口 + ChromaDB 语义搜索。持久化于 `data/memory/`（gitignored）
- `llm_backend_manager.py` — 多 Provider 编排，主/备自动降级（验证缓存 120s TTL + 真实失败 30s 冷却）
- `load_llm.py` — Ollama / OpenAI 兼容 HTTP 客户端。**结构化错误（LLMError 系列，错误绝不伪装成模型回复）+ 连接/429/5xx 指数退避重试 + 请求指纹日志（前缀漂移标尺）+ `on_failure` 降级回调**
- `combat_session.py` — 战斗会话包装器：组装 CombatEngine + CombatDataLoader，管理生命周期、玩家操作、敌人 AI、SSE 推送
- `combat_data_loader.py` — 从 `data/combat/enemies/*.md`、`encounters/*.md` 和 `backgrounds/` 加载战斗数据（含背景图解析）
- `avatar_color.py` — 从角色 PNG 头像提取主导色（hex），用于 UI 主题配色
- `index_manager.py` — 基于 `imports` 字段的文档关系图，YAML 导出/导入
- `hooks/` — Hook 管道：`pipeline.py`（执行器）+ `attribute_roll.py` + `wiki_prefetch.py`

API 层（`src/blueprints/`）：Flask Blueprint — `chat.py`（对话/叙述/SSE/战斗触发）、`combat.py`（战斗 SSE）、`cards.py`（卡牌 JSON CRUD）、`documents.py`、`sessions.py`、`scene.py`、`environment.py`、`index.py`、`wiki.py`、`llm.py`、`assets.py`、`memories.py`、`status.py`、`worldbook.py`（书 CRUD/导入/条目/默认书/会话绑定）。

战斗引擎（`src/combat_engine/`）：`engine.py`（回合循环/AP/士气）、`entity.py`（CombatUnit）、`grid.py`（7×7 寻路/范围）、`card.py`（卡牌/CardPool）、`card_data.py`（职业基础卡牌）、`card_loader.py`（`data/characters/<名>/combat.json` + `data/classes/<职业>/cards.json` → 卡牌实例）、`dice.py`。

服务层（`src/services/`）：`buff_pool.py`、`dice.py`、`attribute_loader.py`。共享工具（`src/shared/`）：`helpers.py`（SSE 响应工厂、记忆注入）、`cache.py`。Provider（`src/providers/`）：`openai.py`、`deepseek.py`。

测试：`tests/`（gitignored，仅本地）— `test_world_book.py`、`test_worldbook_integration.py`、`test_llm_client.py`，运行 `python -m pytest tests/ -q`。

### 前端架构

入口 `main.tsx`（React 18 createRoot）→ `App.tsx`：Sidebar（导航：对话/资产/世界书/索引/战斗/设置）+ StatusBar（状态栏）+ 内容区（ChatView / CombatView / DocumentManager / WorldBookManager / IndexManager / SettingsPanel）。轮询后端状态 5s、LLM 状态 10s、会话列表 15s。

组件按功能域组织：
- `components/ChatView.tsx` — 对话页容器：会话列表 + 场景面板（角色/物品/环境/记忆/任务）+ `ChatPanel.tsx`（消息流/流式输出/选项/变体/回滚/对话气泡）
- `components/chat/` — 气泡渲染子组件（DialogueBubble、NarrationText、AvatarPlaceholder 等）
- `components/combat/CombatView.tsx` — 战斗主控（50k+ LOC，最大组件）
- `components/combat/` — CSS 网格（CombatGrid）+ PixiJS Spine 覆盖层（PixiCombatScene，runtime-3.8）+ 手牌（CombatHand）+ 卡组查看（DeckViewer）+ 卡牌编辑（CardEditor）+ 状态/事件面板 + Spine 动画规格（spineAnimSpecs.ts）
- `components/DocumentManager.tsx` — 文档树 + Markdown 编辑器 + 图片资产管理（上传/裁剪/卡面）
- `components/WorldBookManager.tsx` — 世界书管理：导入（文件/粘贴）、条目编辑器、会话绑定、酒馆格式导出
- `components/SettingsPanel.tsx` — LLM 配置/主题/叙述选项
- `audio/audioManager.ts` — 战斗音效管理

`stores/appStore.ts`（Zustand 4）：**Key 刷新模式** — 多个自增整数 key（`envRefreshKey`、`memoryRefreshKey`、`chatRefreshKey`、`characterRefreshKey`、`sceneSwitchKey`），组件比较 key 检测数据过期。**按会话存储** — 消息/流式/发送状态按 `sessionId` 隔离，切换会话不丢失。关键状态：`combatContext`（VIEWING/TARGETING + 选中卡牌/单位）、`pendingAutoNarrate`（战后自动叙述）、`dialogueBubbleMode`（气泡/纯文本切换）。

`hooks/useApi.ts`：REST + SSE 客户端（`connectSSE` GET 事件流、`createPostSSE` POST 流式），自动检测 Electron/浏览器环境。

工具：`utils/dialogueParser.ts` — 解析 `「」` 对话为 `DialogueSegment[]`，前文叙述匹配场景角色名确定说话人。`utils/baseUrl.ts` — 后端地址解析（Electron/浏览器）。`components/MarkdownRenderer.tsx` — 统一 Markdown 渲染。


### 设计文档（`docs/`）

- `combat-design.md` — 战斗引擎架构与机制设计
- `combat-numerical-design.md` — 战斗数值公式与平衡参数
- `combat-ui-design.md` — 战斗界面交互与布局设计
- `combat-core-design.md` — 战斗核心设计（近期重构权威源）
- `combat-background-prompts.md` — 战斗背景图生成提示词规范
- `prompt.md` — Prompt 工程策略与模板设计
- `system-update-log.md` — 系统更新日志


