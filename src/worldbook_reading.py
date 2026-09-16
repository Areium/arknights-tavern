"""世界书依赖构建的**自适应选择性阅读**选择器（纯本地、确定性）。

问题：分析阶段（第一遍「读全文出分析卡」）要读整本书。262 条 / 73.3 万字符的书要发
50 个请求、约 71 万输入 token，而这些 token 里很大一部分是**复述型剧情正文**——
对「这条设定依赖哪条设定」的判断贡献很低。判定阶段的 batching 已经优化过一轮
（见 `worldbook-builder-performance.md`），本模块处理的是**第一遍分析的输入量**。

做法：**本地扫描整篇正文**（引用、结构、公式/表格特征全都在本地看到），然后只把
**选中的原始区段**送给模型。这是有意的取舍：

- 本地扫描仍是**全量**的：`collect_candidates` 依旧在整篇正文里找明确引用，
  候选对**一个都不会少**；判定阶段照旧能拿到引用附近的原文窗口。
- 模型只读**选中的区段**：短条目全读，长条目读「导语 + 定义段 + 依赖/否定限定语 +
  正文任意位置的代表性引用邻域」，并且**保留小标题目录**（带可信偏移量）以便
  模型知道还有哪些章节没读。
- 选不动就**保守回退全文**（规则/属性/公式/表格/外部章节引用等），而不是赌模型能猜。
- 读完之后还有**一次性补充**：卡片可以声明 `needs_more_context`，此时只补
  **尚未成功读过**的区段，已经成功读过的区段**绝不重发**。

诚实性要求（重要）：选择性阅读意味着**部分正文没有被模型看到**。因此
`coverage` 必须如实暴露（`partial` + 未读字符数 + 被省略的章节标题），
调用方**不得**在存在未读正文时宣称「全部依赖都已发现」。

本模块刻意**不导入** `worldbook_builder`：它只依赖标准库，可单独测试，
也不会与构建器形成循环依赖。切片一律来自原文、逐字保留，绝不拼接编造的省略号。
"""

import hashlib
import re

# 选择策略版本：参与自适应缓存的键。改动选择逻辑 / 预算常量必须递增，
# 否则「按旧策略选出来的跨度」会被当成新策略的缓存直接复用。
READING_POLICY_VERSION = "wb-reading-v1"

# 阅读模式
READING_MODE_ADAPTIVE = "adaptive"
READING_MODE_FULL = "full"
READING_MODES = (READING_MODE_ADAPTIVE, READING_MODE_FULL)
# 兼容直接调用 `run_build` 的旧调用方与测试：默认仍是「读全文」，
# 语义与改造前完全一致（见 `DependencyBuildJob.__init__`）。
READING_MODE_DEFAULT = READING_MODE_FULL

# ── 选择预算 ──
SHORT_ENTRY_CHARS = 1200        # ≤ 这个长度：全读（不值得为省几百字冒险漏掉限定语）
TARGET_SELECTED_CHARS = 1200    # 长条目的目标选中量（软上限，可被「必须包含」的区段撑破）
HARD_CAP_SELECTED_CHARS = 1600  # 硬上限：超出后不再追加「锦上添花」的区段
INTRO_CHARS = 240               # 导语：开头固定保留，定义条目的第一段通常在这里
QUALIFIER_NEIGHBOR_CHARS = 160  # 依赖/否定限定语命中点两侧各取多少字符
REFERENCE_NEIGHBOR_CHARS = 160  # 明确引用命中点两侧各取多少字符
OUTLINE_MAX_ITEMS = 40          # 目录最多列出几个小标题
OUTLINE_TITLE_CHARS = 60        # 单个小标题的字符上限
OUTLINE_MAX_CHARS = 900         # 目录整体的字符上限（超出按比例截断标题）
MAX_MIDDLE_TAIL_WINDOWS = 3     # 长正文「中部/尾部代表性窗口」最多几个（去重后）
MAX_PARAGRAPH_CHARS = 700       # 单个选中段落（定义段）的字符上限
REFERENCE_WINDOW_CHARS = 380    # 引用邻域的单窗口上限（引用要看到上下文，不需要整块档案）
SNAP_FORWARD_CHARS = 80         # 边界吸附换行的最大距离（超出就不再找，绝不跳到文末）
TABLE_ROW_MIN = 3               # 到几行表格才算「表格密集」（回退全文的客观门槛）

# 长正文：超过这个长度且没有结构线索时，除导语外还要看中部与尾部的代表性窗口，
# 否则「只在开头出现的引用」会被误判成「这条没有依赖」。
LONG_PROSE_CHARS = 2400

