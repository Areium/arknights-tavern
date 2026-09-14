"""按条目自带的可信元数据推断分类：只认显式信号，不按名字或正文猜测。

信号优先级（高 → 低）：

1. **uid 生成器前缀**：`characters_<角色目录名>_index` / `items_*` / `enemies_*` …
   内置生成器写出的 uid 前缀本身就是来源元数据，也顺带给出角色关联。
2. **group 字段**：整合包把酒馆的 group 当作类别使用；只在白名单取值内生效，
   取值范围外（`group1`、`always` 之类）一律忽略，不猜测外部书的用法。
3. **名称括号后缀**：`泰拉世界基础设定（世界观设定）` 这类写法。

三条信号在预装整合包里完全一致，可以互为交叉验证；互相矛盾的条目会被记进
`conflicts`，识别不出任何信号的条目保持未分类。分类只决定"条目属于哪一类"，
是否按需载入仍由 scope_mode 与分类的 scope_type 决定，本模块不改变载入模式。
"""

from dataclasses import dataclass, field
import re
from typing import Optional

from worldbook_scope import UNCLASSIFIED

WORLDVIEW = "worldview"
CHARACTER = "character"
OTHER = "other"

#: 分类 id 与 scope_type 是两个概念：分类 id 沿用既有 DEFAULT_CATEGORIES 的命名，
#: 便于与用户已保存的分类互换。
CHARACTER_CATEGORY = "characters"

#: 设定类分类统一挂在「世界观设定」下并继承 worldview 类型，这样「世界设定类条目
#: 在按需载入下始终作为候选」的既有语义不变，而界面上又能看到具体类别。
SETTING_PARENT_ID = "worldview"

#: 角色条目识别不出角色目录名时的落点：必须是 other，否则 _validate_entry_scope 会拒绝。
UNLINKED_CHARACTERS_ID = "characters_unlinked"

#: 内置生成器的类别表（顺序即展示顺序）。scope_type 与旧迁移保持一致：
#: 世界观/规则/属性/种族/职业/天气/地点 → worldview；角色 → character；其余 → other。
PRESET_CATEGORIES = [
    {"id": WORLDVIEW, "name": "世界观设定", "scope_type": WORLDVIEW, "parent_id": None, "sort_order": 10},
    {"id": "rules", "name": "规则设定", "scope_type": WORLDVIEW, "parent_id": SETTING_PARENT_ID, "sort_order": 11},
    {"id": "attributes", "name": "属性设定", "scope_type": WORLDVIEW, "parent_id": SETTING_PARENT_ID, "sort_order": 12},
    {"id": "races", "name": "种族设定", "scope_type": WORLDVIEW, "parent_id": SETTING_PARENT_ID, "sort_order": 13},
    {"id": "classes", "name": "职业设定", "scope_type": WORLDVIEW, "parent_id": SETTING_PARENT_ID, "sort_order": 14},
    {"id": "weather", "name": "天气设定", "scope_type": WORLDVIEW, "parent_id": SETTING_PARENT_ID, "sort_order": 15},
    {"id": "locations", "name": "地点设定", "scope_type": WORLDVIEW, "parent_id": SETTING_PARENT_ID, "sort_order": 16},
    {"id": CHARACTER_CATEGORY, "name": "角色设定", "scope_type": CHARACTER, "parent_id": None, "sort_order": 20},
    {"id": UNLINKED_CHARACTERS_ID, "name": "角色条目（未关联）", "scope_type": OTHER, "parent_id": None, "sort_order": 21},
    {"id": "items", "name": "物品设定", "scope_type": OTHER, "parent_id": None, "sort_order": 30},
    {"id": "enemies", "name": "敌人设定", "scope_type": OTHER, "parent_id": None, "sort_order": 31},
    {"id": "plots", "name": "剧情设定", "scope_type": OTHER, "parent_id": None, "sort_order": 32},
    {"id": "plot_graph", "name": "节点图", "scope_type": OTHER, "parent_id": None, "sort_order": 33},
]

_BY_ID = {c["id"]: c for c in PRESET_CATEGORIES}

#: uid 前缀 → 分类 id。长前缀在前，避免 plots_ / plot_ 这类互相吞并。
_UID_RULES = (
    ("plot_graph_", "plot_graph"),
    ("characters_", CHARACTER_CATEGORY),
    ("attributes_", "attributes"),
    ("enemies_", "enemies"),
    ("classes_", "classes"),
    ("weather_", "weather"),
    ("location_", "locations"),
    ("locations_", "locations"),
    ("world_", WORLDVIEW),
    ("rules_", "rules"),
    ("races_", "races"),
    ("items_", "items"),
    ("plots_", "plots"),
)

