# 系统更新设计与维护文档

> 记录战斗系统的架构演进、关键修改与未来规划方向
> 最后更新：2026-09-12

---

## 目录

1. [更新记录](#更新记录)
2. [当前系统状态](#当前系统状态)
3. [未来修改计划](#未来修改计划)
4. [系统整体架构](#系统整体架构)

---

## 更新记录
### 2026-09-12 — 战斗系统重构批次 3：升级属性点 + 难度带生效 + LLM 生成铺垫

> 承接批次 2（编辑器）。本批次补齐"成长曲线不好"与"为 AI 生成战斗铺垫"两件事，并把散落的
> 威胁模型收敛成一份可复用实现。

- **升级重新发放属性点**（`src/combat_rules.py` + `src/combat_settlement.py`）：
  `data/combat/rules/growth.json` 可配「每级属性点」（默认 1）；默认
  `auto_allocate_attribute_points=true` 时自动加到**最低未满属性**并写回
  `attribute_changes` → 会话覆盖 → 下一次战斗的战斗数值（HP/攻/防/速…按公式派生）。
  关掉自动分配则累积为 `progress.attribute_points` 待分配。结算界面新增
  「属性点 +N（已自动分配/待分配）」与专精点行。
  此前 `attribute_changes` 在 v1 恒为空（"属性只由剧情里程碑改变"），现按用户要求重做。
- **难度带与威胁预算生效**（`src/combat_balance.py` + `data/combat/rules/difficulty.json`）：
  - 威胁模型从 `scripts/migrate_balance_v1.py` 抽成共享实现（五类模板 / 威胁点 /
    期望 DPR / 有效生命 / 阶段带推荐），校验器、编辑器、生成与审计工具共用；
  - 校验器返回 `metrics.threat`（实际威胁 vs 声明预算、声明阶段带 vs 模型推荐），
    容差 25%，**只警告不阻断**；逐单位 `stats` 覆盖会重新分类（hp 150 的"士兵"不再算 1.6 威胁）；
  - 节点写 `difficulty.apply_band_scaling: true` 时，敌人数值按阶段带倍率缩放
    （T0 ×0.8 … T4 ×1.75/×1.5），一套敌人覆盖多个难度档；默认关闭（数值即文件终值）。
- **生成 → 校验 → 试跑 → 入库 闭环**（为 LLM 生成铺垫）：
  - `docs/battle-spec.md`：节点 JSON 全字段、格子效果、威胁与阶段带锚点、硬错误/警告清单、
    世界书分发格式 —— LLM 与设计者共用的规格说明书；
  - `tools/validate_battle_spec.py`：候选规格结构+数值自洽校验（退出码门禁，支持批量/stdin）；
  - `tools/simulate_battle.py`：**未入库候选**也能固定种子试跑，输出胜率/中位回合/P90/
    首回合清场/治疗溢出/血损/每轮 AP，并支持 `--min-win-rate` 等阈值判定；
  - `tools/generate_battle_spec.py`：按阶段带程序化生成合法战斗（保留中央通路避免软锁，
    按威胁预算凑编排，生成后自校验），作为 LLM 的确定性基线与兜底；
  - `.agents/skills/combat-designer/SKILL.md`：给代理/LLM 的流程规范（铁律：不改引擎、
    先校验后试跑再入库、数值要有依据；含判定标准表与回报格式）。
- **审计工具收敛**：新增 `tools/balance_audit.py`（敌人分层一致性 + §12「XP 与威胁点单调」
  + 节点预算/阶段带），产出 `perf_tests/balance_audit_report.md`；删除已失效的
  `scripts/migrate_balance_v1.py`、`scripts/tune_encounters_v1.py`
  （输入格式 `data/combat/encounters|enemies/*.md` 已在批次 1 被 JSON 节点 + 统一敌人库替代）。
  当前审计结论：敌人分层偏差 0、XP 单调性 0 问题、节点 1 处真实偏差
  （`enc_elite_hunt` 实际威胁 11.0 vs 声明预算 7.0，待设计者决定是调预算还是削编排）。
- **文档对齐**：`docs/combat-numerical-design.md` 升到 v1.2 —— 共享 AP 旧口径
  （`2 + (INT-5)//3`、上限 3、AP=3 卡"不可行"）全部改为 v1 实际值（基础 4 / 最高 5），
  网格与距离改为自由尺寸 + 统一曼哈顿。
- **测试**：新增 `tests/test_combat_growth_balance.py`（24 项：属性点分配/满值封顶/写回载荷/
  威胁分类/阶段带推荐/预算告警/带宽缩放生效/生成器与两个 CLI 闭环/可复现性/接口指标）；
  更新 `perf_tests/test_settlement_v1.py` 的成长断言。全量 `bash scripts/run_tests.sh` =
  153 + 58 + 4 个 legacy 脚本全绿；前端 `tsc --noEmit` 通过。

### 2026-09-12 — 战斗系统重构批次 2：节点注册表 + 世界书携带 + 可视化编辑器

> 承接批次 1（JSON 节点战场）。本批次把"手写 JSON 节点"变成"可编辑 + 可随世界书分发"，并让编辑器读到会话的剧情节拍进度。

- **节点注册表**（`src/combat_nodes.py`）：JSON 读写 + `_hash` 冲突检测（与卡牌共用
  `src/shared/json_hash.py`，同一套"带着旧 hash 保存 → 409"语义）+ 校验（敌人名称/数量上限/
  站位越界与阻挡/回合上限/奖励/阶段带/度量）+ 剧情节拍绑定扫描 + 会话进度 + 世界书条目编解码。
  校验规则与**开战前**一致：错误阻止保存与试打，警告仅提示。
- **接口**（`src/blueprints/combat_nodes.py`）：`GET /api/combat/nodes?session_id=`（总览：
  地图尺寸/单位数/节拍绑定/`progress` = done·current·locked/来源世界书/待创建标记）、
  `POST`（新建，空波次可存但不可开战）、`GET|PUT|DELETE /api/combat/nodes/<id>`
  （PUT 带 `_hash` → 409；DELETE 被剧情引用时 409，需 `force=1`）、
  `POST /api/combat/nodes/validate`（只校验不落盘）、`GET …/worldbook`（条目预览）、
  `POST /api/combat/nodes/import-worldbook`（按条目或书 id 导入）、
  `GET /api/combat/nodes/progress?session_id=`。
- **世界书携带**：节点可编码为一条世界书条目 —— `content` 内 ```json combat-node 围栏块
  （酒馆格式唯一无损文本通道）+ `raw.extensions.arknights_tavern.entry_type=combat_node`。
  导入世界书时**自动落地**为 `data/combat/nodes/*.json`（校验失败逐条返回错误、不落半成品）；
  导出前从注册表**回灌**条目 content，节点侧编辑不丢。
- **编辑器**（`frontend/src/components/combat/BattleNodeEditor.tsx` + `BattleMapCanvas.tsx`）：
  左侧节点列表（搜索/新建/删除/剧情节拍绑定/进度徽章/待创建提示），右侧 — 基本信息（含
  `plot/chapter/beat` 绑定）、**地图绘制**（行列调整、画格子笔刷、整图填充、玩家/敌方部署区
  涂抹）、**敌人编成**（波次增删、从图鉴加敌人、数量、**逐单位血量覆盖**、📍点图指定站位）、
  难度与奖励、服务端校验面板；顶部支持**保存（含 409 冲突重新加载）**与**⚔ 试打**。
  入口：内容中心新增「战斗节点」Tab；战斗视图战前卡片的「⚙ 编辑此节点」直接跳到该节点。
- **保底**：空节点（没有敌人）可保存但开战会被拒绝（`NodeError` → 400 与可读原因），
  避免出现"零敌人战场"。
- **测试**：新增 `tests/test_combat_nodes.py`（22 项：校验矩阵、CRUD 冲突、删除保护、
  进度、世界书往返、坏条目拒绝、整书导入、空节点拦截）。全量 `bash scripts/run_tests.sh` =
  151 + 58 + 4 个 legacy 脚本全绿；前端 `tsc --noEmit` 与 `vite build` 通过。

### 2026-09-12 — 战斗系统重构批次 1：JSON 节点战场 + 统一曼哈顿度量 + 可扩展地形

> 承接批次 0（去历史包袱）。本批次把"固定 7×7 网格 + 全局遭遇文件 + 切比雪夫距离"换成"自由尺寸战场 JSON + 统一曼哈顿 + 地形系统"，并完成敌人库合并。

- **数据格式切换**：`data/combat/encounters/*.md`（16 个）→ `data/combat/nodes/<node_id>.json`，
  **node_id 与原 encounter_id 一致**，所以剧情节拍里的 `[COMBAT:enc_*]` 零改动即可解析
  （16 个节点中 8 个已自动回填 `bind.{plot_id,chapter_id,beat_id}`）。
  两套敌人库（`data/enemies/` 叙事 11 个 + `data/combat/enemies/` 战斗 11 个，其中 2 个重名且内容不一致）
  合并为 `data/enemies/` 单一库：叙事 `attributes` + 战斗 `combat_stats`；无 `combat_stats` 的敌人
  由引擎按 `attributes` 派生数值（与玩家同一套公式）。
- **地图即数据**：`map.{rows,cols,tiles,tile_defs,deploy}`；`tiles` 支持二维 `tile_id` 数组或
  整图简写（`"ground"`）；部署区支持 `rect`/`cells` 两种写法并**真正生效**（此前 `grid_size`/
  `deploy_zones` 字段写了但代码从不读取，玩家固定 4 坐标、敌人随机落点）。上限 40×40 / 1200 格，
  校验精确到行列，软锁（出生点被墙封死）给警告不阻断。
- **可扩展地形**：格子效果由 `data/combat/tiles/*.json` 与节点内联 `tile_defs` 定义 ——
  `blocks_movement`/`blocks_los`/`move_cost`/`defense_bonus`/`evasion_bonus`/`damage_bonus`/
  `on_enter`/`on_round_start`（伤害·治疗·状态）。内置 ground/wall/cover/high_ground/hazard_fire；
  未知字段只警告（为 `on_attack`/`aura` 等留扩展位），**新增一种格子不需要改引擎代码**。
- **统一曼哈顿度量**：移动与攻击范围都改成曼哈顿（8 向，**斜向步代价 ×2**，等价于曼哈顿距离）；
  移动走 Dijkstra（含 `move_cost` 与占位），默认**禁止切角**（`rules.allow_corner_cut` 可开），
  攻击需要视线（Bresenham + 拐角；起点/终点所在格不参与阻挡，"站在掩体里仍可被瞄准"）。
  敌人 AI 的斜向贪心踏步改为**寻路下一步**（此前遇墙会卡死）。
- **射程覆盖影响与补偿**：r≥2 覆盖约减半（`(2r+1)²` → `2r²+2r+1`），r=1 由 8 邻格降为 4 正交格。
  据此对**单体近战卡**（玩家 11 张 + 敌方 `enemy_atk`/`enemy_heavy`）执行射程 1 → 2 迁移，
  补回 4 个斜角邻格；CV 预算随之收紧这几张卡的伤害（`scripts/cv_audit.py --apply`，
  新增 `melee_range_manhattan` 例外说明）。前后对照见 `perf_tests/metric_migration_report.md`
  （中位回合平均 +0.07，胜率与血损率基本持平）。
- **接口**：新增只读 `GET /api/combat/nodes`、`/api/combat/nodes/<id>`、`/api/combat/enemies`、
  `/api/combat/tiles`；战斗状态 DTO 换成 `rows/cols/tiles/tile_defs/deploy/map_warnings/
  range_metric/valid_moves_unit`（**移除 `grid_size`**），`valid_moves` 改由服务端权威计算
  （此前恒为空数组、前端自己按切比雪夫推）；`GET …/state?selected_unit=` 支持按选中单位取可达格。
  combat-test 改为节点直启（删除 `data/plots/combat-test` 的敌人池随机采样间接层）。
- **前端**：`CombatGrid` 按行列渲染（非正方形）+ 地形着色与字形 + 部署区标识；`cellSize`
  自适应（`clamp(min(availW/cols, availH/rows), 28, 72)`）；移动高亮改读服务端 `valid_moves`；
  范围/AOE 高亮与后端同度量（`metricDistance`）；战前卡片改为战斗节点下拉（显示尺寸与敌数、
  剧情节拍绑定）。
- **回归网**：新增 `tests/test_combat_map.py`（33）、`tests/test_grid_terrain.py`（13）、
  `tests/test_terrain_effects.py`（17）、`tests/test_combat_api.py`（8）；黄金基线按"有意变更项"
  重录（`tests/golden/`），全量 `bash scripts/run_tests.sh` = 99 + 58 + 4 个 legacy 脚本全绿。

### 2026-09-12 — 战斗系统去历史包袱（批次 0：回归网 + 删死代码 + 文档归档）

> 背景：项目仍处早期，**不承担旧会话/旧数据兼容**。战斗重构分三批（0 去包袱 → 1 JSON 节点地图 + 统一曼哈顿度量 + 地形 → 2 节点注册表 + 世界书绑定 + 编辑器），本条目为批次 0。

- **回归网入库**：`tests/` 解除 `.gitignore` 并纳入版本控制；新增 `tests/golden/combat_openings.json`（16 场战斗的开局结构快照）与 `tests/golden/combat_sim_metrics.json`（固定种子模拟指标），由 `tests/test_combat_golden.py`、`tests/test_combat_sim_golden.py` 守护（`GOLDEN_RECORD=1` 重录）。统一入口 `scripts/run_tests.sh`（pytest + `tests/legacy/` 脚本式检查 + 无外部依赖的 `perf_tests` 子集）。此前 AGENTS.md 写的 `python -m pytest tests/ -q` 是错的：`tests/test_*.py` 是 import 即执行并 `sys.exit()` 的脚本，会让 pytest 收集器直接 INTERNALERROR。
- **删除死代码**：战斗态从不落盘（`session.combat` 仅内存），故删除 `CombatSession.from_dict`（约 100 行）与 `CombatEngine.to_dict/from_dict`（含 v0→v1 平衡迁移分支）、`CombatUnit.from_dict`、`CardPool.from_dict`；`CombatSession.to_dict()` 收敛为结算专用的 `snapshot()`（`blueprints/combat.py` 三处调用点同步）。若将来需要"战斗中恢复"，应以「节点 spec + 命令流重放」实现。
- **修一处真 bug**：`CombatUnit.to_dict()` 缺 `is_alive`，导致结算侧 `player_alive` 恒为 True（阵亡干员按存活 100% 拿经验）。现已导出 `is_alive`。
- **删除失效工具**：`tools/migrate_combat_md_to_json.py`、`tools/split_combat_cards.py`（源格式 `combat.md`/index.md 战斗段已不存在）。`scripts/sync_cards_json_from_code.py` **保留**——`scripts/cv_audit.py:226` 依赖它生成 cv 审计基线。
- **文档口径**：`docs/combat-core-design.md` 归档至 `docs/archive/`（该文档自述"已实现"，而 AGENTS.md 仍称其"未实现的目标态"，两处口径矛盾已修正）；其 B1「7×7 网格明确不改」条款作废，后续以批次 1 的可变地图为准。
- **并发核查**：入场两次 `git status` 快照一致（无并发写）；发现休眠 worktree `../arknights-tavern-ui-preview`（分支 `design/ui-preview-20260912`，11 小时前创建、近 2 小时无写入），未触碰。
### 2026-09-12 — Windows 一键重启修复：Electron 二进制自愈 + bat 编码修复

- **Electron 起不来的根因（关键）**：electron 42 的 `install.js` 依赖 `extract-zip@2 + yauzl@2`（2015 年的流式解压栈），在 Node 26 上解压 electron zip 时解压 promise 永不落定——写完第 1 个文件（`dxil.dll`）即静默挂起，事件循环清空后 node 以退出码 0 结束：不报错、不写 `path.txt`。于是 `npm run dev` 时 vite-plugin-electron 一加载 electron 包就抛 `ENOENT ... path.txt`，游戏窗口起不来。修复：用系统自带 bsdtar 从 `@electron/get` 下载缓存（`%LOCALAPPDATA%\electron\Cache`，zip 已在且校验可用）解压补齐 `dist/` 并写 `path.txt`。
- **restart-win.ps1 自愈预检**：启动前检测到 `node_modules/electron/dist/electron.exe` 缺失时，自动从下载缓存解压补齐（优先选与已装 electron 包同版本的 zip；tar 不可用时回退 `Expand-Archive`），防未来重跑 `npm install` 后复发。
- **restart-win.bat 编码修复**：`chcp 65001` 与 bat 内多字节中文注释组合会让 cmd.exe 在码页切换后按错误字节偏移重解析脚本，把注释片段（"一个窗口"、"待前端进程……"）当命令执行（`'...' is not recognized as an internal or external command`）。bat 改为纯 ASCII（逻辑与中文输出全部在 ps1 侧），`chcp 65001` 保留——对纯 ASCII 的 bat 是安全的。
- **后端就绪探测加固**：ps1 原用 `Invoke-WebRequest` 探测 `/api/status`，它会走系统代理——挂代理的机器上连 127.0.0.1 都可能被拦截（表现为等待 60s 超时，Electron 的 PythonProcessManager 健康检查同样失败，误判后端缺失再拉起第二个 Flask 抢占 5000）。改用 `HttpWebRequest` + `Proxy=$null` 直连回环。

### 2026-08-21 — 对话延迟优化：真流式 + 分调用思考档位

- **修复伪流式（关键）**：`load_llm.py` 流式路径由 `httpx client.post()`（先下载完整响应体再 `iter_lines`，导致 SSE 所有 chunk 一次性到达、首字可见≈总时长）改为 `client.stream()` 真流式；ApiLLM 与 LocalLLM（Ollama）同步修复，保留连接错误/429/5xx 重试与 400/422 stream_options 降级。实测叙述首字 20.5s → ~0.4-0.8s。
- **按调用类型显式思考档位**：`ApiLLM.chat`/`LocalLLM.chat` 新增 `thinking` 参数；新增配置 `narration_reasoning_effort`（默认 `none`）控制剧情叙述/角色对话；标记提取、回忆生成、文档摘要批处理固定 `thinking="none"`。此前 `enable_thinking=false` 时不发任何参数，DeepSeek 混合模型仍缺省思考（实测 ~550 tok），现在显式发送 `reasoning_effort=none` 才能真正关闭。
- **实测收益**：叙述总时长 20.5-23.2s → ~2.7-3.5s；标记提取 3.9-8.0s → ~1.2-2s；提取空/截断重试率明显下降。
- **设置 UI**：设置页新增「叙述思考档位」（关闭/低/中/高）。
- **其他**：embedding 端点首次失败后短路跳过（自由模式每轮省 2 次注定失败的网络请求）；`docs/perf-round-latency.md` 记录完整分段测量与前后对比。

### 2026-08-18 — 外部世界书/角色卡导入修复 + 玩家身份角色

- **世界书导入支持 PNG 角色卡**：`/api/worldbook/import` 识别 PNG 签名，经 character_card 解析提取内嵌世界书（character_book / extensions.world），前端文件选择器放开 `.png`；纯 JSON/JSONL 导入行为不变
- **角色卡连带导入角色（角色/开场白可正常使用）**：世界书导入遇到角色卡（PNG/JSON）时，除导入内嵌世界书外自动写入 `data/characters/<slug>/index.md` + 头像（复用 /api/characters/import 同一条流水线，抽为 character_card.import_character_card / write_character_dir），响应携带 character 信息，前端提示"角色已连带导入，可入队使用"
- **开场白与场景对应**：角色卡导入把 `scenario`/`first_mes` 写入角色 frontmatter（正文保留分节），SceneManager 首轮叙述注入 `<opening_setup>`（场景设定 + 角色开场白，含 {{char}}/{{user}} 宏替换），开场叙述忠实呈现卡片设定；CharacterAgent 常驻 prompt 不重复注入（dump 排除 first_mes/scenario）
- **角色入队界面修复**：/api/characters 返回的 DocumentInfo 增加 `name` 兼容别名（此前前端读 `c.name` 得到 undefined → 磁贴无名字/无头像/选中态失效/入队加载失败）；新建向导与大厅角色选择器统一按目录名（slug）加载、显示显示名，选中磁贴增加 ✓/「已入队」徽章，完成页列出所选角色名单
- **玩家身份角色（用户自身）**：会话新增 `player_identity`（默认"博士"，创建时可选任意角色卡），持久化到 session.json（导出/导入存档携带）；新建会话向导新增「玩家身份」步骤（默认博士 + 角色库可选，头像/✓ 选中态）；对话/叙述 identity 默认取会话身份；叙述与角色对话注入 `<player_profile>`（身份简介/标签/背景，src/player_profile.py 进程内缓存）；用户消息气泡显示身份名；会话大厅统计网格显示玩家身份
- **测试**：tests/test_full_import_flow.py（解析/写盘/档案全流程）+ tests/test_api_integration.py（Flask 集成：PNG 导入/连带角色/会话身份/叙述注入）全绿，测试自清理无残留

### 2026-08-16 — 内容中心整合：三模块合一 + 方舟整合包（统一管理）

- **单一入口**：顶栏/主页导航「资产 / 世界书 / 索引」三项合并为「🗂️ 内容中心」（内部 Tab：角色·剧情 / 世界书 / 索引 / 资产 / 卡牌）；会话大厅「索引配置」跳转改走内容中心索引 Tab
- **统一管理模式（整合包机制）**：不做内置/导入分层——data/packs/arknights.json（git 跟踪）作为随程序分发的方舟整合包，WorldBookManager 首次启动自动安装到 data/worldbooks/（source=preinstalled），与用户导入的书在同一列表、同一套规则下管理（启用/停用、编辑、删除、一键重装、复制、导出）
- **世界书 API**：列表/详情新增 source/is_preinstalled/enabled；所有书可写（无只读层）；新增 POST /reinstall（重装整合包）、GET /search?q=（跨书/条目检索）；resolve 回退链扩展为 会话绑定 > 全局默认书 > 已启用的预装包
- **消除功能重叠**：DocumentManager 移除重复的依赖引用管理（编辑/扫描/批量扫描/断裂跟踪），收敛到索引 Tab，仅保留「🔗 在索引中管理」入口；删除 findDocNameInTree 等孤儿代码
- **统一检索**：内容中心顶栏全局搜索框跨世界书条目/文档检索，命中一键跳转对应 Tab 并选中该书
- **来源徽章**：新组件 SourceBadge —— 预装（青）/ 导入（紫），全列表统一标识
- **生成脚本**：scripts/generate_builtin_worldbook.py 从角色/剧情 index.md 生成整合包（19 角色 + 3 剧情 = 22 条）
- **测试**：test_world_book.py / test_worldbook_integration.py 全绿（31 用例）；自定义 data_dir 不注入预装包保持测试隔离
- **文档**：新增 docs/content-hub-design.md 设计文档；README 导航/世界书章节同步
- **角色卡导入**：POST /api/characters/import（SillyTavern 角色卡 PNG/JSON）→ data/characters/<slug>/index.md（source: imported）+ 头像 + 内嵌世界书自动导入；内容中心「角色·剧情」Tab 顶部「⬆角色卡」一键导入；新模块 src/character_card.py（PNG tEXt 解析/ST v1/v2 规范化）

### 2026-08-15 — 代码清理与可维护性优化（冗余淘汰）

- **删除死代码**：ChibiSprite.tsx、SessionList.tsx（已被 fallbackToken / 会话大厅取代）；清理其专属孤儿 CSS（.unit-hit-shake、.chibi-placeholder* 全套）
- **tsconfig 开启 noUnusedLocals/noUnusedParameters** 并修复 16 处未使用代码：App 轮询变量、CropModal pctAspect、ChatPanel handleSelectVariant（整段死函数）、CombatCard cardArtGradient 死 hash 计算、GridCell 无用 unit prop（CombatGrid 传参同步简化）、UnitStatusPanel labelColor、HomeMenu storyCount、DocumentManager scanExisting 只写状态 / closeContextMenu / updated / clearBrokenRefForDoc、IndexManager allEntityPaths、SessionManagerView bookName
- **.gitignore 补全**：.dsh-tmp/、.pi-subagents/、src/data/（运行时数据，消除长期未跟踪噪音）
- **README 更新**：过时的「左侧边栏/左侧导航」描述改为主页主菜单 → 会话大厅 → 沉浸式会话/战斗的新流程
- **Vite 构建优化**：pixi / react 手动分包（大依赖独立 chunk，利于缓存与并行加载），chunkSizeWarningLimit 600 消除构建告警
- **脚本整理**：录音（record_loopback.py）/ 转换（convert_audio.py）工具移入 scripts/audio/ 供复用，删除一次性生成/清理脚本

### 2026-08-15 — 音频控制增强：静音改暂停/继续 + BGM 音量条

- **静音改为暂停/继续**：audioManager.setMuted 由 stopBgm 改为 pauseBgm/resumeBgm（记住播放进度，再次点击从原位置继续），新增 resumeMenuBgmAfterUnmute（取消静音后若无 BGM 在播则启动菜单轮播）
- **BGM 音量可调**：setBgmVolume 按元素增益恢复音量（菜单曲目 ×0.6、战斗 ×1，WeakMap 记录）；UI 三处新增音量条——主页页脚（home-vol-slider）、管理页顶栏、设置页「音频」区块（BGM 音量 + 音效音量 + 静音开关 + 失焦暂停）

### 2026-08-15 — 主页 BGM 更换为 Mureka 生成曲目（双曲轮播）

- 用 Mureka 生成的两首自作曲替换合成 menu_loop.wav：`data/audio/bgm/menu_1.mp3` / `menu_2.mp3`（192kbps 44.1kHz）
- audioManager `startMenuBgm` 改为曲目列表顺序轮播：`playMenuTrack(index)` 播完 ended 自动切下一首，两首播完回到第一首；背景音量取用户音量 ×0.6 适配完整编曲响度；原 `menu_loop.wav` 移除

### 2026-08-15 — 菜单 BGM 重做（温暖陪伴风）

- 参考米哈游 BSide: Olivia Lin 电台气质重制 menu_loop.wav：C 大调 66bpm · 16 小节，毛毡钢琴琶音（Cmaj7-G6-Am7-Fmaj7）+ 卡林巴五声音阶旋律 + 柔和贝斯 + 垫底 pad + 黑胶爆豆/磁带嘶声；修复首尾交叉淡化的循环接缝（前移截断法，接缝仅剩单采样自然步进）

### 2026-08-15 — 游戏化界面改版：主页主菜单 + 沉浸式会话/战场 + 战斗 UI 强化

- **主页主菜单（HomeMenu）**：应用启动进入游戏主页 —— 全屏背景图（menu_bg.jpg）+ 氛围遮罩 + 「点击进入」闸门（满足浏览器自动播放策略，启动菜单 BGM）；居中栏目菜单（会话大厅/资产/世界书/索引/文档/设置），带渐显动画与主入口强调；底部显示后端/LLM 状态与音频开关
- **菜单 BGM**：audioManager 新增 startMenuBgm（data/audio/bgm/menu_loop.wav，numpy 生成 32s 无缝循环氛围乐）；菜单类页面（主页/大厅/管理页）自动播放，进入对话静默，战斗 BGM 由战斗接管
- **界面外壳重构（App.tsx）**：移除常驻 Sidebar，改为三层结构 —— 主页（全屏主菜单）/ 管理页（GameTopBar 顶栏：返回主菜单 + 管理页导航 + 音频开关，底部 StatusBar）/ 沉浸式页面（chat 与 combat 全屏无顶栏）。ChatView 保持常驻挂载以保留 SSE 流
- **沉浸式对话（ChatView）**：新增顶栏（返回大厅 / 主菜单 / 剧情·自由模式切换 / 场景面板折叠 → 全宽沉浸）；进入会话即全屏故事体验，调节世界书/阵容等需退出到大厅
- **会话大厅**：in_combat 会话卡片/详情新增「⚔ 进入战斗」直达全屏战场；头部新增「战斗演练」入口（无会话测试战场）；进入会话时自动同步对话模式
- **战斗 UI**：
  - 任务状态栏（CombatQuestBar）：战场顶部胶囊显示主任务，点击展开进行中任务列表（主线/支线/深层 + 目标），随 envRefreshKey 刷新
  - 单位模型升级（fallbackToken）：无 Spine 单位由 10px 圆点升级为职业令牌 —— 队伍色圆环 + 半透明底座 + 职业徽章，异步加载角色头像（圆形蒙版裁剪），上方名字下方 HP 条；playAttack/playHit/playDeath 对非 Spine 单位生效（冲刺/闪红抖动/渐隐下沉）
  - 出牌动画（CardFlyOverlay）：出牌时卡牌克隆沿弧线飞向目标格子（WAAPI 460ms，中途放大落点淡出），点击与拖拽两条出牌路径均触发，与手牌缩回动画叠加
### 2026-08-13 — 破甲 + 净化（卡组完成收尾）

- **破甲（ignore_def）**：Card 新增 ignore_def（物理攻击无视防御比例）；compute_damage 按 (1-ignore_def) 折算 DEF；guard_pierce「破甲斩」/ sniper_ap_round「穿甲弹」生效（无视 50% 防御）
- **净化（cleanse）**：Card 新增 cleanse；CombatUnit.clear_debuffs() 驱散减速/束缚/虚弱/沉默/燃烧/致盲（保留增益）；medic_cleanse「净化术」生效
- **战场扫描**：cmd_scan 复用 weaken（虚弱多受 25% 伤害）
- **测试**：tests/test_pierce_cleanse.py（3 用例：破甲减抗/净化保留增益/卡牌声明）
### 2026-08-13 — 状态效果收尾：闪避 + 致盲（卡组完成）

- **闪避（evade）**：CombatUnit.status 新增 evade；check_hit 中防御者闪避姿态 → EVA +3（更难被命中）；spec_evade「闪避姿态」生效
- **致盲（blind）**：check_hit 中攻击者被致盲 → HIT -3（更难命中）；spec_smoke「烟雾弹」生效
- **前端**：UnitStatusPanel 新增闪避/致盲徽章
- 至此 10 种状态效果 + 16 张描述性卡牌全部生效，卡组完成度闭环（仅剩破甲/净化/位移等可选精化）
- **测试**：tests/test_evade_blind.py（3 用例：闪避提 DC/致盲降命中/卡牌声明）
### 2026-08-13 — 状态效果补充：嘲讽（taunt）+ 侦察标记/领域展开

- **嘲讽（taunt）**：CombatUnit.status 新增 taunt；效果支持 self 标志（施加在施法者自己而非目标）；敌人 AI 目标选择（_enemy_target）优先攻击嘲讽中的玩家；defender_taunt「嘲讽打击」生效
- **侦察标记/领域展开**：vang_recon「侦察标记」、supp_zone「领域展开」复用 weaken 效果（虚弱目标多受 25% 伤害）
- **前端**：UnitStatusPanel 新增嘲讽徽章
- **测试**：tests/test_taunt.py（4 用例：无嘲讽打最近/有嘲讽打嘲讽者/嘲讽为自效果/卡牌声明）
### 2026-08-13 — 状态效果补充：沉默 + 燃烧 DoT

- **沉默（silence）**：CombatUnit.status 新增 silence；被沉默单位无法施放源石技艺（arts）卡牌（play_card 拦截 + 敌方 AI 跳过 arts 卡）；supp_nullify「源石沉默」/ supp_disrupt「干扰术」卡牌生效
- **燃烧（burn/DoT）**：新增 apply_burn(damage, duration)；每回合开始 _apply_burn 造成 burn_damage 点伤害（护盾先吸收，可致死）；caster_burn「法力灼烧」卡牌生效
- **前端**：UnitStatusPanel 新增沉默/燃烧状态徽章
- **测试**：tests/test_silence_burn.py（5 用例：沉默挡法术不挡物理/燃烧施加与递减/燃烧掉血/卡牌声明）
### 2026-08-13 — 战斗反馈打磨：闪避文字 + 伤害定位 + 状态音效

- **闪避/未命中浮动文字**：命中判定修复（feat/hit-fix）后 dodge/miss 造成 0 伤害，此前因前端 `damage > 0` 守卫被完全静默；现在 miss/dodge 显示「闪避」浮动文字 + miss 音效 + 攻击者 Spine 动作
- **伤害定位修复**：后端 damage/heal/death/status/物品治疗事件补齐 target_pos（此前前端 `target_pos || [4,4]` 永远回退到网格中心，伤害数字/粒子/受击特效错位）
- **状态效果音效**：前端处理 status 事件——护盾播 shield 音效、减速/束缚/虚弱/增幅播 ui 音效
- **CSS**：新增 .damage-number.miss（灰白描边小字「闪避」）
### 2026-08-13 — 敌人意图头顶图标（战斗 UI）

- CombatView 玩家回合（PLAYER_TURN）在敌人头顶渲染意图徽章：⚔攻击 / 💢重击 / 🌐范围攻击 / 👣移动 / 🛡坚守，复用 getCellCenter + relativeRef 与伤害数字同一套 DOM 定位，zIndex 90 叠加于 Spine 画布之上
- 与侧面板「意图 → 目标」行互补：读牌无需移眼到侧栏，战术可读性提升
### 2026-08-13 — 角色成长面板（成长可视化）

- **后端**：scene.py get_character_merged 新增返回 progress（level/xp）+ combat_stats（派生战斗数值，与 CombatUnit.from_character_metadata 同源：HP/PATK/MATK/HEAL/DEF/RES/SPD/HIT/EVA/MAX_AP）
- **前端**：CharacterDetailCard 会话活跃时拉取合并数据，新增「成长」区块（Lv + XP 进度条，阈值 level×100）与「战斗数值」区块（10 维），成长→属性→战斗数值反馈可视化
- 至此角色成长闭环可感知：战斗胜利→XP→升级属性+1→战斗数值提升→下次战斗更强
### 2026-08-13 — 卡组构建（战后 1 选 1）

- **持久化卡组**：会话 overlay 新增 combat_deck（战后选中的奖励卡），CombatSession.start 新增 bonus_cards 参数——开场按 class_required 匹配小队角色解析 owner 后注入共享牌堆（换阵容也能用）
- **战后 1 选 1**：胜利结算生成 3 张候选卡（_squad_card_pool 聚合小队各职业卡池去重，_generate_card_choices 排除已拥有）；新端点 POST /combat/card-pick 落库
- **前端**：CombatView 战利品面板新增卡牌三选一（选中后高亮并提示「已加入卡组」，下场战斗可用）；useApi.combatCardPick
- **测试**：tests/test_deck_building.py（5 用例：卡池聚合/候选去重/全拥有无候选/奖励卡注入 owner 解析/无匹配回退第一角色）
### 2026-08-13 — 命中/闪避检定修复 + 数值重平衡

- **修复 dodge bug**：compute_damage 原来只判 miss（自然 1），未达 DC 的 dodge 仍造成全额伤害，导致 HIT/EVA 属性几乎无效；现在 `not hit`（miss 或 dodge）均 0 伤害，play_card 的伤害与状态施加统一改为 `hr.hit`
- **DC 重平衡**：`10 + EVA` → `6 + EVA`。数据实测：角色 HIT≈13 vs 敌人 EVA≈5、敌人 HIT≈6 vs 角色 EVA≈10，若只修 bug 敌人命中率仅 ~37%（过于无力）；改用 DC=6 后玩家 ~95%（自然 1 仍失手）、敌人 ~56%，命中/闪避真正生效且战斗保持张力
- **命中结果透出**：damage 事件已含 hit_result（HIT/DODGE/MISS/CRIT），前端 miss/dodge 音效与结果展示复用
- **文档**：combat-design.md / combat-numerical-design.md 公式同步为 DC=6+EVA
- **测试**：tests/test_hit_fix.py（5 用例：dodge/miss 0 伤害、命中、暴击翻倍、DC=6 判定）+ 修复 test_combat_engine.py SPD 排序测试随机性（monkeypatch roll_d20）
### 2026-08-13 — 状态效果运行时（卡组完成度）

- **状态模型**：CombatUnit 新增 status（shield/slow/bind/weaken/strengthen），apply_status / tick_status（每回合递减）/ status_amount；take_damage 先扣护盾再扣 HP
- **卡牌声明**：Card 新增 effects 字段（[{type,value/duration}]）；重装·防御阵线/不破壁垒、医疗·守护之盾（护盾）、辅助·减速术（减速）、束缚术（束缚）、削弱（虚弱）、增幅过载（增幅）等卡牌现在真正生效（此前为 0 伤害/纯文案）
- **引擎**：play_card 命中后施加 effects + 虚弱/增幅 ±25% 伤害修正 + 护盾吸伤（damage 事件透出实际扣血与 shielded）；move_unit 束缚禁移 / 减速移动减半；_start_round 递减持续状态
- **前端**：CombatUnitDTO.status + UnitStatusPanel 状态徽章（护盾/减速/束缚/虚弱/增幅）
- **测试**：tests/test_status_effects.py（9 用例：护盾吸伤/状态递减/束缚禁移/减速减距/护盾卡群体生效/卡牌声明/状态透出）
### 2026-08-13 — 难度曲线：回合上限 + 撤退（fail-forward）

- **回合上限**：CombatEngine 消费 encounter.conditions.max_rounds，超过上限强制判负（battle_end winner=enemy reason=回合超时），为战斗加入时间压力
- **撤退（escape）**：CombatEngine 新增 escape()（仅 escape_enabled 时可用），玩家主动撤退结束战斗 winner=escaped，不判死亡、无奖励、剧情继续（fail-forward）
- **状态透出**：get_state 新增 max_rounds / escape_enabled；to_dict/from_dict 持久化；前端回合数显示「第 X/N 回合」+ 战斗操作栏新增「撤退」按钮
- **战后叙述**：/combat/complete 对 escaped/timeout 生成差异化结果描述与战后自动叙述（撤退/战败均为 fail-forward，不 GAME OVER）
- **测试**：tests/test_combat_difficulty.py（6 用例：回合超时/无上限/撤退/撤退禁用/条件读取/会话撤退动作）
### 2026-08-13 — 战前简报流（剧情模式战斗触发改造）

- **两段式战斗触发**：chat.py 的 _apply_combat_trigger → _apply_combat_briefing：标记提取到 [COMBAT:enc_id] 后不再自动开战，改为下发 combat_briefing 事件（含遭遇名 + 打法列表 approaches）；非流式路径在 JSON 响应中返回 combat_briefing
- **前端简报面板**：ChatPanel 收到 combat_briefing 后弹「战前打法选择」弹窗（强攻/突袭/谈判/撤退卡片），选打法后 POST /combat/start {approach_id}；谈判检定成功展示 d20 结果并可「继续」、失败展示检定后「进入战斗」、撤退直接触发战后自动叙述
- **状态**：appStore 新增 pendingBriefing；useApi 新增 onCombatBriefing 处理器 + combat_briefing 分发；types 新增 ApproachDTO / CombatBriefingDTO
- 至此「剧情模式」完整闭环：叙述 → 战前简报 → 选打法 → 投点/开战 → 结算奖励 → 战后自动叙述（对齐 combat-core-design.md C1）
### 2026-08-13 — 战前打法（Approach）+ 剧情投点（d20 展示）

- **战前打法**：新增 src/combat_approaches.py（resolve_approach 映射 enemy_scale/first_strike/player_effects/reward_mult + roll_check d20 剧情投点 + 兜底打法）；encounters 新增 approaches 字段（enc_snow_convoy/enc_final_showdown/enc_training/初遇整合运动）
- **战斗参数**：CombatSession.start() 消费 enemy_scale（敌人缩放）、first_strike（首回合共享 AP+1）、reward_mult（奖励倍率，to_dict/from_dict 持久化）；/combat/start 支持 approach_id（combat/check/avoid 三态）；/combat/complete 应用 reward_mult
- **剧情投点**：谈判/抉择类打法走 d20 检定（取小队最高属性，自然 20 必成 / 自然 1 必败），成功避免战斗、失败以 fail_combat 参数强制开战
- **修复 bug**：同名敌人 count>1 共享 unit_id 导致 add_enemy_unit 互相覆盖（遭遇战只生成 1 个该敌人）→ 现在生成唯一 unit_id（name#n），敌人数恢复设计值
- **前端**：手动开战路径（CombatView）新增打法卡片 + d20 检定结果 + 撤退提示；useApi.combatStart 支持 approach_id
- **测试**：tests/test_combat_approaches.py（13 用例：resolve/roll_check/enemy_scale/first_strike/reward_mult/唯一 unit_id）
### 2026-08-13 — 敌人意图 + SPD 行动顺序（战斗可读性）

- **敌人意图**：CombatEngine 在 ROUND_START 为每个存活敌人计算意图（attack/heavy/aoe/move/defend），含目标单位与伤害估算区间；ai_behavior=defensive 的敌人离队时坚守、aggressive 的追击（消费 enemy frontmatter 已有的 ai_behavior 字段）
- **SPD 行动顺序**：敌人阶段由 dict 顺序改为按 SPD 降序逐个行动，先手权真正生效
- **意图透出**：CombatState 新增 enemy_intents，随 state.enemy_intents 与 round_start SSE 事件下发；前端敌方面板（UnitStatusPanel）显示「意图 → 目标（伤害区间）」行
- **敌人出牌确定性**：敌人不再每回合随机抽 1 张，改为从完整卡池挑选当前最优卡（范围可达 + 可命中多人时偏好 AOE），使意图与实际行动一致（可被玩家读牌应对）
- **数据管道**：CombatUnit 新增 ai_behavior 字段（create_enemy/to_dict/from_dict/combat_data_loader 全链路）；新增 tests/test_combat_engine.py（6 用例：意图分类/防守坚守/SPD 顺序/状态透出）

### 2026-08-13 — LLM 调用工程优化（借鉴 DSH 调用纪律）

- **结构化错误**：`load_llm.py` 不再把错误伪装成模型回复（修复错误文本被当成角色台词/写入记忆的隐患），改为抛 `LLMError` 系列（connect/timeout/http/unknown）；连接错误与 429/5xx 指数退避重试，读超时不重试
- **请求指纹日志**：每次 LLM 调用记录 sha1 指纹 + token 估算，作为前缀缓存漂移的测量标尺
- **路由信任**：`get_llm()` 去掉每次 ping，改为 120s 验证缓存 TTL + 真实失败 `on_failure` 回调标记端点进入 30s 降级冷却
- **世界书注入纪律**：常驻 position-0 条目留稳定层，触发型条目一律进动态层（请求前缀缓存稳定）

### 2026-08-13 — 世界书（酒馆 Lorebook 兼容）导入与管理

- 新增 `src/world_book.py`：数据模型 + 4 源解析（酒馆 v1 导出 / v2 规格 / 角色卡内嵌 / 聊天备份 .jsonl）+ 触发匹配（主副键/selective/常驻/概率/大小写/全词）+ 注入格式化（token 预算、`{{user}}`/`{{char}}` 宏）+ 酒馆格式回灌导出
- 新增 `src/blueprints/worldbook.py`：书 CRUD、导入（文件/JSON）、条目 CRUD、全局默认书、会话绑定、resolve 查询
- 注入链路：叙述模式（`<reference>` 稳定层 + `<world_book>` 动态层）与对话模式（卡前/卡后）双通道；会话绑定存于 overlay `worldbook_id`，回落全局默认书
- 前端新增「📖 世界书」面板（`WorldBookManager.tsx`）：导入/条目编辑/会话绑定/导出；Sidebar 与 App 视图接入
- 实测兼容：导入 GitHub 社区世界书（艾尔登法环 6 本 + 明日方舟 2 本，最大 1221 条目）；修复旧版酒馆 `disable` 停用字段解析与回灌导出

### 2026-08-12 — 战斗功能工作提交（音频/物品/Spine 工具）

- 新增战斗音效资源（`data/audio/`）与前端 `audio/audioManager.ts`
- 新增物品数据（源石碎片/急救包等 11 件）、`docs/combat-core-design.md` 设计文档
- 新增 `tools/download_audio.py`、`tools/import_spine.py`、`frontend/src/components/combat/spineAnimSpecs.ts`、`frontend/src/utils/baseUrl.ts`
- 战斗计时日志（叙述/提取/回忆的 LLM 调用耗时）与 combat action 类型扩展（物品使用）

### 2026-08-06 — 会话级战斗背景覆盖

- 每个会话新增背景覆盖目录 `data/memory/sessions/<mode>/<session_id>/backgrounds/`：丢入 `<bg_id>.<ext>` 替换对应背景、`default.<ext>` 替换兜底背景，只影响当前会话
- 选用优先级变为：会话覆盖图 > 全局图；背景 ID 仍按「遭遇战 `background` → 地点 `combat_bg` → default」确定
- `resolve_background()` 新增 `session_dir`/`session_id` 参数；`CombatSession.start()` 接收会话数据目录；`Session.data_dir` 属性统一会话路径
- 会话详情接口新增 `backgrounds_dir` 字段（绝对路径，方便用户直接打开目录放图）
- 新增路由 `GET /api/sessions/<id>/backgrounds/<file>` 提供会话覆盖图（含路径穿越与文件类型防护）

### 2026-08-06 — 战斗背景系统 + AI 生成工作流

- 战斗界面支持场景背景图：根容器由纯色改为 `backgroundImage` + 压暗渐变遮罩（顶/底压暗保证文字与手牌可读，中部露出画面），无图时回退原纯色
- 背景选用优先级：遭遇战 frontmatter `background` → 地点 frontmatter `combat_bg` → `default` 背景；后端在 `CombatSession.start()` 解析为 `background_url` 透传进战斗状态 DTO
- `combat_data_loader.py` 新增 `load_background` / `background_image_url` / `resolve_background`；`from_dict` 恢复时按遭遇战重新解析
- 新增资产类别 `combat_backgrounds`（data/categories.yaml），图片走现有 `/api/assets/` 路由，文档管理界面可直接编辑提示词与上传图片
- 数据约定：`data/combat/backgrounds/<bg_id>/index.md`（提示词 + 元信息）+ 图片文件；内置 `default`（含程序化生成的占位图）与 `wasteland_ruins`（待生成）两个条目
- `session_manager.start_combat()` 传入当前剧情地点；剧情模式战斗背景随场景联动
- 新增 `tools/generate_combat_backgrounds.py`：`--scaffold` 为被引用但缺失的背景建提示词草稿、`--dry-run` 导出提示词、默认调用 OpenAI 兼容 images 接口批量出图（配置 `config/image_config.json`）
- 新增 `docs/combat-background-prompts.md`：构图规范（轻微俯视 + 中央开阔地面 + 远景地标 + 无人物无文字 + 偏暗重暗角）、基础提示词模板、场景配方与各平台参数
- 地点模板 TEMPLATE.md 补充 `combat_bg` 字段说明；遭遇战「初遇整合运动」指定 `background: wasteland_ruins`


### 2026-05-27 — 卡牌打出动画 + 手牌重排 + 剧情格式迁移

- 新增卡牌打出动画（`card-play-out`）：打出时卡牌放大 1.15× → 发光 → 淡出上浮 36px，时长 0.45s
- 乐观动画时序：动画立即播放，API 并行调用，保证最小 400ms 显示
- 手牌重排：React key 从 `card_id-index` 改为 `card_id-owner`，剩余卡牌 CSS transition 平滑过渡（0.3s）
- `cardPlayInProgressRef` 防重复守卫覆盖点击/拖拽/键盘三种出牌路径
- 剧情格式迁移：`combat-test` 和 `near-light` 从旧多文件格式迁移到单一 `plot.md`
- `session_overlay.py`：`_extract_section` 改用顶层边界表头模式，避免嵌套子标题提前截断
- `combat.py`：测试战斗配置读取从 `index.md` → `plot.md`
- `.gitignore` 新增 `data/characters/*/spine/`、`temp_*.png`

### 2026-05-25 — 战斗卡牌数据拆分 + UI 微调 + 配置清理

- 12 个角色的战斗卡牌定义从 `index.md` 提取到独立 `combat.md`（专属卡牌 + 通用卡牌池）
- 新增 `tools/split_combat_cards.py` 迁移脚本 + `tools/check_imports.py` imports 诊断工具
- ChatPanel / DialogueBubble 角色名字号 `text-xs` → `text-sm`
- constants.py 移除废弃的 `子职业一览` 配置，`战斗定位` depth 3→1

### 2026-05-25 — Markdown 文档渲染 + Prompt 卫生改进

- 新增 `MarkdownRenderer.tsx` 组件（react-markdown），文档预览从纯文本改为富文本渲染
- 支持标题/列表/引用/代码块/表格/图片/链接等全部标准 markdown 元素，含暗色主题样式
- style.css 新增 amber/purple/orange/blue/green/red 色系 light-mode 覆盖
- SceneManager 上下文注入：`plot_state` 加前缀"剧情结构参考（导航用，非脚本）"，`plot_log` 加前缀"已发生的事件，请勿重复"
- `_rewrite_plot_state` 移除当前节拍内的具体场景/对话原文，仅保留节拍名 + 轮次计数 + 下一节拍方向摘要
- `_PLOT_LOG_HEADER` 常量：引导 LLM 参考已有内容推进新剧情而非重复
- chat.py 修复第二条叙述路径遗漏的 `append_plot_log` + `update_beat_progress` 调用
- document_manager.py 子文档跳过逻辑简化 + 文件夹检测修复

### 2026-05-25 — 会话自有文档：剧情状态与进度日志解耦

- 节拍系统从"代码动态拼接 prompt 上下文"重构为"会话自有文档"模式
- 新增 `init_session_docs(plot_id)`：从 narrative.md 模板生成 `plot_state.md` + `plot_log.md` 写入会话目录
- `plot_state.md`：YAML frontmatter（chapter_idx/beat_idx/completed_beats）+ Markdown body（剧情概要/章节结构/节拍路线图/当前节拍详情）
- `plot_log.md`：增量轮次日志，每次叙述追加一行摘要（`append_plot_log`）
- `read_session_doc()` / `write_session_doc()` 通用会话文档读写 + 内存缓存
- SceneManager 上下文注入从 `get_beat_context()` + `get_narrative_overview()` 改为读取会话文档
- `record_narration_on_beat()` 拆分为 `append_plot_log()` + `update_beat_progress()`，日志记录与节拍推进解耦

### 2026-05-25 — 数据清理 + Prompt 上下文重排 + 默认图片系统 + 子文档扫描

- **数据清理**：全部角色/职业/势力文档的 `imports` 去除冗余 `| name` 后缀，移除废弃的 `# 可检索条目` 章节
- `index_manager.py` 写 imports 前先剥离已有后缀防重复堆积
- `near-light` 剧情 frontmatter 重构：规范字段排列，新增 sub-document imports（narrative/pacing/opening/quests/scenes/setting）
- **Prompt 上下文重排**：SceneManager 注入顺序从 "状态→开场→叙事→预加载→角色→动态" 改为 "状态→角色→玩家→动态→开场→进度→背景"
- 以 `get_narrative_overview()` 剧情概览（概要+章节结构）替代全文注入，避免具体场景描写引导 LLM 重复叙述
- **默认图片系统**：新增 `GET/PUT /api/assets/<category>/<entity>/default-image` API，读写 index.md frontmatter 中的 `default_avatar`/`default_skin`
- 前端图片面板新增预览大图、设为默认头像/立绘、子目录分组、默认标记（★）
- **子文档扫描**：`document_manager.py` 第三遍扫描收集实体目录内的非 index.md 子文档，复合 doc_id 支持
- `documents.py` 搜索扩展匹配 doc_id 和完整路径（`category/doc_id`）
- 前端依赖面板可折叠、验证改用 `valid` 替代 `exists`

### 2026-05-25 — 节拍引导简化 + 图片资产管理 + 跨分类搜索

- **节拍引导简化**：`get_beat_context()` 移除当前节拍详细内容和指令性语言，仅保留路线图定位 + 下一节拍方向提示
- SceneManager prompt 从 7 条规则简化为 6 条，改为自然推进策略（"推进到自然结束点时输出 [BEAT_COMPLETE]"）
- 上下文注入顺序优化：先注入剧情参考文档全文，再注入节拍进度定位
- **图片资产管理**：新增 `POST /api/assets/<category>/upload` 和 `DELETE /api/assets/<category>/<path>` API，含路径穿越防护
- `_list_entity_images()` 重写为递归子目录扫描（支持 avatar/skin 等深层目录），返回 `size` 字段
- 前端 DocumentManager 新增图片过滤、分类/实体级上传、hover 删除按钮、文件大小展示
- **跨分类搜索**：`searchDocuments` 移除 category 必传限制，`exclude_doc_id` 替代 `doc_id`
- 搜索和 imports 建议结果新增 `path`、`level`、`title` 字段
- 陈 index.md imports 格式迁移 + 移除废弃的"可检索条目"

### 2026-05-25 — 剧情节拍跟踪系统

- `session_overlay.py` 新增 `init_beat_state` / `get_beat_context` / `advance_beat` / `record_narration_on_beat` 等方法
- 解析 `data/plots/<id>/narrative.md` 章节/节拍结构（`_parse_narrative_beats`），注入 LLM prompt 引导剧情推进
- LLM 输出 `[BEAT_COMPLETE]` 标记时自动推进到下一节拍，跨章节自动处理
- 超过 8 轮叙述未完成当前节拍时强制自动推进
- `SceneManager.py` 新增第 6/7 条系统规则（遵循节拍指引 + 输出完成标记），注入节拍上下文和剧情参考文档
- `chat.py` 流式/气泡/请求三条路径均集成 `_handle_beat_complete` 和 `record_narration_on_beat`
- 会话创建时自动初始化节拍状态（`sessions.py`）

### 2026-05-25 — 角色立绘全屏限制 + 位置优化

- CharacterIllustration 仅在 `isFullscreen` 时渲染，避免非全屏下遮挡战斗界面
- 立绘位置左移（12rem）、上移（82px），渐变蒙版柔化

### 2026-05-25 — 战斗触发流程修复

- CombatView 接入 `combatSessionId`：LLM 触发战斗时自动加载已启动的会话（`useEffect` 监听 → `fetchState` + `connectSSE`）
- `chat.py` `_handle_combat_trigger` 不再通过私有属性 `_overlay` 获取 overlay，改为 `session.overlay`

### 2026-05-25 — LLM 触发战斗系统 + 9 角色叙事卡牌扩展

**LLM 触发战斗系统**：
- LLM 战术模式 prompt 中注入可用遭遇列表，叙述时输出 `[COMBAT:encounter_id]` 标记
- 后端检测标记 → 自动启动战斗会话 → 发送 SSE `combat_trigger` 事件
- 战斗中自动守卫（423 Locked）所有对话/叙述路由
- 战斗结束后自动写入场景事件日志（含遭遇 ID 和胜负）
- 新增 `PUT /api/sessions/<id>/combat-mode` 切换叙事/战术模式
- `Session.start_combat()` 便捷方法

**前端战斗 UX**：
- ChatPanel 标题栏：战斗中状态徽章（⚔）、战术模式复选框、手动触发按钮
- 战斗中禁用输入框和发送按钮（placeholder 变为"战斗中，无法对话..."）
- SSE `onCombatTrigger` 处理器自动切换至战斗视图
- 角色立绘定位和缩放优化（`left: 15rem; transform: scale(1.2)`）

**叙事卡牌扩展（9 角色，~30 张）**：

| 角色 | 新增卡牌 |
|------|---------|
| 德克萨斯 | POCKY时间(★)、企鹅物流·配送(★★)、狼的嗅觉(★★★)、德克萨斯之名(★★★★★★) |
| 玛恩纳·临光 | 公文包格挡(★)、上班族的直觉(★★)、老骑士的忠告(★★★)、十三年前的那一剑(★★★★★★) |
| 瑕光 | 扳手敲击(★)、装备评估(★★)、大师之作(★★★★★★) |
| 砾 | 飞刀投掷(★)、反监视训练(★★)、无胄盟的遗产(★★★★★★) |
| 银灰 | 贵族剑击(★)、谈判的艺术(★★) |
| 闪灵 | 基础包扎(★)、安眠之触(★★)、罪与赦(★★★) |
| 阿米娅 | 源石技艺·弹(★)、领导者的鼓舞(★★)、罗德岛的战术(★★★) |
| 陈 | 拔刀斩(★)、警官的直觉(★★)、赤霄·压制(★★★) |
| 霜星 | 冰霜之触(★)、冻土的记忆(★★) |

**文档更新**：
- `combat-design.md`：网格尺寸 9×8→7×7 全面修正
- `combat-numerical-design.md` v1.0→v1.1：双轨卡牌体系（叙事 vs 引擎）、动态共享 AP 上限表、Buff/Debuff 系统附录
- 已实现功能清单新增：LLM 触发战斗、叙事卡牌体系（30+张）

### 2026-05-25 — 角色卡牌扩展：临光 / 佐菲娅 / 博士

- 临光新增 3 张卡牌：盾牌格挡(★)、骑士的号令(★★)、耀骑士之名(★★★)
- 佐菲娅(新角色)新增 4 张卡牌：基础剑术(★)、社交之眼(★★)、临光的家徽(★★★★★)、家族的脊梁(★★★★★★)
- 博士新增 4 张卡牌：战术指令·前进(★)、战场评估(★★)、博士的计策(★★★)、石棺的记忆(★★★★★★)
- 6★ 卡牌均包含详细剧情影响段落，与角色弧线和世界观设定深度绑定

### 2026-05-25 — 会话级 Token 累计统计 + 聊天面板标题栏

- Session 新增 `total_usage` 累计字段，持久化到会话 JSON
- 所有 LLM 调用路径（chat/group-chat/narrate/narrate-continue/narrate-variant）接入 `accumulate_usage()`
- ChatPanel 新增标题栏：会话名、当前轮数、累计 token 消耗（入/出）
- Session 类型定义扩展 `narration_count` 和 `total_usage`

### 2026-05-25 — Phase 2 后端重构：Blueprint 架构 + Wiki 工具调用 + 结构化对话

**修改动机**：原有 `app.py` 2569 行单体路由难以维护，缺乏工具调用和结构化输出能力，registry_manager 设计过时。

**核心变更**：

| 模块 | 变更 |
|------|------|
| `src/app.py` | 从 2569 行单体重构为 115 行 Flask factory（`create_app()`），路由拆分为 13 个 Blueprint |
| `src/blueprints/` | 新增 13 个功能域 Blueprint（sessions, chat, scene, combat, documents, index, llm, wiki, environment, assets, legacy, memories, status） |
| `src/wiki_manager.py` | 新增 WikiManager：全量目录索引、imports 链 BFS 展开（depth 0/1/2）、模糊查询、目录摘要注入、LLM 摘要回填 |
| `src/session_context.py` | 新增会话文档缓存：角色变化时沿 imports 链预加载 |
| `src/CharacterAgent.py` | 新增 `wiki_query` 工具调用（最多 3 轮），会话文档上下文注入，token 用量追踪 |
| `src/SceneManager.py` | 新增结构化叙述模式（JSON 片段数组：narration/dialogue）、3 级 JSON 修复回退、`narrate_stream()` 线程+队列流式生成 |
| `src/load_llm.py` | `chat()` 返回值从 `str` 改为 `dict`（`{type, content, usage, tool_calls}`），新增工具调用解析（Ollama/OpenAI），`chat_text()` 向后兼容辅助 |
| `src/session_manager.py` | RegistryManager → WikiManager 迁移，Session 集成 WikiManager/SessionContext |
| `src/constants.py` | 新增核心章节提取规则、属性名中英文映射 |
| `src/avatar_color.py` | 从头像提取主题色，自动写入角色 frontmatter |
| `src/services/` | 新增 buff 池抽取系统和 d20 骰子系统 |
| `src/shared/` | 抽取公共辅助（SSE 响应、JSON 错误、缓存失效） |
| `src/combat_session.py` | 新增 `CombatTestSessionManager` 替代全局 dict |
| 删除文件 | `GameAgent.py`（840 行）、`registry_manager.py`（489 行）、`logging_setup.py`、`main.py`、`ui.py` — 均为死代码 |
| 前端 | 对话气泡模式（DialogueBubble/AvatarPlaceholder/NarrationText/LoadingIndicator/TokenUsage）、角色立绘组件（CharacterIllustration）、对话解析器（dialogueParser）、SSE 事件扩展（dialogue_segments/token_usage） |
| 数据模板 | v4.0→v5.0：imports 依赖链替代可检索条目章节，新增 summary 字段 |
| 资产 | 12 个角色 + 1 个新角色（佐菲娅）的 avatar/skin PNG 资产 |
| 依赖 | 移除 `readchar`，新增 `Pillow`（头像取色） |

### 2026-05-24 — 代码与数据冗余清理

- 移除未使用的 npm 依赖（react-markdown、d3-force、@types/d3-force）
- 删除前端死代码：`getCellSize`/`getCardSize`（combatConfig）、`getIndexGraph`/`getOverrides`/`listDocuments`（useApi）、`"MOVING"` UI 模式（appStore）
- 删除 CombatGrid 未使用的 props（`grid`、`validTargets`、`validMoves`）
- 删除后端死代码：`combat_data_loader.py` 中未使用的卡牌加载方法、`engine.py` 中 3 个未使用方法（`get_unit_hand`/`get_active_unit`/`to_dict`）、`index_manager.py` 中未使用的会话配置函数
- 清理死数据：删除 `data/combat/cards/` 下 55 个卡牌 markdown 文件（卡牌数据已由 `card_data.py` 硬编码管理）
- `engine.py` 中 `execute_enemy_turn` 重命名为 `_execute_enemy_turn`（仅内部调用）
- 修复 `app.py` 中 `_project_root` 变量名遮蔽导致战斗测试 500 错误
- 战斗错误提示增加 5 秒自动消失

### 2026-05-24 — 全局索引管理系统 + 等距网格优化

**修改动机**：原有索引分散在文档 frontmatter 中，缺乏全局管理视图和可视化引用树。战斗网格需要等距 3D 效果和小精灵覆盖层优化。

**修改内容（本地）**：

| 模块 | 变更 |
|------|------|
| `src/index_manager.py` | 新增全局索引配置管理器：CRUD、反向引用树构建、会话级配置、YAML 导入/导出、全量树合并（含未配置文档） |
| `frontend/src/components/IndexManager.tsx` | 新增索引管理组件：三栏布局（配置文件列表 + 文档树 \| 详情引用编辑 \| 实体选择添加）、引用树全屏视图、类别筛选、YAML 导入/导出、会话配置切换 |
| `frontend/src/components/DocumentManager.tsx` | 移除逐文档索引编辑面板，索引管理统一由 IndexManager 处理 |
| `frontend/src/components/Sidebar.tsx` | 新增"🔗 索引"导航项 |
| `frontend/src/App.tsx` | 注册索引视图路由 |
| `frontend/src/stores/appStore.ts` | `currentView` 类型扩展 `"index"` |
| `frontend/src/types/index.ts` | 新增索引配置树类型定义 |
| `frontend/src/hooks/useApi.ts` | 新增索引配置 API 方法（全量树、添加/移除文档、来源列表） |
| `src/app.py` | 新增索引配置 REST 路由 |

**修改内容（远程）**：

| 模块 | 变更 |
|------|------|
| `CombatGrid.tsx` | 等距 3D 网格渲染、小精灵覆盖层叠加 |
| `GridCell.tsx` | 单元格交互优化、反选支持 |
| `CombatView.tsx` | 交互逻辑重构、状态管理优化 |
| `AttackArrow.tsx` | 攻击箭头简化重构 |
| `CombatParticles.tsx` | 粒子特效优化 |
| `gridUtils.ts` | 新增网格工具模块 |

### 2026-05-23 — 角色悬浮提示 + 会话覆盖战斗集成

- 新增 `CombatUnitTooltip` 组件（Portal 浮层，展示属性/数值）
- 战斗启动时应用会话 overrides（角色编辑后的属性流入战斗）
- 新增 `POST /combat/complete` 战斗结算写回端点
- 新增 DeckViewer 卡组查看组件（按角色分组，手牌/抽牌堆/弃牌堆/消耗堆）

### 2026-05-23 — 战斗 UI 合并与优化

- 拖拽出牌支持，3D 透视网格，CSS 粒子特效
- GridCell 按钮嵌套修复（ChibiSprite 改为 pointer-events-none）
- 选中/活跃单位视觉区分（分别使用不同边框样式）
- 卡牌攻击范围高亮

---

## 当前系统状态

### 已实现功能

- [x] 共享卡池系统（全队共用抽牌堆/手牌/弃牌堆/消耗堆）
- [x] 共享回合制（全队同时行动，自由选择角色出牌）
- [x] 双 AP 池（共享 AP + 个人 AP）
- [x] 角色保底机制（每轮每角色至少 1 张可用牌）
- [x] 敌方 AI（寻敌→出牌→移动）
- [x] 命中/伤害计算（d20 体系）
- [x] 网格站位（9×8，Chebyshev 距离）
- [x] 卡牌目标模式（SINGLE/ADJACENT/CROSS/LINE_3/ROW/ALL_ALLIES/GLOBAL）
- [x] 角色属性→战斗数值映射
- [x] 会话 overrides 战斗集成
- [x] 战斗结算写回
- [x] SSE 事件流（伤害/治疗/死亡/回合/战斗结束）
- [x] 浮动伤害数字 + 粒子特效
- [x] 角色悬浮工具提示（属性+数值）
- [x] 卡组查看器
- [x] 战斗测试模式（无需会话）
- [x] 战斗存档/读档
- [x] Blueprint 模块化路由架构（13 个功能域）
- [x] Wiki 文档目录索引 + imports 链预加载
- [x] LLM 工具调用（wiki_query）
- [x] 结构化对话输出（JSON narration/dialogue 片段）
- [x] SSE 流式叙述（Token 级渐进显示）
- [x] 对话气泡模式（角色主题色）
- [x] 角色立绘展示（战斗选中时）
- [x] 会话级 token 累计统计
- [x] Buff/Debuff 抽取池系统
- [x] d20 独立掷骰服务
- [x] LLM 自动触发战斗（[COMBAT:ID] 标记 + SSE 事件）
- [x] 战斗中对话守卫（423 Locked）
- [x] 叙事/战术战斗模式切换
- [x] 叙事卡牌体系（12 角色 × 30+ 张专属卡牌，1-6★）

### 已知限制

- [ ] 敌方 AI 简单（仅攻击最近目标，无策略）
- [ ] 无角色死亡后的卡组清理
- [ ] 精英牌消耗后无法回收
- [ ] 无 buff/debuff 系统
- [ ] 网格移动无碰撞检测（单位不可重叠但可穿越）

---

## 未来修改计划

### 短期（下一阶段）

1. **个人 AP 系统完善**
   - 当前个人 AP 在回合开始时重置，但未在前端展示
   - 移动消耗个人 AP 而非共享 AP
   - 角色专属牌消耗个人 AP，通用牌消耗共享 AP

2. **敌方 AI 增强**
   - 引入行为模式（攻击型/防守型/支援型）
   - 优先攻击低血量/高威胁目标
   - 敌方治疗单位 AI

3. **buff/debuff 系统**
   - 状态效果（眩晕、中毒、脆弱、加固等）
   - 持续时间与层数
   - 与卡牌/遗物系统的交互

4. **战斗 UI 打磨**
   - 攻击动画（弹道/冲击）
   - 单位受伤/死亡动画
   - 音效系统接口

### 中期

5. **遗物/物品系统**
   - 战斗中被动效果（属性加成、触发效果）
   - 主动物品（一次性/冷却制）
   - 物品数据从 markdown 加载

6. **多波次遭遇战**
   - 波次间增援
   - 波次过渡动画
   - 波次奖励/回复

7. **战斗回放**
   - 记录全部行动序列
   - 回放渲染（步进/自动播放）

### 长期

8. **PvP 框架**
   - 双方轮流操作的异步对战
   - 匹配与排行

9. **模组化遭遇战编辑器**
   - 可视化编辑遭遇配置
   - 预览敌方站位

---

## 系统整体架构

### 技术栈

```
┌─────────────────────────────────────────────────┐
│                   Frontend                       │
│  React 18 + TypeScript + Zustand + Tailwind     │
│  Vite 构建  ·  Electron 桌面壳（可选）           │
├─────────────────────────────────────────────────┤
│                   Backend                        │
│  Flask (Python 3.12) + REST + SSE               │
│  Blueprint 架构  ·  WikiManager  ·  SceneManager │
│  SessionManager  ·  SessionContext  ·  Overlay   │
├─────────────────────────────────────────────────┤
│                Combat Engine                     │
│  纯 Python  ·  独立于 Flask                      │
│  engine.py  ·  entity.py  ·  card.py            │
│  grid.py  ·  dice.py  ·  card_data.py           │
├─────────────────────────────────────────────────┤
│                   Data                           │
│  Markdown + YAML Frontmatter                     │
│  data/characters/  ·  data/combat/              │
│  Wiki 目录索引  ·  imports 依赖链               │
│  overrides.json（会话层持久化）                  │
└─────────────────────────────────────────────────┘
```

### 前端架构

```
frontend/src/
├── components/
│   ├── ChatPanel.tsx            — 对话面板（SSE 流式、气泡模式、token 统计）
│   ├── Sidebar.tsx              — 主导航栏
│   ├── DocumentManager.tsx      — 文档管理（树/内容编辑器）
│   ├── IndexManager.tsx         — 全局索引配置管理（三栏布局 + 引用树）
│   ├── SettingsPanel.tsx        — 设置面板
│   ├── SessionList.tsx          — 会话列表（自动命名、去重）
│   ├── CharacterPanel.tsx       — 角色面板
│   ├── chat/                    — 对话气泡组件
│   │   ├── DialogueBubble.tsx   — 角色对话气泡（主题色边框/背景）
│   │   ├── AvatarPlaceholder.tsx — 角色头像占位图
│   │   ├── NarrationText.tsx    — 叙述文本
│   │   ├── LoadingIndicator.tsx — 等待加载指示器
│   │   └── TokenUsage.tsx       — 单次响应 token 消耗展示
│   └── combat/
│       ├── CombatView.tsx          — 战斗主视图（状态管理、事件中枢）
│       ├── CombatGrid.tsx          — 网格渲染（等距 3D、拖放、单元格）
│       ├── GridCell.tsx            — 单个单元格（单位显示、小精灵、高亮）
│       ├── ChibiSprite.tsx         — 角色小精灵（纯展示，pointer-events-none）
│       ├── CombatHand.tsx          — 手牌扇形布局
│       ├── CombatCard.tsx          — 单张卡牌（拖拽源、渐变、AP 消耗）
│       ├── UnitStatusPanel.tsx     — 角色状态面板（HP/AP/属性摘要）
│       ├── CombatUnitTooltip.tsx   — 角色悬浮提示（Portal，属性+数值）
│       ├── CombatEventLog.tsx      — 战斗事件日志
│       ├── CombatParticles.tsx     — Canvas 粒子特效
│       ├── CharacterIllustration.tsx — 角色立绘展示（选中时显示）
│       ├── gridUtils.tsx           — 网格工具函数
│       └── DeckViewer.tsx          — 卡组查看器（按角色/牌堆分组）
├── hooks/
│   └── useApi.ts               — API 客户端（REST + SSE）
├── utils/
│   └── dialogueParser.ts       — 对话解析器（「」→ 气泡片段，说话人推断）
├── stores/
│   └── appStore.ts             — Zustand 全局状态
├── types/
│   └── index.ts                — TypeScript 类型定义
└── style.css                   — 战斗样式（粒子动画、网格 3D、手牌扇形）
```

### 后端架构

```
src/
├── app.py                      — Flask 应用入口（create_app 工厂模式）
├── constants.py                — 共享常量（核心章节规则、属性映射）
├── session_manager.py          — 会话生命周期管理 + token 累计
├── SceneManager.py             — 场景管理：多角色对话、结构化叙述、SSE 流式生成
├── CharacterAgent.py           — 角色代理：角色扮演 + wiki_query 工具调用 + 记忆
├── session_overlay.py          — 会话层数据覆盖（overrides.json）
├── session_context.py          — 会话文档缓存（imports 链预加载）
├── wiki_manager.py             — Wiki 文档索引与查询（目录构建、imports 链展开、模糊查询、摘要回填）
├── index_manager.py            — 全局索引配置管理（CRUD、反向引用树、会话级配置）
├── avatar_color.py             — 从头像提取主题色，写入角色 frontmatter
├── combat_session.py           — 战斗会话封装（CombatEngine → REST/SSE）
├── combat_data_loader.py       — 战斗数据加载（遭遇/敌人）
├── document_manager.py         — 文档 CRUD + 冲突检测
├── llm_backend_manager.py      — LLM 多后端检测与自动降级
├── load_llm.py                 — LLM 加载器（Ollama/API），支持工具调用和 token 追踪
├── environment_state.py        — 环境状态追踪
├── memory.py                   — 向量记忆系统（ChromaDB）
├── blueprints/                  — Flask Blueprints（功能域路由拆分）
│   ├── sessions.py             — 会话 CRUD + 剧情列表
│   ├── chat.py                 — 对话/叙述 API（SSE 流式、变体生成）
│   ├── scene.py                — 场景角色/物品/覆盖管理 + 角色头像/立绘
│   ├── combat.py               — 会话战斗 + 战斗测试
│   ├── documents.py            — 文档 CRUD + 冲突检测
│   ├── index.py                — 索引配置管理
│   ├── llm.py                  — LLM 后端配置
│   ├── wiki.py                 — Wiki 目录查询 + 摘要回填
│   ├── environment.py          — 环境状态
│   ├── assets.py               — 静态资源
│   ├── legacy.py               — 旧版路由兼容
│   ├── memories.py             — 回忆系统
│   └── status.py               — 健康检查
├── services/                    — 服务层
│   ├── dice.py                 — d20 掷骰系统（关键词检测、文本解析）
│   └── buff_pool.py            — Buff/Debuff 随机抽取池（稀有度分层）
├── shared/                      — 共享工具
│   ├── helpers.py              — JSON 错误、SSE 响应、记忆上下文注入
│   └── cache.py                — 文档变更后缓存失效
└── combat_engine/
    ├── __init__.py             — 公开 API 导出
    ├── engine.py               — 战斗状态机、回合管理、敌方 AI
    ├── entity.py               — 战斗单位（属性映射、数值换算）
    ├── card.py                 — 卡牌、卡池（抽牌/弃牌/消耗）
    ├── card_data.py            — 卡牌数据定义、职业卡池、起始卡组
    ├── grid.py                 — 网格系统（站位、移动、距离、目标解析）
    └── dice.py                 — d20 掷骰、命中判定、伤害计算
```

### 数据流

```
Markdown 数据 ──→ CombatDataLoader ──→ CombatEngine
                                          │
会话 overrides ──→ SessionOverlay ──→ character_metas
                                          │
                    ┌─────────────────────┘
                    ▼
              CombatSession
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   REST API    SSE Stream   状态快照
   (action)    (events)    (get_state)
        │           │           │
        ▼           ▼           ▼
   CombatView ◄── React State ◄── JSON
```


### 战斗状态机

```
INIT ──→ ROUND_START ──→ PLAYER_TURN ──（玩家结束回合）──→ ENEMY_TURN
  ↑                                            │                │
  │                              轮次+1，抽牌，重置 AP            │
  │                                            │                │
  └────────────────────────────────────────────┘                │
                                                    所有敌方行动完成
                                                           │
                                                    检查胜负 ──→ END
```

### 核心数据模型

```
CombatUnit                    Card                      CardPool
├─ unit_id                   ├─ card_id                ├─ deck: list[Card]
├─ name                      ├─ name                   ├─ hand: list[Card]
├─ team (player/enemy)       ├─ damage_type            ├─ discard: list[Card]
├─ char_class                ├─ min/max_damage         ├─ exhaust: list[Card]
├─ HP / PATK / MATK / ...    ├─ atk_scale              └─ hand_size: int
├─ AP (personal)             ├─ target (SINGLE/...)
├─ pos [row, col]            ├─ range
├─ attributes (raw 1-10)     ├─ cost
└─ is_alive                  ├─ tier (basic/elite)
                             ├─ class_required
                             └─ owner (character name)
```

### 共享 AP 计算

```
SHARED_AP_MAX = 2 + max(0, (highest_tactical_planning - 5) // 3)
                 ───   ──────────────────────────────────────
                 基础               战术规划加成
                                   (6-7: +0, 8-10: +1, ...)
```

### 卡牌保底机制

每轮抽牌后，检测每位存活角色在共享手牌中是否至少有一张归属卡牌。如果没有，从抽牌堆/弃牌堆/消耗堆中随机找一张该角色的卡牌，替换手牌中随机一张。此机制保证每位角色都有可用的行动选择。
