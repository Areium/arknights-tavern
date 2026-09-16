"""
世界书（SillyTavern Lorebook 兼容）核心模块。

职责：
- WorldBookEntry / WorldBook — 规范化条目与书的数据模型
- parse_lorebook() — 解析酒馆世界书的 4 种来源：
    1. 世界书导出 JSON（v1，顶层 entries map）
    2. v2 规格（entries[].keys / extensions）
    3. 角色卡内嵌世界书（data.character_book / data.extensions.world）
    4. 聊天备份 .jsonl（逐行提取内嵌世界书数据）
- 触发匹配：主/副关键词正则扫描 + selective / 概率 / 常驻语义
- format_injection() — 按 position / group_weight / depth 排序并格式化注入文本，
  支持 token 预算与 {{user}} / {{char}} 宏替换
- WorldBookManager — data/worldbooks/ 目录 CRUD + 会话绑定解析 + 全局默认书

与酒馆的语义映射（见计划文档）：
    key/keysecondary → trigger_keys/secondary_keys
    constant → always_active；insertion_order/position → position(0=卡前/1=卡后)
    depth → depth；scanDepth → scan_depth；probability → probability
    caseSensitive/matchWholeWords → case_sensitive/match_whole_words
    excludeRecursion/preventRecursion → 简化为「每轮每条目最多注入一次」
    extensions/automationId/displayIndex → raw 原样保留，导出时可回灌酒馆
"""

import copy
import hashlib
import json
import logging
import random
import re
import threading
import time
import uuid
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from worldbook_scope import (
    EXTENSION_KEY, UNCLASSIFIED, validate_categories, validate_policy,
    expand_sources, find_scope_extension,
    ACTIVATION_ALWAYS, ACTIVATION_MANUAL, ACTIVATION_ROSTER_ANY,
    EXPANSION_NONE, EXPANSION_REQUIRES_CLOSURE, EXPANSION_LEGACY_DEPTH,
    SCHEMA_VERSION_V3, resolve_v3_scope, validate_v3_rules,
    v2_rules_from_import_config, equivalent_v3_roots,
)
from worldbook_classify import classify_entries, needs_classification

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WORLDBOOKS_DIR = _PROJECT_ROOT / "data" / "worldbooks"

# 整合包分发源（随程序分发，git 跟踪）：首次启动自动安装到 _WORLDBOOKS_DIR
_PACKS_DIR = _PROJECT_ROOT / "data" / "packs"
# 未显式配置全局默认书时，按此顺序回退到已安装且启用的预装包（无则跳过）
_PACK_FALLBACK_IDS = ["arknights"]

# 旧安装副本刷新前的留存后缀：`<id>.json.pre-refresh.bak`
# （不以 .json 结尾，避免被 list_books 当成一本书；去掉后缀即可还原）
_PACK_BACKUP_SUFFIX = ".pre-refresh.bak"

# 支持探测的来源格式标签
SOURCE_V1 = "sillytavern_v1"
SOURCE_V2 = "sillytavern_v2"
SOURCE_CARD = "character_card"
SOURCE_JSONL = "chat_backup_jsonl"
SOURCE_MANUAL = "manual"
SOURCE_PREINSTALLED = "preinstalled"

DEFAULT_CATEGORIES = [
    {"id": "worldview", "parent_id": None, "name": "世界观设定", "scope_type": "worldview", "sort_order": 10},
    {"id": "characters", "parent_id": None, "name": "角色", "scope_type": "character", "sort_order": 20},
    {"id": "other", "parent_id": None, "name": "其他", "scope_type": "other", "sort_order": 30},
]


def _pack_rev(data: dict) -> str:
    """整合包内容指纹（版本号）。

    只覆盖影响注入结果的字段（id / name / entries），忽略 created_at / updated_at /
    source / pack_rev 这类易变字段——否则每次重新生成分发包都会「看起来变了」，
    导致每次启动都白刷一遍。
    """
    payload = json.dumps(
        {
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "entries": data.get("entries", []),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class ImportReport:
    """导入结果报告。"""
    source_format: str = ""
    imported: int = 0
    skipped: int = 0
    warnings: list = field(default_factory=list)
    entry_uids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_format": self.source_format,
            "imported": self.imported,
            "skipped": self.skipped,
            "warnings": self.warnings,
        }


@dataclass
class WorldBookEntry:
    """规范化后的世界书条目。

    字段与酒馆的映射见模块 docstring。`raw` 保留原始条目字典，
    用于导出时无损回灌酒馆。
    """
    uid: str
    content: str
    name: str = ""
    trigger_keys: list = field(default_factory=list)       # key / keys
    secondary_keys: list = field(default_factory=list)     # keysecondary / secondary_keys
    always_active: bool = False                            # constant
    selective: bool = True                                 # 主键命中后才检查副键
    enabled: bool = True
    position: int = 0                                      # 0=卡前 1=卡后
    depth: int = 4
    scan_depth: int = 4
    probability: int = 100
    group: str = ""
    group_weight: int = 100
    case_sensitive: bool = False
    match_whole_words: bool = False
    # 应用私有元数据；不参与酒馆匹配语义，仅用于会话按需载入。
    category_id: str = ""
    character_id: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "name": self.name,
            "content": self.content,
            "trigger_keys": self.trigger_keys,
            "secondary_keys": self.secondary_keys,
            "always_active": self.always_active,
            "selective": self.selective,
            "enabled": self.enabled,
            "position": self.position,
            "depth": self.depth,
            "scan_depth": self.scan_depth,
            "probability": self.probability,
            "group": self.group,
            "group_weight": self.group_weight,
            "case_sensitive": self.case_sensitive,
            "match_whole_words": self.match_whole_words,
            "category_id": self.category_id,
            "character_id": self.character_id,
            "raw": self.raw,
        }

    @staticmethod
    def from_dict(data: dict) -> "WorldBookEntry":
        return WorldBookEntry(
            uid=str(data.get("uid", "")),
            content=str(data.get("content", "")),
            name=str(data.get("name", "")),
            trigger_keys=list(data.get("trigger_keys") or []),
            secondary_keys=list(data.get("secondary_keys") or []),
            always_active=bool(data.get("always_active", False)),
            selective=bool(data.get("selective", True)),
            enabled=bool(data.get("enabled", True)),
            position=int(data.get("position", 0)),
            depth=int(data.get("depth", 4)),
            scan_depth=int(data.get("scan_depth", 4)),
            probability=int(data.get("probability", 100)),
            group=str(data.get("group", "")),
            group_weight=int(data.get("group_weight", 100)),
            case_sensitive=bool(data.get("case_sensitive", False)),
            match_whole_words=bool(data.get("match_whole_words", False)),
            category_id=str(data.get("category_id", "") or ""),
            character_id=str(data.get("character_id", "") or ""),
            raw=dict(data.get("raw") or {}),
        )


# ─────────────────────────────────────────────────────────────
# 解析器
# ─────────────────────────────────────────────────────────────

def _first(data: dict, *names, default=None):
    """按优先级取第一个存在的字段（兼容 v1/v2 命名差异）。"""
    for n in names:
        if n in data and data[n] is not None:
            return data[n]
    return default


def _as_str_list(value) -> list[str]:
    """把关键词字段规范化为字符串列表（酒馆部分版本用逗号分隔字符串）。"""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return [p for p in parts if p]
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item.strip())
        return [p for p in result if p]
    return []


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _parse_position(entry: dict, extensions: dict) -> int:
    """解析插入位置：insertion_order / position / extensions.position。

    酒馆取值：0/1 整数，或 "before_char"/"after_char"（v2），
    旧版还有 "before"/"after"。统一映射为 0=卡前 / 1=卡后。
    """
    value = _first(entry, "insertion_order", "position",
                   default=_first(extensions, "position", default=0))
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("before_char", "before", "before_char_defs"):
            return 0
        if v in ("after_char", "after", "after_char_defs"):
            return 1
        return _to_int(v, 0) if v.isdigit() else 0
    return 0 if _to_int(value, 0) == 0 else 1


