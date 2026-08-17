"""
玩家身份角色档案 — 让用户以自身身份角色参与对话。

"博士"等玩家身份在 data/characters/<identity>/index.md 中有完整设定
（frontmatter summary/tags + 正文背景），但对话/叙述 prompt 过去只注入
一行"身份：博士"，缺乏角色感。本模块把玩家角色的设定读取为结构化文本，
注入叙述与角色对话 prompt，让 LLM 以玩家角色视角推进剧情。

- 会话创建时可选择玩家身份（默认"博士"），见 session_manager.player_identity
- 档案按 identity 进程内缓存（会话内设定不变）
"""

import logging
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHARS_DIR = _REPO_ROOT / "data" / "characters"

# identity → 档案文本 | None（不存在/解析失败），进程内缓存
_profile_cache: dict[str, str | None] = {}

# 可注入正文的最大字符数（防超长设定占满上下文）
_MAX_BODY_CHARS = 400


def load_player_profile(identity: str) -> str | None:
    """读取玩家身份角色的设定，返回注入用文本；无角色文件时返回 None。

    文本结构（供 LLM 理解玩家是谁）：
        玩家身份：<name>
        身份简介：<frontmatter summary>
        身份标签：<tags>
        身份背景：<正文第一段>
    """
    identity = (identity or "").strip() or "博士"
    if identity in _profile_cache:
        return _profile_cache[identity]

    path = _CHARS_DIR / identity / "index.md"
    if not path.is_file():
        _profile_cache[identity] = None
        return None

    try:
        data = frontmatter.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("读取玩家身份档案 %s 失败: %s", identity, e)
        _profile_cache[identity] = None
        return None

    meta = data.metadata
    lines = [f"玩家身份：{identity}"]
    summary = str(meta.get("summary", "") or "").strip()
    if summary:
        lines.append(f"身份简介：{summary}")
    tags = meta.get("tags") or []
    if isinstance(tags, (list, tuple)):
        tag_str = "、".join(str(t) for t in tags if str(t).strip())[:80]
        if tag_str:
            lines.append(f"身份标签：{tag_str}")

    # 正文：跳过空行与 markdown 标题，取第一段作为身份背景
    body_para = []
    for line in (data.content or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        body_para.append(stripped)
        if sum(len(p) for p in body_para) >= _MAX_BODY_CHARS:
            break
    if body_para:
        lines.append(f"身份背景：{' '.join(body_para)[:_MAX_BODY_CHARS]}")

    text = "\n".join(lines)
    _profile_cache[identity] = text
    return text


def invalidate_profile_cache(identity: str | None = None):
    """清除玩家身份档案缓存（角色卡变更后调用）。"""
    if identity is None:
        _profile_cache.clear()
    else:
        _profile_cache.pop(identity, None)
