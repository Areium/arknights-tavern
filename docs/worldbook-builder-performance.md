# 世界书依赖自动构建：性能设计

`src/worldbook_builder.py` 把一本世界书变成依赖图谱：元数据索引 → 长条目分段 → 明确引用候选对
→ 分析卡（读全文）→ 依赖判定 → 程序校验。

老实现的问题不在「做了多少事」，而在**每件事都按最贵的粒度付费**：

| 症状 | 老实现 | 后果 |
|---|---|---|
| 分析按固定批量切 | 固定 6 个分块/请求 | 短条目批次半空、长条目撞输出上限；分批不随内容变化 |
| 判定重发整段正文 | 每个候选对带双方 1800–6000 字原文 | 1621 对候选 → 322 万输入 token，**判定占了绝大部分** |
| 估算与执行各写一套 | 干跑用一个粗略除数，执行用另一套批量 | 界面上的请求数/费用预估和真实开销对不上 |
| 缓存只绑正文 hash | 判定键 = 双方内容 hash | 改了别名或卡片提炼规则，旧判定仍被复用 |

本文件记录改后的设计与实测数据。实现细节以代码为准。

## 1. 自适应装箱：按**真实渲染**结果装箱（分析 + 判定共用一套规划器）

规划器抽到 `src/worldbook_builder_plan.py`，**估算与执行走同一份代码**：

- `Unit`：一个待处理单元（分块或候选对），只带 `key` 与 `payload`——**不带任何 token 估算字段**。
- `ExactPacker(render, instruction_tokens, input_budget, output_budget, max_units, output_of)`：
  持有生产代码**真正用的那个渲染函数**。装箱时把候选批次真的渲染成请求正文，再用
  `estimate_tokens` 量它，而不是猜「一个单元大概多少 token」。
- `plan_analysis()` / `plan_adjudication()`：在 `worldbook_builder.py` 里把单元喂给装箱器，
  并把 `build_analysis_prompt` / `build_adjudication_prompt` 作为 `render` 回调传进去。
- `plan_cost()` / `packs_all_units()`：干跑估算与**覆盖完整性断言**。

旧实现有两处系统性低估，现已被「按真实渲染装箱」直接消除：

1. **共享上下文只算了一次**：`seen_shared` 把去重后的上下文开销按「全剧只付一遍」摊掉，
   但真实请求里每个请求都要各带一份自己的上下文；且旧实现根本没把 **system 提示词**算进去。
   现在 `instruction_tokens=_system_tokens()` 进入**每一个**请求的预算核算。
2. **按 token 数去重**：旧 `RequestPacker._evaluate` 会把「两个大小相同的不同上下文」当成重复，
   于是高估了去重收益。现在去重只按 `uid + 窗口文本`（证据）与 `uid`（上下文），
   是真正的同一份内容才合并。

关键性质：**装箱是纯函数，且与执行逐字节一致**。`estimate_workload()` 用同一个规划器算出
`estimated_calls` / `estimated_input_tokens`，界面显示的就是执行时会发生的数量。
基准脚本会对「规划值 vs 真实渲染总量」做漂移校验（`drift`），不等就失败。

**保持来源顺序**：贪心装箱**不排序**。同一来源的多个候选对连续排布，它们共享的条目上下文
与证据窗口才可能被去重——排序会把同来源的对打散，去重收益随之消失。

### 上限常量

| 常量 | 值 | 含义 |
|---|---|---|
| `ANALYSIS_MAX_UNITS` | 16 | 单次分析请求最多几个分块 |
| `ANALYSIS_INPUT_TOKEN_BUDGET` | 16000 | 分析请求输入预算 |
| `ANALYSIS_OUTPUT_TOKEN_BUDGET` | 6000 | 分析请求输出预算 |
| `ADJUDICATION_MAX_UNITS` | 28 | 单次判定请求最多几对候选 |
| `ADJUDICATION_INPUT_TOKEN_BUDGET` | 12000 | 判定请求输入预算 |
| `ADJUDICATION_OUTPUT_TOKEN_BUDGET` | 6000 | 判定请求输出预算 |
| `ADJUDICATION_PAIR_OUTPUT_TOKENS` | 160 | 单对判定的输出票额 |

