# 性能基准与瓶颈报告（2026-09-12）

> 分支：perf/benchmark-report（基线 main@b9dcbe8）
> 运行环境：Windows / Python 3.12.1（miniconda）/ chromadb 1.5.9 / httpx 0.28.1
> 线上配置：`deepseek-v4-flash` @ api.deepseek.com，`enable_thinking=true`，`reasoning_effort=medium`，
> `narration_reasoning_effort=none`，`auto_generate_choices=true (3)`，`dialogue_bubble_mode=true`，
> `max_output_tokens=8192`，`word_limit=500`
> 前置背景：2026-08 轮（docs/perf-round-latency.md §5）已落地真流式、按调用类型思考档位、embedding 短路。
> 本轮为修复后的回归复测 + 记忆/前缀缓存两个未量化维度的补测。

---

## 0. 摘要

三个维度各跑一轮基准，外加两个探针（ChromaDB 延迟、真实 API 前缀缓存命中），结论：

| # | 瓶颈 | 严重度 | 实测依据 |
|---|---|---|---|
| B1 | **生产语义记忆从未运行**：`ApiLLM.embed` 打 DeepSeek `/embeddings`（端点不存在），首次失败短路后全程纯滑窗 | 高（功能缺失） | 代码路径 + 探针：ONNX 本地嵌入 133ms/次可用但未接线 |
| B2 | **前缀缓存被装配顺序架空**：SceneManager 把每轮增长的 `plot_state/plot_log` 放在世界书稳定层**之前**；且生产世界书 22/22 条目全是触发型，稳定层实际为空 | 高（成本/延迟） | 真实 API：头部插入变化 → cache_hit 768→**0** |
| B3 | **每轮动态尾过大**：世界书触发样本 6.8k tokens + 滑窗 1.7k~4.2k + 历史 3k 字，全部逐轮 miss | 中 | bench_tokens + 窗口探针 |
| B4 | 前端流式渲染 per-token `setSessionMessages`（无 rAF 批处理、无 memo） | 中 | ChatPanel.tsx:1223 起 |
| B5 | CombatView 上帝组件（77KB/1804 行，28 个 useState） | 中（架构债） | 详见 §4，拆解优先级次于 B1–B4 |

---

## 1. SSE 流式：首 token 与整体延迟（bench_stream_verify ×3）

脚本对同一叙述请求测三种用法，各跑 3 轮取中位：

| 用法 | 首 chunk（3 轮） | 中位 | 总时长中位 | 内容流 span |
|---|---|---|---|---|
| `client.post()+iter_lines`（伪流式） | 4078 / 5188 / 3953 ms | **4078 ms** | 4078 ms | **0 ms**（整段一次性到达） |
| `client.stream()` thinking=on | 625 / 531 / 672 ms | **625 ms** | 4344 ms | 3719 ms |
| `client.stream()` thinking=off* | 797 / 328 / 609 ms | **609 ms** | 4172 ms | 3515 ms |

\* thinking=off 分支不发 `reasoning_effort` 参数，模型仍缺省思考（reasoning_chunks 99–202）——
与 8 月报告根因 B 一致；线上由 `narration_reasoning_effort=none`（显式发送 none）规避。

**结论**：
- 伪流式与真流式的 TTFT 差 = 整段生成时长（本轮 ~4s，8 月重思考时 20.5s）。假设回归成立。
- 生产 `load_llm.py` 已使用 `_open_stream_with_retry`（client.stream，L238/485/493 核实），
  **该瓶颈在 main 上已修复**，本维度作为回归基线留档。
- 当前叙述调用总时长 ~4.0–5.3s（正文 491–837 字 + reasoning 114–221 chunks），
  TTFT ~0.6s，处于 8 月修复后的预期区间。

## 2. 记忆检索：ChromaDB 延迟与滑动窗口成本

### 2.1 召回正确性（bench_memory_recall）

ONNX 嵌入模式下：窗口外 8 条事实召回 **8/8（100%）**，窗口内去重正确，降级路径正常。
检索管道本身无功能缺陷——前提是有可用的嵌入函数。

### 2.2 延迟探针（合成集合，recent_turns=10）

| 指标 | 10 docs | 50 | 100 | 200 |
|---|---|---|---|---|
| `retrieve()` p50 | 130 ms | 128 | 136 | **153 ms** |
| `add()` p50（嵌入+写入+持久化） | 148 ms | 170 | 150 | **188 ms** |
| `build_context()` p50 | 128 ms | 130 | 142 | 157 ms |