#: group / 名称后缀白名单。取值不在表内的 book 一律不分类，避免猜错外部书的 group 语义。
_LABEL_RULES = {
    "世界观": WORLDVIEW, "世界观设定": WORLDVIEW, "世界设定": WORLDVIEW, "world": WORLDVIEW, "worldview": WORLDVIEW,
    "规则": "rules", "规则设定": "rules", "rules": "rules",
    "属性": "attributes", "属性设定": "attributes", "attributes": "attributes",
    "种族": "races", "种族设定": "races", "races": "races",
    "职业": "classes", "职业设定": "classes", "classes": "classes",
    "天气": "weather", "天气设定": "weather", "weather": "weather",
    "地点": "locations", "地点设定": "locations", "location": "locations", "locations": "locations",
    "物品": "items", "物品设定": "items", "items": "items",
    "敌人": "enemies", "敌人设定": "enemies", "enemies": "enemies",
    "角色": CHARACTER_CATEGORY, "角色设定": CHARACTER_CATEGORY,
    "character": CHARACTER_CATEGORY, "characters": CHARACTER_CATEGORY,
    "剧情": "plots", "剧情设定": "plots", "plots": "plots", "plot": "plots",
    "节点图": "plot_graph", "节点图设定": "plot_graph",
}

_SIGNAL_ORDER = ("uid-prefix", "group", "name-suffix")
_SIGNAL_LABELS = {"uid-prefix": "uid 前缀", "group": "group 字段", "name-suffix": "名称后缀"}
_SUFFIX_RE = re.compile(r"[（(]([^（()）]{1,16})[)）]\s*$")


def signal_label(signal: str) -> str:
    return _SIGNAL_LABELS.get(signal, signal)


def character_id_from_uid(uid: str) -> Optional[str]:
    """`characters_<角色目录名>_index` → 角色目录名；不符合约定时返回 None。"""
    uid = str(uid or "")
    if not uid.startswith("characters_") or not uid.endswith("_index"):
        return None
    middle = uid[len("characters_"):-len("_index")]
    return middle or None


def _category_from_uid(uid: str) -> Optional[str]:
    lowered = str(uid or "").lower()
    for prefix, category_id in _UID_RULES:
        if lowered.startswith(prefix):
            return category_id
    return None


def _category_from_label(text: str) -> Optional[str]:
    key = str(text or "").strip()
    if key in _LABEL_RULES:
        return _LABEL_RULES[key]
    return _LABEL_RULES.get(key.lower())


def _category_from_name(name: str) -> Optional[str]:
    match = _SUFFIX_RE.search(str(name or ""))
    return _category_from_label(match.group(1)) if match else None


def entry_votes(uid: str, group: str = "", name: str = "") -> dict:
    """返回该条目各信号给出的分类投票；信号互相矛盾时调用方可用它提示用户。"""
    votes = {}
    category_id = _category_from_uid(uid)
    if category_id:
        votes["uid-prefix"] = category_id
    category_id = _category_from_label(group or "")
    if category_id:
        votes["group"] = category_id
    category_id = _category_from_name(name or "")
    if category_id:
        votes["name-suffix"] = category_id
    return votes


def classify_entry(uid: str, group: str = "", name: str = "", character_id: str = ""):
    """返回 (分类 id, 命中的信号列表, 投票明细)；无信号时分类为 None。"""
    votes = entry_votes(uid, group, name)
    if not votes:
        return None, [], {}
    for signal in _SIGNAL_ORDER:
        if signal in votes:
            chosen = votes[signal]
            # 角色分类必须带角色目录名，否则保存时会被 _validate_entry_scope 拒绝。
            if chosen == CHARACTER_CATEGORY and not (character_id_from_uid(uid) or character_id):
                chosen = UNLINKED_CHARACTERS_ID
            return chosen, list(votes), votes
    return None, [], {}