`ANALYSIS_BATCH` / `ADJUDICATION_BATCH` 保留为**装箱上限的别名**，不再是另一套固定值
（`test_analysis_batch_constants_match_planner_caps` 守住这一点）。

超大单元（单个分块或单对本身就超预算）不会把请求撑爆：装箱器让它**独占一个请求**并标记
`oversized`，覆盖与上限断言都放行它。执行侧对 `oversized` 的处理是**结构化失败/安全切分**，
绝不静默发送超限请求：分析侧继续按更小粒度切分正文，判定侧记 `oversized_request` 失败批次留待重试。

## 2. 判定请求：从「整段正文」到「引用窗口 + 提炼上下文」

判定只需要两样东西：**引用出现的那一小段原文**，以及**这条自身解释了什么、还有什么没解释**
（后者才是 `requires` 的来源）。老实现把两样都换成了整段正文。

改成：

- **证据窗口** `evidence_windows(content, needle)`：在正文里定位引用，只取命中处两侧
  `EVIDENCE_CONTEXT_CHARS=220` 字符，硬上限 `EVIDENCE_MAX_CHARS=700`。
  - 逐字命中 → `exact`；忽略空白命中 → `normalized`（正文写「凯 尔 希」也能定到）；
  - 定位不到 → 退化取开头 `EVIDENCE_PREFIX_CHARS=120` 字符并标 `prefix`；
  - 正文为空 → `missing`，窗口为空串。
  - 两侧被裁掉时写入显式标记 `…（上文已截断）` / `…（下文已截断）`。
- **证据窗口表**：`_collect_evidence()` 按 **uid + 窗口文本** 去重（不是只按摘要去重），
  每个窗口在请求里**只列一次**，带稳定引用 `e0`、`e1`……；`<pair>` 行只写
  `a_ref="e0" b_ref="e1"`，不再把原文各粘一遍。同一 uid 的**不同**片段是不同条目，
  各自保留、不会互相覆盖——没有原文被丢弃。
- **条目上下文** `entry_context(card)`：从分析卡提炼摘要（≤120 字）、自身定义、未解释概念
  （各 ≤4 条、每条 ≤40 字），整体硬上限 `CONTEXT_MAX_CHARS=700`，超限补 `…（已截断）`。
- **上下文去重**：同一个请求里同一条目的上下文只出现一次，由 `<context id="…">` 引用。

### 上下文不足 → 必须 unsure

截断标记不是装饰。提示词明确要求看到截断标记或窗口不足时回答 `unsure`；
执行侧再兜一层——`build_adjudication_prompt()` 返回的 `payloads` 带上每对的
`a_empty` / `b_empty` / `a_span` / `b_span` / `a_clip` / `b_clip`，若任一侧窗口为空，
**无论模型答什么都降级为 `unsure`** 并写入原因「证据窗口缺失，已强制待复核」。

模型没有原文依据时不能给出 `requires`，这是数据完整性问题，不能只靠提示词自觉。

## 3. 缓存正确性与失效

分层缓存，分析卡与判定**各自绑定提示词版本**：

| 层 | 键绑定 |
|---|---|
| 分析卡 | `内容 hash + 模型 + ANALYSIS_PROMPT_VERSION` |
| 判定 | `双方 uid + 双方内容 hash + 模型 + ADJUDICATION_PROMPT_VERSION + 卡片上下文指纹 + 证据窗口指纹` |

由此得到两条重要行为：

- **只改判定提示词 → 分析卡仍有效**，不必重付整本书的分析费（`ADJUDICATION_PROMPT_VERSION` 变，
  `ANALYSIS_PROMPT_VERSION` 不变）。
- **卡片上下文或证据窗口变了 → 旧判定失效**，即使正文、名称、别名一个字符都没动。

分块身份是**稳定哈希** `chunk_id = uid:index:hash`，断点续跑按 `chunk_id` 恢复；
检测到旧实现的数字式断点 id 时**整条重问**而不是按返回顺序猜测迁移。

### 响应校验

校验规则的核心是：**只有逐对唯一校验通过、且与请求候选对完全对应的结论才能进结算与缓存**。
不满足的一律记为可重试的失败批次。