# ── 内容线索（客观、可解释，不做语义猜测）──
# 依赖/否定/限定语：这些词决定「例外是否成立」。命中它们的段落若被选中窗口切断，
# 会丢掉「仅在 X 时 / 不需要 Y」这类限定，从而把关系判反，所以必须整段保留。
#
# 词表覆盖**真正会改变依赖结论**的结构化表达式。刻意不收录裸的「必须」「约束」
# 这类泛用词（角色设定叙事里到处都是，实测 180 条长条目 61 条命中，等于没优化）；
# 但**结构化形式必须抓到** —— `必须先`、`必须依照`、`必须理解`、`只有…才能`、
# `取决于`、`以…为前提`。这些是「这条要求先读另一条」的直接语言标记，
# 漏掉它们等于漏掉 golden 语料里的关键证据（见 `docs/worldbook-selective-reading.md`）。
QUALIFIER_TERMS = (
    # 显式依赖
    "依赖于", "依赖", "前提条件", "前提", "取决于", "以…为前提", "为基础", "依照",
    # 条件 / 例外 / 否定
    "仅当", "仅在", "除非", "否则", "不需要", "无需", "不得", "除外", "例外",
    # 必须类（只收结构化搭配，不收裸「必须」）
    "必须先", "必须先理解", "必须依照", "必须理解", "必须遵循", "必须参照",
    "必须先读", "必须先看", "必须先了解",
)
# 正则形式的限定结构：`只有…才能` / `以…为前提` / `必须…才能` / `除非…否则`。
QUALIFIER_STRUCTURE_PATTERN = re.compile(
    r"只有[^\n。；]{1,40}(?:才|方能|方能)"
    r"|以[^\n。；]{1,30}为前提"
    r"|(?:必须|需要)[^\n。；]{1,30}(?:才能|方可|之后才能)"
    r"|除非[^\n。；]{1,60}否则")
# 英文对应式（只在整词处匹配，避免 `must` 命中 `mustard` 之类噪声）。
QUALIFIER_PATTERN_EN = re.compile(
    r"\b(?:requires?|required|depends? on|dependent on|only if|unless|without"
    r"|must (?:first|follow|read|understand))\b", re.I)
# 复杂规则/属性条目：**公式 / 判定式 / 表格**才是可客观识别的信号。
# 这里刻意不用「系统 / 规则 / 数值 / 属性」这类普通词：它们在角色设定正文里同样常见，
# 用它们当回退条件会让 180 条长条目里 154 条直接回退全文，目标随之失去意义
# （见 `docs/worldbook-selective-reading.md` 的取舍说明）。
FORMULA_CUE_PATTERN = re.compile(
    r"(?:\broll\b|Roll点|骰|1d\d|d\d{1,2}\s*[+-]|\d+\s*d\s*\d+|概率\s*=|阈值\s*[=＝]|\d+\s*[%％]\s*的?\s*概率)",
    re.I)
# 结构性外键引用：指向**另一份语料文件**（`data/characters/`、`plots/*.md`、
# `scenes.md`）。这类引用是本地扫描的证据来源，但**不构成回退全文**的理由 ——
# 真正要看的是这些引用的**邻域**（已在 reference 区段里），而不是整条正文。
EXTERNAL_REF_PATTERN = re.compile(
    r"(?:参见|详见|见)\s*[^\s，。；]{0,40}?\.(?:md|json|yaml|yml|txt)"
    r"|(?:data/|assets/|plots/|scenes\.md|quests\.md)"
    r"|[\w./-]{2,60}\.(?:md|json|yaml|yml)"
)

# 小标题：markdown 标题，或「短行 + 全角冒号」的字段式小标题（与分块器同一套识别）。
_HEADING_PATTERN = re.compile(r"(?m)^[ \t]{0,3}(?:#{1,6}[ \t]+[^\n]*|[^\n：:]{1,30}[：:][ \t]*)$")
# 段落边界：空行（保留换行以便切片落在真实字符边界上）。
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n")
# 表格行
_TABLE_ROW = re.compile(r"(?m)^[ \t]{0,3}\|.*\|[ \t]*$")


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    """证据/引用比对用的宽松规范化（与 `worldbook_builder._norm` 同一口径）。"""
    return re.sub(r"\s+", "", text or "")


def _locate_all(text: str, needle: str) -> list[int]:
    """整篇正文里 needle 的所有出现位置（忽略空白的宽松命中）。

    与 `worldbook_builder._locate_span` 同一套匹配语义：先逐字，再忽略空白。
    只用来定位「引用邻域」的候选窗口，不改变候选对的认定。
    """
    text = text or ""
    needle = needle or ""
    if not text or not needle:
        return []
    starts = []
    start = text.find(needle)
    while start != -1:
        starts.append(start)
        start = text.find(needle, start + 1)
    if starts:
        return starts
    keys = [re.escape(ch) for ch in needle if not ch.isspace()]
    if not keys:
        return []
    return [match.start() for match in re.finditer(r"\s*".join(keys), text)]


