"""
session_export — 会话存档导出/导入（社区传播）。

核心矛盾：会话目录自包含（session.json / overrides.json / resources / docs /
memories / backgrounds），但运行时引用全局资源（角色卡 index.md、角色基础形象、
全局背景图）。只拷会话目录，接收方缺全局资源会话不完整。

解法：导出时自动快照依赖到归档包（自包含）；导入时还原依赖到全局库（幂等）。
日常运行零拷贝（引用全局）+ 传播自包含两全。

zip 结构：
    manifest.json                     版本/会话元数据/依赖清单
    session/<mode>/<id>/...           会话目录（自有数据）
    snapshots/characters/<name>/...   角色卡 + 基础形象（index.md + 媒体）
    snapshots/backgrounds/<bg_id>/... 全局背景目录（index.md + 图片）
"""

import json
import logging
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SESSIONS_DIR = _REPO_ROOT / "data" / "memory" / "sessions"
_CHARS_DIR = _REPO_ROOT / "data" / "characters"
_BG_ROOT = _REPO_ROOT / "data" / "combat" / "backgrounds"

_FORMAT_VERSION = 1
_SNAPSHOT_EXTS = {".md", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
_MEDIA_SUBDIRS = ("avatar", "skin", "card_face")
_MAX_TOTAL_SIZE = 800 * 1024 * 1024  # 800MB — 防止 zip 炸弹


# ── 依赖解析 ──

def _parse_dependency_names(session_dir: Path) -> dict:
    """解析会话引用的全局依赖：角色名 + 背景 ID。"""
    deps: dict = {"characters": set(), "backgrounds": set()}

    # overrides.json 中的角色/物品覆盖
    overrides_path = session_dir / "overrides.json"
    if overrides_path.exists():
        try:
            data = json.loads(overrides_path.read_text(encoding="utf-8"))
            chars = data.get("characters", {})
            if isinstance(chars, dict):
                deps["characters"].update(chars.keys())
        except Exception:
            logger.warning("overrides.json 解析失败: %s", overrides_path)

    # 背景覆盖 → 全局背景 ID
    bg_dir = session_dir / "backgrounds"
    if bg_dir.is_dir():
        for f in bg_dir.iterdir():
            if f.is_file() and f.suffix.lower() in _SNAPSHOT_EXTS:
                deps["backgrounds"].add(f.stem)

    # resources/characters/ 下有形象覆盖 → 对应全局角色
    res_chars = session_dir / "resources" / "characters"
    if res_chars.is_dir():
        for entry in res_chars.iterdir():
            if entry.is_dir():
                deps["characters"].add(entry.name)

    return deps


def _snapshot_character(name: str, snap_root: Path) -> None:
    """快照角色卡 + 基础形象媒体到 snap_root/characters/<name>/。"""
    src = _CHARS_DIR / name
    if not src.is_dir():
        return
    dst = snap_root / "characters" / name
    dst.mkdir(parents=True, exist_ok=True)
    if (src / "index.md").is_file():
        shutil.copy2(src / "index.md", dst / "index.md")
    for sub in _MEDIA_SUBDIRS:
        subdir = src / sub
        if not subdir.is_dir():
            continue
        for f in subdir.iterdir():
            if f.is_file() and f.suffix.lower() in _SNAPSHOT_EXTS:
                (dst / sub).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst / sub / f.name)


def _snapshot_background(bg_id: str, snap_root: Path) -> None:
    """快照全局背景目录到 snap_root/backgrounds/<bg_id>/。"""
    src = _BG_ROOT / bg_id
    if not src.is_dir():
        return
    shutil.copytree(src, snap_root / "backgrounds" / bg_id)


# ── 导出 ──

def export_session_zip(session_dir: Path, session_meta: dict, out_path: Path) -> None:
    """打包会话存档（会话目录 + 依赖快照 + manifest）到 out_path。"""
    mode = session_dir.parent.name
    sid = session_dir.name
    deps = _parse_dependency_names(session_dir)
    manifest = {
        "format_version": _FORMAT_VERSION,
        "session": {
            "id": sid,
            "mode": mode,
            "name": session_meta.get("name", ""),
            "combat_mode": session_meta.get("combat_mode", "narrative"),
            "player_identity": session_meta.get("player_identity", "博士"),
            "plot_id": session_meta.get("plot_id"),
        },
        "dependencies": {
            "characters": sorted(deps["characters"]),
            "backgrounds": sorted(deps["backgrounds"]),
        },
    }

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 会话自有目录
        base = f"session/{mode}/{sid}"
        if session_dir.is_dir():
            for f in session_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f"{base}/{f.relative_to(session_dir).as_posix()}")

        # 依赖快照（写入临时目录再压入，保证结构可控）
        with tempfile.TemporaryDirectory() as tmp:
            snap_root = Path(tmp) / "snapshots"
            for name in deps["characters"]:
                _snapshot_character(name, snap_root)
            for bg_id in deps["backgrounds"]:
                _snapshot_background(bg_id, snap_root)
            if snap_root.is_dir():
                for f in snap_root.rglob("*"):
                    if f.is_file():
                        zf.write(f, f"snapshots/{f.relative_to(snap_root).as_posix()}")

        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))