def _normalize_entry(raw_entry: dict, index: int, warnings: list) -> Optional[WorldBookEntry]:
    """把一条酒馆条目规范化为 WorldBookEntry。

    返回 None 表示跳过（如 content 为空）。
    """
    extensions = raw_entry.get("extensions")
    extensions = extensions if isinstance(extensions, dict) else {}

    scope_meta = extensions.get(EXTENSION_KEY, {})
    scope_meta = scope_meta if isinstance(scope_meta, dict) else {}

    content = _first(raw_entry, "content", default="")
    if not isinstance(content, str) or not content.strip():
        warnings.append(f"条目 #{index} 内容为空，已跳过")
        return None

    trigger_keys = _as_str_list(_first(raw_entry, "key", "keys", "trigger_keys"))
    secondary_keys = _as_str_list(
        _first(raw_entry, "keysecondary", "secondary_keys", "trigger_secondary_keys"))
    always_active = _to_bool(_first(raw_entry, "constant", default=False), False)

    if not trigger_keys and not secondary_keys and not always_active:
        warnings.append(
            f"条目 #{index}（{content[:20]}…）无关键词且非常驻，永远不会被触发")

    uid = str(_first(raw_entry, "uid", "id",
                     default=_first(extensions, "id", default=f"entry_{index}")))
    use_probability = _to_bool(_first(raw_entry, "useProbability", default=True), True)
    probability = _to_int(
        _first(raw_entry, "probability",
               default=_first(extensions, "probability", default=100)), 100)
    if not use_probability:
        probability = 100

    # enabled 兼容两种写法：显式 enabled 字段 / 旧版酒馆的 disable 字段
    if "enabled" in raw_entry or "enabled" in extensions:
        enabled = _to_bool(_first(raw_entry, "enabled", default=True), True)
    elif "disable" in raw_entry:
        enabled = not _to_bool(raw_entry.get("disable"), False)
    else:
        enabled = True

    return WorldBookEntry(
        uid=uid,
        name=str(_first(raw_entry, "comment", "name",
                        default=_first(extensions, "display_name", default="")) or ""),
        content=content,
        trigger_keys=trigger_keys,
        secondary_keys=secondary_keys,
        always_active=always_active,
        selective=_to_bool(_first(raw_entry, "selective", default=True), True),
        enabled=enabled,
        position=_parse_position(raw_entry, extensions),
        depth=_to_int(_first(raw_entry, "depth",
                             default=_first(extensions, "depth", default=4)), 4),
        scan_depth=_to_int(_first(raw_entry, "scanDepth", default=4), 4),
        probability=probability,
        group=str(_first(raw_entry, "group", default="") or ""),
        group_weight=_to_int(_first(raw_entry, "groupWeight", default=100), 100),
        case_sensitive=_to_bool(_first(raw_entry, "caseSensitive", "case_sensitive",
                                       default=False), False),
        match_whole_words=_to_bool(_first(raw_entry, "matchWholeWords", "match_whole_words",
                                          default=False), False),
        category_id=str(scope_meta.get("category_id", "") or ""),
        character_id=str(scope_meta.get("character_id", "") or ""),
        raw=copy.deepcopy(raw_entry),
    )


def _extract_entry_collections(obj) -> list[list[dict]]:
    """从任意 JSON 对象中递归提取世界书条目集合。

    返回 list[list[dict]]——每个内层 list 是一组原始条目
    （可能来自多本书的合并场景，如 .jsonl 聊天备份）。
    """
    if not isinstance(obj, dict):
        return []

    # 1. 顶层 entries map/list（v1 导出 / v2 直接结构）
    entries = obj.get("entries")
    if entries is not None:
        if isinstance(entries, dict):
            # map 的 key 常作为条目身份（部分导出没有 uid 字段），兜底注入
            result = []
            for k, v in entries.items():
                if isinstance(v, dict) and "uid" not in v and "id" not in v:
                    v = dict(v, uid=k)
                result.append(v)
            return [result]
        if isinstance(entries, list):
            return [entries]

    # 2. character_book（v2 角色卡 / 独立 v2 书）
    cb = obj.get("character_book")
    if isinstance(cb, dict):
        cb_entries = cb.get("entries")
        if isinstance(cb_entries, (dict, list)):
            found = _extract_entry_collections({"entries": cb_entries})
            if found:
                return found

    # 3. 旧版内嵌 world（extensions.world 或 world 字段）
    for world_key in ("world",):
        world = obj.get(world_key)
        if isinstance(world, dict):
            found = _extract_entry_collections(world)
            if found:
                return found

    ext = obj.get("extensions")
    if isinstance(ext, dict):
        world = ext.get("world")
        if isinstance(world, dict):
            found = _extract_entry_collections(world)
            if found:
                return found

    # 4. 角色卡 data 子结构（v1/v2 卡内嵌）
    data = obj.get("data")
    if isinstance(data, dict):
        found = _extract_entry_collections(data)
        if found:
            return found

    # 5. 单个条目对象（有 content 且有 key/keys）
    if "content" in obj and ("key" in obj or "keys" in obj):
        return [[obj]]

    return []


def _dedupe_entries(entries: list[WorldBookEntry]) -> list[WorldBookEntry]:
    """按 uid 去重（.jsonl 多消息可能重复携带同一本书）。"""
    seen: dict[str, WorldBookEntry] = {}
    for e in entries:
        key = e.uid
        if key in seen:
            # 内容相同直接跳过；不同则加后缀保留
            if seen[key].content == e.content:
                continue
            key = f"{key}__dup_{len(seen)}"
        seen[key] = e
    return list(seen.values())


def parse_lorebook(source) -> tuple[list[WorldBookEntry], ImportReport]:
    """解析世界书数据，返回 (条目列表, 导入报告)。

    Args:
        source: dict（已 json.loads 的对象）或 str（JSON 文本，
                多行时按 .jsonl 逐行解析）。

    自动探测来源：v1 导出 / v2 规格 / 角色卡内嵌 / 聊天备份。
    """
    warnings: list[str] = []
    raw_collections: list[list[dict]] = []
    source_format = SOURCE_MANUAL

    if isinstance(source, str):
        text = source.strip()
        if not text:
            return [], ImportReport(SOURCE_MANUAL, 0, 0, ["内容为空"])
        # 先尝试整体 JSON，失败则按 .jsonl 逐行解析
        try:
            obj = json.loads(text)
            collections = _extract_entry_collections(obj)
            if collections:
                source_format = SOURCE_V1
                raw_collections.extend(collections)
            else:
                warnings.append("未在其中发现世界书条目（无 entries/character_book/world 结构）")
        except json.JSONDecodeError:
            jsonl_count = 0
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(f"跳过无法解析的行: {line[:60]}…")
                    continue
                jsonl_count += 1
                collections = _extract_entry_collections(obj)
                raw_collections.extend(collections)
            if jsonl_count:
                source_format = SOURCE_JSONL
            if not raw_collections:
                warnings.append("聊天备份中未发现世界书数据")
    elif isinstance(source, dict):
        # 角色卡内嵌（data.character_book / data.extensions.world）优先标记
        data = source.get("data") if isinstance(source.get("data"), dict) else {}
        if isinstance(data.get("character_book"), dict) or (
                isinstance(data.get("extensions"), dict)
                and isinstance(data["extensions"].get("world"), dict)):
            source_format = SOURCE_CARD
        collections = _extract_entry_collections(source)
        if not collections:
            warnings.append("未在数据中发现世界书条目")
        raw_collections.extend(collections)
        # v2 特征：条目使用 keys 字段；否则视为 v1 导出
        if raw_collections and any(
                ("keys" in e and "key" not in e) for c in raw_collections for e in c):
            if source_format == SOURCE_MANUAL:
                source_format = SOURCE_V2
        elif raw_collections and source_format == SOURCE_MANUAL:
            source_format = SOURCE_V1
    else:
        return [], ImportReport(SOURCE_MANUAL, 0, 0, ["不支持的数据类型"])

    entries: list[WorldBookEntry] = []
    skipped = 0
    idx = 0
    for collection in raw_collections:
        for raw_entry in collection:
            idx += 1
            if not isinstance(raw_entry, dict):
                skipped += 1
                warnings.append(f"条目 #{idx} 不是对象，已跳过")
                continue
            entry = _normalize_entry(raw_entry, idx, warnings)
            if entry is None:
                skipped += 1
            else:
                entries.append(entry)

    entries = _dedupe_entries(entries)
    report = ImportReport(
        source_format=source_format,
        imported=len(entries),
        skipped=skipped,
        warnings=warnings,
        entry_uids=[e.uid for e in entries],
    )
    return entries, report


# ─────────────────────────────────────────────────────────────
# 书
# ─────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 字符按 1 token，其余按 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + other // 4


# 解析器版本：随解析语义变更递增。会话快照记录它，用于判断旧快照是否需重算。
RESOLVER_VERSION = 3
# 每个书保留的策略版本快照上限（不可变历史，供会话恢复绑定版本）。
MAX_POLICY_REVISIONS = 40


