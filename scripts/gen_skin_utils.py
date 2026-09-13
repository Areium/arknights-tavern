#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成皮肤的颜色工具类覆盖块，并写回 skin-prts.css / skin-tavern.css。

为什么是生成而不是手写
----------------------
皮肤要覆盖的是 Tailwind 的颜色工具类。实测（排除 components/combat，战斗页不换肤）
前端用到 186 个基础工具类 + 大量 hover:/focus:/placeholder: 变体 = 243 个。
手写第一版只覆盖 78 个，漏掉 body 上的 `bg-surface-dark`，导致内容区整片仍是深色。
所以改为按色板生成：改色板 → 重跑本脚本即可。

两个必须注意的点
----------------
1. Tailwind v3 的 `@layer` 是 PostCSS 指令，产物**没有原生 CSS 层**，所以普通
   class（特异度 0,1,0）会盖过裸 `body`（0,0,1）。`<body class="bg-surface-dark
   text-gray-100">` 的类写在 frontend/index.html 里 —— body 规则必须写成
   `html.skin-x body`(0,2,1) 且放在 @scope 之外（见 _promote 说明 / CSS 内注释）。
2. 扫描范围必须包含 frontend/index.html，否则 bg-surface-* 全漏。
   combat 目录默认排除（战斗页不换肤），但 PlotGraphPage / GraphCanvas 渲染在
   ContentHub 的「剧情图」Tab 下、不在 .bg-combat-bg 子树内，必须纳入扫描，
   否则该页的页面 chrome 在皮肤下留默认深色。

用法
----
    python scripts/gen_skin_utils.py            # 生成并写回两个 CSS
    python scripts/gen_skin_utils.py --check    # 只报告条数，不写文件

