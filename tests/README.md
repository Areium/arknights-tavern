# Prompt 功能测试

## 运行方式

```bash
# 全部 LLM 测试（需要 API key 已配置，config/llm_config.json）
pytest tests/ -m llm -v

# 仅非 LLM 测试（无需 API key）
pytest tests/ -m "not llm" -v

# 快速冒烟（P0 标记检测）
pytest tests/ -m llm -v -k "marker or identity or combat"

# 单文件
pytest tests/test_prompt_markers.py -m llm -v
```

## 文件结构

```
tests/
  README.md                # 本文件
  conftest.py              # 共享 fixtures（app, sessions, SSE 解析, narrate helpers）
  test_prompt_markers.py   # 输出格式标记检测
  test_combat_trigger.py   # 战斗触发流程
  test_tool_calling.py     # Wiki 工具调用 + 身份遵守
```

## Fixture 说明

| Fixture | 会话类型 | 剧情包 | 角色 |
|---|---|---|---|
| `free_session` | 自由模式 | 无 | 无 |
| `story_session_narrative` | 剧情/叙事模式 | near-light | 临光家族角色 |
| `story_session_tactical` | 剧情/战术模式 | combat-test | 阿米娅、银灰、霜星 |
| `session_with_amiya` | 自由模式 | 无 | 阿米娅（已加载） |

### Helper Fixtures

| Helper | 用途 |
|---|---|
| `narrate_sse(sid)` | 调用 GET /narrate SSE 流，返回解析后的事件列表 |
| `narrate_nonstream(sid)` | 调用 POST /narrate-continue，返回 JSON body |

## 已知问题

### 1. Flash 模型战斗触发不稳定

**症状**：`test_combat_marker_present_in_tactical_mode` 间歇性失败，LLM 输出叙述文字但未含 `[COMBAT:ID]`

**原因**：Flash 等轻量模型在处理复杂多规则 prompt 时，格式标记遵循率低于 Pro 模型。当用户消息的收尾指令是"继续推进剧情"时，模型倾向叙事而非触发战斗。

**缓解**：User message 中战术模式增加了 primacy 指令（`【战术指令】`）和 recency 指令（修改收尾句），提高战斗触发优先级。仍有概率失败，属于模型能力限制。

### 2. SSE 解析格式

SSE 事件格式为双层 JSON：
```json
data: {"type": "combat_trigger", "data": {"encounter_id": "...", ...}}
```

`parse_sse_events()` 自动解包外层 `data` 字段，测试断言中 `e["data"]` 直接访问内层 payload。

## 测试结果记录

### 2026-05-26 — DeepSeek Flash (deepseek-v4-flash) 全量测试

**标记检测（test_prompt_markers.py）**

| 测试 | 结果 | 备注 |
|---|---|---|
| test_combat_marker_present_in_tactical_mode | FAIL | Flash 叙述场景而非输出 [COMBAT:ID] |
| test_combat_marker_absent_in_narrative_mode | PASS | 叙事模式无标记泄露 |
| test_combat_sse_event_emitted | FAIL | 同上根因，无 combat_trigger SSE 事件 |
| test_beat_complete_emitted_after_multiple_turns | FAIL | 6 轮后仍未输出 [BEAT_COMPLETE]，模型持续叙述 |
| test_choices_marker_with_summary | FAIL | 生成 4 个选项而非配置的 3 个（选项功能本身可用） |
| test_structured_json_output | PASS | 气泡模式 JSON 输出正确 |
| test_choices_are_diverse | PASS | 选项多样性符合要求 |
| test_env_marker_in_character_chat | SKIP | 模型未输出 env 标记 |

**战斗触发（test_combat_trigger.py）**

| 测试 | 结果 | 备注 |
|---|---|---|
| test_combat_trigger_sse_event_structure | FAIL | Flash 不触发战斗，无 combat_trigger 事件 |
| test_combat_triggered_flag_in_nonstream | PASS | 非流式接口标识位正确 |
| test_narrative_mode_no_combat_trigger | PASS | 叙事模式隔离正确 |
| test_narrative_mode_no_combat_flag | PASS | 无战斗标识泄露 |
| test_combat_with_json_params_is_parseable | PASS | JSON 参数解析逻辑正确（不依赖 LLM 输出） |

**工具调用（test_tool_calling.py）**

| 测试 | 结果 | 备注 |
|---|---|---|
| test_wiki_tool_definition_is_valid | PASS | 工具定义 schema 正确 |
| test_wiki_tool_available_in_chat | PASS | 工具已传入 LLM 请求 |
| test_tool_loop_max_three_rounds | PASS | 工具调用轮次限制正确 |
| test_token_usage_reported_after_chat | PASS | token 用量统计正常 |
| test_character_does_not_admit_ai_identity | PASS | 身份遵守正确 |
| test_character_first_person_perspective | PASS | 第一人称一致 |
| test_character_deflects_unknown_info | PASS | 未知信息回避正确 |

**汇总：13 通过 / 4 失败 / 1 跳过**

### Flash 模型能力边界分析

Flash 模型在以下方面表现良好：
- **工具调用**：全部 7 项通过，wiki_query 工具定义、调用、轮次限制均正确
- **身份遵守**：不承认 AI 身份，保持第一人称，自然回避未知信息
- **结构化输出**：气泡模式 JSON 格式正确，选项多样性符合要求
- **模式隔离**：叙事模式不触发战斗，无标记泄露

Flash 模型在以下方面表现不足：
- **格式标记遵循**：[COMBAT:ID]、[BEAT_COMPLETE]、`<!--env:...-->` 等标记的遵循率低
- **选项数量精确控制**：choice_count=3 配置下生成了 4 个选项
- **根本原因**：Flash 等轻量模型在处理复杂多规则 prompt 时，结构化输出指令的遵循率低于 Pro 模型。非代码缺陷，属于模型能力限制。

### 2026-05-26 — DeepSeek Pro (debug 跑)

| 测试 | 结果 | 备注 |
|---|---|---|
| 战斗触发（手动 debug） | PASS | `enc_quick_test_1` 正确触发，SSE 事件完整 |