class Span:
    """一段**原文**切片的稳定身份 + 选择理由。

    `span_id` 绑定 `正文 hash + 起止 + 策略版本`：正文任何位置改动、策略版本变更，
    或者起止位移，身份都会变，断点续跑因此不会张冠李戴（与分块 `chunk_id` 同一思路）。
    """

    __slots__ = ("start", "end", "reason", "span_id")

    def __init__(self, content: str, start: int, end: int, reason: str,
                 content_hash: str = None):
        self.start = int(start)
        self.end = int(end)
        self.reason = reason
        self.span_id = _span_id(content_hash if content_hash is not None else _sha(content),
                                self.start, self.end)

    @property
    def chars(self) -> int:
        return max(0, self.end - self.start)

    def to_dict(self) -> dict:
        return {"span_id": self.span_id, "start": self.start, "end": self.end,
                "reason": self.reason, "chars": self.chars}


def _span_id(content_hash: str, start: int, end: int) -> str:
    return f"{content_hash[:12]}:{start}:{end}:{READING_POLICY_VERSION}"


class ReadingSelection:
    """一条条目的阅读选择结果。

    `full=True` 表示走的是保守回退（读全文）；否则只读 `spans`。`spans` 一律是
    **互不重叠、按原文顺序**的原始切片集合，`text` 是它们的逐字拼接。
    """

    __slots__ = ("uid", "content_hash", "full", "spans", "reason", "outline",
                 "total_chars", "selected_chars", "rule_or_table_heavy",
                 "qualifier_uids")

    def __init__(self, uid: str, content: str, full: bool, spans: list, reason: str,
                 outline: list = None, content_hash: str = None,
                 rule_or_table_heavy: bool = False, qualifier_uids=None):
        self.uid = uid
        self.content_hash = content_hash if content_hash is not None else _sha(content)
        self.full = bool(full)
        self.spans = list(spans)
        self.reason = reason
        self.outline = list(outline or [])
        self.total_chars = len(content or "")
        self.selected_chars = (self.total_chars if self.full
                               else sum(span.chars for span in self.spans))
        # 这两项让**本地确定性线索**在补充阶段可用（不依赖模型自报）：
        # 规则/属性类条目、含依赖或否定限定语的条目，即使模型没要求补充上下文，
        # 也按保守口径补一轮「已读跨度的补集」。
        self.rule_or_table_heavy = bool(rule_or_table_heavy)
        self.qualifier_uids = list(qualifier_uids or [])

    @property
    def omitted_chars(self) -> int:
        return max(0, self.total_chars - self.selected_chars)

    @property
    def coverage(self) -> str:
        return "full" if self.full else "partial"

    @property
    def span_ids(self) -> list:
        return [span.span_id for span in self.spans]

    def unread_spans(self, content: str = "", chunk_chars: int = 1800,
                     max_spans: int = None) -> list:
        """**尚未被读过**的正文补集 —— 升级阅读要读的完整剩余部分。

        补集 = 已成功读到跨度的**逐字补集**，按原文顺序切成不超过
        `chunk_chars` 的连续切片（切片边界落在小标题/段落边界上更好读，
        但**绝不丢字**：所有未被读到的字符都会出现在某个切片里）。

        这不是「再抽样一次」：升级阅读的语义是**把剩下的读全**，因此这里
        不做均匀取样、不设窗口上限。真正的规模控制交给下游的
        `ExactPacker`（按请求预算装箱）与整批预算 —— 装不下就如实留在待办，
        不假装读过。已经成功读到的字符**绝不重发**。
        """
        if self.full or not content:
            return []
        total = len(content)
        read = [(span.start, span.end) for span in self.spans]
        gaps = []
        cursor = 0
        for start, end in sorted(read):
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < total:
            gaps.append((cursor, total))
        gaps = [(a, b) for a, b in gaps if b - a > 0]
        if not gaps:
            return []
        # 每个 gap 内部再按 chunk_chars 切开：保证单个单元不会撑爆请求预算，
        # 同时**不丢弃任何字符**（最后一片可以短于 chunk_chars）。
        pieces = []
        for start, end in gaps:
            position = start
            while position < end:
                step = min(chunk_chars, end - position)
                cut = position + step
                if cut < end:
                    cut = self._soft_cut(content, position, cut)
                if cut <= position:
                    cut = min(end, position + step)
                pieces.append((position, min(cut, end)))
                position = min(cut, end)
        spans = [Span(content, a, b, "supplement", content_hash=self.content_hash)
                 for a, b in pieces]
        if max_spans is not None:
            spans = spans[:max_spans]
        return spans

    def _soft_cut(self, content: str, start: int, cut: int) -> int:
        """把补集切片边界吸附到**附近**的段落/小标题边界（不切在句子中间）。

        找不到合适边界时返回原 `cut` —— 语义仍是「连续读下去」，
        只是切片尾巴可能落在句子中间，下游靠 `part` 标识拼接。
        """
        window = content[max(start, cut - 200):cut]
        for marker in ("\n\n", "\n#", "\n"):
            position = window.rfind(marker)
            if position > 0:
                candidate = max(start, cut - 200) + position + len(marker)
                if candidate > start:
                    return candidate
        return cut

    def to_dict(self, include_spans: bool = False) -> dict:
        data = {"uid": self.uid, "coverage": self.coverage, "reason": self.reason,
                "total_chars": self.total_chars, "selected_chars": self.selected_chars,
                "omitted_chars": self.omitted_chars,
                "span_count": 0 if self.full else len(self.spans),
                "outline": list(self.outline)}
        if include_spans:
            data["spans"] = [span.to_dict() for span in self.spans]
        return data


