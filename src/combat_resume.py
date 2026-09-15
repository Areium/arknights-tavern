"""战斗挂起存档 —— 「临时返回主页/会话，稍后继续打」的落盘层。

背景
----
战斗态原本只活在内存（会话战挂在 `session.combat`，战斗测试挂在
`CombatTestSessionManager`），因此进程重启、空闲超时或会话重建都会丢局。
本模块把 `CombatSession.suspend_snapshot()` 的完整快照原子写盘，恢复时经
`CombatSession.from_suspend_snapshot()` 原样重建，使战斗可跨页面切换 / 重启继续。

存档位置
--------
- 会话战：`<会话数据目录>/combat_resume.json`（随会话删除一并清理）
- 战斗测试：`data/memory/combat_resumes/<test_id>.json`（测试战斗无会话目录）

两处都在 `data/memory/`（已 gitignore）之下，不会污染版本库。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_RESUME_DIR = _PROJECT_ROOT / "data" / "memory" / "combat_resumes"

SESSION_RESUME_NAME = "combat_resume.json"


# ── 路径 ──

def session_resume_path(session) -> Path:
    """会话战的挂起存档路径（会话目录内，随会话删除自动清理）。"""
    return Path(session.data_dir) / SESSION_RESUME_NAME


def test_resume_path(test_id: str) -> Path:
    """战斗测试的挂起存档路径。"""
    return TEST_RESUME_DIR / f"{test_id}.json"


# ── 读写 ──

def write_resume(path: Path, payload: dict) -> None:
    """原子落盘（先写临时文件再 os.replace），避免中途崩溃留下截断存档。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "suspended_at": payload.get("suspended_at") or time.time()}
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def read_resume(path: Path) -> dict | None:
    """读取挂起存档；不存在或损坏返回 None（损坏存档不应让恢复流程抛错）。"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取战斗挂起存档失败 %s: %s", path, e)
        return None


def clear_resume(path: Path) -> bool:
    """删除挂起存档；返回是否确实删掉了文件。"""
    path = Path(path)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        logger.warning("删除战斗挂起存档失败 %s: %s", path, e)
        return False


# ── 汇总（供前端「继续战斗」入口） ──

def summarize(payload: dict | None) -> dict | None:
    """把存档压成前端入口需要的最小信息（不含完整单位/牌堆）。"""
    if not payload:
        return None
    engine = payload.get("engine") or {}
    state = engine.get("state") or {}
    units = engine.get("units") or {}
    return {
        "encounter_id": payload.get("encounter_id", ""),
        "suspended_at": payload.get("suspended_at"),
        "round_num": state.get("round_num", 0),
        "phase": state.get("phase", ""),
        "battle_over": state.get("phase") == "END",
        "player_alive": sum(
            1 for u in units.values()
            if u.get("team") == "player" and u.get("is_alive")
        ),
        "hand_size": len((engine.get("shared_pool") or {}).get("hand") or []),
        "pending_waves": len(engine.get("pending_waves") or []),
    }


def list_test_resumes() -> list[dict]:
    """列出全部战斗测试挂起存档（按挂起时间倒序）。"""
    if not TEST_RESUME_DIR.is_dir():
        return []
    items = []
    for path in sorted(TEST_RESUME_DIR.glob("*.json")):
        payload = read_resume(path)
        info = summarize(payload)
        if not info:
            continue
        items.append({"test_id": path.stem, **info})
    items.sort(key=lambda it: it.get("suspended_at") or 0, reverse=True)
    return items
