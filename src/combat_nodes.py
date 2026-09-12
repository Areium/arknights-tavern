"""战斗节点注册表：JSON 读写、校验、剧情节拍绑定与世界书编解码。

战斗节点是"一场战斗"的唯一真相源（`data/combat/nodes/<node_id>.json`）：

- **地图**：`map.{rows,cols,tiles,tile_defs,deploy}`（校验见 `combat_map.resolve_map`）
- **敌人**：`waves[].enemies[]`（`enemy`/`count`/`positions`/可选 `stats` 数值覆盖），
  或 `enemies_def` 内联定义（节点自包含，随世界书一起搬家）
- **绑定**：`bind.{plot_id,chapter_id,beat_id}` —— 剧情节拍里用 `[COMBAT:<node_id>]` 引用
- **世界书**：节点可编码为一条世界书条目（```json combat-node 围栏块），
  导入世界书即落地为节点文件，导出时从注册表回灌

写盘走 `compute_json_hash` 冲突检测（409），与卡牌编辑一致。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from combat_map import MapError, resolve_map
from shared.json_hash import compute_json_hash

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
NODE_DIR = _PROJECT_ROOT / "data" / "combat" / "nodes"
TILES_DIR = _PROJECT_ROOT / "data" / "combat" / "tiles"
PLOT_DIR = _PROJECT_ROOT / "data" / "plots"

TEMPLATE_STEM = "TEMPLATE_node"

# 规模上限（与 combat_map 的尺寸上限配套，防止一屏塞几百个单位）
MAX_WAVES = 6
MAX_UNITS_PER_WAVE = 12
MAX_TOTAL_UNITS = 48

# 世界书条目承载战斗节点时的围栏标记
WORLD_BOOK_FENCE = "combat-node"
_ENTRY_TYPE = "combat_node"
_EXT_NAMESPACE = "arknights_tavern"
_FENCE_RE = re.compile(r"```json\s+combat-node\s*\n(.*?)\n```", re.DOTALL)


class NodeError(ValueError):
    """节点校验失败（`errors` 为可读原因列表）。"""

    def __init__(self, errors: list[str] | str):
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("；".join(self.errors))


class NodeConflictError(NodeError):
    """`_hash` 不匹配：文件已被其他进程/窗口修改，拒绝覆盖。"""


# ── 路径与读取 ──

def node_path(node_id: str) -> Path:
    return NODE_DIR / f"{node_id}.json"


def node_exists(node_id: str) -> bool:
    return node_path(node_id).is_file()


def load_node_file(node_id: str) -> dict | None:
    """直接读节点文件（不经过 loader 的别名索引，编辑器保存前校验用）。"""
    path = node_path(node_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise NodeError(f"节点文件解析失败 {path.name}: {e}") from e
    data.setdefault("node_id", path.stem)
    return data


def list_node_files() -> list[Path]:
    if not NODE_DIR.is_dir():
        return []
    return sorted(p for p in NODE_DIR.glob("*.json")
                  if not p.stem.upper().startswith("TEMPLATE"))


def template_data() -> dict:
    """模板节点（新建时的默认骨架）；模板缺失时给内置最小骨架。"""
    path = NODE_DIR / f"{TEMPLATE_STEM}.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("_hash", None)
            return data
        except (OSError, ValueError):
            logger.warning("模板节点解析失败，使用内置骨架: %s", path)
    return {
        "schema_version": 1,
        "node_id": "",
        "name": "",
        "summary": "",
        "bind": {"plot_id": "", "chapter_id": "", "beat_id": ""},
        "rules": {"range_metric": "manhattan", "allow_corner_cut": False},
        "map": {
            "rows": 7, "cols": 7, "tiles": "ground",
            "deploy": {"player": {"rect": [3, 0, 5, 1]},
                       "enemy": {"rect": [3, 5, 5, 6]}},
        },
        "waves": [{"enemies": []}],
        "conditions": {"max_rounds": 8, "escape_enabled": True},
        "rewards": {"xp": 0, "items": [], "unlock": []},
        "difficulty": {"category": "test", "encounter_type": "normal",
                       "band": "T1", "threat_budget": 0, "target_rounds": 4},
        "balance_version": 1,
    }


# ── 校验 ──

def validate_node(data: dict, *, enemy_names: set[str] | None = None,
                  include_balance: bool = True) -> dict:
    """校验节点规格。

    返回 `{"errors": [...], "warnings": [...], "metrics": {...}}`；不抛异常，
    便于编辑器实时提示。`metrics.threat` 为威胁/预算/阶段带对照（设计者调难度用）。
    """
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict = {}
    data = data or {}

    node_id = str(data.get("node_id") or "").strip()
    if not node_id:
        errors.append("缺少 node_id")
    elif not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff-]{1,64}", node_id):
        errors.append(f"node_id '{node_id}' 含非法字符（允许中英文/数字/下划线/连字符）")
    if not str(data.get("name") or "").strip():
        errors.append("缺少 name")

    # 地图（尺寸/格子/部署区/软锁）
    try:
        battle_map = resolve_map(data.get("map"), tiles_dir=TILES_DIR)
        warnings.extend(battle_map.warnings)
    except MapError as e:
        battle_map = None
        errors.extend(e.errors)

    inline_enemies = set((data.get("enemies_def") or {}).keys())
    known = set(enemy_names or set()) | inline_enemies

    waves = data.get("waves") or []
    if not isinstance(waves, list) or not waves:
        errors.append("至少需要 1 个波次（waves）")
        waves = []
    if len(waves) > MAX_WAVES:
        errors.append(f"波次数 {len(waves)} 超过上限 {MAX_WAVES}")

    total_units = 0
    for wi, wave in enumerate(waves):
        entries = (wave or {}).get("enemies")
        if not isinstance(entries, list):
            errors.append(f"wave[{wi}] 缺少 enemies 数组")
            continue
        units = 0
        used_positions: set[tuple[int, int]] = set()
        for ei, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"wave[{wi}].enemies[{ei}] 不是对象")
                continue
            name = str(entry.get("enemy") or entry.get("name") or "").strip()
            label = f"wave[{wi}].enemies[{ei}]"
            if not name:
                errors.append(f"{label} 缺少 enemy 名称")
                continue
            if known and name not in known:
                errors.append(f"{label} 引用了未知敌人 '{name}'（既不在地图词典也不在 enemies_def）")
            try:
                count = int(entry.get("count", 1) or 1)
            except (TypeError, ValueError):
                errors.append(f"{label}.count 非整数")
                continue
            if not 1 <= count <= MAX_UNITS_PER_WAVE:
                errors.append(f"{label}.count {count} 超出 1..{MAX_UNITS_PER_WAVE}")
            units += count

            positions = entry.get("positions") or []
            if positions and len(positions) != count:
                warnings.append(f"{label} 站位 {len(positions)} 个与数量 {count} 不符，缺的会自动落位")
            if battle_map:
                for pos in positions:
                    try:
                        cell = (int(pos[0]), int(pos[1]))
                    except (TypeError, ValueError, IndexError):
                        errors.append(f"{label} 站位 {pos} 非法")
                        continue
                    if not battle_map.in_bounds(cell):
                        errors.append(f"{label} 站位 {cell} 越界（地图 {battle_map.rows}×{battle_map.cols}）")
                    elif battle_map.is_blocked(cell):
                        errors.append(f"{label} 站位 {cell} 落在不可通行格")
                    elif cell in used_positions:
                        warnings.append(f"{label} 站位 {cell} 与同波次其它单位重复，会顺延落位")
                    used_positions.add(cell)
            stats = entry.get("stats") or entry.get("combat_stats")
            if stats is not None and not isinstance(stats, dict):
                errors.append(f"{label}.stats 应为对象（数值覆盖）")
        if units > MAX_UNITS_PER_WAVE:
            errors.append(f"wave[{wi}] 单位数 {units} 超过上限 {MAX_UNITS_PER_WAVE}")
        total_units += units

    if total_units == 0 and not errors:
        errors.append("没有任何敌人：至少配置 1 个单位")
    if total_units > MAX_TOTAL_UNITS:
        errors.append(f"敌人总数 {total_units} 超过上限 {MAX_TOTAL_UNITS}")

    conditions = data.get("conditions") or {}
    try:
        max_rounds = int(conditions.get("max_rounds", 0) or 0)
        if max_rounds < 0:
            errors.append("conditions.max_rounds 不能为负")
    except (TypeError, ValueError):
        errors.append("conditions.max_rounds 非整数")

    rewards = data.get("rewards") or {}
    try:
        if int(rewards.get("xp", 0) or 0) < 0:
            errors.append("rewards.xp 不能为负")
    except (TypeError, ValueError):
        errors.append("rewards.xp 非整数")

    difficulty = data.get("difficulty") or {}
    band = str(difficulty.get("band") or "")
    if band and band not in ("T0", "T1", "T2", "T3", "T4"):
        warnings.append(f"difficulty.band '{band}' 不在 T0–T4 之内")

    rules = data.get("rules") or {}
    metric = str(rules.get("range_metric") or "manhattan")
    if metric not in ("manhattan", "chebyshev"):
        warnings.append(f"rules.range_metric '{metric}' 未知，将按 manhattan 处理")

    # 威胁 / 预算 / 阶段带对照（只警告不阻断：设计者可能有意做难关卡）
    if include_balance and not errors:
        try:
            from combat_balance import node_budget_report
            from combat_data_loader import CombatDataLoader
            report = node_budget_report(data, loader=CombatDataLoader())
            warnings.extend(w for w in report.pop("warnings", []) if w not in warnings)
            metrics["threat"] = report
        except Exception as exc:  # 数值模型异常不应阻断结构性校验
            logger.warning("威胁预算计算失败: %s", exc)

    return {"errors": errors, "warnings": warnings, "metrics": metrics}


# ── 写入 ──

def save_node(data: dict, expected_hash: str = "",
              *, enemy_names: set[str] | None = None) -> dict:
    """校验并写入节点（`_hash` 冲突检测）；返回落盘后的节点。"""
    data = dict(data or {})
    node_id = str(data.get("node_id") or "").strip()
    report = validate_node(data, enemy_names=enemy_names)
    if report["errors"]:
        raise NodeError(report["errors"])

    path = node_path(node_id)
    if path.is_file():
        current = json.loads(path.read_text(encoding="utf-8"))
        current_hash = str(current.get("_hash") or "")
        if expected_hash and current_hash and expected_hash != current_hash:
            raise NodeConflictError(
                "保存冲突：节点文件已被其他进程/窗口修改，请刷新后重试")

    data.pop("_hash", None)
    data["_hash"] = compute_json_hash(data)
    NODE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    logger.info("战斗节点已保存: %s", path.name)
    data["warnings"] = report["warnings"]
    return data


def create_node(node_id: str, name: str = "", *, from_template: bool = True) -> dict:
    """按模板新建节点（已存在则报错）。

    刻意**不做完整校验**：新建时波次通常是空的，编辑器随后填充；但开战前
    `CombatSession.start` 会拒绝"没有敌人"的节点，因此不会出现空战场。
    """
    node_id = str(node_id or "").strip()
    if not node_id:
        raise NodeError("缺少 node_id")
    if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff-]{1,64}", node_id):
        raise NodeError(f"node_id '{node_id}' 含非法字符（允许中英文/数字/下划线/连字符）")
    if node_exists(node_id):
        raise NodeError(f"节点已存在: {node_id}")
    data = template_data() if from_template else {}
    data.update({"node_id": node_id, "name": name or node_id})
    data.setdefault("waves", [{"enemies": []}])

    data.pop("_hash", None)
    data["_hash"] = compute_json_hash(data)
    NODE_DIR.mkdir(parents=True, exist_ok=True)
    node_path(node_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("战斗节点已创建: %s", node_id)
    return data


def delete_node(node_id: str, *, force: bool = False,
                bindings: dict | None = None) -> dict:
    """删除节点。被剧情节拍引用时默认拒绝（避免剧情打不开战斗）。"""
    path = node_path(node_id)
    if not path.is_file():
        raise NodeError(f"节点不存在: {node_id}")
    refs = (bindings or node_bindings()).get(node_id, [])
    if refs and not force:
        where = "、".join(f"{r['plot_id']}/{r.get('beat_id') or '?'}" for r in refs[:3])
        raise NodeError(f"节点被剧情引用（{where}），如需删除请显式确认")
    path.unlink()
    logger.info("战斗节点已删除: %s", node_id)
    return {"deleted": node_id, "referenced_by": refs}


# ── 剧情节拍绑定与进度 ──

def node_bindings() -> dict[str, list[dict]]:
    """扫描 plot 文档，返回 node_id → [{plot_id, chapter_id, beat_id}]。"""
    bindings: dict[str, list[dict]] = {}
    if not PLOT_DIR.is_dir():
        return bindings
    for path in sorted(PLOT_DIR.glob("*/index.md")):
        plot_id = path.parent.name
        chapter_id = ""
        beat_id = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            ch = re.match(r"^## 章节\s*(\d+)[：:]\s*(.+)$", line)
            if ch:
                chapter_id = ""
                beat_id = ""
                continue
            if not chapter_id:
                id_m = re.match(r"^\*\*ID\*\*[：:]\s*`?(\w+)`?", line)
                if id_m:
                    chapter_id = id_m.group(1)
                    continue
            beat_m = re.match(r"^####\s+(beat_\w+)", line)
            if beat_m:
                beat_id = beat_m.group(1)
                continue
            for node_id in re.findall(r"\[COMBAT:([\w-]+)\]", line):
                if node_id == "ID":
                    continue
                bindings.setdefault(node_id, []).append({
                    "plot_id": plot_id,
                    "chapter_id": chapter_id,
                    "beat_id": beat_id,
                })
    return bindings


def node_progress(session) -> tuple[dict[str, dict], dict]:
    """读取会话的节拍进度，返回 (node_id → 进度, 会话剧情上下文)。

    进度状态：`done`（已完成节拍）/ `current`（当前节拍）/ `locked`（尚未到达）。
    没有剧情或没有节拍状态时返回空字典（编辑器据此只显示"未绑定"）。
    """
    overlay = getattr(session, "overlay", None)
    if overlay is None:
        return {}, {}
    beat_state = overlay.get_beat_state() or {}
    plot_id = overlay.get_plot_id() or ""
    if not plot_id or not beat_state:
        return {}, {"plot_id": plot_id, "chapter_idx": None, "beat_idx": None}

    from session_overlay import parse_narrative_beats  # 复用同一套节拍解析器

    text = overlay._load_narrative_text(plot_id) if hasattr(overlay, "_load_narrative_text") else ""
    chapters = parse_narrative_beats(text) if text else []
    ci = int(beat_state.get("chapter_idx", 0) or 0)
    bi = int(beat_state.get("beat_idx", 0) or 0)
    completed = set(beat_state.get("completed_beats") or [])

    progress: dict[str, dict] = {}
    for chi, chapter in enumerate(chapters):
        for bti, beat in enumerate(chapter.get("beats") or []):
            ids = re.findall(r"\[COMBAT:([\w-]+)\]", beat.get("content", "") or "")
            if not ids:
                continue
            if beat["id"] in completed:
                state = "done"
            elif chi == ci and bti == bi:
                state = "current"
            else:
                state = "locked"
            for node_id in ids:
                if node_id == "ID":
                    continue
                progress[node_id] = {
                    "state": state,
                    "plot_id": plot_id,
                    "chapter_idx": chi + 1,
                    "chapter_id": chapter.get("id", ""),
                    "chapter_title": chapter.get("title", ""),
                    "beat_id": beat["id"],
                    "beat_summary": (beat.get("summary") or "")[:80],
                }
    return progress, {"plot_id": plot_id, "chapter_idx": ci + 1, "beat_idx": bi + 1}


def node_overview(session=None) -> tuple[list[dict], dict]:
    """编辑器用的节点总览：注册表 + 剧情节拍绑定 + 会话进度 + 是否有配置。"""
    from combat_data_loader import CombatDataLoader

    loader = CombatDataLoader()
    bindings = node_bindings()
    progress, plot_ctx = node_progress(session) if session is not None else ({}, {})

    rows: list[dict] = []
    seen: set[str] = set()
    for path in list_node_files():
        node = load_node_file(path.stem) or {}
        node_id = node.get("node_id", path.stem)
        seen.add(node_id)
        summary = next((n for n in loader.list_nodes() if n["node_id"] == node_id), {})
        rows.append({
            "node_id": node_id,
            "name": node.get("name", node_id),
            "summary": node.get("summary", ""),
            "rows": (node.get("map") or {}).get("rows"),
            "cols": (node.get("map") or {}).get("cols"),
            "wave_count": len(node.get("waves") or []),
            "unit_total": summary.get("unit_total", 0),
            "bind": node.get("bind") or {},
            "markers": bindings.get(node_id, []),
            "progress": progress.get(node_id),
            "source_worldbook": (node.get("source") or {}).get("book_id", ""),
            "hash": node.get("_hash", ""),
        })

    # 剧情里引用但还没有配置的节点（编辑器应能提示"待创建"）
    for node_id, markers in bindings.items():
        if node_id in seen:
            continue
        rows.append({
            "node_id": node_id,
            "name": node_id,
            "summary": "",
            "rows": None,
            "cols": None,
            "wave_count": 0,
            "unit_total": 0,
            "bind": markers[0] if markers else {},
            "markers": markers,
            "progress": progress.get(node_id),
            "source_worldbook": "",
            "hash": "",
            "missing": True,
        })

    rows.sort(key=lambda r: (r.get("missing", False), r["node_id"]))
    return rows, {"plot": plot_ctx, "bindings": len(bindings)}


# ── 世界书编解码 ──

def encode_node_for_worldbook(node: dict) -> dict:
    """把节点编码为世界书条目（content 围栏块 + raw.extensions 标记）。"""
    payload = {k: v for k, v in (node or {}).items() if k not in ("_hash", "warnings")}
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    node_id = payload.get("node_id", "")
    name = payload.get("name", node_id)
    lines = [f"```json {WORLD_BOOK_FENCE}", compact, "```"]
    if payload.get("summary"):
        lines += ["", str(payload["summary"])]
    return {
        "uid": f"combat_node_{node_id}",
        "name": f"节点：{name}",
        "content": "\n".join(lines),
        "trigger_keys": [name, node_id],
        "raw": {
            "extensions": {
                _EXT_NAMESPACE: {
                    "entry_type": _ENTRY_TYPE,
                    "node_id": node_id,
                }
            }
        },
    }


def is_combat_node_entry(entry: dict) -> bool:
    """判断世界书条目是否承载战斗节点（extensions 标记或围栏块）。"""
    raw = (entry or {}).get("raw") or {}
    ext = ((raw.get("extensions") or {}).get(_EXT_NAMESPACE) or {})
    if ext.get("entry_type") == _ENTRY_TYPE:
        return True
    if ext.get("node_id") and _FENCE_RE.search(str((entry or {}).get("content") or "")):
        return True
    return bool(_FENCE_RE.search(str((entry or {}).get("content") or "")))


def decode_worldbook_entry(entry: dict) -> dict | None:
    """从世界书条目解出节点规格；不是战斗节点条目则返回 None（不抛错）。"""
    content = str((entry or {}).get("content") or "")
    match = _FENCE_RE.search(content)
    if not match:
        if is_combat_node_entry(entry):
            raise NodeError(f"战斗节点条目 '{entry.get('name', '')}' 缺少 ```json {WORLD_BOOK_FENCE} 代码块")
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError as e:
        raise NodeError(f"战斗节点条目 '{entry.get('name', '')}' 的 JSON 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise NodeError(f"战斗节点条目 '{entry.get('name', '')}' 的内容应为 JSON 对象")
    raw = (entry or {}).get("raw") or {}
    ext = ((raw.get("extensions") or {}).get(_EXT_NAMESPACE) or {})
    if ext.get("node_id"):
        data.setdefault("node_id", ext["node_id"])
    return data


def import_worldbook_nodes(entries: list[dict], *, book_id: str = "",
                           overwrite: bool = True,
                           enemy_names: set[str] | None = None) -> dict:
    """把世界书里的战斗节点条目落地为节点文件。

    返回 `{"imported": [...], "skipped": [...], "errors": [...]}`；
    校验失败的条目不落盘（不产生半成品）。
    """
    imported: list[dict] = []
    skipped: list[str] = []
    errors: list[str] = []

    for entry in entries or []:
        try:
            data = decode_worldbook_entry(entry)
        except NodeError as e:
            errors.extend(e.errors)
            continue
        if data is None:
            continue
        node_id = str(data.get("node_id") or "").strip()
        if not node_id:
            errors.append(f"条目 '{entry.get('name', '')}' 缺少 node_id")
            continue
        data.setdefault("name", entry.get("name", node_id))
        if node_exists(node_id) and not overwrite:
            skipped.append(node_id)
            continue
        data["source"] = {"type": "worldbook", "book_id": book_id,
                          "entry_uid": entry.get("uid", "")}
        try:
            save_node(data, enemy_names=enemy_names)
        except NodeError as e:
            errors.extend(f"{node_id}: {msg}" for msg in e.errors)
            continue
        imported.append({"node_id": node_id, "book_id": book_id})

    return {"imported": imported, "skipped": skipped, "errors": errors}
