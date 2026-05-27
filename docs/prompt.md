一、已被研究证实的 “强遵循” 格式（按效果强度排序）
1）XML/HTML 标签分区（最强、最稳）
论文：Microsoft/MIT（2024）、Anthropic（2023）
把 Prompt 拆成角色、任务、规则、工具、输出格式、示例六大块，每块用唯一标签包裹
实测：指令遵循率 +15%~25%，长上下文下遗忘率显著降低
为什么有效：LLM 对标签边界有天然 “分区注意力”，能区分指令 vs 数据 vs 示例，减少被用户输入 “伪指令” 带偏
xml
<role>
你是一个严谨的订单处理Agent，只执行订单相关操作，不闲聊。
</role>

<core_rules>
- MUST：先校验订单号格式（12位数字）
- MUST：金额必须>0
- NEVER：修改用户提供的商品ID
</core_rules>

<tools>
<tool name="query_order">参数：order_id(str)，返回：status/amount
</tool>

<output_format>
严格JSON：{"thought":"...","action":"...","result":"..."}
</output_format>
2）JSON Schema 强结构（机器级遵循）
论文：ICLR 2024、Microsoft（2024）
直接给严格 JSON Schema，不是 “建议格式”
实测：在法律 / 合规类任务中，比 Markdown 高 42%；GPT-3.5 不同格式间最大差 40%
关键：禁止自由文本，所有字段必填、类型固定、枚举限定
json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["step", "action", "reason", "confidence"],
  "properties": {
    "step": {"type": "integer", "minimum": 1},
    "action": {"type": "string", "enum": ["query", "validate", "confirm", "reject"]},
    "reason": {"type": "string", "maxLength": 200},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  }
}
3）关键规则 “首尾放置”（对抗 Lost-in-the-Middle）
论文：UW/Allen Institute（2023）、Anthropic（2024）
最关键规则放最前 + 最后再重申；绝对不要埋在中间
实测：长上下文（>10k token）下，中间规则遗忘率 >60%；首尾重复可将召回率从 30%→85%
口诀：核心三句放开头，禁忌三句放结尾，中间只放流程与细节
4）ReAct 思维链（强制 “先思考再行动”）
论文：Google DeepMind（2022）、Anthropic（2023）
强制输出：Thought → Action → Observation
实测：工具调用错误率 -50%，多步任务完成率 +42%
模板：
plaintext
你必须严格按以下格式输出：
Thought：[你的推理过程，为什么这么做]
Action：[调用哪个工具+参数]
Observation：[工具返回结果，无需你生成]
5）正向命令式语言（MUST/ALWAYS/NEVER）
论文：Prompt Engineering Guide（2024）、OpenAI（2023）
用强动词：MUST、ALWAYS、NEVER、STRICTLY、FORBIDDEN
避免弱词：try、consider、please、you may
避免纯负面：不说 “不要错”，说 “必须准确”
实测：规则遵守率 +20%，歧义减少
6）少样本示例（2–3 个，结构化）
论文：ICLR 2024、Microsoft（2024）
给2–3 个完整成功案例，用和输出一致的格式
不要放错误示例（易被模仿）
示例放在规则后、输出格式前
二、优先级排序（写 Prompt 时严格按此顺序）
1. 角色与核心身份（最前，1–2 句）
2. 绝对硬规则（MUST/NEVER，前 1/3，首尾重复）
3. 任务目标与流程（步骤化，清晰）
4. 工具定义（精确参数 + 示例）
5. 输出格式（JSON Schema/XML，强制）
6. 少样本示例（2–3 个，结构化）
7. 最终重申核心约束（最后一段，简短）
禁忌：不要把背景故事写太长（研究证明无效，反而稀释权重）