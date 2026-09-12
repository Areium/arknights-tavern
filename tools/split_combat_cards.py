"""Split combat sections from character index.md to combat.md."""
import re
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAR_DIR = os.path.join(BASE, "data", "characters")

SPLIT_RE = re.compile(r'\n(?=# (?:角色能力|卡牌)\b)')
TEMPLATE_COMBAT_RE = re.compile(r'\n(?=# 卡牌\b)')

for name in sorted(os.listdir(CHAR_DIR)):
    subdir = os.path.join(CHAR_DIR, name)
    index_path = os.path.join(subdir, "index.md")
    combat_path = os.path.join(subdir, "combat.md")
    if not os.path.isfile(index_path):
        continue
    if os.path.exists(combat_path):
        print(f"SKIP {name}: combat.md already exists")
        continue

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        print(f"SKIP {name}: no YAML frontmatter")
        continue

    parts = SPLIT_RE.split(content, maxsplit=1)
    if len(parts) != 2:
        print(f"SKIP {name}: no combat section found")
        continue

    narrative, combat = parts
    narrative = narrative.rstrip() + "\n"
    combat = combat.lstrip()

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(narrative)

    with open(combat_path, "w", encoding="utf-8") as f:
        f.write(combat)

    narrative_len = len(narrative)
    combat_len = len(combat)
    saved = combat_len
    print(f"OK {name}: narrative={narrative_len} chars, combat={combat_len} chars, saved ~{saved} chars per preload")

print("\nDone.")