CSS 里的替换区间由 `工具类覆盖（自动生成…）` / `工具类覆盖结束` 两个标记界定，
标记之外的手写块（组件基元、徽章、大厅、气泡、氛围层等）不会被触碰。
"""
import argparse
import collections
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FRONTEND = os.path.join(REPO, "frontend")
SRC = os.path.join(FRONTEND, "src")
SKIN_DIR = os.path.join(SRC, "styles")

FAMILIES = {
    "gray", "slate", "zinc", "neutral", "stone", "red", "orange", "amber", "yellow",
    "lime", "green", "emerald", "teal", "cyan", "sky", "blue", "indigo", "violet",
    "purple", "fuchsia", "pink", "rose", "white", "black", "surface",
}

TOKEN_RE = re.compile(
    r"^(?P<variants>(?:[a-z-]+:)*)"
    r"(?P<prefix>bg|text|border|accent|placeholder|from|to|via|ring|divide|fill|stroke|caret|outline)"
    r"-(?P<family>[a-z]+)"
    r"(?:-(?P<shade>\d{2,3}|[a-z]+))?"
    r"(?:/(?P<alpha>\d{1,3}))?$"
)

VARIANT_SEL = {
    "hover": ":hover", "focus": ":focus", "focus-visible": ":focus-visible",
    "active": ":active", "disabled": ":disabled", "checked": ":checked",
    "placeholder": "::placeholder", "group-hover": None,   # None = 特殊处理
}

PREFIX_PROP = {
    "bg": "background-color", "text": "color", "border": "border-color",
    "accent": "accent-color", "placeholder": "color", "fill": "fill", "stroke": "stroke",
}

# ─────────────────────────── 色板（改这里即可调色） ───────────────────────────

PRTS_GRAY = {
    50: "#f4f9fd", 100: "#dce8f2", 200: "#c6d8e8", 300: "#a8bdd1", 400: "#8ca3b8",
    500: "#6f849a", 600: "#54687c", 700: "#122032", 750: "#0e1a29", 800: "#0b1524",
    850: "#060c16", 900: "#04070d", 950: "#02040a",
}
TAVERN_GRAY = {
    50: "#2a2118", 100: "#40342a", 200: "#4a3d31", 300: "#5b4c3e", 400: "#6d5c4b",
    500: "#8a7862", 600: "#a89880", 700: "#f3ead7", 750: "#f0e5cf", 800: "#fbf6e9",
    850: "#f7f0dd", 900: "#ece1c9", 950: "#e0d3b5",
}
PRTS_BORDER_GRAY = {
    100: "rgba(56,189,248,.08)", 200: "rgba(56,189,248,.10)", 300: "rgba(56,189,248,.14)",
    400: "rgba(56,189,248,.18)", 500: "rgba(56,189,248,.20)", 600: "rgba(56,189,248,.35)",
    700: "rgba(56,189,248,.22)", 800: "rgba(56,189,248,.14)", 900: "rgba(56,189,248,.10)",
}
TAVERN_BORDER_GRAY = {
    100: "#cbb894", 200: "#e8dcc2", 300: "#e0d3b5", 400: "#cbb894", 500: "#c0ab84",
    600: "#b8a37c", 700: "#d8c9a8", 800: "#e0d3b5", 900: "#cbb894",
}

PRTS_ACCENT = {
    "amber": {100: "#f7e3b8", 200: "#f4d99c", 300: "#f0c060", 400: "#dfa63a", 500: "#c68d26", 600: "#a97419"},
    "orange": {300: "#f0c060", 400: "#dfa63a", 500: "#c68d26"},
    "yellow": {200: "#f4d99c", 300: "#f0c060", 400: "#dfa63a", 500: "#c68d26"},
    "red": {200: "#fecaca", 300: "#fca5a5", 400: "#fb5e5e", 500: "#f87171", 600: "#ef4444", 700: "#dc2626", 800: "#b91c1c", 900: "#7f1d1d"},
    "rose": {400: "#fb5e5e", 500: "#f87171"},
    "pink": {400: "#fb5e5e"},
    "blue": {200: "#bae6fd", 300: "#7dd3fc", 400: "#38bdf8", 500: "#0ea5e9", 600: "#0284c7", 700: "#0369a1"},
    "sky": {400: "#38bdf8", 500: "#0ea5e9", 600: "#0284c7"},
    "cyan": {200: "#bae6fd", 300: "#7dd3fc", 400: "#38bdf8", 500: "#0ea5e9", 600: "#0284c7", 700: "#0369a1"},
    "indigo": {400: "#38bdf8", 500: "#0ea5e9"},
    "green": {200: "#a7f3d0", 300: "#86efac", 400: "#3ddc97", 500: "#10b981", 600: "#059669", 700: "#047857"},
    "emerald": {200: "#a7f3d0", 300: "#86efac", 400: "#3ddc97", 500: "#10b981", 600: "#059669", 700: "#047857"},
    "teal": {400: "#3ddc97", 500: "#10b981"},
    "lime": {400: "#3ddc97"},
    "violet": {200: "#ddd6fe", 300: "#c4b5fd", 400: "#a78bfa", 500: "#8b5cf6", 600: "#7c3aed", 700: "#6d28d9"},
    "purple": {200: "#ddd6fe", 300: "#c4b5fd", 400: "#a78bfa", 500: "#8b5cf6", 600: "#7c3aed", 700: "#6d28d9"},
    "fuchsia": {400: "#a78bfa", 500: "#8b5cf6"},
}
TAVERN_ACCENT = {
    "amber": {100: "#6b4a16", 200: "#7d5618", 300: "#8f6220", 400: "#a87b2f", 500: "#8a6420", 600: "#7a5718"},
    "orange": {300: "#a87b2f", 400: "#a87b2f", 500: "#8a6420"},
    "yellow": {200: "#7d5618", 300: "#8f6220", 400: "#a87b2f", 500: "#a87b2f"},
    "red": {200: "#8c3a2c", 300: "#a03d2d", 400: "#8c3a2c", 500: "#b04a38", 600: "#a03d2d", 700: "#8c3a2c", 800: "#7c2d20", 900: "#6b2618"},
    "rose": {400: "#a03d2d", 500: "#b04a38"},
    "pink": {400: "#a03d2d"},
    "blue": {200: "#35566b", 300: "#3f6a83", 400: "#6b8299", 500: "#557089", 600: "#3f6a83", 700: "#35566b"},
    # sky 的 200/700 与 500 对齐 400：原 skin-tavern 生成区内的手写补漏值
    # （#334e63 保羊皮纸可读性、#6b8299 与 t-sky 变量一致）已并入调色板。
    "sky": {200: "#334e63", 400: "#6b8299", 500: "#6b8299", 600: "#3f6a83", 700: "#6b8299"},
    "cyan": {200: "#35566b", 300: "#3f6a83", 400: "#6b8299", 500: "#557089", 600: "#3f6a83", 700: "#35566b"},
    "indigo": {400: "#6b8299", 500: "#557089"},
    "green": {200: "#4a6040", 300: "#4f6545", 400: "#5b7350", 500: "#5b7350", 600: "#4a6040", 700: "#3f5237"},
    "emerald": {200: "#4a6040", 300: "#4f6545", 400: "#5b7350", 500: "#5b7350", 600: "#4a6040", 700: "#3f5237"},
    "teal": {400: "#5b7350", 500: "#5b7350"},
    "lime": {400: "#5b7350"},
    "violet": {200: "#5c4a6b", 300: "#6b5580", 400: "#7d6394", 500: "#6b5580", 600: "#5c4a6b", 700: "#4d3e59"},
    "purple": {200: "#5c4a6b", 300: "#6b5580", 400: "#7d6394", 500: "#6b5580", 600: "#5c4a6b", 700: "#4d3e59"},
    "fuchsia": {400: "#7d6394", 500: "#6b5580"},
}

# tailwind.config.js 里的自定义 surface 色板
PRTS_SURFACE = {"dark": "#04070d", "card": "#0b1524", "border": "rgba(56,189,248,.22)", "hover": "#122032"}
TAVERN_SURFACE = {"dark": "#ece1c9", "card": "#fbf6e9", "border": "#d8c9a8", "hover": "#f3ead7"}

PRTS_SPECIAL = {"white": "#eaf4fc", "black": "#02040a"}
TAVERN_SPECIAL = {"white": "#fbf6e9", "black": "#d8c9a8"}

# 手调对比度覆盖：调色板是 bg/text/border 共用的，但部分「文字色」压在皮肤底色上
# 不达 4.5:1，需要按 (skin, prefix, family, shade) 精确覆盖（此前手改在生成区内，
# 重跑即丢 —— 现收编进脚本，保证重跑可复现）。带 alpha 的 token 仍按
# with_alpha(覆盖值, alpha) 派生。
COLOR_OVERRIDES = {
    # PRTS：深空底上 gray-500/600 文字提亮一档（保持 500 亮于 600 的层次）
    ("prts", "text", "gray", 500): "#7f96ac",
    ("prts", "text", "gray", 600): "#6f849a",
    # tavern：羊皮纸上灰阶 500/600 与琥珀系文字压深到墨水层次
    ("tavern", "text", "gray", 500): "#665644",
    ("tavern", "text", "gray", 600): "#5b4c3e",
    ("tavern", "text", "amber", 100): "#4e350c",
    ("tavern", "text", "amber", 200): "#5c3f10",
    ("tavern", "text", "amber", 300): "#6b4a16",
    ("tavern", "text", "amber", 400): "#7d5a1c",
    ("tavern", "text", "amber", 500): "#6b4a16",
    ("tavern", "text", "amber", 600): "#5c3f10",
}

ORDER = ["gray", "surface", "amber", "yellow", "orange", "red", "rose", "pink",
         "blue", "sky", "cyan", "indigo", "green", "emerald", "teal", "lime",
         "violet", "purple", "fuchsia", "white", "black"]
TITLES = {
    "gray": "灰阶（底色 / 文字 / 边框）", "surface": "自定义 surface 色板",
    "amber": "amber → 金 / 烛火", "white": "white / black", "black": "white / black",
}

BEGIN = "  /* ═══ 工具类覆盖（由 scripts/gen_skin_utils.py 生成，勿手改） ═══ */"
END = "  /* ═══ 工具类覆盖结束 ═══ */"

# combat 目录默认排除（战斗页不换肤，根在 .bg-combat-bg 子树内，@scope 已隔离）；
# 例外：剧情图页（PlotGraphPage）被 ContentHub「剧情图」Tab 引用，渲染在换肤
# DOM 内，GraphCanvas 仅被它使用 —— 这两个文件必须参与扫描。
COMBAT_INCLUDE_FILES = {"PlotGraphPage.tsx", "GraphCanvas.tsx"}


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _fmt(a):
    s = ("%.3f" % a).rstrip("0").rstrip(".")
    return s if s else "0"


def with_alpha(color, alpha):
    a = alpha / 100.0
    m = re.match(r"rgba?\(([^)]+)\)", color)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        return "rgba(%s, %s, %s, %s)" % (parts[0], parts[1], parts[2], _fmt(a))
    r, g, b = hex_to_rgb(color)
    return "rgba(%d, %d, %d, %s)" % (r, g, b, _fmt(a))


def resolve(skin, prefix, fam, shade, alpha):
    ov = COLOR_OVERRIDES.get((skin, prefix, fam, shade))
    if ov is not None:
        return with_alpha(ov, alpha) if alpha else ov

    is_prts = skin == "prts"
    gray = PRTS_GRAY if is_prts else TAVERN_GRAY
    border_gray = PRTS_BORDER_GRAY if is_prts else TAVERN_BORDER_GRAY
    accent = PRTS_ACCENT if is_prts else TAVERN_ACCENT
    surface = PRTS_SURFACE if is_prts else TAVERN_SURFACE
    special = PRTS_SPECIAL if is_prts else TAVERN_SPECIAL

    if fam in ("white", "black"):
        base = special.get(fam)
    elif fam == "surface":
        base = surface.get(shade)
    elif fam in ("gray", "slate", "zinc", "neutral", "stone"):
        base = border_gray.get(shade) if prefix == "border" else gray.get(shade)
    else:
        shades = accent.get(fam)
        if not shades:
            return None
        if shade is None:
            return None
        if shade not in shades:
            shade = min(shades, key=lambda s: abs(s - shade))
        base = shades[shade]

    if base is None:
        return None
    return with_alpha(base, alpha) if alpha else base


def scan_used():
    """扫描前端真实用到的颜色工具类。必须包含 index.html（body 的类在那里）。"""
    used, skipped = collections.Counter(), collections.Counter()
    targets = [os.path.join(FRONTEND, "index.html")]
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist")]
        if os.path.join("components", "combat") in dirpath:
            # 战斗页不换肤；但剧情图两文件挂在 ContentHub 下、渲染在换肤 DOM 内
            targets += [os.path.join(dirpath, f) for f in filenames
                        if f in COMBAT_INCLUDE_FILES]
            continue
        targets += [os.path.join(dirpath, f) for f in filenames if f.endswith((".tsx", ".ts"))]

    for path in targets:
        try:
            src = io.open(path, encoding="utf-8").read()
        except OSError:
            continue
        for token in re.findall(r"[A-Za-z0-9_:/\[\]%.,()\-]+", src):
            m = TOKEN_RE.match(token)
            if not m or m.group("family") not in FAMILIES:
                continue
            variants = [v for v in m.group("variants").split(":") if v]
            if any(v not in VARIANT_SEL for v in variants):
                skipped[token] += 1
                continue
            used[token] += 1
    return used, skipped


def build_block(skin, used):
    groups = collections.defaultdict(list)
    for tok, n in used.items():
        m = TOKEN_RE.match(tok)
        if m.group("prefix") not in PREFIX_PROP:
            continue
        shade = m.group("shade")
        shade = int(shade) if (shade and shade.isdigit()) else shade
        alpha = int(m.group("alpha")) if m.group("alpha") else None
        val = resolve(skin, m.group("prefix"), m.group("family"), shade, alpha)
        if val is None:
            continue
        groups[m.group("family")].append(
            (tok, [v for v in m.group("variants").split(":") if v],
             m.group("prefix"), shade, alpha, val))

    out, total = [], 0
    for fam in ORDER:
        items = groups.get(fam)
        if not items:
            continue
        items.sort(key=lambda t: (t[2], t[3] if isinstance(t[3], int) else 0, t[4] or 0))
        out.append("  /* ── %s ── */" % TITLES.get(fam, fam))
        seen = set()
        for tok, variants, prefix, shade, alpha, val in items:
            if tok in seen:
                continue
            seen.add(tok)
            cls = "." + tok.replace("/", "\\/").replace(":", "\\:")
            prop = PREFIX_PROP[prefix]
            if not variants:
                out.append("  %s { %s: %s; }" % (cls, prop, val))
            elif variants == ["group-hover"]:
                out.append("  .group:hover %s { %s: %s; }" % (cls, prop, val))
            else:
                out.append("  %s%s { %s: %s; }"
                           % (cls, "".join(VARIANT_SEL[v] or "" for v in variants), prop, val))
            total += 1
        out.append("")
    return "\n".join(out), total


def splice(path, block):
    src = io.open(path, encoding="utf-8").read()
    if BEGIN not in src or END not in src:
        return None
    return src[: src.index(BEGIN)] + BEGIN + "\n" + block + END + src[src.index(END) + len(END):]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="只报告条数，不写文件")
    args = ap.parse_args()

    used, skipped = scan_used()
    print("扫描到颜色工具类（含变体）: %d" % len(used))
    if skipped:
        print("跳过（响应式/未支持变体）: %d -> %s"
              % (len(skipped), ", ".join(list(skipped)[:8])))

    rc = 0
    for skin, fname in (("prts", "skin-prts.css"), ("tavern", "skin-tavern.css")):
        path = os.path.join(SKIN_DIR, fname)
        block, total = build_block(skin, used)
        print("%s: 生成 %d 条规则" % (fname, total))
        if args.check:
            continue
        new = splice(path, block)
        if new is None:
            print("   !! 未找到 BEGIN/END 标记，跳过（标记应存在于文件内）")
            rc = 1
            continue
        io.open(path, "w", encoding="utf-8", newline="").write(new)
        print("   已写入 %s" % fname)
    return rc


if __name__ == "__main__":
    sys.exit(main())