- **缺失**：别的对答了但漏了这一对（含整批 `judgments` 为空）→ 记 `failed_batches`，
  保持待重试，**绝不静默写成 `none`**。空响应是「模型什么都没说」，不是「模型说没关系」。
- **重复**：同一对返回冲突结论 → **既不写缓存也不进结算**，记失败待重试。
  （旧实现把重复项留在结果里落盘，续跑时该对被当成「已结算」而不再问模型，
  会从冲突响应里得出假 `success`——这是被复现过的 P1。）
- **未知**：出现请求里没有的候选对 → 记录并拒绝，不猜测归属。
- **非对象 / 非法关系**：拒绝该条并记录，不静默忽略。
- **显式 `none`**：模型**逐对**明确回答 `none` 时，那是有效结论，正常写缓存、重试不重复计费。

区分「空响应」与「显式 none」是硬要求：前者必须能重试，后者才是结论。

## 3.9 预算与续跑：保留**全部**未完成工作

- `job.pending_pairs` 在判定开始前记为**整批 `todo`**，随进度逐步收窄；
  预算耗尽 / 失败留下的候选对**原样保留**（含失败项），终态不无条件清空。
- `job.pending_card_uids` / `pending_chunk_ids` 同理，续跑 API 据此知道还差什么。
- `failed_batches` 随任务 **save/load 往返**（重启后重试 API 只认它；漏载入等于丢掉「还差哪些」）。
- 终态**不会在覆盖不全时声称 `success`**：只要还有未结算候选对或失败批次，就是 `partial`。
- **版本检查点**：`analysis_version` / `adjudication_version` 与当前提示词版本不一致时，
  旧卡片 / 旧判定作废。清空 `judgments` 后由「全部候选对 − 已结算」重算 `todo`，
  因此这是**全量重排**，不会只重跑某个子集；已完成的历史 `result` 保持可读（仅标注非当前版本）。

人工锁定的结论、被拒绝的边、v3 规则与结构化 `LLMError` 都原样保留。

## 4. 指标：估算 ≠ 真实

`job.metrics` 持久化在任务里，`to_dict` / `load` 往返一致：

| 字段 | 含义 |
|---|---|
| `planned_requests` / `requests` | 规划出的请求数 / 实际发出的请求数 |
| `analysis_requests` / `adjudication_requests` | 分阶段请求数 |
| `json_repair_calls` | JSON 修复调用数（**计入** `requests`，不藏账） |
| `cache_hits` / `analysis_cache_hits` | 命中缓存的单元数 / 整条分析卡命中数 |
| `estimated_sent_tokens` | 每次实际发送正文的估算输入合计（与规划值对照） |
| `actual_known` | 是否**至少有一次**上报过 usage |
| `usage_partial` | 上报次数 < 请求数：`actual_*` 是**部分合计**，不是全量实测 |
| `usage_requests_*` / `usage_reported_*` | 每字段的请求数分母 / 实际上报次数 |
| `actual_prompt_tokens` / `actual_completion_tokens` / `actual_total_tokens` | 累加的真实用量 |

两条诚实性要求，都有回归守着：

1. **`requests` 等于真实调用数**：正常请求与 JSON 修复请求走**同一个**计数点
   （`_count_request`），修复不会被漏记导致「几次请求」低报。
2. **未知 ≠ 0，部分 ≠ 全量**：provider 不报 usage 时 `actual_known=False`、用量记 0；
   只报了一部分时 `usage_partial=True`，界面明确标注这是**部分**覆盖，
   不把部分合计显示成完整实测总量。

界面据此把「估算」和「实际」分开显示，不把估算冒充实际。

## 5. 实测

### 5.1 确定性对照（本仓库，无网络）

`scripts/benchmark_worldbook_builder.py` 是**确定性、无网络**的对照：同一本书、同一批候选对，
老实现（固定 6 / 8 批量、整段正文）与新实现（真实渲染装箱 + 引用窗口）各算一遍 token 与请求数。

脚本的**默认值是相对本仓库的**（本仓库自己的预装世界书，不依赖某个开发者机器上的兄弟目录，
也不绑定任何历史任务 ID）；要跑下面这份真实 262 条书的对照，按需显式指定输入：