def content_revision(entries) -> str:
    """条目正文指纹：只覆盖 uid + 正文哈希。

    用于标记「分析证据是否过期」——正文变了，旧证据就不再可信；
    它**不是**正文快照，正文仍按实时语义读取。
    """
    payload = sorted(
        (str(getattr(e, "uid", "") or (e.get("uid") if isinstance(e, dict) else "")),
         hashlib.sha256(
             (str(getattr(e, "content", "") or (e.get("content") if isinstance(e, dict) else "")))
             .encode("utf-8")).hexdigest())
        for e in entries
    )
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _compile_pattern(key: str, case_sensitive: bool, whole_words: bool):
    """把酒馆关键词编译为正则（酒馆 key 本身就是正则）。

    非法正则降级为字面量匹配；whole_words 用 ASCII 词边界 lookaround
    （对 CJK 关键词自然失效，即不施加边界约束）。
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        re.compile(key, flags)
        pattern = key
    except re.error:
        pattern = re.escape(key)
    if whole_words:
        pattern = rf"(?<![A-Za-z0-9_])(?:{pattern})(?![A-Za-z0-9_])"
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def _entry_matches(entry: WorldBookEntry, scan_text: str) -> bool:
    """判断条目是否被触发（酒馆语义）。"""
    if entry.always_active:
        return True

    primaries = [_compile_pattern(k, entry.case_sensitive, entry.match_whole_words)
                 for k in entry.trigger_keys]
    primaries = [p for p in primaries if p is not None]
    secondaries = [_compile_pattern(k, entry.case_sensitive, entry.match_whole_words)
                   for k in entry.secondary_keys]
    secondaries = [p for p in secondaries if p is not None]

    if entry.selective:
        # 必须命中主键；若存在副键则还需命中至少一个副键
        if not primaries:
            return False
        if not any(p.search(scan_text) for p in primaries):
            return False
        if secondaries and not any(p.search(scan_text) for p in secondaries):
            return False
        return True

    # 非 selective：副键等价于主键
    for p in primaries + secondaries:
        if p.search(scan_text):
            return True
    return False


def _substitute_macros(content: str, identity: str, active_char: Optional[str]) -> str:
    """替换 {{user}} / {{char}} 宏。"""
    content = content.replace("{{user}}", identity or "")
    if active_char is not None:
        content = content.replace("{{char}}", active_char)
    else:
        content = content.replace("{{char}}", "")
    return content


class WorldBook:
    """一本世界书：id + 元信息 + 条目集合 + 触发/格式化逻辑。

    source: "preinstalled"（随程序分发的整合包安装副本）| "imported"（用户导入/新建）
    enabled: 书级启用开关，停用的书不参与解析。
    pack_rev: 预装包内容指纹（安装/刷新时写入）。用于判断安装副本是否落后于分发源；
              随书持久化，这样用户在界面上编辑预装书后不会被下次启动误判成「旧版本」而覆盖。
    所有书统一管理、统一可写；预装包删除后可从分发源一键重装。
    """

    def __init__(self, book_id: str, name: str = "", entries: list = None,
                 source_format: str = SOURCE_MANUAL, budget_tokens: int = 0,
                 source: str = "imported", enabled: bool = True,
                 pack_rev: str = "", schema_version: int = 2,
                 categories: list = None, dependency_edges: list = None,
                 import_config: dict = None, scope_mode: str = None,
                 dependency_rules: dict = None, related_edges: list = None,
                 policy_revisions: list = None):
        self.id = book_id
        self.name = name or book_id
        self.source_format = source_format
        self.budget_tokens = budget_tokens  # 0 = 不限制
        # source: "preinstalled"（随程序分发的整合包，安装副本）| "imported"（用户导入）
        self.source = source if source in (SOURCE_PREINSTALLED, "imported", "builtin") else "imported"
        if self.source == "builtin":
            # 旧版字段兼容
            self.source = SOURCE_PREINSTALLED
        self.enabled = bool(enabled)
        self.created_at = time.time()
        self.updated_at = time.time()
        self.pack_rev = str(pack_rev or "")
        self.entries: list[WorldBookEntry] = list(entries or [])
        self.schema_version = 3 if dependency_rules else 2
        self.scope_mode = scope_mode or ("selective" if schema_version >= 2 and categories else "legacy")
        if self.scope_mode not in ("legacy", "selective"):
            raise ValueError("scope_mode 必须是 legacy 或 selective")
        self.categories = self._normalize_categories(categories)
        for entry in self.entries:
            entry.category_id = entry.category_id or "unclassified"
        self.dependency_edges = self._normalize_edges(dependency_edges)
        self.import_config = self._normalize_import_config(import_config)
        # ── v3：全书底层有向图 + 条件起点（分类只负责组织，不决定候选）──
        known = {e.uid for e in self.entries}
        self.related_edges = []
        self.dependency_rules = None
        if dependency_rules is not None:
            # 关联补充边可能随规则集一起序列化，也可能独立存放（旧写入路径）。
            # 两处都要认，否则「保存一次再读回」会把 related 边丢掉。
            payload = dict(dependency_rules)
            if related_edges and not payload.get("related_edges"):
                payload["related_edges"] = list(related_edges)
            rules, requires, related = validate_v3_rules(
                known, payload, self.dependency_edges)
            self.dependency_rules = rules
            self.dependency_edges = requires
            self.related_edges = related
        elif related_edges:
            _, _, self.related_edges = validate_v3_rules(
                known, {"roots": [], "requires_edges": [], "related_edges": related_edges})
        # 不可变策略版本历史：会话可据此恢复「它创建时绑定的规则」，而不只是版本号。
        self.policy_revisions = self._normalize_revisions(policy_revisions)

    def _normalize_revisions(self, value) -> list[dict]:
        result = []
        for raw in value if isinstance(value, list) else []:
            if not isinstance(raw, dict):
                continue
            revision = raw.get("revision")
            if type(revision) is not int or revision < 1:
                continue
            result.append({
                "revision": revision,
                "resolver_version": int(raw.get("resolver_version", RESOLVER_VERSION) or RESOLVER_VERSION),
                "scope_mode": raw.get("scope_mode", "selective"),
                "rules": copy.deepcopy(raw.get("rules")) if isinstance(raw.get("rules"), dict) else None,
                "requires_edges": copy.deepcopy(raw.get("requires_edges") or []),
                "related_edges": copy.deepcopy(raw.get("related_edges") or []),
                "fixed_entry_uids": list(raw.get("fixed_entry_uids") or []),
                "dependency_sources": copy.deepcopy(raw.get("dependency_sources") or []),
                "created_at": float(raw.get("created_at", time.time())),
            })
        result.sort(key=lambda item: item["revision"])
        return result[-MAX_POLICY_REVISIONS:]

    @property
    def v3_enabled(self) -> bool:
        """是否按 v3 规则解析（否则沿用 v2 语义，旧会话不受影响）。"""
        return self.dependency_rules is not None

    def rules_snapshot(self, revision: int = None) -> dict:
        """返回可恢复的规则快照：优先取指定修订的不可变版本，否则用当前规则。"""
        if revision is not None:
            for item in reversed(self.policy_revisions):
                if item["revision"] == revision:
                    return copy.deepcopy(item)
            if revision != self.import_config["revision"]:
                raise ValueError("请求的规则版本不存在；请重新预览当前版本")
        return {
            "revision": self.import_config["revision"],
            "resolver_version": RESOLVER_VERSION,
            "scope_mode": self.scope_mode,
            "rules": copy.deepcopy(self.dependency_rules),
            "requires_edges": copy.deepcopy(self.dependency_edges),
            "related_edges": copy.deepcopy(self.related_edges),
            "fixed_entry_uids": list(self.import_config["fixed_entry_uids"]),
            "dependency_sources": copy.deepcopy(self.import_config["dependency_sources"]),
            "created_at": time.time(),
        }

    def record_policy_revision(self):
        """把当前策略固化为一个不可变版本（同一修订号只记一次）。"""
        snapshot = self.rules_snapshot()
        for item in self.policy_revisions:
            if item["revision"] == snapshot["revision"]:
                return
        self.policy_revisions.append(snapshot)
        self.policy_revisions = self.policy_revisions[-MAX_POLICY_REVISIONS:]

    def equivalent_v3_rules(self, extra_roots=None, requires_edges=None,
                            related_edges=None) -> dict:
        """把当前 v2 配置映射成**范围等价**的 v3 规则集。

        这是显式迁移（用户在界面上确认「启用按需规则」）时用的：
        - legacy → 每条 always + none；
        - selective → 世界观分类 always + none，角色分类 roster_any + none；
        - 固定导入 → always + none；导入源 → always + legacy_depth（保留 max_depth）。
        结果与旧语义逐条等价，不会因为「保存一次」就悄悄少载入一堆条目。
        """
        rules, requires, related = v2_rules_from_import_config(
            self.import_config, requires_edges if requires_edges is not None else self.dependency_edges)
        known = {r["entry_uid"] for r in rules["roots"]}
        roots = list(rules["roots"])
        for root in equivalent_v3_roots(self.entries, self.categories, self.scope_mode,
                                        self.category_scope_type):
            if root["entry_uid"] in known:
                continue
            known.add(root["entry_uid"])
            roots.append(root)
        for root in extra_roots or []:
            if isinstance(root, dict) and root.get("entry_uid") in known:
                continue
            if isinstance(root, dict) and root.get("entry_uid"):
                known.add(root["entry_uid"])
                roots.append(root)
        return {"roots": roots,
                "root_rule": {"entry_uids": sorted(known)},
                "requires_edges": requires,
                "related_edges": related if related_edges is None else related_edges,
                "rejected": [], "edge_meta": {}}

    def adopt_v2_as_v3(self):
        """把现有 v2 配置无损升级为 v3 起点（范围等价，不改候选）。

        只显式调用：旧书/旧会话不会因为读一次就悄悄改变语义。
        """
        payload = self.equivalent_v3_rules()
        rules, requires, related = validate_v3_rules(
            {e.uid for e in self.entries}, payload, self.dependency_edges)
        self.dependency_rules = rules
        self.dependency_edges = requires
        self.related_edges = related
        self.schema_version = 3
        return self

    @staticmethod
    def _normalize_categories(categories) -> list[dict]:
        return validate_categories(categories if categories is not None else [])

    def _normalize_edges(self, edges) -> list[dict]:
        known = {e.uid for e in self.entries}
        result, seen = [], set()
        for raw in edges if isinstance(edges, list) else []:
            if not isinstance(raw, dict):
                continue
            source, target = str(raw.get("from_uid", "") or ""), str(raw.get("to_uid", "") or "")
            key = (source, target)
            if source in known and target in known and source != target and key not in seen:
                seen.add(key)
                result.append({"from_uid": source, "to_uid": target})
        return result

    def _normalize_import_config(self, config) -> dict:
        config = config if isinstance(config, dict) else {}
        known = {e.uid for e in self.entries}
        fixed = []
        for uid in config.get("fixed_entry_uids", []) if isinstance(config.get("fixed_entry_uids", []), list) else []:
            uid = str(uid)
            if uid in known and uid not in fixed:
                fixed.append(uid)
        sources = []
        for raw in config.get("dependency_sources", []) if isinstance(config.get("dependency_sources", []), list) else []:
            if not isinstance(raw, dict):
                continue
            uid = str(raw.get("entry_uid", "") or "")
            depth = raw.get("max_depth", 0)
            if uid in known and type(depth) is int and 0 <= depth <= 32:
                sources.append({"entry_uid": uid, "max_depth": depth})
        return {"fixed_entry_uids": fixed, "dependency_sources": sources,
                "revision": max(1, _to_int(config.get("revision", 1), 1))}

    # ── 序列化 ──

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "source_format": self.source_format,
            "budget_tokens": self.budget_tokens,
            "source": self.source,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entries": [e.to_dict() for e in self.entries],
            "schema_version": self.schema_version,
            "scope_mode": self.scope_mode,
            "categories": self.categories,
            "dependency_edges": self.dependency_edges,
            "import_config": self.import_config,
        }
        if self.dependency_rules is not None:
            data["dependency_rules"] = self.dependency_rules
        # related_edges 独立持久化：v3 书与「已配置关联补充但尚未启用 v3」的书都要能往返
        if self.related_edges:
            data["related_edges"] = self.related_edges
        if self.policy_revisions:
            data["policy_revisions"] = copy.deepcopy(self.policy_revisions)
        # 仅预装包携带指纹，用户导入/新建的书序列化形态保持不变
        if self.pack_rev:
            data["pack_rev"] = self.pack_rev
        return data

    @staticmethod
    def from_dict(data: dict) -> "WorldBook":
        book = WorldBook(
            book_id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            entries=[WorldBookEntry.from_dict(e) for e in data.get("entries", [])],
            source_format=str(data.get("source_format", SOURCE_MANUAL)),
            budget_tokens=int(data.get("budget_tokens", 0)),
            source=str(data.get("source", "imported")),
            enabled=bool(data.get("enabled", True)),
            pack_rev=str(data.get("pack_rev", "")),
            schema_version=int(data.get("schema_version", 1) or 1),
            categories=data.get("categories"),
            dependency_edges=data.get("dependency_edges"),
            import_config=data.get("import_config"),
            scope_mode=data.get("scope_mode"),
            dependency_rules=data.get("dependency_rules"),
            related_edges=data.get("related_edges"),
            policy_revisions=data.get("policy_revisions"),
        )
        book.created_at = float(data.get("created_at", time.time()))
        book.updated_at = float(data.get("updated_at", time.time()))
        # 预装整合包由内置生成器写出，uid 前缀 / group / 名称后缀都是可靠来源元数据；
        # 外部书没有这类元数据时保持原样，不按名字或关键词猜测。
        if book.source == SOURCE_PREINSTALLED and needs_classification(data.get("categories")):
            apply_auto_classification(book, first_install="categories" not in data)
        return book

    def category_scope_type(self, category_id: str) -> str:
        """返回分类的有效类型；父链异常时安全回落 other。"""
        by_id = {c["id"]: c for c in self.categories}
        seen = set()
        current = by_id.get(category_id)
        while current and current["id"] not in seen:
            seen.add(current["id"])
            kind = current.get("scope_type")
            if kind in ("worldview", "character"):
                return kind
            current = by_id.get(current.get("parent_id"))
        return "other"

    def resolve_import_scope(self, roster_character_ids: list[str] = None) -> dict:
        """固定候选 UID 快照；不改变条目的关键词、常驻位置或预算。"""
        if roster_character_ids is None:
            roster_character_ids = []
        if not isinstance(roster_character_ids, list) or any(
                not isinstance(x, str) or not x.strip() for x in roster_character_ids):
            raise ValueError("roster_character_ids 必须是非空字符串组成的数组")
        roster = {x.strip() for x in roster_character_ids}
        known = {e.uid: e for e in self.entries}
        legacy = self.scope_mode == "legacy"
        reasons = {"legacy": set(known) if legacy else set(), "worldview": set(),
                   "roster": set(), "fixed": set(self.import_config["fixed_entry_uids"]),
                   "dependency": expand_sources(self.import_config["dependency_sources"], self.dependency_edges)}
        if not legacy:
            for entry in self.entries:
                kind = self.category_scope_type(entry.category_id)
                if kind == "worldview":
                    reasons["worldview"].add(entry.uid)
                elif kind == "character" and entry.character_id in roster:
                    reasons["roster"].add(entry.uid)
        selected = set().union(*reasons.values())
        resolved = [e.uid for e in self.entries if e.uid in selected and self.enabled and e.enabled and e.content.strip()]
        return {"book_id": self.id, "policy_revision": self.import_config["revision"],
                "roster_character_ids": sorted(roster), "resolved_entry_uids": resolved,
                "legacy_full_scope": legacy, "resolved_at": time.time(),
                "selection_reasons": {uid: [reason for reason, uids in reasons.items() if uid in uids]
                                      for uid in sorted(selected)},
                "excluded_entries": [{"uid": e.uid, "name": e.name,
                                      "reason": "世界书已停用" if not self.enabled else "条目已停用" if not e.enabled else "内容为空"}
                                     for e in self.entries if e.uid in selected and e.uid not in resolved]}

    def preview_scope(self, roster_character_ids=None) -> dict:
        scope = self.resolve_import_scope(roster_character_ids)
        resolved = set(scope["resolved_entry_uids"])
        full = [e for e in self.entries if e.enabled and e.content.strip()]
        costs = {e.uid: estimate_tokens(e.content) for e in full}
        total, selected = sum(costs.values()), sum(costs.get(uid, 0) for uid in resolved)
        warnings = []
        pending = sum(e.category_id == "unclassified" for e in full)
        if pending:
            warnings.append(f"{pending} 条尚未分类；按需模式下不会自动导入，可归类或设为固定导入。")
        unlinked = sum(self.category_scope_type(e.category_id) == "character" and not e.character_id for e in full)
        if unlinked:
            warnings.append(f"{unlinked} 条角色设定未关联角色，不能随阵容自动导入。")
        entry_names = {entry.uid: entry.name for entry in self.entries}
        source_expansions = []
        for source in self.import_config["dependency_sources"]:
            expanded = expand_sources([source], self.dependency_edges) & resolved
            source_expansions.append({
                "entry_uid": source["entry_uid"],
                "name": entry_names.get(source["entry_uid"], source["entry_uid"]),
                "max_depth": source["max_depth"],
                "entries": [{"uid": entry.uid, "name": entry.name}
                            for entry in self.entries if entry.uid in expanded],
            })
        return {"scope": scope, "entry_count": len(resolved), "full_entry_count": len(full),
                "full_estimated_tokens": total, "resolved_estimated_tokens": selected,
                "saved_estimated_tokens": total - selected,
                "saved_percent": round(100 * (total - selected) / total, 1) if total else 0,
                "breakdown": {reason: {"entry_count": sum(reason in scope["selection_reasons"].get(uid, []) for uid in resolved),
                                       "estimated_tokens": sum(costs.get(uid, 0) for uid in resolved if reason in scope["selection_reasons"].get(uid, []))}
                              for reason in ("worldview", "roster", "fixed", "dependency", "legacy")},
                "source_expansions": source_expansions,
                "warnings": warnings}

    # ── v3 解析 ──

    def resolve_v3_import_scope(self, roster_character_ids=None, revision=None,
                                manual_entry_uids=None):
        """按 v3 规则解析候选范围。

        revision 指定时使用该修订的**不可变规则版本**（会话恢复用），
        否则使用当前规则。manual_entry_uids 是「只作用于本次会话」的手动追加。
        """
        snapshot = self.rules_snapshot(revision) if revision is not None else None
        rules = (snapshot or {}).get("rules") or self.dependency_rules
        requires = (snapshot or {}).get("requires_edges")
        related = (snapshot or {}).get("related_edges")
        if requires is None:
            requires = self.dependency_edges
        if related is None:
            related = self.related_edges
        if rules is None:
            raise ValueError("这本书没有 v3 依赖规则")

        # 手动追加作为临时起点进入**同一次**解析：它会沿 requires 闭包补齐、
        # 带上 manual 选用原因并进入展示树。解析完再并集会漏掉依赖，也没有解释。
        manual = [uid for uid in (manual_entry_uids or [])
                  if isinstance(uid, str) and any(e.uid == uid for e in self.entries)]

        result = resolve_v3_scope(
            self.entries, rules, requires, related,
            roster_character_ids=roster_character_ids,
            policy_revision=(snapshot or {}).get("revision", self.import_config["revision"]),
            content_revision=content_revision(self.entries),
            book_id=self.id,
            manual_entry_uids=manual,
        )
        result["resolver_version"] = RESOLVER_VERSION
        if (snapshot or {}).get("scope_mode", self.scope_mode) == "legacy":
            uids = sorted(e.uid for e in self.entries
                          if self.enabled and e.enabled and e.content.strip())
            result.update(resolved_entry_uids=uids, legacy_full_scope=True,
                          selection_reasons={uid: ["legacy"] for uid in uids})
        return result

    def preview_v3_scope(self, roster_character_ids=None, manual_entry_uids=None,
                         revision=None, full_scope=False):
        """v3 预览：候选范围 + 解释 + 与草稿绑定的一致性指纹。

        `full_scope=True` 表示「本次会话显式全量兼容」：预览结果与创建会话时一致，
        因此这里必须真的把范围换成全量，而不是只加一句提示。
        """
        scope = self.resolve_v3_import_scope(roster_character_ids, revision, manual_entry_uids)
        full = [e for e in self.entries if e.enabled and e.content.strip()]
        if full_scope:
            uids = sorted(e.uid for e in full)
            scope = {**scope, "resolved_entry_uids": uids,
                     "selection_reasons": {uid: ["full_scope"] for uid in uids},
                     "active_roots": [], "resolved_edges": [], "display_tree": [],
                     "cross_references": [], "issues": [], "legacy_full_scope": True}
        resolved = set(scope["resolved_entry_uids"])
        costs = {e.uid: estimate_tokens(e.content) for e in self.entries}
        total = sum(costs.get(e.uid, 0) for e in full)
        selected = sum(costs.get(uid, 0) for uid in resolved)
        by_uid = {e.uid: e for e in self.entries}

        warnings = []
        if full_scope:
            warnings.append("已选择「本次会话全量兼容」：这次会载入全部启用条目，"
                            "只影响本会话，不改变这本书的规则。")
        pending = sum(e.category_id == "unclassified" for e in full)
        if pending:
            warnings.append(f"{pending} 条尚未分类；未分类条目不会被任何起点激活，"
                            "可归类、设为起点或手动追加。")
        unlinked = sum(self.category_scope_type(e.category_id) == "character"
                       and not e.character_id for e in full)
        if unlinked:
            warnings.append(f"{unlinked} 条角色设定未关联角色，不能随阵容激活。")

        unselected = [{"uid": e.uid, "name": e.name, "category_id": e.category_id}
                      for e in full if e.uid not in resolved]
        return {
            "scope": scope,
            "schema_version": SCHEMA_VERSION_V3,
            "scope_mode": self.scope_mode,
            "resolver_version": RESOLVER_VERSION,
            "full_scope": bool(full_scope),
            "entry_count": len(resolved),
            "full_entry_count": len(full),
            "full_estimated_tokens": total,
            "resolved_estimated_tokens": selected,
            "saved_estimated_tokens": total - selected,
            "saved_percent": round(100 * (total - selected) / total, 1) if total else 0,
            "active_roots": scope["active_roots"],
            "resolved_edges": scope["resolved_edges"],
            "selection_reasons": scope["selection_reasons"],
            "display_tree": scope["display_tree"],
            "cross_references": scope["cross_references"],
            "issues": scope["issues"],
            "draft_hash": self.policy_draft_hash(roster_character_ids, manual_entry_uids,
                                                 revision, full_scope),
            "policy_revision": scope["policy_revision"],
            "content_revision": scope["content_revision"],
            "breakdown": {
                reason: {"entry_count": sum(reason in scope["selection_reasons"].get(uid, [])
                                            for uid in resolved),
                         "estimated_tokens": sum(costs.get(uid, 0) for uid in resolved
                                                 if reason in scope["selection_reasons"].get(uid, []))}
                for reason in ("always", "roster", "requires", "manual", "full_scope")},
            "manual_entry_uids": scope["manual_entry_uids"],
            "unselected_entries": unselected[:200],
            "unselected_count": len(unselected),
            "entry_names": {uid: (by_uid[uid].name or uid) for uid in scope["resolved_entry_uids"]
                            if uid in by_uid},
            "warnings": warnings,
        }

    def policy_draft_hash(self, roster_character_ids=None, manual_entry_uids=None,
                          revision=None, full_scope=False) -> str:
        """草稿指纹：规则 + 边 + 阵容 + 手动追加 + 是否显式全量兼容。

        用于「预览与创建必须一致」：只要其中任何一项不同，指纹就不同，
        创建会话时校验失败而不是静默换一套范围。
        """
        snapshot = self.rules_snapshot(revision) if revision is not None else None
        payload = {
            "book_id": self.id,
            "revision": (snapshot or {}).get("revision", self.import_config["revision"]),
            "rules": (snapshot or {}).get("rules") or self.dependency_rules,
            "requires_edges": (snapshot or {}).get("requires_edges") or self.dependency_edges,
            "related_edges": (snapshot or {}).get("related_edges") or self.related_edges,
            "roster": sorted({c.strip() for c in (roster_character_ids or []) if isinstance(c, str)}),
            "manual": sorted(set(manual_entry_uids or [])),
            "full_scope": bool(full_scope),
            "content_revision": content_revision(self.entries),
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def session_scope_snapshot(self, roster_character_ids=None, manual_entry_uids=None,
                               revision=None, full_scope=False) -> dict:
        """生成会话要持久化的 v3 范围快照。

        绑定的是**完整规则/关联/边的不可变版本**（不只是版本号），并记录解析器版本、
        阵容、手动追加、激活根、UID、原因、参与边与展示路径。正文仍按实时语义读取，
        因此这里保存的是规则与解析结果，不是条目正文副本。

        `full_scope=True` 是**显式**的全量兼容：本次会话载入全部启用且有正文的条目，
        不改动这本书的规则，也不影响别的会话。
        """
        scope = self.resolve_v3_import_scope(roster_character_ids, revision, manual_entry_uids)
        snapshot = self.rules_snapshot(scope["policy_revision"])
        result = {
            "scope_mode": snapshot.get("scope_mode", self.scope_mode),
            "book_id": self.id,
            "schema_version": SCHEMA_VERSION_V3,
            "resolver_version": RESOLVER_VERSION,
            "policy_revision": scope["policy_revision"],
            "content_revision": scope["content_revision"],
            "rules": snapshot.get("rules"),
            "requires_edges": snapshot.get("requires_edges"),
            "related_edges": snapshot.get("related_edges"),
            "roster_character_ids": sorted(scope["roster_character_ids"]),
            "manual_entry_uids": scope["manual_entry_uids"],
            "active_roots": scope["active_roots"],
            "resolved_entry_uids": scope["resolved_entry_uids"],
            "selection_reasons": scope["selection_reasons"],
            "resolved_edges": [e for e in scope["resolved_edges"] if e.get("active")],
            "display_tree": scope["display_tree"],
            "issues": scope["issues"],
            "legacy_full_scope": False,
            "full_scope": False,
            "resolved_at": scope["resolved_at"],
        }
        result.update({
            "inheritance": {
                "policy_revision": scope["policy_revision"],
                "content_revision": scope["content_revision"],
                "resolver_version": RESOLVER_VERSION,
                "rules": copy.deepcopy(snapshot.get("rules")),
                "requires_edges": copy.deepcopy(snapshot.get("requires_edges") or []),
                "related_edges": copy.deepcopy(snapshot.get("related_edges") or []),
                "captured_at": scope["resolved_at"],
            },
            "local_overrides": {"requires_edges": [], "related_edges": []},
            "suppressed_edges": [], "inheritance_conflicts": [], "scope_revision": 1,
        })
        if not full_scope:
            return result
        uids = sorted(e.uid for e in self.entries if e.enabled and (e.content or "").strip())
        result.update({
            "resolved_entry_uids": uids,
            "selection_reasons": {uid: ["full_scope"] for uid in uids},
            "active_roots": [],
            "resolved_edges": [],
            "display_tree": [],
            "issues": [],
            "legacy_full_scope": True,
            "full_scope": True,
        })
        return result

    def refresh_session_scope(self, existing_scope, roster_character_ids=None) -> dict:
        """按会话**已绑定**的规则版本重算范围（角色入队 / 离队时调用）。

        关键：不能拿「这本书现在长什么样」去覆盖会话快照，否则
        - 绑定的不可变规则版本会被换成最新版本；
        - 手动追加（本会话作用域）会消失；
        - 显式全量兼容会被悄悄取消；
        - 选用原因 / 参与边 / 展示树会退化成一份没有解释的 UID 列表。

        v3 快照沿用绑定的 revision / manual / full_scope 重算；
        v2 快照沿用旧语义，不静默升级。
        """
        if not isinstance(existing_scope, dict):
            existing_scope = {}
        if existing_scope.get("schema_version") != SCHEMA_VERSION_V3:
            refreshed = self.resolve_import_scope(roster_character_ids)
            manual = [uid for uid in (existing_scope.get("manual_entry_uids") or [])
                      if isinstance(uid, str)]
            by_uid = {entry.uid: entry for entry in self.entries}
            if existing_scope.get("full_scope"):
                resolved = sorted(uid for uid, entry in by_uid.items()
                                  if self.enabled and entry.enabled and (entry.content or "").strip())
                refreshed.update({"resolved_entry_uids": resolved,
                                  "selection_reasons": {uid: ["full_scope"] for uid in resolved},
                                  "legacy_full_scope": True, "full_scope": True})
            else:
                resolved = list(refreshed.get("resolved_entry_uids") or [])
                reasons = dict(refreshed.get("selection_reasons") or {})
                for uid in manual:
                    entry = by_uid.get(uid)
                    if entry and self.enabled and entry.enabled and (entry.content or "").strip():
                        if uid not in resolved:
                            resolved.append(uid)
                        reasons.setdefault(uid, []).append("manual")
                refreshed.update({"resolved_entry_uids": resolved,
                                  "selection_reasons": reasons,
                                  "full_scope": False})
            # 保留 v2 会话级覆盖字段；解析器版本仍保持 v2，不静默升级。
            return {**existing_scope, **refreshed,
                    "manual_entry_uids": manual,
                    "roster_character_ids": sorted(set(roster_character_ids or []))}
        # 会话自带完整规则；即使书的历史版本被移除也能恢复。
        from session_worldbook_dependencies import effective_graph, effective_rules, normalize_scope
        managed = normalize_scope(existing_scope)
        graph = effective_graph(managed)
        bound = copy.deepcopy(self)
        bound.dependency_rules = effective_rules(managed)
        bound.dependency_edges = copy.deepcopy(graph["requires_edges"])
        bound.related_edges = copy.deepcopy(graph["related_edges"])
        bound.scope_mode = existing_scope.get("scope_mode", "selective")
        bound.import_config["revision"] = managed["inheritance"].get("policy_revision", 1)
        bound.policy_revisions = []
        refreshed = bound.session_scope_snapshot(
            roster_character_ids,
            existing_scope.get("manual_entry_uids") or [],
            None,
            bool(existing_scope.get("full_scope")),
        )
        refreshed.update({
            "inheritance": managed["inheritance"],
            "local_overrides": managed["local_overrides"],
            "suppressed_edges": managed["suppressed_edges"],
            "inheritance_conflicts": managed.get("inheritance_conflicts") or [],
            "scope_revision": managed["scope_revision"],
            "rules": copy.deepcopy(bound.dependency_rules),
            "requires_edges": copy.deepcopy(bound.dependency_edges),
            "related_edges": copy.deepcopy(bound.related_edges),
        })
        return refreshed

    def eligible_uids_for(self, overlay):
        scope = getattr(overlay, "get_worldbook_scope", lambda: None)()
        if scope is None:
            if not hasattr(overlay, "set_worldbook_scope"):
                return None
            # 首次使用时为旧会话留存全量兼容快照，之后新增条目不悄悄扩张旧剧情。
            scope = {"book_id": self.id, "policy_revision": self.import_config["revision"],
                     "resolved_entry_uids": [e.uid for e in self.entries if e.enabled and e.content.strip()],
                     "legacy_full_scope": True, "resolved_at": time.time()}
            overlay.set_worldbook_scope(scope)
        return set(scope.get("resolved_entry_uids", [])) if scope.get("book_id") == self.id else set()

    # ── 触发 ──

    def collect_matches(self, recent_text: str, current_input: str,
                        rng: random.Random = None, eligible_uids: set[str] | None = None) -> list[WorldBookEntry]:
        """扫描最近对话 + 当前输入，返回被触发的条目（按注入顺序排序）。

        Args:
            recent_text: 最近对话文本（由调用方按 scan_depth 组装）。
            current_input: 当前用户输入。
            rng: 可注入随机源（测试用），默认使用全局 random。
        """
        scan_text = f"{recent_text or ''}\n{current_input or ''}"
        if not scan_text.strip():
            scan_text = current_input or ""

        matched: list[WorldBookEntry] = []
        for entry in self.entries:
            if eligible_uids is not None and entry.uid not in eligible_uids:
                continue
            if not entry.enabled:
                continue
            if not _entry_matches(entry, scan_text):
                continue
            if entry.probability < 100:
                roll = (rng or random).random() * 100
                if roll >= entry.probability:
                    continue
            matched.append(entry)

        # 排序：position（卡前/卡后）→ group_weight 降序 → depth 升序
        matched.sort(key=lambda e: (e.position, -e.group_weight, e.depth, e.uid))
        return matched

    # ── 格式化 ──

    def format_injection(self, entries: list[WorldBookEntry], identity: str = "博士",
                         active_char: Optional[str] = None) -> tuple[str, str]:
        """格式化注入文本。

        Returns:
            (before, after)：稳定层与动态层条目文本。

        前缀缓存纪律（对齐 DSH）：稳定层只收「position=0 且常驻」的条目——
        它们在会话内字节不变，可安全留在请求前缀；**触发型条目即使声明
        position=0 也一律进动态层**，否则每次触发的不同注入会破坏前缀缓存。
        应用 {{user}}/{{char}} 宏替换与 token 预算（budget_tokens>0 时截断）。
        """
        before_parts: list[str] = []
        after_parts: list[str] = []
        used = 0
        included_any = False

        for entry in entries:
            text = _substitute_macros(entry.content, identity, active_char)
            if entry.name:
                text = f"### {entry.name}\n{text}"
            cost = estimate_tokens(text)
            # 预算：超限跳过；但至少保留一条，避免全部被截断
            if self.budget_tokens > 0 and included_any and used + cost > self.budget_tokens:
                continue
            used += cost
            included_any = True
            if entry.position == 0 and entry.always_active:
                before_parts.append(text)
            else:
                after_parts.append(text)

        before = "\n\n".join(before_parts)
        after = "\n\n".join(after_parts)
        if before:
            before = f"【世界书】\n{before}"
        if after:
            after = f"【世界书】\n{after}"
        return before, after

    # ── 回灌酒馆导出 ──

    def export_st(self) -> dict:
        """导出为酒馆 v1 世界书格式（entries map）。

        优先使用条目 raw 原始字段并同步已编辑的值，保证回灌酒馆无损；
        本应用新建的条目（无 raw）按酒馆字段合成。
        """
        entries_map: dict[str, dict] = {}
        for i, entry in enumerate(self.entries):
            out = dict(entry.raw) if entry.raw else {}
            # 同步可能被编辑过的字段
            out["uid"] = entry.uid
            out["key"] = entry.trigger_keys
            out["keysecondary"] = entry.secondary_keys
            out["comment"] = entry.name
            out["content"] = entry.content
            out["constant"] = entry.always_active
            out["selective"] = entry.selective
            if "disable" in out:
                # 旧版酒馆用 disable 表示停用，保持同一写法
                out["disable"] = not entry.enabled
                out.pop("enabled", None)
            else:
                out["enabled"] = entry.enabled
            out["insertion_order"] = entry.position
            out["depth"] = entry.depth
            out["scanDepth"] = entry.scan_depth
            out["probability"] = entry.probability
            out["useProbability"] = entry.probability < 100
            out["group"] = entry.group
            out["groupWeight"] = entry.group_weight
            out["caseSensitive"] = entry.case_sensitive
            out["matchWholeWords"] = entry.match_whole_words
            out["displayIndex"] = out.get("displayIndex", i)
            extensions = out.get("extensions")
            out["extensions"] = {**(extensions if isinstance(extensions, dict) else {}),
                                 EXTENSION_KEY: {"category_id": entry.category_id,
                                                 "character_id": entry.character_id}}
            key = str(out.get("uid", i))
            entries_map[key] = out
        extension = {EXTENSION_KEY: {
            "schema_version": self.schema_version, "scope_mode": self.scope_mode,
            "categories": copy.deepcopy(self.categories),
            "dependency_edges": copy.deepcopy(self.dependency_edges),
            "import_config": copy.deepcopy(self.import_config),
        }}
        if self.dependency_rules is not None:
            extension[EXTENSION_KEY]["dependency_rules"] = copy.deepcopy(self.dependency_rules)
            extension[EXTENSION_KEY]["related_edges"] = copy.deepcopy(self.related_edges)
            extension[EXTENSION_KEY]["policy_revisions"] = copy.deepcopy(self.policy_revisions)
        return {"entries": entries_map, "extensions": extension}


def auto_classification_patch(book: WorldBook, result) -> dict:
    """把一次分类结果折算成**统一草稿补丁**（分类 + 条目归属 + 角色关联）。

    统一草稿模式下，自动分类不能绕过草稿直接写盘（否则会丢掉用户正在编辑的其它改动）。
    服务端把结论算成一份可以直接 `patch` 进草稿的补丁，前端并入后照常走
    `PUT /configuration` 一次原子提交 —— 校验口径与直接应用完全一致。
    """
    categories = validate_categories(result.categories(existing=book.categories))
    known = {c["id"] for c in categories}
    scope_of = {c["id"]: c.get("scope_type") for c in categories}
    moves: dict[str, str] = {}
    updates: dict[str, dict] = {}
    for entry in book.entries:
        target = result.assignments.get(entry.uid)
        if not target or target not in known:
            target = entry.category_id if entry.category_id in known else UNCLASSIFIED["id"]
        character_id = ""
        if scope_of.get(target) == "character":
            character_id = result.character_ids.get(entry.uid) or entry.character_id or ""
            if not character_id:
                # 角色分类必须带角色目录名，否则保存会被 _validate_entry_scope 拒绝。
                target = UNCLASSIFIED["id"]
        if target != entry.category_id:
            moves[entry.uid] = target
        if character_id != (entry.character_id or ""):
            updates[entry.uid] = {"character_id": character_id}
    return {"categories": categories, "entry_moves": moves, "entry_updates": updates}


def apply_auto_classification(book: WorldBook, first_install: bool = False):
    """按条目自带的可信元数据重建分类与角色关联。

    只改「条目属于哪一类」和随之而来的角色关联，**不碰载入模式、固定导入与依赖策略**。
    调用方负责决定时机：`from_dict` 只在分类形同未分类时自动调用（用户编辑过的分类不会被
    覆盖），接口则用于用户显式点击「自动分类」。

    first_install 仅供预装包首次安装使用：沿用「预装包直接进入按需载入」的既有语义。
    已存在的旧书只修分类，不隐式切换载入模式（旧书仅编辑分类不自动启用按需载入）。
    """
    result = classify_entries(book.entries)
    if not result.matched:
        return result
    patch = auto_classification_patch(book, result)
    book.categories = patch["categories"]
    known = {c["id"] for c in book.categories}
    for entry in book.entries:
        if entry.uid in patch["entry_moves"]:
            entry.category_id = patch["entry_moves"][entry.uid]
        if entry.uid in patch["entry_updates"]:
            entry.character_id = patch["entry_updates"][entry.uid]["character_id"]
        elif entry.category_id in known and book.category_scope_type(entry.category_id) != "character":
            entry.character_id = ""
    if first_install:
        book.scope_mode = "selective"
    return result


# ─────────────────────────────────────────────────────────────
# 管理器
# ─────────────────────────────────────────────────────────────

class WorldBookManager:
    """世界书存储管理器：统一管理 data/worldbooks/（全部可写）。

    整合包（Content Pack）机制：
    - data/packs/<id>.json 为随程序分发的整合包（git 跟踪，分发源）。
    - 首次启动自动安装：把分发源复制到 data/worldbooks/<id>.json（source=preinstalled），
      与用户导入的书在同一列表、同一套规则下管理（启用/停用、编辑、删除、重装）。
    - 预装包被删除后，可通过 reinstall_book() 从分发源一键重装还原。

    绑定解析规则：会话 overlay 显式绑定的书 > 全局默认书 > 已安装且启用的预装包 > None。
    """

    def __init__(self, data_dir: Path | str = None):
        self._dir = Path(data_dir) if data_dir else _WORLDBOOKS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._packs_dir = _PACKS_DIR
        self._cache: dict[str, WorldBook] = {}
        # 按书锁：覆盖「读修订 → 校验 → 提交」整段，避免原子替换仍然丢更新。
        self._book_locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        # 仅默认数据目录自动安装整合包（自定义目录用于测试/隔离，不注入预装内容）
        if data_dir is None:
            self._ensure_packs_installed()

    def book_lock(self, book_id: str) -> threading.RLock:
        """取这本书的写锁（可重入）。同一本书的读-改-写必须整体持锁。"""
        with self._locks_guard:
            lock = self._book_locks.get(book_id)
            if lock is None:
                lock = threading.RLock()
                self._book_locks[book_id] = lock
            return lock

    # ── 整合包安装 ──

    def _ensure_packs_installed(self):
        """启动时把 data/packs/ 下的整合包安装/刷新到 data/worldbooks/。

        按内容指纹（`pack_rev`）判断版本，而不是「存在就跳过」：

        - 目标不存在 → 安装（source=preinstalled，写入指纹）
        - 目标存在、source=preinstalled、指纹落后 → 刷新为新版本；
          刷新前把旧副本留存为 `<id>.json.pre-refresh.bak`（用户对预装书的编辑可恢复）
        - 目标存在、内容其实与分发源一致（旧副本只是缺 pack_rev 字段）→ 只补指纹，不动数据
        - 目标存在但 source 非 preinstalled（用户导入/自建的同名书）→ 不动
        """
        if not self._packs_dir.is_dir():
            return
        for path in sorted(self._packs_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                book_id = str(data.get("id", "")).strip()
                if not book_id:
                    continue
                data["source"] = SOURCE_PREINSTALLED
                data.setdefault("enabled", True)
                rev = _pack_rev(data)
                target = self._path(book_id)

                if not target.is_file():
                    self._write_pack(target, data, rev)
                    logger.info("已安装预装整合包: %s (%s)", data.get("name", book_id), book_id)
                    continue

                old = self._read_json(target)
                if old is None:
                    self._write_pack(target, data, rev)
                    logger.warning("预装整合包副本无法解析，已按分发源重装: %s", book_id)
                    continue
                if str(old.get("source") or "") not in (SOURCE_PREINSTALLED, "builtin"):
                    continue  # 同名用户书，不覆盖
                if str(old.get("pack_rev") or "") == rev:
                    continue  # 已是最新
                if _pack_rev(old) == rev:
                    # 内容一致，只是旧副本没有指纹字段 → 补上即可，不改数据、不留备份
                    self._write_pack(target, {**old, "source": SOURCE_PREINSTALLED}, rev)
                    continue

                backup = target.with_name(target.name + _PACK_BACKUP_SUFFIX)
                try:
                    backup.write_bytes(target.read_bytes())
                except OSError as e:
                    logger.warning("留存旧副本失败 %s: %s", backup.name, e)
                self._write_pack(target, data, rev)
                logger.info("已刷新预装整合包: %s (%s) → %d 条；旧副本留存于 %s",
                            data.get("name", book_id), book_id,
                            len(data.get("entries", [])), backup.name)
            except Exception as e:
                logger.warning("安装整合包 %s 失败: %s", path.name, e)

    @staticmethod
    def _read_json(path: Path) -> Optional[dict]:
        """读 JSON 对象；解析失败或不是对象时返回 None。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def _write_pack(self, target: Path, data: dict, rev: str):
        """把整合包内容写入安装副本（统一补 source/enabled/pack_rev）。"""
        payload = dict(data)
        payload["source"] = SOURCE_PREINSTALLED
        payload.setdefault("enabled", True)
        payload["pack_rev"] = rev
        self._cache.pop(target.stem, None)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def is_preinstalled(self, book_id: str) -> bool:
        """该书是否存在分发源（可一键重装）。"""
        return (self._packs_dir / f"{book_id}.json").is_file()

    # ── 路径 ──

    def _path(self, book_id: str) -> Path:
        """统一存储路径（预装包安装副本与导入书同目录）。"""
        return self._dir / f"{book_id}.json"

    def _pack_path(self, book_id: str) -> Path:
        """整合包分发源路径。"""
        return self._packs_dir / f"{book_id}.json"

    def _settings_path(self) -> Path:
        return self._dir / "settings.json"

    def _load_settings(self) -> dict:
        path = self._settings_path()
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("读取世界书设置失败: %s", e)
        return {"default_book_id": None}

    def _save_settings(self, settings: dict):
        path = self._settings_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # ── 默认书 ──

    def get_default_book_id(self) -> Optional[str]:
        return self._load_settings().get("default_book_id")

    def set_default_book_id(self, book_id: Optional[str]):
        settings = self._load_settings()
        settings["default_book_id"] = book_id
        self._save_settings(settings)

    # ── CRUD ──

    def list_books(self) -> list[dict]:
        """列出所有书（统一列表）：预装包在前，导入书按创建时间倒序。"""
        default_id = self.get_default_book_id()
        books = []

        preinstalled = []
        imported = []
        for path in sorted(self._dir.glob("*.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name == "settings.json":
                continue
            try:
                book = self.load(path.stem)
            except Exception as e:
                logger.warning("加载世界书 %s 失败: %s", path.name, e)
                continue
            summary = self._summary(book, default_id)
            (preinstalled if book.source == SOURCE_PREINSTALLED else imported).append(summary)

        # 预装包固定顺序在前（与分发源顺序一致），导入书按时间倒序
        preinstalled.sort(key=lambda s: s["name"])
        books.extend(preinstalled)
        books.extend(imported)
        return books

    def _summary(self, book: "WorldBook", default_id: Optional[str]) -> dict:
        return {
            "id": book.id,
            "name": book.name,
            "source_format": book.source_format,
            "source": book.source,
            "is_preinstalled": self.is_preinstalled(book.id),
            "enabled": book.enabled,
            "budget_tokens": book.budget_tokens,
            "entry_count": len(book.entries),
            "created_at": book.created_at,
            "updated_at": book.updated_at,
            "is_default": book.id == default_id,
        }

    def load(self, book_id: str) -> Optional[WorldBook]:
        if book_id in self._cache:
            return self._cache[book_id]
        path = self._path(book_id)
        if not path.is_file():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        book = WorldBook.from_dict(data)
        if self.is_preinstalled(book_id):
            # 有分发源的书一律视为预装包安装副本（防旧数据缺字段）
            book.source = SOURCE_PREINSTALLED
        self._cache[book_id] = book
        return book

    def save(self, book: WorldBook):
        """统一保存（预装包安装副本与导入书同样可写）。"""
        book.updated_at = time.time()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._dir,
                                             prefix=".worldbook-", suffix=".tmp", delete=False) as f:
                temporary = Path(f.name)
                json.dump(book.to_dict(), f, ensure_ascii=False, indent=2)
                f.write("\n")
            temporary.replace(self._path(book.id))
            self._cache[book.id] = book
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def create_book(self, name: str, entries: list = None,
                    source_format: str = SOURCE_MANUAL,
                    budget_tokens: int = 0) -> WorldBook:
        book_id = uuid.uuid4().hex[:12]
        book = WorldBook(book_id, name=name, entries=entries,
                         source_format=source_format, budget_tokens=budget_tokens,
                         source="imported", categories=copy.deepcopy(DEFAULT_CATEGORIES))
        self.save(book)
        return book

    def import_book(self, name: str, source) -> tuple[WorldBook, ImportReport]:
        """解析并创建一本书。source 为 dict 或 str（JSON/JSONL 文本）。"""
        entries, report = parse_lorebook(source)
        obj = source
        if isinstance(source, str):
            try:
                obj = json.loads(source)
            except ValueError:
                obj = None
        extension = find_scope_extension(obj)
        book = WorldBook(uuid.uuid4().hex[:12], name or "导入的世界书", entries,
                         source_format=report.source_format, scope_mode="legacy")
        if extension:
            if not isinstance(extension.get("import_config", {}), dict):
                raise ValueError("导入的 import_config 必须是对象")
            book.categories = validate_categories(extension.get("categories", []))
            mode = extension.get("scope_mode", "legacy")
            if mode not in ("legacy", "selective"):
                raise ValueError("导入的范围模式无效")
            book.scope_mode = mode
            config, edges = validate_policy({e.uid for e in entries}, {
                **extension.get("import_config", {}), "dependency_edges": extension.get("dependency_edges", [])})
            config["revision"] = max(1, _to_int(extension.get("import_config", {}).get("revision"), 1))
            book.import_config, book.dependency_edges = config, edges
            if any(e.category_id not in {c["id"] for c in book.categories} for e in entries):
                raise ValueError("导入的条目引用了不存在的分类")
            # v3 规则随书回灌；旧书（无 dependency_rules）保持 v2 语义不变。
            rules = extension.get("dependency_rules")
            if isinstance(rules, dict):
                book.dependency_rules, book.dependency_edges, book.related_edges = (
                    validate_v3_rules({e.uid for e in entries}, {
                        **rules, "dependency_edges": extension.get("dependency_edges", []),
                        "related_edges": extension.get("related_edges", []),
                    }))
                book.schema_version = 3
                book.policy_revisions = book._normalize_revisions(extension.get("policy_revisions"))
        self.save(book)
        return book, report

    def duplicate_book(self, book_id: str, new_name: str = None) -> WorldBook:
        """复制任意书为新的导入书（做变体/备份）。"""
        book = self.load(book_id)
        if not book:
            raise ValueError("世界书不存在")
        new_id = uuid.uuid4().hex[:12]
        new_book = WorldBook(
            new_id,
            name=(new_name or f"{book.name}（副本）").strip(),
            entries=copy.deepcopy(book.entries),
            source_format=book.source_format,
            budget_tokens=book.budget_tokens,
            source="imported",
            enabled=book.enabled,
            categories=copy.deepcopy(book.categories),
            dependency_edges=copy.deepcopy(book.dependency_edges),
            import_config=copy.deepcopy(book.import_config),
            scope_mode=book.scope_mode,
            dependency_rules=copy.deepcopy(book.dependency_rules),
            related_edges=copy.deepcopy(book.related_edges),
            policy_revisions=copy.deepcopy(book.policy_revisions),
        )
        new_book.created_at = time.time()
        new_book.updated_at = time.time()
        self.save(new_book)
        return new_book

    def reinstall_book(self, book_id: str) -> WorldBook:
        """从分发源一键重装预装整合包（恢复出厂内容，覆盖现有安装副本）。"""
        pack_path = self._pack_path(book_id)
        if not pack_path.is_file():
            raise ValueError(f"{book_id} 不是预装整合包，无法重装")
        with open(pack_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["source"] = SOURCE_PREINSTALLED
        data.setdefault("enabled", True)
        # 同时写入内容指纹，避免下次启动被判定为「落后」再刷一遍
        self._write_pack(self._path(book_id), data, _pack_rev(data))
        book = self.load(book_id)
        logger.info("已重装预装整合包: %s (%s)", book.name, book_id)
        return book

    def delete_book(self, book_id: str) -> bool:
        """统一删除（预装包删除后可通过「重装」从分发源还原）。"""
        book = self.load(book_id)
        if book is None:
            return False
        if self.get_default_book_id() == book_id:
            self.set_default_book_id(None)
        self._cache.pop(book_id, None)
        path = self._path(book_id)
        if path.is_file():
            path.unlink()
            logger.info("已删除世界书: %s", book_id)
            return True
        return False

    # ── 检索 ──

    def search_books(self, q: str, limit: int = 30) -> list[dict]:
        """跨书/条目检索：书名、条目名、条目内容、触发词（仅检索已安装的书）。"""
        q = (q or "").strip().lower()
        if not q:
            return []
        default_id = self.get_default_book_id()
        results = []
        paths = sorted(self._dir.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths:
            if path.name == "settings.json":
                continue
            try:
                book = self.load(path.stem)
            except Exception:
                continue
            matched_entries = [
                e for e in book.entries
                if q in e.name.lower()
                or q in e.content.lower()
                or any(q in k.lower() for k in e.trigger_keys)
            ]
            if q in book.name.lower() or q in book.id.lower():
                matched_entries = book.entries
            if not matched_entries:
                continue
            results.append({
                "book": self._summary(book, default_id),
                "matches": [e.to_dict() for e in matched_entries[:limit]],
                "match_count": len(matched_entries),
            })
            if len(results) >= limit:
                break
        return results

    # ── 会话绑定解析 ──

    def resolve(self, overlay=None) -> Optional[WorldBook]:
        """解析会话当前生效的世界书：会话绑定 > 全局默认书 > 已安装且启用的预装包。

        Args:
            overlay: SessionOverlay 实例（可空）。
        """
        book_id = None
        if overlay is not None:
            # 新会话显式“不绑定”不得回退全书；已存快照的书被删除/停用也不改绑。
            scope = getattr(overlay, "get_worldbook_scope", lambda: None)()
            if scope is not None:
                book_id = scope.get("book_id")
                book = self.load(book_id) if book_id else None
                return book if book and book.enabled else None
            try:
                book_id = overlay.get_worldbook_id()
            except Exception:
                book_id = None
        if not book_id:
            book_id = self.get_default_book_id()
        if not book_id:
            return self._fallback_preinstalled()
        try:
            book = self.load(book_id)
        except Exception as e:
            logger.warning("加载会话世界书 %s 失败: %s", book_id, e)
            return None
        # 书级停用：显式绑定/默认书被停用时不生效，回退预装包
        if book is None or not book.enabled:
            logger.info("世界书 %s 不存在或已停用，回退预装包", book_id)
            return self._fallback_preinstalled()
        return book

    def _fallback_preinstalled(self) -> Optional[WorldBook]:
        for bid in _PACK_FALLBACK_IDS:
            book = self.load(bid)
            if book is not None and book.source == SOURCE_PREINSTALLED and book.enabled:
                return book
        return None
