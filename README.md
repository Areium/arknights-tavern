# Arknights Txt — 明日方舟文字角色扮演

基于明日方舟世界观的文字角色扮演游戏，支持 CLI 和 Web API 两种交互方式，集成 LLM 驱动角色对话、环境系统和向量记忆。

## 项目结构

```
arknights-txt
├── src
│   ├── main.py              # CLI 入口点，交互式角色扮演
│   ├── app.py               # Flask Web API (http://127.0.0.1:5000)
│   ├── GameAgent.py          # 游戏代理，对话路由 / 工具调用 / 环境管理
│   ├── CharacterAgent.py     # 角色代理，维护角色记忆与 LLM 对话
│   ├── load_llm.py           # LLM 加载器 (Ollama 本地 / API 远程)
│   ├── environment_state.py  # 环境状态追踪 (位置/天气/场景物件)
│   ├── memory.py             # 向量记忆系统 (ChromaDB + 滑动窗口)
│   ├── ui.py                 # 交互式终端 UI (键盘导航选择)
│   └── logging_setup.py      # 文件日志系统
├── data
│   └── characters
│       ├── 阿米娅.md          # 角色定义文件
│       └── 博士.md
├── environment
│   ├── Location              # 地点定义
│   └── weather               # 天气定义
├── requirements.txt
├── .env.example              # API 配置模板 (需复制为 .env)
├── .gitignore
└── README.md
```

## 安装步骤

### 1. 克隆仓库

```bash
git clone <repository-url>
cd arknights-txt
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API 密钥

项目通过 `.env` 文件加载 API 配置，**该文件默认不上传至仓库**（已在 `.gitignore` 中排除）。

首次使用请复制模板并填写：

```bash
cp .env.example .env
```

然后编辑 `.env`，填入你的 API 密钥和接口地址：

```env
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
```

**字段说明：**

| 字段 | 说明 | 示例 |
|---|---|---|
| `API_KEY` | API 密钥（必填） | `sk-xxxxxxxxxxxxxxxx` |
| `BASE_URL` | API 接口地址（必填） | `https://api.deepseek.com/v1` |

> **注意：** 若使用本地 Ollama 模型，`.env` 可不配置，`src/load_llm.py` 中的 `LocalLLM` 会自动连接 `http://localhost:11434`。`ApiLLM` 默认模型为 `Gemini-1.5-Flash`，可通过修改 `ApiModelConfig` 更改。

## 使用说明

### CLI 模式

```bash
python src/main.py
```

进入交互式角色扮演，支持键盘导航选择角色，输入对话内容与角色互动。输入 `exit` 退出。

### Web API 模式

```bash
python src/app.py
```

启动后访问 `http://127.0.0.1:5000`，提供 HTTP API 接口。

## 注意事项

- `.env` 包含 API 凭据，切勿提交或泄露
- 日志文件位于 `logs/` 目录（已在 `.gitignore` 中排除）
- ChromaDB 向量数据存储于 `data/memory/`（已在 `.gitignore` 中排除）