- ONNX 模型冷启动：构造 602 ms + 首次调用 260 ms（**一次性 ~0.9s**）；稳态单文本嵌入 **133 ms**。
- 10→200 条规模增长下 retrieve 仅 +18%：延迟几乎全是固定嵌入成本，ChromaDB 查询本身可忽略。
- 真实记忆库当前仅 2.3MB（单集合），200 条已覆盖可预见的增长空间。

### 2.3 滑动窗口成本（生产参数 recent_turns=10 → 20 条消息）

| 消息体量 | 窗口注入 token（估） | 说明 |
|---|---|---|
| ~200 字/条 | **~1.7k tokens/轮** | 自由模式短回复 |
| ~500 字/条（word_limit 上限） | **~4.2k tokens/轮** | 剧情叙述 |

窗口文本位于 system prompt 尾部的易变区，**每轮内容都变 → 每轮全量 cache-miss**，是纯增量成本。

### 2.4 关键发现：生产环境语义检索从未运行

`CharacterAgent` 注入的是 `ApiLLM.embed` → 打 `POST /embeddings`（DeepSeek 无此端点）→
首次失败置 `_embed_disabled` 永久短路 → `VectorMemory.add/retrieve` 全部走
`embedding is None` 分支：**集合永远为空，语义检索在生产是死代码，全程纯滑窗。**

- 短路修复（8 月 P2）已把浪费降到一次性 ~125ms，但「召回率 8/8」的 ONNX 路径从未被生产接线。
- 接线成本（实测）：一次性冷启动 ~0.9s + 每轮 2 次嵌入 ~270ms（retrieve 1 次 + add 1 次）。
- **建议**：为 `VectorMemory` 增加本地 ONNX 嵌入接线开关（`chromadb.utils.embedding_functions.DefaultEmbeddingFunction`），
  或明确接受纯滑窗并把 `recent_turns` 纳入成本预算（见 B3）。

## 3. 前缀缓存稳定性（bench_tokens + 世界书纪律验证 + 真实 API 探针）

### 3.1 分层注入 token 节省（bench_tokens）

76 篇目录文档：全量注入 37206 tokens vs 分层注入 10151 tokens → **节省 72.7%**。

### 3.2 世界书注入纪律验证（合成书 5 条混合条目）

| 检查项 | 结果 |
|---|---|
| V1 常驻 position=0 → 稳定层（before） | ✅ |
| V2 触发型 position=0 → 动态层（after） | ✅ |
| V3 常驻 position=1 → 动态层（卡后） | ✅ |
| V4 稳定层跨 5 轮不同触发组合逐字节不变（sha1 全等） | ✅ |
| V5 条目顺序打乱 ×5 → 注入输出确定性一致 | ✅ |
| V6 真实默认书稳定层跨输入不变 | ✅（但恒为空字符串，见下） |

`format_injection` 的分层纪律与排序确定性实现正确。

### 3.3 真实 API 前缀缓存命中探针（DeepSeek usage 字段实测）

| 调用 | cache_hit | cache_miss | 结论 |
|---|---|---|---|
| A 首次（冷） | 0 | 1014 | — |
| B 完全相同 | **768** | 246 | 命中 75.7%（64-token 块粒度，尾部零头不命中） |
| C 尾部追加动态内容 | **768** | 252 | **动态层在末尾，前缀命中保持** |
| D 头部插入变化内容 | **0** | 1031 | **前缀缓存整体崩塌** |
| E 头部内容再增长 | **0** | 1044 | 持续归零 |

### 3.4 两个架空前缀缓存的现实因素

1. **稳定层为空**：生产默认书 `arknights` 22 条启用条目**全部是触发型 position=1**
   （常驻 position=0 条目 = 0）。稳定层字节数恒为 0，样本触发 6 条即产生 **6808 tokens** 动态注入。
   世界书对前缀缓存的贡献当前为零；可评估把真正的全局设定（无关键词常驻条目）标记为常驻 position=0。
2. **装配顺序断裂**（代码级发现）：`SceneManager._build_messages` 的 `ref_parts` 中，
   每轮增长的 `plot_state.md` / `plot_log.md`（L800-806）排在 `wb_before`（L828-829）**之前**。
   探针 D/E 证明：前缀中任何靠前位置的变化会使其后全部内容的缓存命中归零——
   **即使世界书有常驻条目，plot_log 每轮增长也会让紧随其后的稳定层缓存失效**。
   修复方向：把 `plot_state/plot_log` 移到动态段（`<conversation_history>` 附近），
   让所有逐轮可变内容集中在稳定前缀之后。可用 `load_llm.py` 的 fingerprint 日志线上回归验证。

