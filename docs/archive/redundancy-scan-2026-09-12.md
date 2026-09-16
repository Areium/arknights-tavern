# 代码库冗余扫描报告

- **扫描对象**：`D:\Code\arknights-tavern`（后端 `src/` 63 个 Python 文件、前端 `frontend/src` 68 个 TS/TSX 文件、脚本/工具/资产目录）
- **扫描日期**：2026-09-12
- **工具**：vulture 2.16（Python 死代码）、pyflakes（未使用导入/变量）、knip（TS 未使用导出/文件/依赖）、tsc `--noUnusedLocals`（已随构建通过）、jscpd（重复代码，min-tokens=60/100）、MD5 哈希去重（assets/ + data/ 共 33,380 个文件）
- **核实方式**：所有候选项均经全库引用搜索人工复核（含字符串引用、动态导入、Flask 路由↔前端调用交叉核对、knip 误报排除）。未经核实的项一律放入「待确认」。
- **重要口径说明**：`assets/`、`tests/`、`data/memory/`、`data/worldbooks/`、`data/characters/*/spine/`、`.tmp/`、`.dsh-tmp/` 均在 `.gitignore` 中，属本地内容；扫描同时覆盖仓库内与本地文件，但分类中已分别标注。

---

## 一、死代码（已核实，建议删除）

### 1.1 整文件死代码（2 个，共 ~298 行）

| 文件 | 行数 | 判断依据 | 建议 |
|---|---|---|---|
| `src/services/buff_pool.py` | 175 | `BuffPool` 类及 `draw_buff`/`draw_debuff`/`is_draw_request`/`parse_draw_request`/`reload` 全部方法在全库（src/tests/perf_tests/tools）**0 导入、0 引用**；`services/__init__.py` 为空，仅 `attribute_loader`/`dice` 被使用 | 删除整文件 |
| `src/combat_engine/card_loader.py` | 123 | 全库 **0 导入**（`combat_engine/__init__.py` 为空、无重导出）；实际卡牌加载走 `card_data.get_starting_deck` / `combat_settlement.get_cards_for_class`。AGENTS.md 将其描述为在用组件属文档过时 | 删除整文件，并同步更新 AGENTS.md |

### 1.2 死函数 / 方法 / 属性 / 常量（按文件分组，共 ~528 行）

**`src/providers/`（LLM 适配器层，共 ~79 行）**
| 位置 | 符号 | 判断依据 | 建议 |
|---|---|---|---|
| `base.py:57-68` | `parse_response`（抽象方法，12 行） | grep 全库，除 providers 内部外无任何调用；`load_llm.py` 自行解析响应，不走适配器 | 删除 |
| `base.py:68-80` | `parse_stream_chunk`（抽象方法，13 行） | 同上 | 删除 |
| `openai.py:68-100` | `parse_response` 实现（33 行） | 同上；且与 `load_llm.py:155-171` 存在逐字重复（见第三节 #4） | 删除 |
| `openai.py:101-121` | `parse_stream_chunk` 实现（21 行） | 同上 | 删除 |

**`src/combat_engine/grid.py`（共 ~92 行）**
| 位置 | 符号 | 判断依据 | 建议 |
|---|---|---|---|
| `:13-16` | 常量 `PLAYER_ROWS`/`PLAYER_COLS`/`ENEMY_ROWS`/`ENEMY_COLS`（4 行） | 全库 0 引用；`engine.py:13` 对它们的 import 本身也是未使用导入（pyflakes 实证） | 删除 |
| `:27-38` | `is_player_zone` / `is_enemy_zone`（12 行） | 唯一外部引用是 `engine.py:11` 的未使用 import；函数仅互相调用 | 删除 |
| `:66-68` | `get_position`（3 行） | 全库 0 引用 | 删除 |
| `:76-78` | `get_alive_units`（3 行） | 全库 0 引用 | 删除 |
| `:93-121` | `get_valid_moves`（29 行） | 全库 0 引用 | 删除 |
| `:122-144` | `cells_in_range`（23 行） | 全库 0 引用 | 删除 |
| `:145-160` | `units_in_range`（16 行） | 全库 0 引用 | 删除 |

**`src/session_overlay.py`（共 ~157 行，本次扫描最大单项）**
9 个方法全库 0 引用（含字符串/getattr 式引用搜索，均已排除）：`delete_environment_overrides`(:248, 9行)、`set_plot_id`(:283, 8行)、`init_beat_state`(:331, 32行)、`get_current_chapter`(:432, 11行)、`get_beat_context`(:477, 38行)、`get_narrative_full_text`(:515, 6行)、`get_narrative_overview`(:521, 25行)、`record_narration_on_beat`(:588, 20行)、`get_check_history`(:939, 8行)。判断为节拍系统早期迭代的遗留 API。建议全部删除。

