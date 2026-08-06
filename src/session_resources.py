"""
session_resources — 会话级资源空间辅助函数。

会话资源空间位于 <session_dir>/resources/ 下（<session_dir> =
data/memory/sessions/<mode>/<id>/）：

- characters/<name>/avatar.<ext> | skin.<ext> | card_face.<ext>
    会话角色形象覆盖（媒体=覆盖式：只存被替换的图，删覆盖即还原全局）

解析优先：会话覆盖 > 全局（角色媒体见 blueprints/scene.py 的
avatar/skin/card-face 端点；背景覆盖见 combat_data_loader.resolve_background）。
"""

import re
from pathlib import Path

_SESSION_MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_MEDIA_TYPES = ("avatar", "skin", "card_face")

_SAFE_NAME_RE = re.compile(r"^[^/\\\x00-\x1f]{1,120}$")


def is_safe_entity_name(name: str) -> bool:
    """实体名（角色名/物品名等）必须非空、无路径分隔符、无控制字符。"""
    return bool(name) and bool(_SAFE_NAME_RE.match(name)) and name not in (".", "..")


def session_resources_dir(session_dir: str | Path) -> Path:
    """会话资源空间根目录：<session_dir>/resources"""
    return Path(session_dir) / "resources"


def session_media_dir(session_dir: str | Path, name: str) -> Path:
    """会话角色形象覆盖目录：<session_dir>/resources/characters/<name>"""
    return session_resources_dir(session_dir) / "characters" / name


def normalize_media_type(media_type: str) -> str:
    """card-face → card_face；校验合法媒体类型。"""
    t = media_type.replace("-", "_")
    if t not in _MEDIA_TYPES:
        raise ValueError(f"未知媒体类型: {media_type}")
    return t


def find_session_media_path(session_dir: str | Path, name: str,
                            media_type: str) -> str | None:
    """查会话角色形象覆盖文件，命中返回绝对路径，否则 None。

    media_type: avatar | skin | card_face（也接受 card-face）
    """
    t = normalize_media_type(media_type)
    d = session_media_dir(session_dir, name)
    for ext in _SESSION_MEDIA_EXTS:
        f = d / f"{t}{ext}"
        if f.is_file():
            return str(f)
    return None


def list_session_media(session_dir: str | Path) -> list[dict]:
    """枚举会话角色形象覆盖：[{type, name, filename, size}]。"""
    result: list[dict] = []
    chars_dir = session_resources_dir(session_dir) / "characters"
    if not chars_dir.is_dir():
        return result
    for entry in sorted(chars_dir.iterdir()):
        if not entry.is_dir():
            continue
        for ext in _SESSION_MEDIA_EXTS:
            for media_type in _MEDIA_TYPES:
                f = entry / f"{media_type}{ext}"
                if f.is_file():
                    result.append({
                        "media_type": media_type,
                        "name": entry.name,
                        "filename": f.name,
                        "size": f.stat().st_size if f.is_file() else 0,
                    })
    return result
