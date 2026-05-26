# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在本仓库中工作时提供指导。

## 任务指令执行
在进行任务前，使用中文重述并优化用户的指令

## Git 工作流

实现和修改重要功能前，遵循以下分支工作流：

1. 使用git从 `main` 创建 **feature 分支**，使用描述性名称（如 `feat/combat-ai`、`fix/memory-leak`）
2. 在 feature 分支上 **完成所有修改**
3. **充分测试**，确保正确性
4. 测试通过后 **合并回 `main`**
5. 合并成功后 **删除 feature 分支**

禁止将大型功能变更直接提交到 `main`。

## 项目架构

### 系统概述

明日方舟主题文字 RPG，包含：剧情模式（LLM 驱动叙事，含选项、记忆和环境）、自由模式（沙盒角色交互）、基于 7×7 网格的回合制战斗系统。

```
Electron + React（frontend/）
       │
       ▼
Flask API（src/app.py）
       │
       ├── SceneManager      — 多角色场景管理
       ├── CharacterAgent    — 角色人设 + 向量记忆
       ├── WikiManager       — 文档索引与查询
       ├── DocumentManager   — 文件 CRUD，基于哈希的冲突检测
       ├── SessionManager    — 多会话生命周期管理
       ├── LLMBackendManager — 多 Provider 编排
       ├── EnvironmentState  — 地点/天气/时间追踪
       ├── CombatSession     — 战斗生命周期管理
       └── combat_engine/    — 回合制网格战斗引擎
```

### 关键代码位置

**API 层**（`src/blueprints/`）：Flask Blueprint，按功能域划分：
- `chat.py` — 对话、群聊、剧情叙述、SSE 流式输出、结构化对话提取、战斗触发处理
- `scene.py` — 场景角色与物品
- `combat.py` — 战斗会话 CRUD 与 SSE 推送
- `documents.py` — 文档 CRUD、导入、搜索
- `sessions.py` — 会话 CRUD、回滚、索引配置
- `environment.py` — 环境状态
- `index.py` — 索引概览、校验、导出/导入
- `wiki.py` — Wiki 查询
- `llm.py` — LLM 配置与状态
- `assets.py` — 图片上传
- `memories.py` — 剧情记忆摘要
- `status.py` — 健康检查端点

**核心后端**（`src/`）：
- `app.py` — Flask 工厂函数 `create_app()`，组装 Manager 和 Blueprint
- `SceneManager.py` — 编排 CharacterAgent，为多角色场景构建共享上下文。方法：`chat()`、`group_chat()`，角色的加载/卸载/切换，场景物品管理。支持结构化对话输出（`parse_structured()`）用于气泡模式渲染
- `CharacterAgent.py` — 单角色人设：带 Wiki 上下文的系统提示词构建、记忆注入、LLM 交互
- `session_manager.py` — 会话生命周期：创建、历史 CRUD、回滚、叙述变体存储。`combat_mode`（"narrative" | "tactical"）是 Session 级别的属性，创建时选定，不可更改
- `session_overlay.py` — 会话级别的角色/物品属性覆盖、剧情日志管理（自动截断保留最近 15 条）、节拍状态追踪
- `session_context.py` — 按会话缓存文档摘要
- `environment_state.py` — 环境状态机：地点、天气、时间转换。从 `data/environment/` 加载（实体文件夹格式）
- `wiki_manager.py` — 从 `categories.yaml` 构建文档目录，提取核心分段（summary/core/full），处理导入引用
- `document_manager.py` — 文件级 CRUD，基于哈希的冲突检测，搜索，文件夹管理
- `index_manager.py` — 索引概览，基于 `imports` 字段的关系图，YAML 导出/导入
- `memory.py` — `VectorMemory`：最近轮次滑动窗口 + ChromaDB 历史语义搜索
- `llm_backend_manager.py` — 多 Provider 检测，主/备用切换，自动降级
- `load_llm.py` — Ollama 和 OpenAI 兼容 API 的 HTTP 客户端，工具调用解析

**LLM Provider**（`src/providers/`）：
- `base.py` — 抽象 `ProviderAdapter`，定义端点 URL、认证、请求体构建、流式/非流式响应解析接口
- `openai.py` — OpenAI 兼容 API 适配器（同时作为 `auto` 默认值）
- `deepseek.py` — DeepSeek API 适配器，支持 reasoning_effort（low/medium/high）

**战斗引擎**（`src/combat_engine/`）：
- `engine.py` — 核心回合循环，卡牌结算，AP 管理，士气
- `entity.py` — CombatUnit：HP、属性、增益/减益
- `grid.py` — 7×7 网格寻路、技能范围计算、移动验证
- `card.py` — 卡牌定义、目标验证、伤害计算
- `card_data.py` — 按职业分类的完整卡牌数据库
- `dice.py` — 骰子分布函数（d20、2d6 等）