**其他单点死代码**
| 位置 | 符号（行数） | 判断依据 | 建议 |
|---|---|---|---|
| `combat_engine/card.py:99-113` | `add_card_to_deck`、`draw_to_hand`（13 行） | 全库 0 引用 | 删除 |
| `combat_engine/entity.py:105` | `is_player` property（5 行） | 全库 0 引用 | 删除 |
| `document_manager.py:686-704` | `git_commit`（19 行） | 全库 0 引用（残留的 git 集成实验代码） | 删除 |
| `document_manager.py:724-727` | `hash_content`（4 行） | 全库 0 引用（哈希实际走 `_hash_file`） | 删除 |
| `index_manager.py:256-303` | `build_graph_data`（48 行） | 全库 0 引用 | 删除 |
| `llm_backend_manager.py:397-403` | `get_llm_for_endpoint`（8 行） | 0 调用方；docstring 称"前端手动选择时用"但前端无此流程（注释误导，见第五节） | 删除 |
| `llm_backend_manager.py:440-443` | `is_available`（7 行） | 0 调用方（状态走 `get_status`） | 删除 |
| `llm_backend_manager.py:123,388` | `_last_fail_time` 属性（2 行） | 只写不读；30s 冷却实际使用 `_endpoint_fail_time` 字典（:124,352-376） | 删除 |
| `services/attribute_loader.py:87-93` | `cn_to_eng`（7 行） | 全库 0 引用 | 删除 |
| `services/dice.py:93-119` | `is_roll_request`、`parse_roll_request`（28 行） | 全库 0 引用（DiceSystem 仅 roll 相关方法被 hooks 使用） | 删除 |
| `session_manager.py:296-309` | `start_combat`（14 行） | 0 引用（战斗由 `combat_session.py` + `blueprints/combat.py` 启动；tests 中的 `_start_combat` 是同名前缀的测试辅助函数，非引用） | 删除 |
| `SceneManager.py:206-217` | `get_active`、`get_active_agent`（12 行） | 全库 0 引用 | 删除 |
| `SceneManager.py:462-483` | `build_status`（22 行） | 全库 0 引用 | 删除 |
| `hooks/pipeline.py:26-37` | `unregister`、`hooks` property（13 行） | 全库 0 引用；疑为预留公共 API（→ 亦见待确认 #3） | 删除 / 待确认 |
| `environment_state.py:61,252,279,329` | `weather_desc` 属性（4 处赋值） | **只写不读**：4 处赋值、全库 0 读取；`get_environment` 序列化字典（`blueprints/environment.py:45-50`）不含该字段。对照 `location_desc` 有读取（:183-185），系未接线完成的预留字段 | 删除或接线（→ 待确认 #4） |

### 1.3 前端死代码（共 ~51 行）

| 位置 | 符号 | 判断依据 | 建议 |
|---|---|---|---|
| `frontend/src/hooks/useApi.ts:707-727` | `createPostSSE` 函数（21 行） | knip 报告未使用导出；人工 grep 全前端（含本文件内部）**0 调用**；AGENTS.md 将其列为既有功能属文档过时 | 删除函数，并同步 AGENTS.md |
| `frontend/src/types/index.ts` | 6 个导出类型：`DocumentInfo`、`DocumentContent`、`MoveResult`、`SSEEvent`、`GroupChatResponse`、`IndexGraph`（~30 行） | knip 报告 + 人工逐符号 grep 验证：全前端 0 引用（含 `import("../types").X` 内联类型语法已排除误判） | 删除 |

---

## 二、未使用的导入与依赖

### 2.1 Python 未使用导入（pyflakes 实证，src/ 内 21 处）

