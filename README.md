# Arknights Txt — 明日方舟文字角色扮演

基于明日方舟世界观的文字角色扮演游戏，支持 CLI 终端和 Electron + React Web UI 两种交互方式。集成 LLM 驱动的角色对话、场景管理、环境系统和向量记忆，提供沉浸式剧情体验。

## 架构概览

```
用户交互层        CLI (src/ui.py)           Electron + React (frontend/)
                      │                           │
                  ┌───┴───────────────────────────┴───┐
API 层           │       Flask API (src/app.py)       │
                  └───┬───────────────────────────┬───┘
                      │                           │
                  ┌───┴───────────────────────────┴───┐
核心引擎         │        GameAgent / SceneManager     │
                  └───┬───────────────────────────┬───┘
                      │                           │
            ┌─────────┼──────────┐                │
       CharacterAgent  LLM    环境系统   文档管理器(DocumentManager)
            │          │        │                │
      向量记忆(Vector) LLM后端  地点/天气       Markdown 数据文件
```

## 项目结构

```
arknights-txt/
├── src/                          # Python 后端
│   ├── main.py                   # CLI 入口
│   ├── app.py                    # Flask Web API 服务
│   ├── GameAgent.py              # 游戏代理：工具调用、对话路由
│   ├── SceneManager.py           # 场景管理器：多角色同场对话
│   ├── CharacterAgent.py         # 角色代理：角色扮演 + 记忆
│   ├── session_manager.py        # 多会话管理
│   ├── document_manager.py       # 文档 CRUD + 哈希冲突检测
│   ├── registry_manager.py       # 索引注册表管理器
│   ├── llm_backend_manager.py    # LLM 多后端检测与自动降级
│   ├── load_llm.py               # LLM 加载器 (Ollama / API)
│   ├── environment_state.py      # 环境状态追踪
│   ├── memory.py                 # 向量记忆系统 (ChromaDB)
│   ├── ui.py                     # 交互式终端 UI
│   └── logging_setup.py          # 日志配置
├── frontend/                     # Electron + React 前端
│   └── src/
│       ├── App.tsx               # 主应用布局
│       ├── components/
│       │   ├── ChatView.tsx      # 对话视图 (组合侧栏 + 聊天面板)
│       │   ├── ChatPanel.tsx     # 聊天面板 (消息流 + 输入)
│       │   ├── CharacterPanel.tsx# 场景角色面板
│       │   ├── CharacterBrowser.tsx # 角色库浏览弹窗
│       │   ├── SessionList.tsx   # 会话列表
│       │   ├── DocumentManager.tsx # 文档编辑器
│       │   ├── EnvironmentPanel.tsx # 环境控制面板
│       │   ├── SettingsPanel.tsx # 设置面板
│       │   ├── Sidebar.tsx       # 导航侧栏
│       │   └── StatusBar.tsx     # 状态栏
│       ├── hooks/useApi.ts       # API 客户端封装
│       ├── stores/appStore.ts    # 全局状态 (Zustand)
│       └── types/index.ts        # TypeScript 类型定义
├── data/                         # 数据文件
│   ├── _INDEX.md                 # 总索引注册表
│   ├── characters/               # 角色定义 (_index.md + 角色卡)
│   ├── classes/                  # 职业定义
│   ├── races/                    # 种族定义
│   ├── factions/                 # 势力/阵营定义
│   ├── items/                    # 物品/装备定义
│   ├── attributes/               # 属性定义
│   ├── plots/                    # 剧情脚本
│   └── world/                    # 世界观设定
├── environment/                  # 环境数据
│   ├── Location/                 # 地点定义 (罗德岛各区域等)
│   └── weather/                  # 天气定义 (晴/雨/雪/雷暴等)
├── requirements.txt
├── .env.example                  # API 配置模板
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

前端（可选，仅 Web UI 需要）：

```bash
cd frontend && npm install
```

### 2. 配置 API 密钥

```bash
cp .env.example .env
```

编辑 `.env`：

```env
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
```

若不配置 `.env`，系统会自动尝试连接本地 Ollama (`http://localhost:11434`)。

### 3. 运行

**CLI 模式：**

```bash
python src/main.py
```

交互式角色扮演，支持键盘导航选择角色、切换模式、输入对话。

**Web UI 模式（开发）：**