def slice_spans(content: str, spans) -> str:
    """把选中的跨度切片并**逐字**拼接（原文顺序，无编造省略号）。"""
    text = content or ""
    return "".join(text[span.start:span.end] for span in spans)


_HEADING_ONLY_RE = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+([^\n]*)$")
_FIELD_ONLY_RE = re.compile(r"(?m)^[ \t]*([^\n：:]{1,30})[：:][ \t]*$")


def _heading_matches(content: str) -> list:
    """所有小标题的 `(start, end, level, title)`，按出现顺序。"""
    found = []
    for match in _HEADING_ONLY_RE.finditer(content):
        title = match.group(1).strip()
        level = len(match.group(0)) - len(match.group(0).lstrip())
        found.append((match.start(), match.end(), match.group(0).count("#"), title))
    if not found:
        for match in _FIELD_ONLY_RE.finditer(content):
            found.append((match.start(), match.end(), 0, match.group(1).strip()))
    return found


def heading_offsets(content: str) -> list:
    """本条正文的标题偏移量表（自带可信偏移量，用于目录与段落边界）。"""
    return [start for start, _end, _level, _title in _heading_matches(content)]


def _paragraph_bounds(content: str) -> list:
    """正文的段落 `(start, end)` 列表：按空行切，同时在任何小标题处强制断开。

    切片必须落在真实字符边界上，且不能把一个小标题和它的正文混成一段。
    """
    text = content or ""
    if not text:
        return []
    cuts = {0, len(text)}
    for match in _PARAGRAPH_SPLIT.finditer(text):
        cuts.add(match.end())
    for start, end, _level, _title in _heading_matches(text):
        cuts.add(start)
        cuts.add(end)
    points = sorted(cuts)
    bounds = []
    for index in range(len(points) - 1):
        start, end = points[index], points[index + 1]
        if end > start and text[start:end].strip():
            bounds.append((start, end))
    return bounds


def _paragraph_at(bounds: list, position: int):
    """position 落在哪个段落里（找不到返回 None）。"""
    for start, end in bounds:
        if start <= position < end:
            return (start, end)
    return None