| 文件:行 | 未使用导入 |
|---|---|
| `src/combat_engine/engine.py:13` | 同一行 8 个：`PLAYER_COL_START`、`PLAYER_COL_END`、`ENEMY_COL_START`、`ENEMY_COL_END`、`TOTAL_ROWS`、`TOTAL_COLS`、`is_player_zone`、`is_enemy_zone`（整行可从 import 列表移除） |
| `src/combat_session.py:14` | `typing.Optional` |
| `src/combat_session.py:27` | `resolve_targets`、`range_between`（注：这两个函数本身在 engine.py 中存活，仅此处导入冗余） |
| `src/blueprints/chat.py:9` | `flask.Response`、`flask.stream_with_context` |
| `src/blueprints/combat.py:10` | `queue` |
| `src/blueprints/combat.py:26` | `_generate_card_choices`、`_squad_card_pool`（combat_settlement 的别名导入） |
| `src/blueprints/scene.py:7` | `pathlib.Path` |
| `src/blueprints/sessions.py:34` | `session_overlay._resolve_plot_dir` |
| `src/document_manager.py:12-13` | `re`、`json` |
| `src/index_manager.py:11` | `json` |
| `src/combat_approaches.py:15` | `random` |
| `src/combat_engine/card.py:15` | `typing.Optional` |
| `src/combat_engine/entity.py:20-21` | `typing.Optional`、`random` |
| `src/hooks/attribute_roll.py:8` | `re` |
| `src/hooks/base.py:7` | `abc.abstractmethod`（`NarrativeHook` 无任何抽象方法，导入未用） |
| `src/shared/helpers.py:5` | `json` |
| `src/combat_engine/card_loader.py:11` | `os`（文件本身已死，随 1.1 一并处理） |

**未使用局部变量（8 处）**：`combat_session.py:126` `char_name`、`environment_state.py:342` `obj_name`、`SceneManager.py:469` `active`、`session_overlay.py:491` `beat`、`blueprints/documents.py:183` `e` / `:426` `content`、`index_manager.py:170` `level_labels`、`llm_backend_manager.py:368` `test`。

**scripts/ 与 tools/（5 处）**：`scripts/generate_builtin_worldbook.py:20` `yaml`、`tools/generate_combat_background_placeholders.py:18` `PIL.ImageFilter` / `:20` `frontmatter`、`tools/split_combat_cards.py:4` `sys`、`scripts/audio/record_loopback.py:12` `rate`、`scripts/prts_scraper/scraper.py:310` `reset_time` / `:339` `e`。

### 2.2 npm 依赖（frontend/package.json）

| 依赖 | 类型 | 判断依据 | 建议 |
|---|---|---|---|
| `concurrently` | devDependency | 全部 5 个 script（dev/dev:electron/dev:web/build/preview）均未调用；仓库脚本与文档中亦无引用 | 删除 |
| `pixi-spine` | dependency | **直接导入为 0**；实际使用的是其子包 `@pixi-spine/runtime-3.8` 与 `@pixi-spine/base`（`PixiCombatScene.tsx`），但这两个包未在 package.json 中声明（knip 报 "unlisted"），仅靠 pixi-spine 的传递依赖提升进 node_modules | **声明修正**：删除 `pixi-spine`，显式声明 `@pixi-spine/runtime-3.8` + `@pixi-spine/base`（或改为从 pixi-spine 导入）——属配置错误而非纯冗余 |
| `electron-builder` | devDependency | 存在 `build` 配置块但无 script 调用；可能为手动 `npx electron-builder` 打包流程 | 待确认 #7 |

### 2.3 pip 依赖（requirements.txt）

**结论：无冗余。** 8 项全部在用：`flask`、`flask_cors`、`httpx`、`PIL`（Pillow）、`frontmatter`（python-frontmatter）、`yaml`（PyYAML）为 src/ 顶层导入；`chromadb` 在 `memory.py:33-35` 延迟导入；`pytest` 用于本地 `tests/`。

---

## 三、重复代码（jscpd 实证，21 处克隆 / 235 行 / 全为 Python，前端 0 重复）

