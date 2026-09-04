# 一轮对话耗时分析与优化建议（实测报告）

> 测量时间：2026-08（perf_tests/bench_round_segments.py / bench_stream_verify.py / bench_effort_levels.py）
> 线上配置：`deepseek-v4-flash` @ api.deepseek.com，`enable_thinking=true`，`reasoning_effort=medium`，
> `auto_generate_choices=true (choice_count=3)`，`dialogue_bubble_mode=true`，`max_output_tokens=8192`，`word_limit=500`

## 1. 一轮对话的时间去哪了（剧情模式实测）

```
t=0            POST /api/sessions/<id>/narrate（SSE）
t≈0            hook（属性骰/预取）+ 消息构建          ~0 ms（纯本地）
t=0 → ~20.5s   Call 1 叙述生成（流式，但见根因 A）
               ├ thinking=medium：1.3k~4k reasoning tokens（占大头）
               └ 正文 ~550 字
t≈20.5s        前端一次性收到全部文本（见根因 A：伪流式）
t=20.5 → ~26s  Call 2 标记提取（选项/摘要/节拍/环境）  均值 5.3s（2~11s，偶发重试翻倍）
               → 选项按钮此时才出现
（每 5 轮）+~2.5s  Call 3 回忆生成（不阻塞阅读，后台）
─────────────────────────────────────────────────
合计：普通轮 ~26-31s；回忆轮 ~28-33s
```

### 分段实测数据

| 阶段 | 实测 | 备注 |
|---|---|---|
| A. 消息构建（SceneManager） | ~0 ms | 纯 Python，可忽略 |
| B. Call 1 叙述（thinking=medium） | **20.5–23.2 s** | reasoning 1.9k–3.1k chars；正文 553–566 字 |
| B'. Call 1 叙述（reasoning_effort=none，真流式） | **~3.0 s（首字 750 ms）** | 347 字；reasoning 0 |
| C. Call 2 提取（thinking=medium） | 3.9–8.0 s（均值 5.3） | choices=3 + beat_state |
| C'. Call 2 提取（effort=none） | 2.2–10.7 s（均值 5.9） | 全部一次成功，重试风险消失 |
| D. 回忆生成 | ~2.5 s | 每 memory_interval 轮一次 |
| E. embedding | 不可用（DeepSeek 无该端点） | 每次失败 ~125 ms，自由模式每轮 2 次 |

## 2. 根因（按感知延迟影响排序）

### A. 伪流式：httpx `client.post()` 全量缓冲（最大头）

`load_llm.py` 中 `ApiLLM.chat`/`LocalLLM.chat` 的流式路径：

```python
response = _post_with_retry(self.client, "/chat/completions", payload)  # ← 默认 stream=False！
for line in response.iter_lines(): ...                                   # ← 在本地缓冲区上迭代
```

httpx 的 `Client.post()` 会**先读完整个响应体**再返回 Response；`iter_lines()` 只是把已缓冲的 SSE 行逐条吐出。实测证据（bench_stream_verify）：

| 用法 | 首 chunk | 总时长 | chunk 到达分布 |
|---|---|---|---|
| `client.post()+iter_lines`（现状） | 7140 ms | 7140 ms | **一次性全部到达** |
| `client.stream()`（正确） | 531 ms | — | 真流式 |

后果：前端 SSE 链路（fetch + ReadableStream，本身是真流式）拿不到增量数据，
**用户在整个 Call 1 期间（20+ s）一个字都看不到**，然后文本"啪"地整段出现。
前端已经在渲染 reasoning 流（ChatPanel onReasoning），但后端根本没把增量推过去。

### B. 叙述调用的思考量过大且不可真正关闭

- `enable_thinking=true` → 每次调用带 `reasoning_effort=medium` → 叙述前先思考 1.3k~4k tokens（方差极大，实测有跑满 4096 tokens 全程无正文的情况）。
- 更隐蔽的坑：`enable_thinking=false` 时 adapter **不发送任何参数**，DeepSeek 混合模型缺省仍思考（实测 554 reasoning tokens、总时长 10.9 s）——"关闭"其实是没关。

| reasoning_effort | 首正文 | 总时长（300 字级叙述） | reasoning tokens |
|---|---|---|---|
| none | **750 ms** | **3.0 s** | 0 |
| low | 2.6 s | 5.6 s | 130 |
| 缺省（无参数） | 7.5 s | 10.9 s | 554 |
| medium（现状） | 7~50 s | 7~52 s | 1.3k~4k+ |

### C. Call 2 串行提取（+2~11 s，且选项按钮等它）

剧情模式 + 自动选项 → 每轮必有提取调用（`_should_extract_markers` 恒真）。
方差大（输出 186~1180 completion tokens），空/截断时还有一次**翻倍重试**（`extract_markers` 内置）。

### D. 自由模式 `CharacterAgent.chat` 非流式

`CharacterAgent.chat` 用 `stream=False`，拿到完整回复后逐字符回调"假装流式"；
且 wiki function calling 最多 3 轮，每轮都是一次完整非流式调用。自由模式整轮无任何增量输出。

### 次要（累计 <1 s）

- embedding 不可用仍每轮发起 2 次失败调用（~250 ms，`_embed_warned` 只压日志不短路）。
- 前端每个 token 触发一次 zustand 全消息列表 setState + `messages.map` 重渲染（无 memo）。
- `get_config()` 每次叙述读一次配置文件（~ms，可忽略）。

## 3. 优化建议（按 ROI 排序）

### P0-1 修复真流式（`client.stream()`）— 首字 20.5 s → ~0.7 s

