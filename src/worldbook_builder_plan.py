"""世界书依赖构建的**确定性请求规划器**。

这个模块只做一件事：把「要问模型的单元」打包成「实际会被发出的请求」，
让**估算**与**执行**共用同一条代码路径，而不是各写一套除法。

为什么需要它：旧实现用固定批量（分析 6 个分块 / 判定 8 对），批量再大也不会
拆分、再小也不会合并，于是出现两种浪费 ——
1. 判定请求把「整个相关章节」重复发给几十个候选对（单请求 3.2 万 token）；
2. 分块数量刚好卡在批次边界时留下半空批次。

现在的规则是**按真实渲染结果装箱**，不是按近似开销算术：

- 规划器不猜「一个单元大概多少 token」。它持有一个 `render(units) -> (text, payloads)`
  回调，**真正把候选批次渲染成请求正文**，再用 `estimate_tokens` 量它的长度。
  这样规划出的规模与真实请求逐字节一致，system 提示词、角色目录、渲染出的
  uid/名称/属性全部计入。
- 贪心装箱**保持来源顺序**（不排序、不打散）：同一来源的候选对连续排布，
  它们共享的条目上下文才可能被去重，也才能让「按来源分组」真正省 token。
- 只有「追加后**实际渲染**超出输入预算 / 输出预算 / 条数上限」时才切分。
- 单个单元本身就超预算时**不静默发送超限请求**：标记为 `oversized` 并由调用方
  决定（分析可安全再切分正文，判定则记结构化失败），绝不悄悄超预算。

本模块不导入 `worldbook_builder`，避免循环依赖；调用方把 `render` 回调传进来。
"""

# 判定请求里每条目的输出票额（模型要为这一对写多少字）。
PAIR_OUTPUT_TOKENS = 160


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 字符按 1 token，其余按 4 字符 1 token。

    与 `world_book.estimate_tokens` 逐字一致；这里复刻一份是为了让规划器
    单独可测、不引入对世界书模块的依赖。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + other // 4


class Unit:
    """一个待发送的单元。

    `key` 是稳定身份（分块的 `chunk_id`、候选对的 `(from_uid, to_uid)`），
    规划器只用它做去重与覆盖记账，**不**从它推断规模 —— 规模一律来自真实渲染。
    `payload` 是渲染该单元所需的数据（分块四元组 / 候选对字典）。
    """

    __slots__ = ("key", "payload")

    def __init__(self, key, payload=None):
        self.key = key
        self.payload = payload


class RequestPlan:
    """一次请求的打包结果：真正要发送的单元，以及**实测**的规模。"""

    __slots__ = ("units", "text", "input_tokens", "expected_output_tokens", "oversized")

    def __init__(self, units, text: str, input_tokens: int, expected_output_tokens: int,
                 oversized: bool = False):
        self.units = list(units)
        self.text = text
        self.input_tokens = int(input_tokens)
        self.expected_output_tokens = int(expected_output_tokens)
        self.oversized = bool(oversized)

    @property
    def keys(self) -> list:
        return [unit.key for unit in self.units]

    def to_dict(self) -> dict:
        return {"units": len(self.units), "input_tokens": self.input_tokens,
                "expected_output_tokens": self.expected_output_tokens,
                "oversized": self.oversized}


class ExactPacker:
    """按**真实渲染**贪心装箱。

    调用方提供：
    - `render(units) -> (text, payloads)`：把这一批单元渲染成实际请求正文；
    - `output_of(unit) -> int`：该单元的预期输出票额。

    其他约束：
    - `instruction_tokens`：system 提示词等**每次请求都付**的固定输入开销，
      必须显式传进来（旧实现漏了它，规划值因此系统性偏低）；
    - `input_budget` / `output_budget` / `max_units`：硬上限。

    贪心策略**按传入顺序**（调用方负责保持来源分组），只做「能不能追加」的判断，
    不重排：重排会打散来源、破坏上下文去重。
    """

    def __init__(self, render, instruction_tokens: int, input_budget: int,
                 output_budget: int, max_units: int, output_of=None):
        if input_budget <= 0 or output_budget <= 0 or max_units <= 0:
            raise ValueError("装箱参数必须为正数")
        self.render = render
        self.instruction_tokens = max(0, int(instruction_tokens))
        self.input_budget = int(input_budget)
        self.output_budget = int(output_budget)
        self.max_units = int(max_units)
        self.output_of = output_of or (lambda unit: 0)

    def plan(self, units) -> list[RequestPlan]:
        units = [unit for unit in units if unit is not None]
        plans, pending = [], []
        for unit in units:
            if not pending:
                pending = [unit]
                continue
            trial = pending + [unit]
            input_tokens, output_tokens = self._measure(trial)
            if (len(trial) > self.max_units
                    or output_tokens > self.output_budget
                    or input_tokens > self.input_budget):
                plans.append(self._finalize(pending))
                pending = [unit]
                continue
            pending = trial
        if pending:
            plans.append(self._finalize(pending))
        return plans

    def _measure(self, units) -> tuple[int, int]:
        """真实渲染这一批并量出 (输入 token, 预期输出 token)。"""
        text, _ = self.render(units)
        return (self.instruction_tokens + estimate_tokens(text),
                sum(self.output_of(unit) for unit in units))

    def _finalize(self, units) -> RequestPlan:
        text, _ = self.render(units)
        input_tokens = self.instruction_tokens + estimate_tokens(text)
        output_tokens = sum(self.output_of(unit) for unit in units)
        oversized = input_tokens > self.input_budget or output_tokens > self.output_budget
        return RequestPlan(units, text, input_tokens, output_tokens, oversized=oversized)


def plan_cost(plans) -> dict:
    """把打包结果折算成对外可展示的请求数 / 输入 token / 输出预算。

    数字直接来自 `RequestPlan` 的**实测**渲染长度，不再由调用方另算一套。
    """
    return {
        "requests": len(plans),
        "units": sum(len(plan.units) for plan in plans),
        "estimated_input_tokens": sum(plan.input_tokens for plan in plans),
        "expected_output_tokens": sum(plan.expected_output_tokens for plan in plans),
        "oversized_requests": sum(1 for plan in plans if plan.oversized),
    }


def packs_all_units(plans, units) -> bool:
    """覆盖性自检：每个单元恰好被规划一次（无丢件、无重复）。"""
    planned = [unit.key for plan in plans for unit in plan.units]
    return sorted(map(repr, planned)) == sorted(map(repr, [unit.key for unit in units]))
