"""JSON 内容哈希：写盘冲突检测（409）的单一实现。

卡牌（`blueprints/cards.py`）与战斗节点（`combat_nodes.py`）共用同一套算法，
保证"前端带着旧 hash 保存 → 文件已被别的进程改过 → 拒绝写入"的行为一致。
"""

from __future__ import annotations

import hashlib
import json


def compute_json_hash(data: dict, length: int = 16) -> str:
    """对 JSON 内容取稳定哈希（忽略 `_hash` 字段本身，键排序，保留中文）。"""
    payload = {k: v for k, v in (data or {}).items() if k != "_hash"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]