`ApiLLM.chat` / `LocalLLM.chat` 流式路径改用 `client.stream("POST", ...)` 上下文管理器：
- 连接错误 / 429 / 5xx 仍可在拿到 status 后重试（保持 `_post_with_retry` 语义）；
- 400/422 的 stream_options 降级重发逻辑保持；
- 迭代中的 `ReadTimeout` 仍映射 `LLMTimeoutError`。
收益：即使思考开着，reasoning 流 ~0.5-1 s 内可见（前端已有渲染）；
正文按解码速度增量到达。感知体验质变，改动集中在 `load_llm.py` 一处。

### P0-2 按调用类型显式设置思考档位 — 叙述 20.5 s → ~3-6 s

deepseek adapter 在 `enable_thinking=False` 时**显式发送 `reasoning_effort: "none"`**（或等价参数），
并按调用类型配置：

| 调用 | 建议档位 | 理由 |
|---|---|---|
| Call 1 叙述 | none（保守可 low） | 创作任务，思考收益低、方差成本极高 |
| Call 2 提取 | none | 分类任务；none 下无截断重试（实测 4/4 一次成功） |
| Call 3 回忆 | none/low | 摘要任务 |
| 自由模式角色对话 | none/low | 同叙述 |

实现点：`llm_backend_manager.get_llm_for_endpoint` 按 endpoint 传参 →
改为按"调用用途"传参（可在 `chat()` 增加参数或构造多个轻量实例）。
配置面加一个「叙述思考档位」选项，而不是全局一个开关。

### P1-1 消除 Call 2：单调用协议（可选，收益 -4~11 s/轮）

把 choices/summary/beat/env 合并进 Call 1：要求模型在叙述正文结束后输出一个
分隔标记 + 单行 JSON（如 `<<<MARKERS>>>{...}`），后端流式解析、本地剥离显示。
失败时回退到现行 Call 2。收益：每轮少一次往返 + token 成本近半。
代价：prompt 复杂化、需要解析容错；建议先做 P0 再评估是否仍需要。

### P1-2 自由模式 CharacterAgent 真流式

`llm.chat` 修复流式后，把 `CharacterAgent.chat` 的无工具路径改为 `stream=True`
（tools 存在时保持非流式）；或流式 + 累积 tool_call deltas（OpenAI 支持流式工具调用）。
配合 wiki_prefetch 预注入，工具轮次本就罕见。

### P2（顺手项）

- embedding 短路：首次失败后标记端点不可用，跳过后续调用（自由模式 -250 ms/轮）。
- 前端 token 批量渲染：rAF/150ms 合并 setState，消息行 React.memo。
- 提取输出膨胀治理：给 choices/summary 加 few-shot 上限示例（实测输出 186~1180 tokens 波动是提取延迟方差主因）。
- `word_limit` 提供 300 字档（解码耗时与字数线性相关：~100 chars/s）。
- 前缀缓存：保持"稳定内容在前"的注入纪律（已有），观察 usage 的 cache_hit（实测 bench 为 0，真实会话内稳定前缀应>0，可用现有 fingerprint 日志验证）。

### 预期效果（P0 两项落地后）

| 指标 | 现状 | P0 后 |
|---|---|---|
| 首个可见输出 | 20.5–23.2 s | **~0.7–1 s** |
| 叙述文本完成 | 20.5–23.2 s | ~3–6 s |
| 选项出现 | ~26 s | ~5–11 s（通常在阅读中完成） |
| 一轮总时长 | 26–31 s | **~5–11 s** |

## 4. 测量工具

- `perf_tests/bench_round_segments.py` — 按线上配置分段计时（A–E）
- `perf_tests/bench_stream_verify.py` — 伪流式假设验证（`results_stream_verify.json`）
- `perf_tests/bench_effort_levels.py` — 思考档位对比（`results_effort_levels.json`）
- 注意：`bench_ttft.py` 经伪流式路径测量，其 ttft_ms 实为总时长，历史数据无效。


## 5. 实施结果（2026-08，分支 perf/round-latency-fix）

P0 两项 + P2 embed 短路已实施：

1. **真流式**：`load_llm.py` 的 ApiLLM/LocalLLM 流式路径改为 `httpx client.stream()`
   （新增 `_open_stream_with_retry`，保留连接错误/429/5xx 重试与 400/422 stream_options 降级）。
2. **按调用类型显式思考档位**：
   - 新增配置 `narration_reasoning_effort`（默认 `none`，设置页可选 none/low/medium/high），剧情叙述/变体/角色对话均透传该档位；
   - 标记提取（Call 2）、回忆生成、文档摘要批处理固定 `thinking="none"`；
   - `ApiLLM.chat` 新增 `thinking` 参数，调用级覆盖实例默认；
   - DeepSeek adapter 在 `enable_thinking=True + reasoning_effort="none"` 时显式发送 `reasoning_effort=none`，从而真正关闭混合模型的缺省思考（此前 `enable_thinking=false` 时不发参数，模型仍缺省思考 ~550 tok）。
3. **embedding 短路**：端点首次失败后不再重复发起注定失败的调用。

实测（真实 DeepSeek API，`deepseek-v4-flash`，200~310 字叙述）：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 叙述首字可见 | 20.5–23.2 s（伪流式，整段到达） | **~0.4–0.8 s** |
| 叙述总时长（thinking=none） | 20.5–23.2 s | **~2.7–3.5 s** |
| 标记提取（Call 2，none） | 3.9–8.0 s（medium） | **~1.2–2 s** |
| 提取空响应/截断重试 | 8%~42%（推理预算耗尽） | 未观测到（全 stop） |
| 自由模式 embedding 失败调用/轮 | 2 次网络请求 | 首次失败后 0 次 |
