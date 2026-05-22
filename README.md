# Arknights Txt — 明日方舟文字角色扮演

基于明日方舟世界观的文字角色扮演游戏，使用 Electron + React 前端与 Flask + LLM 后端，提供沉浸式剧情体验。

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

访问 `http://localhost:5173` 进入 Web 界面。

### 3. 配置 LLM

进入前端设置页面，在「LLM 配置」区域填写 API 信息：

- **云端 API** — 填写 API Key、接口地址和模型名称，点击「测试连接」验证可用性
- **Ollama 本地** — 填写 Ollama 地址和模型名称（需先[安装 Ollama](https://ollama.com)并拉取模型）
- **剧情选项** — 可选开启 LLM 自动生成剧情选项，并设置生成个数（1-5）

点击「保存并重新检测」后，系统会自动检测可用后端并在不可用时降级切换。

也可通过 `.env` 文件配置（会被前端设置覆盖）：

```env
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
```

若不配置任何 API，系统会尝试连接本地 Ollama (`http://localhost:11434`)。

## 架构概览

```
                   Electron + React (frontend/)
                           │
                  ┌────────┴────────┐
API 层           │  Flask API (src/app.py)
                  └────────┬────────┘
                           │
                  ┌────────┴────────┐
核心引擎         │  GameAgent / SceneManager
                  └────────┬────────┘
                           │
            ┌──────────────┼──────────────┐
       CharacterAgent    LLM 后端      环境系统
            │          (云端+本地)    (地点/天气)
      向量记忆(Vector)
```

## 项目结构

```
arknights-txt/
├── src/                          # Python 后端
│   ├── app.py                    # Flask Web API 服务
│   ├── GameAgent.py              # 游戏代理：工具调用、对话路由
│   ├── SceneManager.py           # 场景管理器：多角色同场对话 + 物品
│   ├── CharacterAgent.py         # 角色代理：角色扮演 + 记忆
│   ├── session_manager.py        # 多会话管理
│   ├── session_overlay.py        # 会话覆盖层（模板复制即修改）
│   ├── document_manager.py       # 文档 CRUD + 哈希冲突检测
│   ├── registry_manager.py       # 索引注册表管理器
│   ├── llm_backend_manager.py    # LLM 多后端检测与自动降级
│   ├── load_llm.py               # LLM 加载器 (Ollama / API)
│   ├── environment_state.py      # 环境状态追踪
│   ├── memory.py                 # 向量记忆系统 (ChromaDB)
│   ├── logging_setup.py          # 日志配置
│   └── main.py                   # CLI 入口（已弃用，不再维护）
├── frontend/                     # Electron + React 前端
│   └── src/
│       ├── App.tsx               # 主应用布局
│       ├── components/
│       │   ├── ChatView.tsx      # 对话视图 (角色面板 + 物品面板 + 聊天)
│       │   ├── ChatPanel.tsx     # 聊天面板 (消息流 + 输入 + 剧情选项)
│       │   ├── CharacterPanel.tsx # 场景角色面板 (加载/卸载/切换)
│       │   ├── CharacterBrowser.tsx # 角色库浏览弹窗
│       │   ├── CharacterDetailCard.tsx # 角色详情卡片 (悬停预览/编辑)
│       │   ├── ItemPanel.tsx     # 场景物品面板
│       │   ├── ItemBrowser.tsx   # 物品库浏览弹窗
│       │   ├── ItemDetailCard.tsx # 物品详情卡片 (悬停预览/编辑)
│       │   ├── SessionList.tsx   # 会话列表 (创建/重命名/删除)
│       │   ├── DocumentManager.tsx # 文档编辑器
│       │   ├── EnvironmentPanel.tsx # 环境控制面板
│       │   ├── SettingsPanel.tsx # 设置面板 (LLM 配置/选项生成)
│       │   ├── Sidebar.tsx       # 导航侧栏
│       │   └── StatusBar.tsx     # 状态栏
│       ├── hooks/useApi.ts       # API 客户端封装 + SSE 流式
│       ├── stores/appStore.ts    # 全局状态 (Zustand)
│       └── style.css             # 全局样式
├── data/                         # 数据文件
│   ├── _INDEX.md                 # 总索引注册表
│   ├── characters/               # 角色定义
│   ├── classes/                  # 职业定义
│   ├── races/                    # 种族定义
│   ├── factions/                 # 势力/阵营定义
│   ├── items/                    # 物品/装备定义
│   ├── attributes/               # 属性定义
│   ├── plots/                    # 剧情脚本
│   └── world/                    # 世界观设定
├── environment/                  # 环境数据
│   ├── Location/                 # 地点定义
│   └── weather/                  # 天气定义
├── requirements.txt
├── .env.example
├── .gitignore
└── config/
    └── llm_config.json           # LLM 配置持久化（已 gitignore）
```

## Web UI 功能

- **会话管理** — 创建/切换/删除多个独立会话，每个会话维护自己的场景状态、角色、物品和覆盖数据。支持双击重命名。
- **场景角色** — 浏览角色库，加载/卸载角色到场景。点击角色名即可切换对话目标，悬停查看详细属性/关系/背景。可固定详情卡片并在线编辑角色数据，修改仅影响当前会话，不改变模板。
- **场景物品** — 浏览物品库，添加/移除场景物品。悬停查看详情（稀有度、效果、持有者、描述），支持固定查看和在线编辑，修改仅影响当前会话。
- **剧情对话** — 支持三种对话模式：
  - *自由对话* — 直接与当前活跃角色对话
  - *群聊模式* — 同时向场景中所有角色发消息
  - *剧情推进* — 场景叙述者自动生成剧情文本，并提供后续行动选项
- **剧情选项** — 可在设置中启用 LLM 自动生成选项，根据当前剧情生成 N 个有意义的后续行动（1-5 个），或使用默认选项。单选项时隐藏编号，多选项时显示序号。
- **环境控制** — 调整场景地点、天气、时间。环境状态会注入 LLM 上下文影响对话和叙述。
- **文档编辑** — 在线浏览、创建和编辑数据文档，支持 SHA256 哈希冲突检测防止覆盖他人修改。
- **LLM 配置** — 可视化配置云端 API 和本地 Ollama 后端，支持连接测试。自动检测可用后端并在故障时降级切换。所有配置持久化保存。

## 数据系统

数据以 Markdown 文件 + YAML frontmatter 格式存储，通过多级 `_index.md` 索引注册表组织。

### 索引结构

```
data/
├── _INDEX.md              # 总索引 — 注册所有子索引路径
├── characters/
│   ├── _index.md          # 角色索引 — 键名 → 文件路径 + 元信息
│   ├── 阿米娅.md
│   └── ...
├── items/
│   ├── _index.md          # 物品索引
│   ├── 抑制戒指.md
│   └── ...
├── classes/_index.md      # 职业索引
├── races/_index.md        # 种族索引
└── factions/_index.md     # 势力索引
```

### 索引工作原理

1. **`RegistryManager`** 启动时读取 `data/_INDEX.md`，解析所有子索引路径，构建完整的注册表
2. 每个子目录的 `_index.md` 维护该类别下所有条目的映射：**逻辑键名 → 物理文件路径 + 元信息**
3. 加载实体（角色/物品等）时，先查索引获取文件路径，再读取对应 Markdown 文件解析 YAML frontmatter + 正文
4. 角色卡、物品等彼此通过索引中的键名交叉引用（如角色的 `relationships` 引用其他角色名、物品的 `owner` 引用角色名）
5. 新增条目只需创建 Markdown 文件并在对应 `_index.md` 中注册，无需修改代码

### 会话覆盖

每个会话维护独立的覆盖层（`SessionOverlay`），采用**写时复制**策略：

- 首次加载使用模板文件内容
- 用户在前端编辑后，仅将**变更部分**写入会话覆盖数据
- 后续加载时自动深度合并：覆盖数据优先于模板数据
- 删除覆盖即恢复为模板原始内容
- 覆盖数据存储在会话目录中，不影响模板文件

## 核心机制

- **多角色同场** — 多个角色可同时在场，共享场景上下文和事件日志。点击角色面板中的角色名即可切换对话目标，前端输入框支持直接输入文本或点击剧情选项发送。
- **向量记忆** — 基于 ChromaDB 的语义记忆检索，角色能记住历史对话内容，在后续对话中引用。
- **环境系统** — 地点、天气、时间的状态追踪，LLM 会根据环境描述调整角色对话和叙述风格。
- **多 LLM 后端** — 自动检测可用后端（云端 API / 本地 Ollama），支持运行时切换和故障自动降级。