def _paragraph_for_window(bounds: list, start: int, end: int, max_chars: int,
                         complete: bool = False):
    """把一次命中的邻域**扩到完整段落**。

    扩到整段是有意的：依赖/否定限定语常常跨越「命中点两侧几十个字符」，
    只取窄窗口会把「仅在 X 时不需要 Y」切成「不需要 Y」，把结论判反。

    `complete=True`（限定语专用）时**永不裁剪**：段落多长就取多长。设计上
    「被预算切开的限定语段落 → 整条回退全文」，因为裁掉「除非…」「仅当…」
    的后半句会把例外变成无条件结论。参考邻域（`complete=False`）才允许按
    `max_chars` 收窄 —— 引用邻域只是「看一眼引用附近」，不是语义限定。
    """
    a, b = start, end
    for p_start, p_end in bounds:
        if p_start <= start < p_end:
            a = p_start
        if p_start < end <= p_end:
            b = p_end
    if complete or b - a <= max_chars:
        return (a, b)
    center = (start + end) // 2
    half = max(0, max_chars // 2)
    a = max(a, min(center - half, max(0, b - max_chars)))
    b = min(b, a + max_chars)
    return (a, b)


def _merge_intervals(intervals: list) -> list:
    """合并重叠/相邻区间，保持原文顺序。不做截断（截断需按「理由优先级」决定）。"""
    if not intervals:
        return []
    ordered = sorted((int(a), int(b)) for a, b in intervals if b > a)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


# 区段的「保留优先级」：数值越小越先保留。
# 顺序即取舍逻辑：导语与限定语（例外）不可省 → 定义句 → 引用邻域 → 中部/尾部补样。
_REASON_PRIORITY = {"intro": 0, "qualifier": 1, "definition": 2,
                    "reference": 3, "middle_tail": 4, "context": 5}


def _enforce_cap(candidates: list, cap: int) -> tuple:
    """把候选区段裁到硬上限内，**按理由优先级从低到高丢弃**。

    返回 `(保留的 (start,end,reason) 列表, 是否丢弃过任何区段)`。

    预算是按**并集长度**（互相重叠的部分只算一次）核算的，不是把各候选长度相加：
    导语与限定语、限定语与引用邻域本来就常重叠，按和相加会虚增占用、无谓地
    触发回退（把本来装得下的条目推去读全文，反而更贵）。

    取舍顺序是**按理由优先级**，不是按位置：从尾部截会把限定语段落剥掉，
    从而把「仅在 X 时」变成无条件依赖 —— 那正是设计里明令禁止的。
    因此先丢「中部/尾部补样」，再丢引用邻域，最后才动定义句；
    导语与限定语永不丢弃（若连它们都放不下，调用方按设计回退全文）。
    """
    kept = [item for item in candidates if item[1] > item[0]]
    if _union_length(kept) <= cap:
        return kept, False
    # 优先级低者先丢；同优先级保持原文顺序（稳定，结果确定）。
    order = sorted(range(len(kept)),
                   key=lambda index: (_REASON_PRIORITY.get(kept[index][2], 9),
                                      kept[index][0]))
    dropped_indexes, drop = set(), False
    for index in order:
        if _union_length([item for i, item in enumerate(kept)
                          if i not in dropped_indexes]) <= cap:
            break
        if kept[index][2] in ("intro", "qualifier"):
            continue          # 不可省：宁可整体回退全文，也不裁掉例外
        dropped_indexes.add(index)
        drop = True
    kept = [item for index, item in enumerate(kept) if index not in dropped_indexes]
    return sorted(kept, key=lambda item: item[0]), drop


def _union_length(intervals: list) -> int:
    """区间的**并集**长度（重叠只算一次）。接受 `(start, end)` 或 `(start, end, …)`。"""
    pairs = [(item[0], item[1]) for item in intervals]
    return sum(b - a for a, b in _merge_intervals(pairs))


def _truncate_outline(outline: list) -> list:
    """目录整体超长时按比例截断标题（不丢条目，只是每条更短）。"""
    if not outline:
        return []
    total = sum(len(item["title"]) + 8 for item in outline)
    width = OUTLINE_TITLE_CHARS
    if total > OUTLINE_MAX_CHARS:
        width = max(12, int(OUTLINE_TITLE_CHARS * OUTLINE_MAX_CHARS / total))
    return [{**item, "title": item["title"][:width]} for item in outline]


# 规则 / 属性类条目的**显式**分类线索（uid 前缀、category_id、名称后缀）。
# 这是设计里的独立回退条件，不依赖「正则恰好命中公式」：一个规则条目即使正文
# 里没有 `Roll点` 这类式子，只要它被明确分类为规则/属性/职业/敌人数值，
# 就按「复杂规则/属性」保守回退全文。分类线索必须是白名单匹配，识别不出不分类。
RULE_UID_PREFIXES = (
    "rules_", "rule_", "classes_", "class_", "enemies_", "enemy_",
    "attributes_", "attribute_", "stats_", "static_", "mechanics_", "systems_",
)
# 名称后缀（与 `worldbook_builder._ENTITY_NAME_SUFFIXES` 同一套受控后缀口径）。
RULE_NAME_SUFFIXES = ("规则设定", "属性设定", "数值设定", "系统设定", "机制设定",
                      "职业设定", "敌人设定", "模板")
RULE_CATEGORY_HINTS = {"rules", "rule", "mechanics", "attributes", "stats",
                       "classes", "systems", "enemies", "enemy"}


def _rule_category_hint(uid: str, category: str = "") -> bool:
    """UID 前缀 / 分类 id / 名称后缀是否明确指向「规则·属性·数值」类条目。"""
    text = str(uid or "").strip()
    lowered = text.lower()
    if lowered.startswith(RULE_UID_PREFIXES):
        return True
    if str(category or "").strip().lower() in RULE_CATEGORY_HINTS:
        return True
    if text.endswith(RULE_NAME_SUFFIXES):
        return True
    match = re.search(r"[（(]([^（）()]{1,12})[）)]\s*$", text)
    return bool(match and match.group(1).strip() in RULE_NAME_SUFFIXES)


def _is_rule_or_table_heavy(content: str, uid: str = "", category: str = "") -> bool:
    """复杂规则/属性条目 → 保守回退全文。

    **两个独立理由，任一成立即回退**（对应设计里的两条要求）：

    1. **显式分类线索**（`_rule_category_hint`）：uid 前缀 / category / 名称后缀
       明确指出这是规则、属性、职业、敌人数值类条目。这是设计要求的类别回退，
       不依赖正则是否恰好匹配到公式。
    2. **内容线索**：表格行 ≥ `TABLE_ROW_MIN`，或命中可正则化的公式/判定式。

    两者都**不含**「正文提到别的语料文件」：那是引用邻域该覆盖的事，
    也不是「系统 / 规则 / 数值」这类泛用词，否则绝大多数角色设定都会回退。
    """
    if _rule_category_hint(uid, category):
        return True
    text = content or ""
    if not text:
        return False
    if len(_TABLE_ROW.findall(text)) >= TABLE_ROW_MIN:
        return True
    return bool(FORMULA_CUE_PATTERN.search(text))


def _qualifier_hits(content: str) -> list:
    text = content or ""
    hits = [(start, start + len(term), term)
            for term in QUALIFIER_TERMS
            for start in _locate_all(text, term)]
    hits.extend((match.start(), match.end(), match.group(0))
                for match in QUALIFIER_STRUCTURE_PATTERN.finditer(text))
    hits.extend((match.start(), match.end(), match.group(0))
                for match in QUALIFIER_PATTERN_EN.finditer(text))
    return hits


def select_spans(content: str, reference_terms=None, uid: str = "",
                 content_hash: str = None, category: str = "") -> ReadingSelection:
    """为一条条目选择要读的原文区段（**确定性、纯本地**）。

    规则（顺序固定，任意一次运行结果相同）：

    1. 空正文 / 短条目（≤ `SHORT_ENTRY_CHARS`）→ 全读。
    2. 复杂规则 / 属性 / 公式 / 表格 / 规则类分类 → 保守回退全读。
    3. 否则（长条目）：
       - 导语（开头 `INTRO_CHARS`）；
       - 含定义句（「X 是/指/表示…」）的段落；
       - 含依赖/否定/限定语的段落：**整段保留、永不裁剪**（命中被窗口切断 →
         回退全文，绝不剥掉例外）；
       - **正文任意位置**（含中部与尾部）的明确引用邻域，抽样后取代表；
       - 长无结构正文额外补中部/尾部代表性窗口；
       - 小标题目录（带偏移量）——目录本身告知模型还有哪些章节没读。
    4. 合并重叠、保持原文顺序、硬上限按**并集**核算（超出时按理由优先级丢弃补样）。

    `reference_terms` 是本地扫描得到的明确引用词（名称 / UID / 别名，
    即候选对里的 `matched`）。**候选对本身不受本函数影响**：即便某个引用
    没有落在选中区段里，`collect_candidates` 也照样产出该候选对，
    判定阶段仍会拿到引用附近的原文窗口。
    """
    text = content or ""
    if not text:
        return ReadingSelection(uid, text, True, [], "empty", content_hash=content_hash)
    if len(text) <= SHORT_ENTRY_CHARS:
        return ReadingSelection(uid, text, True, [], "short_entry", content_hash=content_hash)
    if _is_rule_or_table_heavy(text, uid, category):
        return ReadingSelection(uid, text, True, [], "rule_or_table_content",
                                content_hash=content_hash, rule_or_table_heavy=True)

    bounds = _paragraph_bounds(text)
    candidates = []          # (start, end, reason)
    must_keep = []           # 必须在硬上限之前保留的区段（导语 / 限定语所在段）

    intro_end = _intro_end(text)
    candidates.append((0, intro_end, "intro"))
    must_keep.append((0, intro_end))

    # 定义句：这条自身解释了什么（判定 requires 的主要来源）。
    for start, end in bounds:
        segment = text[start:end]
        if _DEFINITION_RE.search(segment):
            a, b = start, min(end, start + MAX_PARAGRAPH_CHARS)
            candidates.append((a, b, "definition"))
            break

    # 依赖 / 否定 / 限定语：只出现在中后部的也必须保留（否则例外被剥离）。
    # **整段取，不裁剪** —— 裁掉「除非…」「仅当…」的后半句会把例外读成无条件。
    qualifier_terms_hit = []
    for start, end, _term in _qualifier_hits(text):
        a, b = _paragraph_for_window(bounds, start, end, MAX_PARAGRAPH_CHARS,
                                     complete=True)
        candidates.append((a, b, "qualifier"))
        must_keep.append((a, b))
        qualifier_terms_hit.append((a, b))

    # 明确引用邻域：**从任意位置**取（中部 / 尾部都算）。先在**未合并**的窗口上
    # 抽代表，再合并 —— 先合并会把相邻命中连成整条正文，抽样就无从下手了。
    raw_windows = []
    for term in sorted({_norm(term) for term in (reference_terms or []) if term}):
        for start in _locate_all(text, term):
            a, b = _paragraph_for_window(bounds, start, start + len(term),
                                         MAX_PARAGRAPH_CHARS)
            a = min(a, start)
            b = max(b, start + len(term))
            # 引用邻域只需要「引用出现处的上下文」，不需要整个 700 字档案块：
            # 按命中点居中收窄到 REFERENCE_WINDOW_CHARS，再向两侧补邻居字符。
            if b - a > REFERENCE_WINDOW_CHARS:
                center = (start + start + len(term)) // 2
                half = REFERENCE_WINDOW_CHARS // 2
                a = max(a, center - half)
                b = min(b, a + REFERENCE_WINDOW_CHARS)
            raw_windows.append((max(0, a - REFERENCE_NEIGHBOR_CHARS),
                                min(len(text), b + REFERENCE_NEIGHBOR_CHARS)))
    intro_cut = intro_end
    for a, b in _merge_intervals(_thin_windows(raw_windows, intro_cut)):
        # 跨越导语边界的窗口：导语已经覆盖到 `intro_cut`，这里只补它之后的部分，
        # 避免「引用恰好在导语末尾」把窗口拉成 Intro + 整段（那会白吃预算）。
        start = max(a, intro_cut)
        if b > start:
            candidates.append((start, b, "reference"))

    # 长无结构正文：中部 / 尾部代表性窗口（用段落边界切，避免切在词中间）。
    if len(text) > LONG_PROSE_CHARS:
        for a, b in _middle_tail_windows(bounds, text):
            candidates.append((a, b, "middle_tail"))

    outline = _truncate_outline([{"offset": start, "level": level, "title": title}
                                 for start, _end, level, title in _heading_matches(text)]
                                [:OUTLINE_MAX_ITEMS])

    # 按「理由优先级」裁到硬上限：丢的是补样，绝不会是限定语或导语。
    kept, dropped = _enforce_cap(candidates, HARD_CAP_SELECTED_CHARS)
    selected_pairs = _merge_intervals([(a, b) for a, b, _ in kept])
    if not selected_pairs:
        return ReadingSelection(uid, text, True, [], "no_selection",
                                content_hash=content_hash)
    if not _qualifiers_covered(text, must_keep, selected_pairs):
        # 限定语段落被裁掉（或与其它区段合并后被切断）：例外会丢失 → 回退全文。
        return ReadingSelection(uid, text, True, [], "qualifier_cut_by_cap",
                                content_hash=content_hash)
    total_selected = sum(b - a for a, b in selected_pairs)
    if not dropped and total_selected > TARGET_SELECTED_CHARS * 2:
        # 没有可丢的补样却仍然远超目标：这条几乎「必须全读」。与其读一半，
        # 不如读全文，免得模型拿着七零八落的片段给出错误结论。
        return ReadingSelection(uid, text, True, [], "excessive_selection",
                                content_hash=content_hash)
    if total_selected > HARD_CAP_SELECTED_CHARS:
        # 硬上限不可突破（合并后可能比候选总和更小，但绝不会更大）。
        return ReadingSelection(uid, text, True, [], "over_hard_cap",
                                content_hash=content_hash)

    spans = [Span(text, a, b, _span_reason(kept, a, b),
                  content_hash=content_hash or _sha(text))
             for a, b in selected_pairs]
    return ReadingSelection(uid, text, False, spans,
                            "selected", outline=outline,
                            content_hash=content_hash,
                            rule_or_table_heavy=_is_rule_or_table_heavy(text, uid, category),
                            qualifier_uids=qualifier_terms_hit)


_DEFINITION_RE = re.compile(
    r"(?:是指|指的是|指的是|是|指|表示|定义为)[^\n]{2,80}"
    r"|(?:^|\n)[^\n]{1,24}(?:是|指)[^\n]{2,60}")


def _intro_end(text: str, target: int = INTRO_CHARS) -> int:
    """导语结束位置：先按 `target` 取，再吸附到**目标附近**的换行。

    不能写成「找 target 之后的第一个换行」：正文若有一段长行（`【字段】` 档案、
    单段式角色简介、无空行的连续散文），那个换行可能在几千字符之外，导语就会
    一口气吞掉整条正文（实测常见：整条 2400 字的角色条目只因为「下一个换行在
    结尾」而全读）。这里把吸附范围限制在 `target` 附近一小段内，越界就保持
    `target` 本身 —— 结构化程度低的正文因此**仍然可以被选择性阅读**。
    """
    if target >= len(text):
        return len(text)
    nearby = text.find("\n", target)
    if 0 <= nearby <= target + SNAP_FORWARD_CHARS:
        return nearby
    return target


def _snap_forward(text: str, position: int) -> int:
    """把切片边界吸附到**附近**换行（不切在句子中间）。

    附近没有换行时返回 `position` 本身，**绝不**跳到文末：无结构长散文必须
    保持可选，否则「没有小标题」就等价于「整条必须全读」，优化在散文上归零。
    """
    if position >= len(text):
        return len(text)
    nearby = text.find("\n", position)
    if 0 <= nearby <= position + SNAP_FORWARD_CHARS:
        return nearby
    return position


def _span_reason(kept: list, start: int, end: int) -> str:
    """合并后的区段取一个代表性理由：包含它的候选里优先级最高的那个。"""
    covering = {reason for a, b, reason in kept if a <= start and end <= b and b > a}
    for name in sorted(covering, key=lambda item: _REASON_PRIORITY.get(item, 9)):
        return name
    return "context"


def _qualifiers_covered(text: str, must_keep: list, selected) -> bool:
    """限定语段落是否被**完整**保留（含该段落为空的退化情形）。

    注意合并：限定语段落可能与相邻区段合并成一个更大的区间，此时它仍是被完整
    覆盖的；只有「合并后仍被切掉一段」才算丢失。
    """
    for a, b in must_keep:
        if b <= a:
            continue
        covered = any(s <= a and b <= e for s, e in selected)
        if not covered:
            return False
    return True


def _interval_kept(interval, selected) -> bool:
    """该区段是否仍被完整保留在选中集合里（用于「限定语被裁掉 → 回退全文」判断）。"""
    a, b = interval
    for s, e in selected:
        if s <= a and b <= e:
            return True
    return False


def _thin_windows(windows: list, intro_end: int) -> list:
    """引用窗口的**代表**筛选：避免「每个别名命中都标记为必读」导致全书回退。

    这一步必须在**合并之前**做：合并会把相邻窗口连成一条长区间，之后再也分不开。
    输入是未合并的原始窗口列表，本函数先按窗口**中心**做均匀取样（覆盖头 / 中 / 尾），
    再用被选中的那几个窗口去合并。

    关于「被筛掉的窗口不是丢弃」：候选对仍由 `collect_candidates` 在整篇正文上
    产出，判定阶段照样会拿到引用附近（含中部 / 尾部）的原文窗口；
    这里省的只是**第一遍分析**里的重复输入。
    """
    outside = [item for item in windows if item[1] > intro_end]
    if not outside:
        return []
    ordered = sorted(outside)
    if len(ordered) <= MAX_MIDDLE_TAIL_WINDOWS:
        return ordered
    step = (len(ordered) - 1) / (MAX_MIDDLE_TAIL_WINDOWS - 1)
    picked, used = [], set()
    for index in range(MAX_MIDDLE_TAIL_WINDOWS):
        position = min(len(ordered) - 1, int(round(index * step)))
        if position not in used:
            used.add(position)
            picked.append(ordered[position])
    return picked


def _middle_tail_windows(bounds: list, text: str) -> list:
    """长无结构正文的中部 / 尾部窗口（最多两个，落在段落边界上）。"""
    total = len(text)
    if not bounds or total <= LONG_PROSE_CHARS:
        return []
    windows = []
    for fraction in (0.5, 0.85):
        target = int(total * fraction)
        best = min(bounds, key=lambda item: abs(item[0] - target))
        start, end = best
        end = min(end, start + MAX_PARAGRAPH_CHARS)
        windows.append((start, end))
    return _merge_intervals(windows)


def selection_cache_identity(selection: ReadingSelection) -> str:
    """自适应缓存的阅读策略指纹：策略版本 + 模式 + 正文 hash + 选中跨度身份。"""
    return _sha("|".join([
        READING_POLICY_VERSION,
        READING_MODE_ADAPTIVE,
        selection.content_hash,
        selection.coverage,
        ",".join(selection.span_ids),
    ]))


def build_reading_plan(entries, reference_terms_by_uid=None, mode: str = READING_MODE_ADAPTIVE,
                       content_hashes=None, categories=None) -> dict:
    """为整本书产出阅读计划：`uid -> ReadingSelection`。

    `mode == "full"` 时每条都全读（与改造前逐字一致），因此 FULL 模式可以完整复用
    既有的全量分析路径与缓存语义。`categories` 是 `uid -> category_id`，
    供「规则/属性类条目」的**显式分类回退**使用。
    """
    if mode not in READING_MODES:
        raise ValueError(f"未知的阅读模式：{mode!r}（只能是 {READING_MODES}）")
    selections = {}
    for entry in entries or []:
        uid = getattr(entry, "uid", "") or ""
        content = getattr(entry, "content", "") or ""
        content_hash = (content_hashes or {}).get(uid)
        if mode == READING_MODE_FULL:
            selections[uid] = ReadingSelection(uid, content, True, [], "full_mode",
                                               content_hash=content_hash)
            continue
        selections[uid] = select_spans(
            content, (reference_terms_by_uid or {}).get(uid), uid=uid,
            content_hash=content_hash, category=(categories or {}).get(uid, ""))
    return selections


def summarize_reading_plan(selections) -> dict:
    """紧凑的阅读报告（对外暴露；绝不在每次轮询里 dump 全部跨度表）。

    口径：`total_chars` 是全书正文字符；`selected_chars` 是**实际会读的原始字符**
    （重叠已合并，因此是去重后的量）；`omitted_chars` 是**没有被模型看到**的正文。
    区别 `selected_chars` 与真实发送 token：前者是正文字符，后者还含提示词与
    system 开销，两者不可混用（与 `worldbook-builder-performance.md` 的指标口径一致）。
    """
    values = list((selections or {}).values())
    total = sum(item.total_chars for item in values)
    selected = sum(item.selected_chars for item in values)
    partial = [item for item in values if not item.full]
    omitted = sum(item.omitted_chars for item in values)
    reasons = {}
    for item in values:
        reasons[item.reason] = reasons.get(item.reason, 0) + 1
    return {
        "reading_mode": READING_MODE_ADAPTIVE,
        "policy_version": READING_POLICY_VERSION,
        "entries": len(values),
        "total_chars": total,
        "selected_chars": selected,
        "omitted_chars": omitted,
        "partial_entries": len(partial),
        "full_entries": len(values) - len(partial),
        "coverage": "full" if not partial else "partial",
        "reasons": reasons,
        # 下面两项在补齐阶段才会变化，由构建器填充。
        "supplemented_entries": 0,
        "supplement_spans": 0,
    }
