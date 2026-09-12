"""剧情节点图（Plot Graph）—— 自由画布布局的序列化与世界书存取。

一个剧情一张图。图文档（graph doc）是**布局层**数据：节点坐标、类型、连线
与分支关系、自由备注内容。剧情/节拍/战斗的"内容真相源"不变
（data/plots/<plot_id>/index.md 与 data/combat/nodes/<node_id>.json），
图节点通过 `ref` 引用它们，因此图可随意增删重排而不伤及底层数据。

**保存粒度：一个剧情一条世界书条目**（uid = `plot_graph_<plot_id>`）：
- 节点坐标与连线是强关联数据，拆成每节点一条会产生跨条目一致性负担
  （半张图、孤儿连线），单条目天然原子——导入/导出/删除都是整图操作；
- 与战斗节点条目（`combat-node` 围栏）同构：content 内 ```json plot-graph
  围栏块 + raw.extensions.arknights_tavern.entry_type 标记，世界书导出回灌
  酒馆时原样保留 raw，做到无损往返；
- 条目 trigger_keys 留空且非常驻：布局数据只服务编辑器，**绝不注入叙事上下文**
  （这与战斗节点条目不同——后者有关键词，会随剧情提及而注入）。

图文档结构（schema_version=1）：
    {
      "schema_version": 1,
      "plot_id": "fengxue_guojing",
      "title": "风雪过境",              # 冗余展示名，读取时以剧情文档为准
      "worldbook_id": "arknights",      # 归属书（保存时后端强制回填）
      "nodes": [{
        "id": "n_k3x9q2",              # 图内唯一（n_ + base36）
        "type": "plot|chapter|beat|combat|note",
        "title": "...", "content": "",  # note 节点承载自由文本；引用节点仅存备注
        "x": 120, "y": 80,
        "ref": null | {"chapter_idx": 1, "beat_id": "beat_x"}
                     | {"node_id": "enc_x"},   # 对底层数据的引用
      }],
      "edges": [{"id": "e_k3x9q3", "from": "n_a", "to": "n_b"}],
      "updated_at": 1730000000.0,
    }

无损性：`save_graph` 只做结构校验与默认值回填，不删除任何未知字段；
`decode_graph_entry` 原样返回 JSON 对象。前端新增字段可透传保存。
"""

from __future__ import annotations

import json
import logging
import re
import time

from world_book import WorldBookEntry

logger = logging.getLogger(__name__)

# 世界书条目承载图文档时的围栏标记与扩展命名空间（与 combat_nodes 同构）
WORLD_BOOK_FENCE = "plot-graph"
_ENTRY_TYPE = "plot_graph"
_EXT_NAMESPACE = "arknights_tavern"
_FENCE_RE = re.compile(r"```json\s+plot-graph\s*\n(.*?)\n```", re.DOTALL)

ENTRY_UID_PREFIX = "plot_graph_"
SCHEMA_VERSION = 1
NODE_TYPES = ("plot", "chapter", "beat", "combat", "note")

# 规模上限：防误操作把世界书条目撑爆（一屏剧情远用不满）
MAX_NODES = 500
MAX_EDGES = 1000


class GraphError(ValueError):
    """图文档校验失败（`errors` 为可读原因列表）。"""

    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("；".join(self.errors))


def entry_uid(plot_id: str) -> str:
    """图文档条目的固定 uid：一个剧情在书里至多一张图。"""
    return f"{ENTRY_UID_PREFIX}{plot_id}"


# ── 规范化与校验 ──

def normalize_graph(doc: dict, *, plot_id: str = "",
                    worldbook_id: str = "") -> dict:
    """回填默认值、收敛类型；保留未知字段（无损）。就地修改并返回 doc。"""
    doc = dict(doc or {})
    doc.setdefault("schema_version", SCHEMA_VERSION)
    doc["schema_version"] = int(doc.get("schema_version") or SCHEMA_VERSION)
    if plot_id:
        doc["plot_id"] = plot_id
    if worldbook_id:
        doc["worldbook_id"] = worldbook_id
    doc.setdefault("title", "")
    doc.setdefault("updated_at", 0)

    nodes: list[dict] = []
    for raw in doc.get("nodes") or []:
        if not isinstance(raw, dict):
            continue
        node = dict(raw)
        node["id"] = str(node.get("id") or "").strip()
        ntype = str(node.get("type") or "note")
        # 未知类型收敛为 note（前向兼容：旧前端读新文件不崩）
        node["type"] = ntype if ntype in NODE_TYPES else "note"
        node["title"] = str(node.get("title") or "")
        node.setdefault("content", "")
        try:
            node["x"] = round(float(node.get("x") or 0), 1)
            node["y"] = round(float(node.get("y") or 0), 1)
        except (TypeError, ValueError):
            node["x"], node["y"] = 0.0, 0.0
        ref = node.get("ref")
        node["ref"] = dict(ref) if isinstance(ref, dict) and ref else None
        nodes.append(node)
    doc["nodes"] = nodes

    edges: list[dict] = []
    for raw in doc.get("edges") or []:
        if not isinstance(raw, dict):
            continue
        edge = dict(raw)
        edge["id"] = str(edge.get("id") or "").strip()
        edge["from"] = str(edge.get("from") or "").strip()
        edge["to"] = str(edge.get("to") or "").strip()
        edges.append(edge)
    doc["edges"] = edges
    return doc