# ── 导入 ──

def _safe_zip_member(name: str) -> bool:
    """zip 成员路径安全校验：仅 manifest.json / session/** / snapshots/**，无穿越。"""
    norm = name.replace("\\", "/")
    if not norm or norm.startswith("/") or ".." in norm.split("/"):
        return False
    if norm == "manifest.json":
        return True
    return norm.split("/", 1)[0] in ("session", "snapshots")


def _extract_zip(zip_path: Path, dest: Path) -> None:
    """安全解压 zip 到 dest（防穿越 + 大小限制）。"""
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if not _safe_zip_member(info.filename):
                raise ValueError(f"非法的 zip 成员: {info.filename}")
            total += info.file_size
            if total > _MAX_TOTAL_SIZE:
                raise ValueError("存档过大，拒绝导入")
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest.resolve()) + os.sep):
                raise ValueError("路径穿越: " + info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _restore_snapshots(snap_root: Path) -> dict:
    """还原依赖快照到全局库（同 ID 幂等：已有 index.md 则跳过）。返回统计。"""
    stats = {"characters": 0, "backgrounds": 0}
    if not snap_root.is_dir():
        return stats

    chars_src = snap_root / "characters"
    if chars_src.is_dir():
        for name in sorted(chars_src.iterdir()):
            if not name.is_dir() or not (name / "index.md").is_file():
                continue
            dst = _CHARS_DIR / name.name
            if (dst / "index.md").exists():
                continue  # 幂等：本地已有则跳过
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(name, dst)
            stats["characters"] += 1

    bgs_src = snap_root / "backgrounds"
    if bgs_src.is_dir():
        for bg in sorted(bgs_src.iterdir()):
            if not bg.is_dir() or not (bg / "index.md").is_file():
                continue
            dst = _BG_ROOT / bg.name
            if (dst / "index.md").exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bg, dst)
            stats["backgrounds"] += 1

    return stats


def _unique_session_id(dst_dir: Path, sid: str) -> str:
    """生成不冲突的会话 ID（保持 sess_N_hex 格式）。"""
    if not (dst_dir / sid).exists():
        return sid
    ts = int(time.time() * 1000)
    return f"sess_{ts // 1000}_{hex(ts)[2:]}"


def _rewrite_session_id(session_dir: Path, new_sid: str) -> None:
    """导入后 id 冲突时更新 session.json 内的 id 字段。"""
    meta_file = session_dir / "session.json"
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return
    if data.get("id") != new_sid:
        data["id"] = new_sid
        meta_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def import_session_zip(zip_path: Path, session_mgr) -> dict:
    """解包会话存档，还原依赖到全局库，放置并注册会话。返回会话 to_dict。"""
    with tempfile.TemporaryDirectory() as tmp:
        extract_dir = Path(tmp)
        _extract_zip(zip_path, extract_dir)

        manifest_path = extract_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("存档缺少 manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format_version") != _FORMAT_VERSION:
            raise ValueError("不支持的存档格式版本")

        # 1. 还原依赖快照到全局库
        restore_stats = _restore_snapshots(extract_dir / "snapshots")
        logger.info("会话导入：还原依赖 %s", restore_stats)

        # 2. 放置会话目录
        session_meta = manifest.get("session", {})
        mode = session_meta.get("mode", "free")
        sid = session_meta.get("id", "")
        src_dir = extract_dir / "session" / mode / sid
        if not src_dir.is_dir():
            raise ValueError("存档中缺少会话目录")
        if mode not in ("free", "story"):
            raise ValueError("非法的会话模式")

        dst_root = _SESSIONS_DIR / mode
        dst_root.mkdir(parents=True, exist_ok=True)
        final_sid = _unique_session_id(dst_root, sid)
        shutil.copytree(src_dir, dst_root / final_sid)
        if final_sid != sid:
            _rewrite_session_id(dst_root / final_sid, final_sid)

        # 3. 注册到内存
        session = session_mgr.import_session_dir(mode, final_sid)
        if not session:
            raise ValueError("会话注册失败")
        return session.to_dict()
