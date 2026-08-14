# arknights-tavern — 明日方舟文字角色扮演

基于明日方舟世界观的文字角色扮演游戏，提供沉浸式剧情体验。

## 快速开始

### 1. 安装依赖

```bash
# Python 后端
pip install -r requirements.txt

# 前端
cd frontend && npm install
```

### 2. 启动服务

```bash
# 终端 1：启动 API 服务
python src/app.py

# 终端 2：启动前端开发服务器
cd frontend && npm run dev
```

访问 `http://localhost:5173` 进入 Web 界面（Electron 桌面端用 `cd frontend && npm run dev:electron`）。

### 3. 配置 LLM

进入前端设置页面（主页主菜单 →「⚙️ 设置」，或管理页顶栏导航），在「LLM 配置」区域填写 API 信息：

- **云端 API** — 填写 API Key、接口地址和模型名称，点击「测试连接」验证可用性
- **Ollama 本地** — 填写 Ollama 地址和模型名称（需先[安装 Ollama](https://ollama.com)并拉取模型）

### 4. 运行测试

```bash
python -m pytest tests/ -q
```

> 注：`tests/` 目录被 .gitignore 忽略（仓库约定），仅本地运行。



## 使用指南

### 对话模式

进入会话后，对话页顶栏可切换两种对话模式（剧情 / 自由）：

**剧情模式**（默认）— 适合体验完整故事线：
- 系统自动推进剧情，生成场景叙述文本
- 每次叙述后提供行动选项（点击即可选择下一步行动）
- 剧情发展受环境、角色状态和之前的选择影响
- 支持回退到任意历史轮次重新选择（见下方「回退系统」）

**自由模式** — 适合与角色自由互动：
- 手动加载角色到场景中，自由对话
- 可选择与单个角色对话或发起群聊
- 自由编辑环境信息（地点、天气、时间）

### 会话大厅

主页主菜单选择「🏛️ 会话大厅」进入游戏主菜单式的大厅：会话列表按剧情/自由分栏，支持搜索与批量管理；选中会话可绑定世界书、配置角色阵容、导出/导入存档；进行中的会话可直接「⚔ 进入战斗」。进入会话后为全屏沉浸体验，调节设定请退出到大厅。

- **新建会话** — 点击「+ 新建」创建当前模式下的新会话
- **切换会话** — 点击会话条目即可切换，对话记录自动保存
- **重命名** — 双击会话名称进行重命名
- **删除** — 点击 ✕ 删除单个会话，或勾选多条后批量删除

### 场景角色与物品

**剧情模式下**，角色和物品由场景自动加载，无需手动操作。点击角色旁的「对话」按钮可切换当前对话目标。

**自由模式下**，可手动管理场景中的角色和物品：
- 点击「+ 添加」浏览角色库/物品库，选择后加载到当前场景
- 悬停角色或物品可预览详细属性
- 点击 📌 可固定详情卡片，固定后可在线编辑，修改仅影响当前会话

### 环境控制

- **自由模式** — 点击「编辑」可从预设下拉列表中选择地点/天气/时间，或选择「✏️ 自定义...」输入任意值
- **剧情模式** — 环境由剧情发展决定，不可直接修改。点击「切换场景」可从预设地点中选择目的地，选择后系统会自动生成场景过渡叙述

### 剧情回忆

剧情模式下，左侧面板底部会显示「回忆」卡片。系统每隔一定轮次自动调用 LLM 将最近的剧情进展总结为章节回忆：

- 回忆以手风琴列表展示，点击展开查看完整摘要
- 默认展开最新一条回忆
- 点击「重新生成」可清除已有回忆，按当前设置重新总结全部历史
- 回忆间隔可在设置页面调整（1-20 轮，默认 5 轮）

### 回退系统

剧情模式下支持多种回退方式，让你可以回到之前的节点重新选择：

- **轮次分割线** — 对话中每两个轮次之间显示 `↩ 回退` 按钮，点击后确认即可回退到该轮，之后的对话记录和回忆将被删除
- **回忆回退** — 展开任意一条回忆，点击底部的 `↩ 回退到此`，回退到该回忆覆盖的最后一轮
- **编辑消息** — 悬停自己发送的消息，点击右上角 `✎` 按钮，修改内容后点「保存并继续」，系统会回退到该消息并重新生成后续叙述
- **删除消息** — 悬停任意消息，点击左上角 `×` 按钮删除单条消息

### 叙述变体

剧情模式下，每条系统生成的叙述消息右下角显示 `◂ 1/1 ▸` 导航：

- 点击 `◂` `▸` 在不同生成版本间切换
- 当前显示的版本即为该轮对话的正式记录
- 点击 `▸` 在最后一个版本时，可输入提示词（或留空）让 LLM 重新生成新版本
- 切换版本后，后续对话上下文仅包含当前选中的版本

### 发送前编辑

设置页面「剧情选项」区域中可开启「选项填充到输入框」功能：

- **开启后** — 点击 LLM 生成的选项会将文本填入输入框，可编辑后再手动发送
- **关闭后**（默认） — 点击选项直接发送

### 剧情选项设置

在设置页面可配置：

- **自动生成选项** — 开启后 LLM 根据当前剧情生成多个有意义的后续行动选项（1-5 个）
- **回忆间隔** — 每隔多少轮对话自动生成一次剧情回忆（1-20 轮）
- **选项填充到输入框** — 控制点击选项后的行为

### 文档编辑

主页主菜单或管理页顶栏切换到「📄 资产」可浏览和编辑数据文档（角色、物品、世界观设定等），支持在线编辑和保存；「🔗 索引」管理文档间 `imports` 引用关系。

### 世界书

管理页顶栏「📖 世界书」管理酒馆（SillyTavern）Lorebook 兼容的世界书：

- **导入** — 支持酒馆世界书导出 JSON（v1/v2）、角色卡内嵌世界书、聊天备份 `.jsonl`，自动探测格式并报告导入/跳过/警告
- **触发机制** — 条目按主/副关键词扫描最近对话自动注入叙述与对话的提示词；支持常驻、选择性、概率、大小写、全词匹配等酒馆语义
- **绑定** — 每本书可绑定到指定会话，未绑定时回落到全局默认书
- **导出** — 一键导出回酒馆 v1 格式，无损回灌（保留 `disable`/`extensions` 等原始字段）

### 战斗系统

剧情模式下可通过遭遇战进入回合制战斗，使用卡牌指挥角色在网格地图上作战。

**启动战斗**：
- 在会话大厅点击「⚔ 战斗演练」进入测试战场，或对 `in_combat` 会话点击「进入战斗」；也可在对话页顶栏手动触发遭遇战
- 在剧情模式中，当故事触发战斗时，系统会自动进入战斗场景
- 也可以使用「战斗测试」模式：无需会话，从 `data/plots/combat-test/` 加载预设战斗

**战斗操作**：
- **选择卡牌** — 点击手牌中的卡牌，或按数字键 1-5 快捷选牌
- **打出卡牌** — 选中卡牌后点击敌方区域的格子，或直接拖拽卡牌到目标格子
- **移动角色** — 点击地图上的我方角色选中，再点击蓝色高亮格子移动
- **查看属性** — 点击角色头像或格子上的小人选中角色，悬停查看详细属性浮窗
- **结束回合** — 点击「结束回合」或按 F 键
- **取消操作** — 按 Esc 键

**战斗界面布局**：
- 左侧：我方角色状态面板（HP 条、AP 点、头像）
- 中央：7×7 等距 3D 网格地图（CSS 3D 透视效果），角色小人 + 特效粒子
- 右侧：敌方角色状态面板
- 底部：手牌区（弧形排列）+ 操作栏 + 事件日志

**数据回写**：战斗结束后，角色的 HP 变化、受伤、死亡等状态会自动回写到当前会话。

**战斗背景**：战斗界面会按场景显示背景图——遭遇战配置（`background` 字段）优先，其次取当前剧情地点（`combat_bg` 字段），都没有则用默认背景。背景图存放于 `data/combat/backgrounds/`，可用 `python tools/generate_combat_backgrounds.py` 通过 AI 批量生成（详见 `docs/combat-background-prompts.md`）。

**会话级背景覆盖**：每个会话有自己的背景目录 `data/memory/sessions/<模式>/<会话ID>/backgrounds/`（会话详情接口的 `backgrounds_dir` 字段返回该路径）。直接把图片放进去即可覆盖本场战斗的背景——文件名对应背景 ID（如 `wasteland_ruins.jpg` 替换该背景，`default.jpg` 替换兜底背景），只影响当前会话，不改动全局资源。

## 架构概览

```
                   Electron + React (frontend/)
                           │
                  ┌────────┴────────┐
API 层           │  Flask API (src/app.py)
                  └────────┬────────┘
                           │
                  ┌────────┴────────┐
核心引擎         │  SceneManager / WikiManager
                  └────────┬────────┘
                           │
            ┌──────────────┼──────────────┐
       CharacterAgent    LLM 后端      环境系统
            │          (云端+本地)    (地点/天气)
      向量记忆(Vector)
```

## 项目结构

```
arknights-tavern/
├── src/                          # Python 后端
│   ├── app.py                    # Flask Web API 服务（create_app 工厂 + Blueprint 注册）
│   ├── constants.py              # 共享常量
│   ├── blueprints/               # Flask Blueprints（chat/combat/cards/documents/
│   │                             #   sessions/scene/environment/index/wiki/llm/
│   │                             #   assets/memories/status/worldbook）
│   ├── shared/                   # 共享工具（SSE 响应工厂/记忆注入/缓存）
│   ├── services/                 # 服务层（Buff 池/骰子系统/属性加载器）
│   ├── hooks/                    # Hook 管道（attribute_roll / wiki_prefetch）
│   ├── providers/                # LLM Provider 适配器（openai / deepseek）
│   ├── SceneManager.py           # 场景管理器：多角色同场 + 两阶段叙述
│   ├── CharacterAgent.py         # 角色代理：角色扮演 + 记忆 + wiki function calling
│   ├── session_manager.py        # 多会话管理（CRUD/回滚/叙述变体）
│   ├── session_overlay.py        # 会话覆盖层（角色/物品/环境/节拍/任务/世界书绑定）
│   ├── session_context.py        # 会话文档缓存（预加载 + wiki 查询缓存）
│   ├── session_resources.py      # 会话级资源（背景覆盖/角色形象覆盖）
│   ├── session_export.py         # 会话存档导出
│   ├── world_book.py             # 世界书（酒馆 Lorebook 兼容）：解析/触发/注入/回灌
│   ├── document_manager.py       # 文档 CRUD + 哈希冲突检测
│   ├── wiki_manager.py           # Wiki 文档索引与查询
│   ├── index_manager.py          # 全局索引导入/导出/校验
│   ├── llm_backend_manager.py    # LLM 多后端检测与降级（验证缓存 + 失败冷却）
│   ├── load_llm.py               # LLM 客户端（结构化错误/重试/请求指纹日志）
│   ├── environment_state.py      # 环境状态追踪
│   ├── memory.py                 # 向量记忆系统 (ChromaDB)
│   ├── avatar_color.py           # 头像主导色提取
│   ├── combat_session.py         # 战斗会话管理
│   ├── combat_data_loader.py     # 战斗数据加载器（遭遇战/敌人/背景）
│   └── combat_engine/            # 战斗引擎（engine/entity/grid/card/card_data/
│                                 #   card_loader/dice）
├── frontend/                     # Electron + React 前端
│   ├── electron/                 # Electron 主进程
│   └── src/
│       ├── App.tsx               # 主应用布局（主页主菜单 / 管理页 / 沉浸式三层外壳）
│       ├── components/           # UI 组件（chat/combat/session 子目录 + WorldBookManager）
│       ├── hooks/useApi.ts       # REST + SSE 客户端封装
│       ├── stores/appStore.ts    # 全局状态（Key 刷新模式）
│       ├── audio/                # 战斗音效管理
│       └── utils/                # dialogueParser / baseUrl 等
├── data/                         # 数据文件（角色/职业/物品/世界观等）
│   ├── categories.yaml           # 类别注册表
│   ├── characters/               # 角色（含 <name>/combat.json 专属战斗卡牌）
│   ├── classes/                  # 职业（含 <class>/cards.json 职业卡池）
│   ├── plots/                    # 剧情（index.md 剧情定义）
│   ├── environment/              # 环境预设（地点/天气）
│   ├── combat/                   # 战斗数据（enemies/ encounters/ backgrounds）
│   ├── rules/                    # 游戏机制规则（buff-pool/combat-system 等）
│   └── worldbooks/               # 世界书运行时数据（gitignored）
├── tools/                        # 脚本工具（音频下载/Spine 导入/背景生成等）
├── docs/                         # 设计文档
├── tests/                        # pytest 测试（gitignored）
└── requirements.txt
```