def validate_graph(doc: dict, *, plot_id: str = "") -> list[str]:
    """结构校验：返回错误列表（空列表 = 通过）。不抛异常。"""
    errors: list[str] = []
    doc = doc or {}
    pid = str(plot_id or doc.get("plot_id") or "").strip()
    if not pid:
        errors.append("缺少 plot_id")

    nodes = doc.get("nodes")
    if not isinstance(nodes, list):
        errors.append("nodes 应为数组")
        nodes = []
    if len(nodes) > MAX_NODES:
        errors.append(f"节点数 {len(nodes)} 超过上限 {MAX_NODES}")

    ids: set[str] = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{i}] 不是对象")
            continue
        nid = str(node.get("id") or "").strip()
        if not nid:
            errors.append(f"nodes[{i}] 缺少 id")
        elif nid in ids:
            errors.append(f"节点 id 重复: {nid}")
        else:
            ids.add(nid)
        if len(nid) > 64:
            errors.append(f"节点 id 过长: {nid[:32]}…")

    edges = doc.get("edges")
    if not isinstance(edges, list):
        errors.append("edges 应为数组")
        edges = []
    if len(edges) > MAX_EDGES:
        errors.append(f"连线数 {len(edges)} 超过上限 {MAX_EDGES}")

    seen_pairs: set[tuple[str, str]] = set()
    edge_ids: set[str] = set()
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"edges[{i}] 不是对象")
            continue
        eid = str(edge.get("id") or "").strip()
        src = str(edge.get("from") or "").strip()
        dst = str(edge.get("to") or "").strip()
        if not eid:
            errors.append(f"edges[{i}] 缺少 id")
        elif eid in edge_ids:
            errors.append(f"连线 id 重复: {eid}")
        else:
            edge_ids.add(eid)
        if not src or not dst:
            errors.append(f"edges[{i}] 缺少 from/to")
            continue
        if src not in ids or dst not in ids:
            errors.append(f"连线 {eid} 引用了不存在的节点（{src} → {dst}）")
        elif src == dst:
            errors.append(f"连线 {eid} 是自环（{src} → {dst}）")
        elif (src, dst) in seen_pairs:
            errors.append(f"连线 {eid} 重复（{src} → {dst}）")
        else:
            seen_pairs.add((src, dst))
    return errors


# ── 世界书编解码（与 combat_nodes.encode_node_for_worldbook 同构） ──

def encode_graph_for_worldbook(doc: dict, *, display_name: str = "") -> dict:
    """把图文档编码为世界书条目（content 围栏块 + raw.extensions 标记）。

    trigger_keys 留空且非常驻：布局数据不进叙事注入（见模块 docstring）。
    """
    payload = {k: v for k, v in (doc or {}).items() if k != "_hash"}
    plot_id = str(payload.get("plot_id") or "")
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    name = display_name or str(payload.get("title") or "") or plot_id
    lines = [f"```json {WORLD_BOOK_FENCE}", compact, "```"]
    return {
        "uid": entry_uid(plot_id),
        "name": f"节点图：{name}",
        "content": "\n".join(lines),
        "trigger_keys": [],
        "raw": {
            "extensions": {
                _EXT_NAMESPACE: {
                    "entry_type": _ENTRY_TYPE,
                    "plot_id": plot_id,
                }
            }
        },
    }


def is_graph_entry(entry: dict) -> bool:
    """判断世界书条目是否承载剧情节点图（extensions 标记或围栏块）。"""
    raw = (entry or {}).get("raw") or {}
    ext = ((raw.get("extensions") or {}).get(_EXT_NAMESPACE) or {})
    if ext.get("entry_type") == _ENTRY_TYPE:
        return True
    if ext.get("plot_id") and _FENCE_RE.search(str((entry or {}).get("content") or "")):
        return True
    return bool(_FENCE_RE.search(str((entry or {}).get("content") or "")))