| # | 重复位置 A ↔ 位置 B | 行数 | 内容 | 合并建议 |
|---|---|---|---|---|
| 1 | `blueprints/cards.py:83-103` ↔ `:126-146` | 21 | `save_class_cards` 与 `save_character_cards` 中带哈希冲突检测的 JSON 保存块（仅日志变量名不同） | 抽取 `_save_cards_json(path, data, expected_hash, label)` 辅助函数，两处各缩至 ~3 行 |
| 2 | `document_manager.py:238-262` ↔ `:282-306` | 25 | 两个文档收集循环中完全相同的 frontmatter 读取 + `DocumentInfo` 组装块 | 抽取 `_collect_doc_info(filepath, ...)`；同文件 `:247-264↔:291-308`(18L)、`:197-207↔:246-256`(11L) 为同一片区的重叠克隆，一并处理 |
| 3 | `blueprints/chat.py:185-203` ↔ `:226-244` | 19 | `session_chat` 与 `session_group_chat` 相同的前导段（会话校验→input 校验→player_info/env_context/config 组装）；`:384-394↔:548-558`(11L)、`:427-436↔:573-582`(10L)、`:463-472↔:612-621`(10L) 为 narrate 系列端点中的同类前导 | 抽取 `_prepare_chat_context(session_id)` 返回 (session, err, payload) |
| 4 | `load_llm.py:155-171` ↔ `providers/openai.py:12-28` | 17 | tool_calls 解析函数**逐字相同**，分处两套 LLM 层 | providers 侧随死代码（1.2）删除即可天然消除 |
| 5 | `blueprints/scene.py:209-221` ↔ `:260-272` | 13 | `set_character_override` 与 `set_item_override` 相同的会话校验 + 参数校验前导 | 抽取公共校验装饰器/辅助函数 |
| 6 | `blueprints/sessions.py:325-336` ↔ `:362-373` | 12 | 会话角色媒体上传/删除端点相同的前导（会话校验→`is_safe_entity_name`→`normalize_media_type`） | 抽取 `_validate_media_request(...)` |
| 7 | `blueprints/environment.py:106-113` ↔ `:138-145` | 8 | location 与 weather 预置列表中相同的 frontmatter 扫描循环 | 抽取 `_scan_presets(dir)` |
| 8 | `blueprints/assets.py:109-119` ↔ `:147-157` | 11 | `get_default_image` 与 `set_default_image` 相同的实体/目录解析段 | 抽取实体解析辅助函数 |
| 9 | `blueprints/cards.py:222-231↔:277-285`、`:250-259↔:301-310` | 2×10 | 角色/职业卡片的 create/delete 端点结构雷同 | 与 #1 合并为统一的卡片 JSON CRUD 辅助层 |
| 10 | `load_llm.py:206-214↔:427-435`(9L)、`:299-309↔:562-572`(11L) | 20 | `ApiLLM` 与 `LocalLLM` 中重试退避 / SSE 流式处理的相似段 | 抽取共享基类或 mixin；属"跨类复制"，重构收益中等 |
| 11 | `combat_settlement.py:436-441↔:459-464`(6L)、`index_manager.py:176-181↔:280-285`(6L)、`SceneManager.py:929-935↔:971-977`(7L) | 19 | 小片段雷同（选项组装 / 级别标签 / 事件推送） | 优先级低，可在路过时顺手合并 |
| 12 | `providers/base.py:41-51` ↔ `providers/openai.py:42-52` | 11 | `build_payload` 抽象签名与实现的参数列表重复 | **建议保留**：接口覆写的固有样板，非可消除冗余 |

**合并收益预估**：#1-#9 去重后约可净减 120-150 行；#4 随死代码删除自动消除。

---

## 四、冗余文件

### 4.1 本地遗留目录/文件（gitignored，不占仓库，但占磁盘，合计约 **500 MB**）

| 路径 | 体积 | 判断依据 | 建议 |
|---|---|---|---|
| `.tmp/` | 52 MB | 含 `bgm/venv`（残留 demucs/julius 虚拟环境）、`shots/`、`backup/`、一次性 mp3/bin | 删除（gitignored，不影响仓库） |
| `.dsh-tmp/` | 38 MB | 80+ 个一次性调试脚本（`audit*.mjs`、`probe*.py`、`test_*.py`）、日志、截图、独立 `node_modules` | 删除或按需归档个别脚本 |
| `assets/_ark_models_tmp/` | 409 MB | **孤儿 git 仓库**：目录内仅剩 `.git`（无工作树），内容为已删除克隆的对象库 | 删除 |
| `src/data/memory/` | 0.2 MB | 旧 ChromaDB 实例：`VectorMemory(persist_dir="data/memory")` 使用**相对路径**，进程 cwd 为 `src/` 时写入此处、cwd 为根目录时写入 `data/memory/`——两份库 mtime 均为当日，**记忆数据已分裂** | 先修代码（persist_dir 改为基于 `__file__` 的绝对路径），再删除 `src/data/`。注意：这是路径缺陷导致的重复，不只是垃圾文件 |
| `assets/integrity_report.txt` | <1 KB | 一次性资源校验报告（记录 8014 个 bad md5） | 删除 |
| `.pytest_cache/`、`.vite/`、`.history/` | 小 | 工具缓存/编辑器本地历史 | 可随时清理 |

### 4.2 仓库内冗余候选文件

