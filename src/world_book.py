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
import json
import logging
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WORLDBOOKS_DIR = _PROJECT_ROOT / "data" / "worldbooks"

# 支持探测的来源格式标签
SOURCE_V1 = "sillytavern_v1"
SOURCE_V2 = "sillytavern_v2"
SOURCE_CARD = "character_card"
SOURCE_JSONL = "chat_backup_jsonl"
SOURCE_MANUAL = "manual"


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
    """一本世界书：id + 元信息 + 条目集合 + 触发/格式化逻辑。"""

    def __init__(self, book_id: str, name: str = "", entries: list = None,
                 source_format: str = SOURCE_MANUAL, budget_tokens: int = 0):
        self.id = book_id
        self.name = name or book_id
        self.source_format = source_format
        self.budget_tokens = budget_tokens  # 0 = 不限制
        self.created_at = time.time()
        self.updated_at = time.time()
        self.entries: list[WorldBookEntry] = list(entries or [])

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "source_format": self.source_format,
            "budget_tokens": self.budget_tokens,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entries": [e.to_dict() for e in self.entries],
        }

    @staticmethod
    def from_dict(data: dict) -> "WorldBook":
        book = WorldBook(
            book_id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            source_format=str(data.get("source_format", SOURCE_MANUAL)),
            budget_tokens=int(data.get("budget_tokens", 0)),
        )
        book.created_at = float(data.get("created_at", time.time()))
        book.updated_at = float(data.get("updated_at", time.time()))
        book.entries = [WorldBookEntry.from_dict(e) for e in data.get("entries", [])]
        return book

    # ── 触发 ──

    def collect_matches(self, recent_text: str, current_input: str,
                        rng: random.Random = None) -> list[WorldBookEntry]:
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
            (before, after)：position=0 的条目文本、position=1 的条目文本。
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
            if entry.position == 0:
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
            out["uid"] = out.get("uid", entry.uid)
            out["key"] = _first(out, "key", default=entry.trigger_keys)
            out["keysecondary"] = _first(out, "keysecondary", default=entry.secondary_keys)
            out["comment"] = _first(out, "comment", default=entry.name)
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
            key = str(out.get("uid", i))
            entries_map[key] = out
        return {"entries": entries_map}


# ─────────────────────────────────────────────────────────────
# 管理器
# ─────────────────────────────────────────────────────────────

class WorldBookManager:
    """世界书存储管理器：data/worldbooks/ 目录 + 会话绑定 + 全局默认书。

    绑定解析规则：会话 overlay 显式绑定的书 > 全局默认书 > None。
    """

    def __init__(self, data_dir: Path | str = None):
        self._dir = Path(data_dir) if data_dir else _WORLDBOOKS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, WorldBook] = {}

    # ── 路径 ──

    def _path(self, book_id: str) -> Path:
        return self._dir / f"{book_id}.json"

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
        """列出所有书（按创建时间倒序）。"""
        books = []
        default_id = self.get_default_book_id()
        for path in sorted(self._dir.glob("*.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name == "settings.json":
                continue
            try:
                book = self.load(path.stem)
            except Exception as e:
                logger.warning("加载世界书 %s 失败: %s", path.name, e)
                continue
            books.append({
                "id": book.id,
                "name": book.name,
                "source_format": book.source_format,
                "budget_tokens": book.budget_tokens,
                "entry_count": len(book.entries),
                "created_at": book.created_at,
                "updated_at": book.updated_at,
                "is_default": book.id == default_id,
            })
        return books

    def load(self, book_id: str) -> Optional[WorldBook]:
        if book_id in self._cache:
            return self._cache[book_id]
        path = self._path(book_id)
        if not path.is_file():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        book = WorldBook.from_dict(data)
        self._cache[book_id] = book
        return book

    def save(self, book: WorldBook):
        book.updated_at = time.time()
        self._cache[book.id] = book
        with open(self._path(book.id), "w", encoding="utf-8") as f:
            json.dump(book.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")

    def create_book(self, name: str, entries: list = None,
                    source_format: str = SOURCE_MANUAL,
                    budget_tokens: int = 0) -> WorldBook:
        book_id = uuid.uuid4().hex[:12]
        book = WorldBook(book_id, name=name, entries=entries,
                         source_format=source_format, budget_tokens=budget_tokens)
        self.save(book)
        return book

    def import_book(self, name: str, source) -> tuple[WorldBook, ImportReport]:
        """解析并创建一本书。source 为 dict 或 str（JSON/JSONL 文本）。"""
        entries, report = parse_lorebook(source)
        book = self.create_book(name or "导入的世界书", entries=entries,
                                source_format=report.source_format)
        return book, report

    def delete_book(self, book_id: str) -> bool:
        if self.get_default_book_id() == book_id:
            self.set_default_book_id(None)
        self._cache.pop(book_id, None)
        path = self._path(book_id)
        if path.is_file():
            path.unlink()
            logger.info("已删除世界书: %s", book_id)
            return True
        return False

    # ── 会话绑定解析 ──

    def resolve(self, overlay=None) -> Optional[WorldBook]:
        """解析会话当前生效的世界书：会话绑定 > 全局默认书。

        Args:
            overlay: SessionOverlay 实例（可空）。
        """
        book_id = None
        if overlay is not None:
            try:
                book_id = overlay.get_worldbook_id()
            except Exception:
                book_id = None
        if not book_id:
            book_id = self.get_default_book_id()
        if not book_id:
            return None
        try:
            return self.load(book_id)
        except Exception as e:
            logger.warning("加载会话世界书 %s 失败: %s", book_id, e)
            return None
