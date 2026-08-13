---
name: workspace-concurrency-guard
description: 在共享 git 工作区中工作时使用——检测是否有其他进程/会话/IDE 正在同时编辑或提交同一个仓库；检测到并发时改用隔离开发；防止文件互相覆盖、git 状态被破坏；以及文件被意外回滚或删除后的恢复。
---

# 工作区并发防护

多个进程（另一个 DSH 会话、用户 IDE、脚本）可能同时操作同一个 git 工作区。本 skill 提供一套流程：**入场检测 → 隔离开发 → 写操作纪律 → 合并收尾 → 冲突恢复**。

## 铁律

- **绝不假设自己独占工作区。** 你看到的文件状态可能几秒后就变。
- **绝不用会摧毁未提交工作的命令**：`git clean -f`、`git checkout -f`、`git reset --hard`、`git stash drop`（不确认归属时）。这些命令毁掉的不只是你的工作，还可能是他人的。
- **绝不盲目重写被回滚的文件。** 内容可能已提交在别的分支或躺在 reflog/stash 里，先找回来再决定。
- **绝不 `git add -A` / `git add .`。** 全局暂存会把并发进程的改动卷进你的提交；永远用精确路径。

## 流程 A：入场检测（开始写操作前，约 10 秒）

1. 快照基线：
   ```bash
   git branch --show-current; git status --short; git stash list; git reflog -5
   ```
2. 稍等片刻（几秒），再次执行同样的快照。
3. **判定并发**：以下任一出现即视为"有其他进程在操作"：
   - 两次快照不同（新增/消失的文件、stash 变化、HEAD 或分支切换）；
   - 工作区出现陌生未跟踪文件或目录（如 `.dsh-plugins*`、临时测试脚本）；
   - `git log --oneline -3` 在任务期间出现新提交；
   - 写/编辑工具报 "file changed since it was read" 或文件不再存在（外部写入/删除）；
   - 项目有明确约定（如 AGENTS.md 标注了共享环境）。

**检测到并发 → 走流程 B（隔离开发），不要在主工作区写文件。**

## 流程 B：隔离开发（检测到并发时）

1. **选择隔离方式**：

   | 方式 | 命令 | 优点 | 缺点 |
   |---|---|---|---|
   | git worktree | `git worktree add -b <分支> <路径> HEAD` | 轻量，共享 .git（refs/对象），索引独立 | 分支名不能与现有分支冲突；共享 refs 受对方操作影响 |
   | 全新 clone | `git clone <仓库> <路径>` | 完全隔离（含 refs），分支名自由 | 需重新同步；node_modules 等可 `ln -s` 共享 |

2. **在隔离区完成开发与验证**（tsc / build 通过后再提交）。提交用精确路径 add。

3. **回传主仓库**：给隔离区添加主仓库为 remote 并推送分支。注意：**目标分支若正被主工作区 checkout，push 会被拒**（"branch is currently checked out"），此时换一个 ref 名推送：
   ```bash
   git push <remote> <分支>:refs/heads/<分支>-iso
   ```

4. **通知用户**：说明分支名、位置、验证结果，合并由用户确认或等并发进程停歇后再做。

## 流程 C：写操作纪律（任何情况下都适用）

- 每次 write/edit 后**立刻** `git status --short` 验证落盘。
- 编辑工具报 "file changed since read" 时：**重读文件**，评估外部改动，再决定是否合并双方修改——不要绕过检查强制覆盖。
- 提交粒度要小：一个功能一个提交，信息按仓库惯例写（如 `feat: ...` / `fix: ...`）。
- 删除任何未跟踪文件前先 `ls -la` 确认归属（可能是并发进程的临时产物，也可能是用户的东西——拿不准就问）。
- 提交前 `git status --short` 确认只包含自己的文件。

## 流程 D：合并与收尾

1. **合并前确认并发已停**：两次 `git log --oneline -2` + `git status --short` 快照一致，无新提交出现。
2. 合并（fast-forward 优先：`git merge --ff-only <分支>`），合并后验证 `tsc` / build。
3. 删除已合并 feature 分支（`git branch -d`），清理临时 worktree（`git worktree remove`）或临时 clone（`rm -rf`）。
4. 清理工作区残留：被并发进程暂存的重复内容用 `git reset` 撤销（确认内容已在分支上）；删除临时测试目录。
5. 需要推送远端时先告知用户。

## 流程 E：冲突恢复（文件被回滚/删除时）

1. **先找内容，再动手写**：
   - `git log --all --oneline -10` — 内容是否已提交在某个分支；
   - `git reflog -15` — 分支/HEAD 最近移动历史；
   - `git stash list` — 是否躺在 stash 里；
   - `git fsck --no-reflogs --unreachable 2>/dev/null | head` — 找 dangling commit（被丢弃的提交），`git show <sha>:<路径>` 查看内容。
2. **恢复误删的 stash**：从 `git stash drop` 的输出或 fsck 结果拿到 sha 后：
   ```bash
   git update-ref refs/stash <sha>
   ```
3. **恢复被删的未跟踪文件**：若内容曾提交在某个隔离 clone/分支，从那里复制回来；否则只能重写（重写前确认没有其他副本）。
4. **恢复被外部重置的工作区**：若自己的工作已提交在分支上，`git checkout -f <自己的分支>` 是安全的；若未提交且外部已重置，优先从 reflog 找回，而不是重做。

## 快速检查清单

- [ ] 入场时做了两次状态快照对比，判定是否并发
- [ ] 并发存在 → 隔离开发，主工作区只读
- [ ] 每次写操作后 `git status --short` 验证
- [ ] 只用精确路径 `git add`，绝不 `git add -A`
- [ ] 未执行 `git clean` / `checkout -f` / `reset --hard` / `stash drop`
- [ ] 合并前确认对方已停，合并后验证构建、删分支、清临时区