def decode_graph_entry(entry: dict) -> dict | None:
    """从世界书条目解出图文档；不是图条目返回 None；JSON 损坏抛 GraphError。"""
    if not is_graph_entry(entry):
        return None
    content = str((entry or {}).get("content") or "")
    match = _FENCE_RE.search(content)
    if not match:
        raise GraphError(f"节点图条目 '{entry.get('name', '')}' 缺少 ```json {WORLD_BOOK_FENCE} 代码块")
    try:
        data = json.loads(match.group(1))
    except ValueError as e:
        raise GraphError(f"节点图条目 '{entry.get('name', '')}' 的 JSON 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise GraphError(f"节点图条目 '{entry.get('name', '')}' 的内容应为 JSON 对象")
    raw = (entry or {}).get("raw") or {}
    ext = ((raw.get("extensions") or {}).get(_EXT_NAMESPACE) or {})
    if ext.get("plot_id"):
        data.setdefault("plot_id", ext["plot_id"])
    return data


# ── 存取（WorldBookManager 为唯一落点） ──

def _find_entry(book, plot_id: str):
    """按 uid / extensions 标记双重定位图条目（uid 是约定，ext 是兜底）。"""
    target = entry_uid(plot_id)
    for entry in book.entries:
        if entry.uid == target:
            return entry
    for entry in book.entries:
        raw = (entry.raw or {}).get("extensions", {}).get(_EXT_NAMESPACE, {})
        if raw.get("entry_type") == _ENTRY_TYPE and raw.get("plot_id") == plot_id:
            return entry
    return None


def load_graph(book_mgr, book_id: str, plot_id: str) -> dict | None:
    """读取某书某剧情的图文档；不存在返回 None。损坏条目按 None 处理并告警。"""
    book = book_mgr.load(book_id) if book_id else None
    if book is None:
        return None
    entry = _find_entry(book, plot_id)
    if entry is None:
        return None
    try:
        doc = decode_graph_entry(entry.to_dict())
    except GraphError as e:
        logger.warning("节点图条目损坏（%s/%s）: %s", book_id, plot_id, e)
        return None
    if doc is None:
        return None
    return normalize_graph(doc, plot_id=plot_id)


def save_graph(book_mgr, book_id: str, doc: dict, *,
               display_name: str = "") -> dict:
    """校验并整图写入世界书条目（同剧情旧条目被替换，保证单条目粒度）。

    返回落盘后的图文档（含 updated_at）。
    """
    plot_id = str((doc or {}).get("plot_id") or "").strip()
    if not book_id:
        raise GraphError("缺少 book_id（图文档归属于某本世界书）")
    if not plot_id:
        raise GraphError("缺少 plot_id")
    doc = normalize_graph(doc, plot_id=plot_id, worldbook_id=book_id)
    errors = validate_graph(doc, plot_id=plot_id)
    if errors:
        raise GraphError(errors)

    doc["updated_at"] = time.time()
    book = book_mgr.load(book_id)
    if book is None:
        raise GraphError(f"世界书不存在: {book_id}")

    entry_data = encode_graph_for_worldbook(doc, display_name=display_name)
    existing = _find_entry(book, plot_id)
    new_entry = WorldBookEntry.from_dict(entry_data)
    if existing is not None:
        # 条目由本模块独占管理：整条替换（保留原 uid 位置）
        index = book.entries.index(existing)
        book.entries[index] = new_entry
    else:
        book.entries.append(new_entry)
    book_mgr.save(book)
    logger.info("剧情节点图已保存: %s → 世界书 %s（%d 节点 / %d 连线）",
                plot_id, book_id, len(doc["nodes"]), len(doc["edges"]))
    return doc


def delete_graph(book_mgr, book_id: str, plot_id: str) -> bool:
    """删除某剧情的图条目（不影响剧情/战斗底层数据）。"""
    book = book_mgr.load(book_id) if book_id else None
    if book is None:
        return False
    entry = _find_entry(book, plot_id)
    if entry is None:
        return False
    book.entries.remove(entry)
    book_mgr.save(book)
    logger.info("剧情节点图已删除: %s ← 世界书 %s", plot_id, book_id)
    return True


def list_graphs(book_mgr, book_id: str) -> list[str]:
    """列出某书里已有图文档的 plot_id 列表（书未定义归属的按条目内 worldbook_id）。"""
    result: list[str] = []
    book = book_mgr.load(book_id) if book_id else None
    if book is None:
        return result
    for entry in book.entries:
        raw = ((entry.raw or {}).get("extensions") or {}).get(_EXT_NAMESPACE) or {}
        if raw.get("entry_type") == _ENTRY_TYPE and raw.get("plot_id"):
            result.append(str(raw["plot_id"]))
    return sorted(set(result))
