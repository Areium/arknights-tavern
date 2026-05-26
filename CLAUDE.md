# CLAUDE.md

## 项目概述

明日方舟主题文字 RPG —— 含剧情模式（LLM 驱动叙事、记忆、环境）、自由模式（沙盒角色交互）、7×7 网格回合制战术战斗。

## 技术栈

- **后端**: Python 3 + Flask (Blueprint 架构), ChromaDB 向量记忆
- **前端**: Electron + React + Vite + TypeScript, Zustand 状态管理
- **LLM**: 多 Provider 支持（OpenAI 兼容 API / DeepSeek），SSE 流式输出

## 常用命令

```bash
# 后端
pip install -r requirements.txt
python src/app.py                          # 默认 http://127.0.0.1:5000
FLASK_DEBUG=true python src/app.py         # 调试模式

# 前端
cd frontend && npm install
cd frontend && npm run dev                 # Electron 开发
cd frontend && npm run dev:web             # 浏览器开发
cd frontend && npm run build               # 生产构建
```

## 开发规范

### Git 工作流

<critical>
重要功能必须在 feature 分支上开发，完成后合并回 main，最后删除 feature 分支。
禁止将大型功能变更直接提交到 main。
</critical>

分支命名: `feat/描述`, `fix/描述`, `refactor/描述`

### 代码风格

- **Python**: 4 空格缩进，类型注解用于函数签名
- **TypeScript**: 严格模式，接口定义在 `types/index.ts`
- **提交信息**: 遵循 `type: description` 格式（如 `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`）

### 架构约束

<critical>
- Manager 层（LLMBackendManager, SessionManager, WikiManager, DocumentManager）在 `app.py` 的 `create_app()` 中初始化，全局共享
- 路由按功能域拆分为 Blueprint，注册在 `src/blueprints/` 下，通过 `register(app, managers)` 挂载
- Session 的 `combat_mode` 在创建时选定（"narrative" | "tactical"），不可更改
- 文档三级加载深度：summary → core → full，由 `core_sections` 控制提取范围
</critical>

### 安全约束

- 所有用户输入在服务端校验，不信任前端传来的原始数据
- LLM API Key 等敏感配置存储在 `config/llm_config.json`，不提交到 Git
- 文件操作限制在 `data/` 目录内，禁止路径遍历