@dataclass
class ClassificationResult:
    """一次分类的完整结果；纯数据，可直接序列化给前端预览。"""

    assignments: dict = field(default_factory=dict)       # uid → 分类 id
    character_ids: dict = field(default_factory=dict)      # uid → 由 uid 约定推导的角色目录名
    evidence: dict = field(default_factory=dict)           # uid → 命中的信号列表（按优先级）
    votes: dict = field(default_factory=dict)              # uid → {信号: 分类 id}
    conflicts: dict = field(default_factory=dict)          # uid → {信号: 分类 id}，仅当信号矛盾
    uses: dict = field(default_factory=dict)               # 分类 id → 条目数
    unmatched: list = field(default_factory=list)          # 未识别出类别的 uid
    signals: dict = field(default_factory=dict)            # 信号 → 作为结论被采用的条目数

    @property
    def matched(self) -> int:
        return len(self.assignments)

    @property
    def total(self) -> int:
        return self.matched + len(self.unmatched)

    def categories(self, existing: Optional[list] = None) -> list:
        """给出建议写入的完整分类数组：只带有条目的分类，外加必要的父分类与未分类。

        传 existing 时，用户已手工改过名字/类型的分类会保留其名称与类型，只补条目归属。
        """
        kept = {c["id"]: dict(c) for c in (existing or []) if isinstance(c, dict) and c.get("id")}
        used = {cid for cid in self.uses if self.uses[cid] > 0}
        for cid in list(used):
            preset = _BY_ID.get(cid)
            if preset and preset.get("parent_id"):
                used.add(preset["parent_id"])
        result = []
        for category_id in sorted(used, key=lambda cid: _sort_key(cid, kept)):
            preset = _BY_ID.get(category_id)
            base = dict(preset) if preset else kept.get(category_id)
            if base is None:
                continue
            saved = kept.get(category_id)
            if saved:
                base["name"] = saved.get("name") or base["name"]
                base["scope_type"] = saved.get("scope_type") or base["scope_type"]
                base["sort_order"] = saved.get("sort_order", base["sort_order"])
            base["parent_id"] = base.get("parent_id")
            result.append(base)
        result.append(dict(UNCLASSIFIED))
        return result

    def to_payload(self, limit: int = 40) -> dict:
        """给接口/前端用的摘要；未识别与矛盾明细都截断，避免大书响应过大。"""
        return {
            "matched": self.matched,
            "unmatched_count": len(self.unmatched),
            "total": self.total,
            "signals": dict(self.signals),
            "categories": [
                {**_BY_ID.get(cid, {"id": cid, "name": cid, "scope_type": OTHER}), "count": count}
                for cid, count in sorted(self.uses.items(), key=lambda item: _sort_key(item[0], {})) if count
            ],
            "character_links": len(self.character_ids),
            "unmatched": self.unmatched[:limit],
            "conflicts": [{"uid": uid, "votes": dict(votes)} for uid, votes in list(self.conflicts.items())[:limit]],
            "unlinked_characters": [uid for uid, cid in self.assignments.items() if cid == UNLINKED_CHARACTERS_ID][:limit],
        }


def _sort_key(category_id: str, kept: dict) -> tuple:
    preset = _BY_ID.get(category_id) or kept.get(category_id) or {}
    return (int(preset.get("sort_order", 999)), category_id)


def classify_entries(entries) -> ClassificationResult:
    """对条目序列做一次分类；entries 需带 uid / group / name / character_id 属性。"""
    result = ClassificationResult()
    for entry in entries:
        uid = str(getattr(entry, "uid", "") or "")
        if not uid:
            continue
        votes = entry_votes(uid, getattr(entry, "group", ""), getattr(entry, "name", ""))
        category_id, signals, detail = classify_entry(
            uid, getattr(entry, "group", ""), getattr(entry, "name", ""),
            str(getattr(entry, "character_id", "") or ""))
        if category_id is None:
            result.unmatched.append(uid)
            continue
        result.assignments[uid] = category_id
        result.evidence[uid] = signals
        result.votes[uid] = detail
        if len(set(votes.values())) > 1:
            result.conflicts[uid] = detail
        adopted = next((s for s in _SIGNAL_ORDER if s in signals), "")
        if adopted:
            result.signals[adopted] = result.signals.get(adopted, 0) + 1
        if category_id == CHARACTER_CATEGORY:
            linked = character_id_from_uid(uid) or str(getattr(entry, "character_id", "") or "")
            if linked:
                result.character_ids[uid] = linked
        result.uses[category_id] = result.uses.get(category_id, 0) + 1
    return result


def has_reliable_metadata(entries) -> bool:
    """是否存在至少一条可信信号；外部书没有这类元数据时不应被自动分类。"""
    for entry in entries:
        if entry_votes(str(getattr(entry, "uid", "") or ""),
                       getattr(entry, "group", ""), getattr(entry, "name", "")):
            return True
    return False


def needs_classification(categories) -> bool:
    """已保存的分类是否「形同未分类」：缺失、空数组、或只剩系统分类 unclassified。"""
    if not isinstance(categories, list):
        return True
    return not [c for c in categories
                if isinstance(c, dict) and c.get("id") and c.get("id") != UNCLASSIFIED["id"]]