**前端**（`frontend/src/`）：
- `App.tsx` — 根布局，视图路由（chat/documents/settings/combat/index），5s/10s 轮询后端状态、LLM 状态、会话列表
- `stores/appStore.ts` — Zustand 状态管理：当前视图、主题、对话模式、会话、战斗状态，各类刷新触发器（基于自增 key，组件比较 key 检测数据过期）
- `hooks/useApi.ts` — API 客户端：REST 端点 + SSE 流处理器，`connectSSE()` 和 `createPostSSE()` 用于流式叙述/对话
- `types/index.ts` — 所有 TypeScript 接口：Session、CombatUnit、CardDTO、SSEEvent 等

**关键前端组件：**
- `components/ChatPanel.tsx` — 主聊天界面：消息、叙述流式输出、选项、叙述变体、编辑/删除/回滚、对话气泡模式
- `components/SessionList.tsx` — 会话侧边栏：CRUD、模式筛选、剧情会话创建时的战斗模式选择器（纯剧情/战术）
- `components/combat/CombatView.tsx` — 完整战斗界面：网格、卡牌、状态面板、事件日志（50k+ LOC，最大组件）
- `components/combat/CombatGrid.tsx` — 7×7 等距 3D 网格，支持拖拽卡牌选择目标
- `components/DocumentManager.tsx` — 文档树浏览器 + 带 frontmatter 的 Markdown 编辑器
- `components/SettingsPanel.tsx` — LLM 配置（多 Provider、DeepSeek 推理强度）、主题、叙述选项、max_output_tokens（256–16384，默认 8192）

### 数据层

**文档分类**定义在 `data/categories.yaml`，按层级划分：
- Level 0：world、rules（全局背景）
- Level 1：attributes、races、classes、weather（基础定义）
- Level 2：factions、locations、items（世界实体）
- Level 3：characters（角色）
- Level 4：plots、enemies、combat_encounters（叙事）
- Level 5：combat_enemies（战斗组件）

**三级加载深度**：summary（~30 tokens，来自 frontmatter）→ core（~150 tokens，来自关键章节）→ full（~400 tokens，完整文件）。由 `constants.py` 中的 `core_sections` 控制。

**文档引用**通过 frontmatter 的 `imports` 字段：`imports: [categories/doc-id | 显示名称]`。由 WikiManager 解析。

### 通信模式

- **轮询**：前端轮询 `/api/status`（5s）、`/api/llm/status`（10s）、`/api/sessions`（15s）、战斗状态（战斗中 1s）
- **SSE 流式输出**：`POST /api/sessions/<id>/chat` 和 `/narrate-continue` 通过 SSE 流式传输 token。事件类型：`text`、`reasoning`、`scene_event`、`memory_event`、`choice`、`dialogue_segments`、`token_usage`、`combat_trigger`
- **战斗 SSE**：专用事件流 `/api/sessions/<id>/combat/events` 用于实时战斗更新
- **Key 刷新模式**：Zustand store 使用自增整数作为触发 key —— 组件轮询并比较 key 以检测数据过期

### Prompt 构建架构

系统所有 prompt 遵循统一的三层模型：

```
System Prompt = Identity + Behavior Rules + Output Format Rules
User Message  = Situation（情境）→ Context（历史）→ Reference（参考资料）
```

**设计原则**：Primacy（身份/情境最前）→ 中间过渡（行为/历史）→ Recency（输出格式标记末尾）。同类信息连续排列，不穿插。

#### 1. 场景叙述 Prompt（SceneManager）

`SceneManager._build_narration_messages()` 负责构建叙述模式的 messages 列表。System prompt 和 user message 在不同位置构建：

**System Prompt** —— 由 `_build_system_prompt()` 统一组装：

| 来源 | 内容 | 条件 |
|---|---|---|
| `_NARRATOR_SYSTEM` 模板 | 身份定义 + 规则 1-5（叙述风格）+ 规则 6（`[BEAT_COMPLETE]`） | 始终 |
| `_NARRATOR_SYSTEM_STRUCTURED` 模板 | 同上 + JSON 输出格式说明 | structured=true |
| builder 方法追加 | 规则 7：战斗模式（tactical→`[COMBAT:ID]` / narrative→叙事描述） | 始终 |
| builder 方法追加 | 规则 8-9：`[CHOICES]` + `[SUMMARY]` | choices_count > 0 |

注：规则 7-9 的编号由 `rule_num` 自动连续递增，不受条件组合影响。

**User Message** —— 在 `_build_narration_messages()` 中按层拼接：