```bash
# 终端 1：启动 API 服务
python src/app.py

# 终端 2：启动前端开发服务器
cd frontend && npm run dev
```

访问 `http://localhost:5173` 进入 Web 界面。

## 使用指南

### CLI 模式

启动后进入交互界面：

1. **加载角色** — 从列表中选择角色加入场景
2. **系统模式** — 管理角色、切换目标、查看环境
3. **角色扮演模式** — Tab 键切换，输入直接与角色对话
4. **剧情推进** — 场景叙述者自动推进故事发展

键盘快捷键：
- `Tab` — 切换系统 / 角色扮演模式
- `1` `2` `3` `4` — 选择菜单项
- `Ctrl+C` — 退出

### Web UI 模式

Flask API 提供 RESTful 接口，前端使用 React + Electron：

- **会话管理** — 创建/切换/删除多会话
- **场景角色** — 浏览角色库，加载/卸载角色，切换对话目标
- **剧情对话** — 角色对话 / 群聊 / 叙述推进
- **环境控制** — 调整地点、天气、时间
- **文档编辑** — 在线浏览和编辑数据文档 (含冲突检测)

### API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/status` | GET | 后端状态 |
| `/api/sessions` | GET/POST | 会话列表/创建 |
| `/api/sessions/<id>` | GET/DELETE | 会话详情/删除 |
| `/api/sessions/<id>/chat` | POST | 角色对话 |
| `/api/sessions/<id>/group-chat` | POST | 群聊 |
| `/api/sessions/<id>/narrate` | GET | 剧情推进 (SSE 流式) |
| `/api/sessions/<id>/narrate-continue` | POST | 剧情推进 (非流式) |
| `/api/sessions/<id>/characters` | GET | 场景角色列表 |
| `/api/sessions/<id>/characters/load` | POST | 加载角色 |
| `/api/sessions/<id>/environment` | GET/PUT | 环境状态 |
| `/api/documents/tree` | GET | 文档树 |
| `/api/documents/<category>/<path>` | GET/PUT | 文档读/写 (带哈希冲突检测) |
| `/api/documents/<category>` | POST | 创建文档 |
| `/api/characters` | GET | 角色库列表 |
| `/api/llm/status` | GET | LLM 后端状态 |

## 数据系统

数据以 Markdown 文件 + YAML frontmatter 格式存储，通过 `_index.md` 索引注册表组织：

```yaml
# data/characters/_index.md
index:
  阿米娅:
    file: "阿米娅.md"
    race: "奇美拉"
    class: "术师"
    faction: "罗德岛"
    tags: ["领袖", "感染者", "魔王继承者"]
```

角色卡示例 (`data/characters/银灰.md`)：

```yaml
---
name: 银灰
class: 近卫
race: 菲林
faction: 维多利亚
tags:
- 贵族
- 战略家
attributes:
  strength: 7
  intelligence: 9
  ...
relationships:
  博士: 互相利用又互相尊重的盟友关系
---
# 角色背景
...markdown 正文描述角色背景、性格、能力等...
```

## 核心功能

- **多角色同场** — 多个角色可同时在场，支持 `[@角色名]` 语法切换对话目标
- **向量记忆** — 基于 ChromaDB 的语义记忆检索，角色能记住历史对话
- **环境系统** — 地点、天气、时间的状态追踪与 LLM 驱动的动态更新
- **文档管理** — RESTful API + 前端编辑器，SHA256 哈希冲突检测
- **多 LLM 后端** — 自动检测可用后端，支持 Ollama 本地 / OpenAI 兼容 API

## 配置

编辑 `.env`：

| 字段 | 说明 | 默认值 |
|---|---|---|
| `API_KEY` | API 密钥 | — |
| `BASE_URL` | API 接口地址 | `https://api.deepseek.com/v1` |
| `API_HOST` | Flask 监听地址 | `127.0.0.1` |
| `API_PORT` | Flask 监听端口 | `5000` |
| `FLASK_DEBUG` | 调试模式 | `true` |

## 注意事项

- `.env` 包含 API 凭据，切勿提交或泄露（已在 `.gitignore` 中排除）
- ChromaDB 向量数据存储在 `data/memory/` 和 `src/data/`（已在 `.gitignore` 中排除）
- 日志文件位于 `logs/` 目录（已在 `.gitignore` 中排除）
