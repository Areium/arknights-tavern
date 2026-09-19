# AGENTS.md

本文件为 AI 编码代理在本仓库中工作时提供指导。**系统架构细节见 `docs/architecture.md`**（模块职责、数据位置、组件清单、文档地图）。

## 工作流（MUST）
- **分支**：从 `main` 建 feature 分支（`feat/…`、`fix/…`）→ 完成全部修改 → 充分测试 → 合并回 `main` → 删除分支。禁止大型功能变更直提 `main`。
- **并发防护**：本仓库可能被多进程（其他 DSH 会话、IDE、脚本）同时操作。写操作前 MUST 加载 `.agents/skills/workspace-concurrency-guard`：入场两次 git 快照对比判定并发，有并发则改用 git worktree / clone 隔离开发；只按精确路径 `git add`（禁 `-A`）；禁 `git clean` / `checkout -f` / `reset --hard` / `stash drop`；合并前确认对方已停；文件被回滚或删除按该技能的 reflog / fsck / stash 流程找回，不盲目重写。
- **换行符**：`core.autocrlf=true` —— 工作区 CRLF、blob LF，勿提交混合换行文件。

## 记忆与文档纪律
- **候选门槛**：只把**通用、跨项目可复用**的经验提交为 AMH 记忆候选 —— 换一个项目、换一批数据仍然成立，且写明适用条件与验证方式。一次排查的现场结论、随本地数据变化的细节，不进候选队列。
- **项目细节进 `docs/notes.md`**：踩坑、口径约定、本机环境差异、已知未修项写进仓库内的 `docs/notes.md`（可评审、随代码演进），不占用记忆候选。
- **不自行裁决候选**：接受/拒绝候选只由本地 CLI 执行（`learn review` / `learn review-batch`），AI 只提交候选与决策建议。

## 子代理分派策略

- 简单任务主代理直接完成。只有存在可独立交付的子任务，且并行能减少等待或隔离大量探索上下文时才派发；不为了用满角色或并发额度而派发。
- 默认同时使用 1–3 个子代理；超过时先判断独立性、工具是否共享状态和整合成本，并受实际工具上限约束。
- 按当前工具实际暴露的角色选择 agent_type：quick_scan 做明确的事实抽取；default 做一般证据整理；code_explorer 做复杂调用链分析；reviewer 做独立风险审查；verifier 做指定范围的验证；mechanical_editor 做明确授权的机械修改。
- 主代理负责设计、复杂实现、范围决策与最终整合。子代理不自行扩展范围，不派生、调用或请求新的子代理。
- 默认 fork_turns="none"，传入目标、路径、已知事实、限制和完成条件；独立审查不传入主代理的预设结论。仅当连续对话上下文确有必要、工具支持且收益明确时使用有限历史，不默认继承全部历史。
- 任务说明必须自包含；已有代理适合后续同类问题时优先复用。不要让多个代理重复检索同一问题。
- 默认只读。机械修改必须明确文件所有权、转换规则、排除范围与验收方法；告知代理还有其他协作者，不回滚他人的修改。遇到设计决策立即交回主代理。
- 通常只回传最终的结论、证据和限制；阻塞、重大反证或可解除主代理依赖的阶段性结论应及时发送，不用固定进度心跳。
- 派发后先做独立工作；只有下一步确实依赖未完成结果时才等待。结果已到达不额外等待；超时后检查仍需等待、缩小任务或接手，避免机械循环。
- 主代理采纳充分、可信的证据，不默认重读全部文件或重跑全部检查；只复核冲突、关键高风险结论和修改后的最终行为。

## 项目概览
明日方舟主题文字 RPG：剧情模式（LLM 叙事 + 选项 + 记忆 + 环境）、自由模式（沙盒角色交互）、自由尺寸等距网格回合制战斗（JSON 战斗节点 + 可扩展地形 + PixiJS Spine 覆盖层）、世界书（酒馆 Lorebook 兼容的关键词触发注入）。
链路：Electron 主进程（`frontend/electron/`）→ React（`frontend/src/`，Vite 代理 `/api` → Flask `:5000`）→ Flask（`src/app.py`，factory 模式组装 Manager + Blueprint）。

## 关键约束
- **世界书注入纪律**：常驻 position-0 条目进稳定层，触发型条目一律进动态层（保持前缀缓存稳定）。
- **皮肤**：颜色工具类覆盖块由 `scripts/gen_skin_utils.py` 按色板生成，**改配色改脚本后重跑，勿手改该区段**；作用域 `@scope (html.skin-*) to (.bg-combat-bg)`，**战斗页不换肤**。
- **会话**：`combat_mode`（`narrative` / `tactical`）创建时选定，**不可更改**。
- **LLM 错误**：走 LLMError 系列结构化错误，**绝不把错误伪装成模型回复**。
- **战斗内容**：节点/敌人/地图改动走 skill `combat-designer` + `tools/`（先 `validate_battle_spec.py` 校验、再 `simulate_battle.py` 试跑，达标才入库），规格见 `docs/battle-spec.md`。
- **测试**：统一入口 `bash scripts/run_tests.sh`（pytest + `tests/legacy/`）。本机无可用 bash 时的等价命令、CLI 夹具编码口径、预装书用例的口径见 `docs/notes.md`。
设计提案：`docs/combat-value-curve-redesign.md`（未实现的目标态，现状以代码为准）。