```
python scripts/benchmark_worldbook_builder.py \
    --book-path <main-repo>/data/worldbooks/arknights.json \
    --cards-file <main-repo>/data/worldbook_jobs/<完成的构建任务>.json
```

分析卡喂入的是**真实历史构建任务里的卡片**——合成空卡片会低估真实成本；
脚本会在报告里注明本次用的是哪一种（`real-historical-cards` / `synthetic-upper-bound`）。

```
世界书：arknights.json · 262 条 · 733130 字符 → 709 分块 / 1621 候选对
分析卡来源：real-historical-cards

阶段      旧请求  新请求   旧输入 token   新输入 token   降幅
分析        119     50        691342         710419     -2.8%
判定        203     97       3244900        1124523     65.3%
合计        322    147       3936242        1834942     53.4%

请求数下降：54.35%（322 → 147）
判定输入 token 下降：65.34%
真实渲染超预算请求：分析 0/50、判定 0/97（预算 12000）
判定渲染总输入：1124523 token（规划值 1124523，无漂移）
```

分析侧 token **略升**是**预期的、也是对的**：分析本来就要读全文，成本几乎不可压缩；
而旧实现的估计里**根本没算 system 提示词**，现在每个请求都如实计入，所以数字反而更准。
收益集中在判定侧——老实现 324 万输入 token 里有 318 万花在重复发送整段正文上。

修复前（review 复现）：判定 **84/85 个请求超预算**（最大 17767 > 12000），
规划 982023 而真实渲染 1290715（漂移 31%）。现在 0/97 超预算、无漂移。

脚本在「判定输入 token 降幅 <50%」或「总请求数降幅 <50%」、
或「任一真实渲染请求超预算」、或「规划值与渲染总量漂移」时**退出码 1**，
且断言全部分块与候选对都被规划到 —— 变快不能以丢覆盖为代价。

### 5.2 真实模型子集测量（不是全量）

在一次独立复核里，真实模型（`cloud:deepseek-v4-flash`）在一个 **6 条目子集**上跑过：

| | 调用 | 实际输入 token |
|---|---|---|
| 基线（主仓库现状） | 3 | 16090 |
| 优化后 | 2 | 13685 |

两次都得出相同的两条 `requires`，证据可逐字核对，优化后失败数 0。
**这只是小子集冒烟，不是全书的真实运行时验证**；262 条全书的真实模型构建**未运行**。
上表 5.1 的 318 → 147 是**估算对照**（确定性渲染），与 5.2 的**实际测量**是两回事，不可混用。

## 6. 验证

| 入口 | 作用 |
|---|---|
| `tests/test_worldbook_builder_perf.py` | 真实渲染装箱与预算、来源顺序、超大单元、覆盖、窗口（中部/尾部/空白/截断）、上下文边界、证据 ref 去重、缺失/重复/未知/空响应可重试、失败批次 save/load、`requests` 计数含修复、部分用量标记、缓存失效、预算/取消/续跑、全书覆盖与规模 |
| `tests/test_worldbook_builder.py`、`tests/test_worldbook_review_fixes.py` | 既有契约回归 |
| `scripts/benchmark_worldbook_builder.py` | 确定性老/新对照 + 真实渲染超预算门禁，达标门禁 |
| `scripts/verify_worldbook_builder_llm.py` | **真实模型**端到端验证（需已配置 LLM，`--config` 指定；未配置时退出码 2 报告「未做真实验证」） |

## 7. 已知限制

- 估算基于字符级近似（CJK 1 字 ≈ 1 token，其余 4 字符 ≈ 1 token），与真实 tokenizer 有偏差；
  预算留了余量，但极端书可能触发 `oversized` 独占请求。
- 判定质量取决于分析卡提炼得是否准确：卡片把关键概念漏掉，判定就看不到该信号。
  这是「用提炼换 token」的固有取舍。
- **全书真实模型构建未运行**：确定性对照（5.1）是全量估算，真实模型验证（5.2）只覆盖 6 条目子集。
- 真实模型上的判定准确率**未做**全书回归对比（需配置 LLM，见验证脚本）。