| 层 | 组件 | 来源 |
|---|---|---|
| **Situation** | 1. 场景状态（位置/天气/时间） | `EnvironmentState.build_context()` |
| | 2. 对话历史 | `_build_conversation_history()`（最近轮次，≤3000 字） |
| | 3. 场景角色 + 可用遭遇（tactical 模式） | `_agents` + `_list_encounters()` |
| | 4. 玩家身份 + 操作 | player_info + user_action |
| | 5. 开场场景（仅首轮，自动清除） | `SessionOverlay.get_plot_context()` |
| **Context** | 6. 场景动态（最近 8 条事件） | `_scene_log` |
| | 7. 剧情结构参考 + 进度日志 | `plot_state.md` + `plot_log.md`（会话自有文档） |
| **Reference** | 8. 预加载 Wiki 文档 + 文档目录 | `SessionContext.format_preloaded()` + `WikiManager.format_catalog_summary()` |
| **Instruction** | 9. 收尾指令 | 结构化模式要求 JSON，非结构化模式要求自然叙述 |

#### 2. 角色对话 Prompt（CharacterAgent）

`CharacterAgent.load_character()` 构建角色人设（含 6 条行为规则），`chat()` 方法按以下顺序拼接 system prompt：

| 层 | 组件 | 来源 |
|---|---|---|
| **Identity** | 1. 角色人设（角色卡 + 6 条核心规则） | `load_character()` → `self.character` |
| | 2. Registry 上下文（种族/职业/阵营，仅无预加载时） | `RegistryManager.build_character_context()` |
| **Situation** | 3. 玩家身份 | player_info |
| | 4. 环境上下文 | `EnvironmentState.build_context()` |
| | 5. 场景上下文（同场角色/物品/动态） | `SceneManager._build_scene_context()` |
| **Context** | 6. 记忆上下文（近期对话记录 + 远期语义检索记忆） | `VectorMemory.build_context()` |
| **Reference** | 7. 预加载 Wiki 文档 | `SessionContext.format_preloaded()`（depth 0-2） |
| | 8. Wiki 文档目录 | `WikiManager.format_catalog_summary()` |
| **Format** | 9. 环境同步规则（`<!--env:...-->`） | `_ENV_RULE` |

角色对话支持 function calling：`_WIKI_TOOL` 定义 wiki 查询工具，chat 循环最多 3 轮工具调用。

**角色人设模板**（`load_character()` 第 91-111 行）以 f-string 注入角色卡 YAML + 正文，核心规则：
1. 唯一身份由【角色卡】决定
2. 严格遵守设定、不虚构
3. 禁止元对话
4. 第一人称视角
5. 维持语气/风格一致性
6. 参考历史对话记录

#### 3. 辅助 Prompt

| 功能 | 文件:行号 | System Prompt |
|---|---|---|
| 选项生成 | `chat.py:209-211` | "你是明日方舟文字冒险游戏的选项生成器。根据当前剧情，生成合理且多样化的后续行动选项。" |
| 对话重组（气泡模式） | `SceneManager.py:856` | "你是文本结构化助手。只输出 JSON，不输出其他内容。" |
| 记忆摘要生成 | `session_manager.py:237` | "你是一个专业的剧情编辑，负责为TRPG游戏记录详尽的剧情摘要。" |
| 文档摘要回填 | `wiki_manager.py:507` | "你是一个文档摘要生成器。根据以下内容，输出一句中文摘要（≤50字）。" |

#### 4. 环境/记忆上下文注入

| 组件 | 文件 | 注入目标 | 内容 |
|---|---|---|---|
| 环境上下文 | `environment_state.py:174` | CharacterAgent、SceneManager | 位置、天气、时间、氛围、场景物品 |
| 记忆上下文 | `memory.py:93` | CharacterAgent | 【远期相关记忆】（ChromaDB 语义搜索）+【近期对话记录】（最近 10 轮） |
| 预加载文档 | `session_context.py:49` | CharacterAgent、SceneManager | 【预加载资料】角色卡/核心设定/延伸参考 |
| 文档目录 | `wiki_manager.py:409` | CharacterAgent、SceneManager | 【可用文档目录】按分类层级排列的文档索引 |
| 剧情记忆 | `helpers.py:32` | SceneManager（叙述流） | 【剧情回顾】最近 3 条记忆摘要 |

#### 5. 输出格式标记一览

所有 LLM 输出的结构化标记，由 `src/blueprints/chat.py` 解析：

| 标记 | 触发条件 | 解析函数 |
|---|---|---|
| `[BEAT_COMPLETE]` | 场景自然结束 | `_handle_beat_complete()` |
| `[COMBAT:遭遇ID]` | tactical 模式 + 敌对威胁 | `_handle_combat_trigger()`（支持 JSON 参数） |
| `[CHOICES]` | choices_count > 0 | `_handle_choices()` |
| `[SUMMARY]` | choices_count > 0 | `_handle_summary()` |
| `<!--env:{"key":"value"}-->` | 环境变化（角色对话） | `chat.py` 中的 env 解析逻辑 |