| 路径 | 判断依据 | 建议 |
|---|---|---|
| `tools/migrate_combat_md_to_json.py` | 一次性迁移脚本，但迁移**从未执行**：`combat_data_loader.py:28,102` 至今读取 `.md`，`data/combat/` 下仍为 md | 待确认 #5（若 json 迁移已废弃则删除） |
| `tools/check_imports.py`、`tools/download_audio.py`、`tools/split_combat_cards.py` | 仅被 `docs/system-update-log.md`（更新日志）提及的一次性工具，无代码/文档流程依赖 | 待确认 #5（建议归档至 `docs/legacy/` 或删除） |
| `scripts/generate_combat_background_placeholders.py` | 全库 0 引用（README/文档/代码均无提及） | 待确认 #5 |
| `perf_tests/results_*.json`（6 个结果文件） | 历史基准测试输出被提交进仓库（`results_combat_diag.json`、`results_combat_experiments.json`、`results_effort_levels.json`、`results_extract_52.json`、`results_recall100.json`、`results_stream_verify.json`） | 建议加入 `.gitignore` 并从版本库移除（保留本地）——实验产物不应入库 |
| `frontend/dist/`、`frontend/dist-electron/` | 构建产物，可随时重新生成 | 建议确认已在 `.gitignore`（当前未跟踪），无需处理；仅提示可清理 |

### 4.3 资产层重复（哈希扫描实证，属分层设计，仅提示不动议删除）

对 `assets/`+`data/` 共 33,380 个文件做 MD5 去重：**5,282 组字节级重复，冗余体积 681.9 MB**。分布：

| 重复范围 | 组数 | 冗余体积 | 性质判定 |
|---|---|---|---|
| `assets/ArknightsGameResource`（原始资源库 12 GB）↔ `assets/organized`（精选集 558 MB） | 4,444 + 533 | 492.3 MB | **设计分层**：organized 是从原始库精选/裁剪的工作集，原始库是溯源底稿。磁盘紧张时可删原始库（12 GB），但属用户决策 → 待确认 #9 |
| assets ↔ `data/characters/<角色>/`（avatar/skin/spine 运行时副本） | 211 | 182.7 MB | **运行时物化**：应用经 `/api/assets` 从 data/ 提供角色图，副本为有意为之 | 不动 |
| data/ 内部（spine `Back/`vs`Front/` 同名 atlas、session 日志模板） | 69 | 6.3 MB | Spine 目录结构固有 + 会话模板文件，均非可删冗余 | 不动 |

---

## 五、过时或无效内容

| 位置 | 内容 | 判断依据 | 建议 |
|---|---|---|---|
| `src/app.py:7` | 模块 docstring 列举 Blueprint 时包含 **"legacy"** | `src/blueprints/` 下不存在 `legacy.py`（已核实 15 个实际文件） | 修正 docstring |
| `AGENTS.md` 前端架构节 | 记载 `useApi.ts` 含 `createPostSSE`（"POST 流式"）为既有能力 | 该函数已死（见 1.3），删除后文档必须同步 | 随 1.3 一并更新 |
| `AGENTS.md` 战斗引擎节 | 将 `card_loader.py` 描述为在用组件（"combat.json + cards.json → 卡牌实例"） | 该文件已死（见 1.1） | 随 1.1 一并更新 |
| `src/llm_backend_manager.py:398` | docstring "为指定端点创建 LLM 实例（前端手动选择时用）" | 全库 0 调用方，注释描述的功能流程不存在 | 随死代码删除 |
| `src/providers/base.py:57-80` | `parse_response`/`parse_stream_chunk` 的 docstring 描述完整响应解析契约 | 无调用方，且 openai.py 实现与 load_llm.py 逐字重复 | 随死代码删除 |
| 全库注释代码 / TODO 扫描 | ≥3 行连续"代码式注释块"：**0 处**；`TODO`/`FIXME`/`XXX`/`HACK` 标记：**0 处** | 启发式扫描（Python `#` 与 TS `//`，含中文注释过滤） | 无发现，此项干净 |

**附带发现（非冗余，供参考）**：`src/blueprints/worldbook.py:133` 存在未定义名 `WorldBook`（pyflakes 报告）——实为字符串类型注解 `"WorldBook"` 引用了未导入的类名，运行时无害（不会被求值），但建议补 import 或删注解以消除静态告警。

---

## 六、待确认清单（证据不足或涉及决策，未归入上述分类）

