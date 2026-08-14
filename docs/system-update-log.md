# 系统更新设计与维护文档

> 记录战斗系统的架构演进、关键修改与未来规划方向
> 最后更新：2026-08-06

---

## 目录

1. [更新记录](#更新记录)
2. [当前系统状态](#当前系统状态)
3. [未来修改计划](#未来修改计划)
4. [系统整体架构](#系统整体架构)

---

## 更新记录

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