## 4. CombatView 拆解优先级的数据输入

### 4.1 体量实测（纠正文档失准）

| 文件 | 行数 | 字节 |
|---|---|---|
| `components/combat/CombatView.tsx` | 1804 | **77 KB**（全仓最大单文件组件） |
| `components/ChatPanel.tsx` | 1334 | 60 KB（同量级） |
| `components/combat/` 全目录 | 5649 | — |

AGENTS.md 称 CombatView「50k+ LOC」**失准**（实为 ~77KB / 1804 行；50k 疑为字节数的误写）。
纯体量并未显著失控，但职责密度高：28 个 `useState`、7 个 `useEffect`、~30 个 `useCallback`，
单组件承担 SSE 连接与状态同步、战斗流程（开始/结束/结算/重试）、卡牌飞行动画、
伤害数字、粒子发射器、拖拽瞄准、hover  tooltip、卡组查看、音频、全屏。

### 4.2 战斗链路的性能/可靠性现状

- **战斗入口可靠性瓶颈在 LLM 提取协议，不在 UI**：`results_combat_experiments.json` 显示
  原提示词战斗触发召回 0.75，失败分类为 empty / json-null-combat（提取输出为空或标记缺失）。
  CombatView 拆解解决不了入口可靠性。
- **流式渲染 per-token setState 仍在**（8 月 P2 未修）：`ChatPanel.tsx` 的 `onReasoning`
  每个 token 全量重建消息数组（`[...prev.slice(0, -1), {...last}]`），无 rAF 批处理、无 memo。
  战斗 SSE 事件驱动更新同构存在（事件→setState→整树重渲染）。
- 战斗页自身在皮肤系统中已被 `@scope ... to (.bg-combat-bg)` 隔离，UI 侧无换肤耦合债务。

### 4.3 拆解优先级结论

**CombatView 拆解的 ROI 低于 B1–B4，建议排在其后。** 理由：
B1（语义记忆）是功能缺失、B2（前缀缓存）每轮都在烧钱且有实测数据、B4（渲染批处理）
直接改善每一次流式输出；CombatView 是架构债而非实测延迟热点。
若启动拆解，建议按职责切四块（均为现有代码的直接搬迁，风险递增排序）：

1. `useCombatSSE`（SSE 连接/事件累积/fetchState 同步）
2. `CombatAnimationLayer`（cardFlight / damageNumbers / particleEmitters）
3. `CombatFlowController`（start/end/settlement/retry/escape 流程）
4. `CombatInteractionHandler`（拖拽/瞄准/hover/点击路由）

## 5. 建议行动（按 ROI 排序）

| 优先级 | 事项 | 预期收益 | 实测依据 |
|---|---|---|---|
| P0 | 接线本地 ONNX 嵌入（或明确放弃语义检索并收紧 recent_turns） | 恢复远期记忆能力；+270ms/轮成本 | §2.2/§2.4 |
| P0 | `plot_state/plot_log` 移到动态段，修复装配顺序 | 稳定前缀跨轮可缓存；命中 0→75%+ | §3.3/§3.4 |
| P1 | 世界书：全局设定改常驻 position=0；设 `budget_tokens` 上限 | 稳定层非空 + 动态尾封顶 | §3.4 |
| P1 | 前端流式渲染批处理（rAF/150ms 合并 setState + 消息行 memo） | 消除 per-token 全树重渲染 | §4.2 |
| P2 | CombatView 按 §4.3 四块拆解 | 可维护性（非延迟热点） | §4.1 |

## 6. 复现

```bash
# 基准（各脚本均为只读或写自身 results，本轮在隔离 worktree 运行）
python perf_tests/bench_stream_verify.py     # ×3 轮，见 §1
python perf_tests/bench_memory_recall.py     # 见 §2.1
python perf_tests/bench_tokens.py            # 见 §3.1
# 探针（临时脚本，未入库；方法已内嵌于本报告数据表）
# - ChromaDB 分规模延迟/窗口成本：ONNX 嵌入 + VectorMemory，10/50/100/200 docs
# - 前缀缓存命中：真实 API 5 调用序列（冷/相同/尾增/头插/头增），读 usage.prompt_cache_hit_tokens
```

测量日期：2026-09-12；API 侧延迟受网络与服务端负载影响，供相对比较，绝对值以同条件复测为准。