| # | 项 | 不确定原因 |
|---|---|---|
| 1 | `src/blueprints/wiki.py` 4 个 HTTP 端点（`/api/wiki/catalog`、`/query`、`/refresh`、`/backfill-summaries`） | 前端与脚本均 0 调用（WikiManager 由 CharacterAgent 内部直连）；但 `app.py:134` 启动日志建议运维时手动 `POST /api/wiki/backfill-summaries`，属**手动运维端点**。确认是否保留 |
| 2 | `AttributeLoader.get_modifier` 的 `attribute_name` 参数（`services/attribute_loader.py:65`） | vulture 100% 置信未使用，但参数具语义自文档作用；删除会改签名 | 保留或加 `_` 前缀，由维护者决定 |
| 3 | `hooks/pipeline.py` 的 `unregister` / `hooks` property | 0 引用，但可能是为 Hook 热插拔预留的公共 API | 若确认为预留则保留并加注释说明 |
| 4 | `environment_state.weather_desc` | 只写不读，但结构上与已接线的 `location_desc` 对称，疑为**待接入 env_context 的半成品** | 删除前确认产品意图（若接线则可丰富 LLM 环境上下文） |
| 5 | `tools/` 4 个一次性脚本（见 4.2） | 是否还有偶发手动使用场景 | 无则归档/删除 |
| 6 | `vite.config.shot.ts` | 仓库内 0 引用，但属手动调用的截图工作流配置（`vite --config`）；`vite.config.web.ts` 同理有 `dev:web` script 引用属正常 | 确认截图流程仍在用则保留 |
| 7 | `electron-builder` 依赖 | 无 script 调用但保留完整打包配置，疑似手动 npx 打包 | 确认打包流程后决定去留 |
| 8 | `perf_tests/results_*.json` ×6 | 历史基准数据是否需留档审计 | 无审计需求则移出版本库 |
| 9 | `assets/ArknightsGameResource/`（12 GB 原始资源库） | 有 organized/ 精选集与 integrity_report 表明其仍在作为溯源底稿 | 磁盘策略决策，非代码问题 |
| 10 | `frontend/electron/` 与 `vite.config.shot.ts` 被 knip 标记为"未引用文件" | 已人工核实为**误报**：electron 三文件是 `package.json main` 指向的入口，shot 配置为手动工作流 | 无需处理，仅说明 |

---

## 七、汇总统计表

| 冗余类型 | 项数 | 预估可删除代码行数 | 磁盘可释放 |
|---|---|---|---|
| 一、死代码（整文件 + 符号级，含前端） | 2 文件 + 约 50 符号 | **~877 行** | — |
| 二、未使用导入/变量（src/ + scripts/tools/） | 21 处导入 + 8 处变量 + 5 处脚本侧 | ~40 行 | — |
| 二、未使用依赖 | npm 1 可删 + 1 声明修正 + 1 待确认；pip 0 | —（package.json 2 行） | node_modules 体积略减 |
| 三、重复代码 | 21 处克隆（235 重复行） | 去重净减 **~120-150 行** | — |
| 四、冗余文件（本地遗留，gitignored） | 5 目录/文件 | — | **~500 MB** |
| 四、冗余文件（仓库内候选 + 待确认） | 5 项 | ~250 行（若全删 4 个一次性脚本） | <1 MB |
| 五、过时注释/文档 | 5 处 | ~6 行（注释） | — |
| 六、待确认 | 10 项 | 视决策 | 至多 ~12 GB（assets 原始库） |
| **合计（确定项）** | — | **约 1,040-1,100 行**（约占 src/+frontend/src 有效代码的 2.5%） | **~500 MB** 本地磁盘 |

### 处理优先级建议

1. **零风险立即删**：`buff_pool.py`、`card_loader.py` 两个整文件；`session_overlay.py` 9 个方法（157 行）；前端 6 个类型 + `createPostSSE`；21 处未使用导入（IDE 可自动修复）。
2. **本轮顺手删**：providers 死方法 + grid.py 死代码 + 各 Manager 死方法；`concurrently` 依赖；`.tmp/`、`.dsh-tmp/`、`assets/_ark_models_tmp/`（本地磁盘立省 ~500 MB）。
3. **需要先改代码再删文件**：`src/data/memory/`（先把 `VectorMemory.persist_dir` 改为绝对路径，消除记忆分裂缺陷）。
4. **重构窗口期处理**：重复代码 #1-#3、#5-#6（blueprints 层前导/保存样板抽取）。
5. **会议决策**：待确认清单 10 项（重点是 wiki 运维端点、weather_desc 半成品、assets 12 GB 原始库）。
