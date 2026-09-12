# AGENTS.md

本文件为 AI 编码代理在本仓库中工作时提供指导。**系统架构细节见 `docs/architecture.md`**（模块职责、数据位置、组件清单、文档地图）。

## 工作流（MUST）
- **分支**：从 `main` 建 feature 分支（`feat/…`、`fix/…`）→ 完成全部修改 → 充分测试 → 合并回 `main` → 删除分支。禁止大型功能变更直提 `main`。
- **并发防护**：本仓库可能被多进程（其他 DSH 会话、IDE、脚本）同时操作。写操作前 MUST 加载 `.agents/skills/workspace-concurrency-guard`：入场两次 git 快照对比判定并发，有并发则改用 git worktree / clone 隔离开发；只按精确路径 `git add`（禁 `-A`）；禁 `git clean` / `checkout -f` / `reset --hard` / `stash drop`；合并前确认对方已停；文件被回滚或删除按该技能的 reflog / fsck / stash 流程找回，不盲目重写。
- **换行符**：`core.autocrlf=true` —— 工作区 CRLF、blob LF，勿提交混合换行文件。

## 项目概览
明日方舟主题文字 RPG：剧情模式（LLM 叙事 + 选项 + 记忆 + 环境）、自由模式（沙盒角色交互）、自由尺寸等距网格回合制战斗（JSON 战斗节点 + 可扩展地形 + PixiJS Spine 覆盖层）、世界书（酒馆 Lorebook 兼容的关键词触发注入）。
链路：Electron 主进程（`frontend/electron/`）→ React（`frontend/src/`，Vite 代理 `/api` → Flask `:5000`）→ Flask（`src/app.py`，factory 模式组装 Manager + Blueprint）。

## 关键约束
- **世界书注入纪律**：常驻 position-0 条目进稳定层，触发型条目一律进动态层（保持前缀缓存稳定）。
- **皮肤**：颜色工具类覆盖块由 `scripts/gen_skin_utils.py` 按色板生成，**改配色改脚本后重跑，勿手改该区段**；作用域 `@scope (html.skin-*) to (.bg-combat-bg)`，**战斗页不换肤**。
- **会话**：`combat_mode`（`narrative` / `tactical`）创建时选定，**不可更改**。
- **LLM 错误**：走 LLMError 系列结构化错误，**绝不把错误伪装成模型回复**。
- **战斗内容**：节点/敌人/地图改动走 skill `combat-designer` + `tools/`（先 `validate_battle_spec.py` 校验、再 `simulate_battle.py` 试跑，达标才入库），规格见 `docs/battle-spec.md`。
- **测试**：统一入口 `bash scripts/run_tests.sh`（pytest + `tests/legacy/`）。
