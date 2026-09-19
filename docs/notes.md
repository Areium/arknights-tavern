# 项目工程笔记（notes）

只记**本项目内、可复现、下次会再撞上**的细节：踩过的坑、口径约定、环境差异、已知未修项。
通用的工程经验、跨项目的方法论**不**放这里；需要长期影响 AI 行为的规则走 `AGENTS.md`
或 `.agents/skills/`，设计目标态走对应的 `docs/*.md` 设计文档。

新增条目请写明：现象 → 根因 → 现状口径 → 证据（文件/用例），并在条目首行标注日期与提交号。

---

## 会话

### 新建向导的「入队角色」不是只由玩家点击决定（2026-09-19，`d91f22a`）

- **现象**：剧情模式下选「长夜临光」后只点了一个角色，入队却有 4～5 名。
- **根因**：点选剧情磁贴时会用该剧情 frontmatter 的 `initial_characters` **覆盖** roster
  （`CreateSessionWizard.tsx` 的 `pickPlot`）。`data/plots/near-light/index.md` 的开场角色是
  临光、瑕光、砾、阿米娅、玛恩纳·临光 共 5 名，点剧情即预勾 5 个；预勾磁贴与玩家自选原先
  完全同款，点一下已预勾的角色其实是在**取消**（5 − 1 = 4）。
- **现状口径**：
  - 预选行为**保留**，但界面显式化：预选角色标「剧情预选」（区别于「已入队」）、顶部说明
    「它们已处于入队状态」并提供「清空阵容」、剧情卡片标注「开场角色 N 名 · 选中后自动预选入队」。
  - 预选只收「非玩家身份」且角色目录存在的角色。
  - 服务端**严格按 `roster_character_ids` 入队**（`blueprints/sessions.py`）：前端总会带该字段，
    因此 `_load_plot_opening(load_characters=False)` 不会再用开场角色补齐 —— **显式空阵容 = 0 角色**，
    剧情开场角色不会兜底（向导里已就这条给出提示）。
- **证据**：`.tmp/repro_story_roster.py` 风格的端到端复现：`POST /api/sessions`
  （`plot_id=near_light`、`roster_character_ids=["临光"]`）→ `characters == ["临光"]`。
- **已知未修（同方向隐患）**：`session_manager._restore_scene()` 在 story 会话持久化场景角色为空时，
  会回退加载**整份** `initial_characters`，同样绕过玩家阵容。当前未触发（正常创建路径会落盘场景状态），
  改动前请先确认该回退是否仍需要。

## 测试

### 本机跑测试的等价命令（2026-09-19）

本机（Windows + conda python）**没有可用的 bash**：`bash scripts/run_tests.sh` 里的 `bash` 实际落到
WSL，而本机未安装 WSL。等价做法：

```powershell
python -m pytest tests/ perf_tests/test_combat_runtime_v1.py perf_tests/test_combat_data_v1.py `
  perf_tests/test_settlement_v1.py perf_tests/test_card_json_roundtrip.py perf_tests/test_cv_budget.py
$env:PYTHONPATH='<repo>\src'; python tests\legacy\<each>.py   # tests/legacy 下逐个跑，需 src 在 PYTHONPATH
```

### CLI 夹具必须自己钉死 UTF-8（2026-09-19，`f6ea4e7`）

- **现象**：`tests/test_combat_growth_balance.py` 里 4 个用例在 `PYTHONIOENCODING=utf-8` 的 shell 下
  报 `_readerthread UnicodeDecodeError: 'gbk' codec`，看起来像工具坏了。
- **根因**：工具 CLI 输出中文；子进程按环境变量写 UTF-8，而父进程 `subprocess.run(text=True)` 按 locale
  （Windows 是 GBK）解码 → 读线程抛错。夹具受**外部环境变量**影响，不在工具本身。
- **现状口径**：`_run()` 统一 `encoding="utf-8", errors="replace"` 并给子进程注入 `PYTHONIOENCODING=utf-8`；
  `balance_audit` 也走同一个 `_run()`，不再自己拼 `subprocess.run`。
- 新增 CLI 用例请复用 `_run()`，不要另写 `text=True` 而不指定 `encoding`。

### 预装书用例依赖 gitignored 的本地数据（2026-09-19，`f6ea4e7`）

`data/worldbooks/` 被 `.gitignore` 忽略，`tests/test_worldbook_*.py` 的"预装书"用例读的是**本地实际内容**，
因此写死数字或写死 v2/v3 状态都会随本地数据漂移而假失败：

- 工作量估算：`estimate_workload` 必须按 `run_build` 的同一份输入算 —— 只把**出现在候选对里的 uid**
  放进 `analysis_metadata`。实测预装书「全量 262 条 → 49 批」对「受审 252 条 → 48 批」，
  混用会让 `card_calls` 断言假失败。
- v3 状态断言：普通保存应断言「保存前后 v3 状态一致」（`after.v3_enabled == original.v3_enabled`），
  不要硬编码 `not after.v3_enabled` —— 预装书早已是 v3。
