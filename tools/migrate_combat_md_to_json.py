"""Migrate combat.md files to combat.json for all characters.

Best-effort parsing of markdown table format into structured JSON.
Cards that can't be fully parsed are flagged with _needs_review: true.
"""

import json
import os
import re
import hashlib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAR_DIR = os.path.join(BASE, "data", "characters")

# ── Regex patterns ──────────────────────────────────────────────────────────

# Card heading: "### 卡牌名 ★★" or "### 卡牌名 ★★★（被动）"
CARD_HEADING_RE = re.compile(r"^###\s+(.+?)\s+(★+)(?:（.+?）)?\s*$")
# Table row: "| **字段** | 内容 |"
TABLE_ROW_RE = re.compile(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.*?)\s*\|$")
# Base value: "**9**（公式：`xxx`）" or "16（公式：`xxx`）"
BASE_VALUE_BOLD_RE = re.compile(r"\*\*(\d+)\*\*\s*[（(]公式[：:]\s*`(.+?)`[）)]")
BASE_VALUE_PLAIN_RE = re.compile(r"(\d+)\s*[（(]公式[：:]\s*`(.+?)`[）)]")
RARITY_RE = re.compile(r"(\d+)\s*星")
COST_SP_RE = re.compile(r"(\d+)\s*SP")
COST_PASSIVE_RE = re.compile(r"被动")

# Numbered list class card: "1. **卡牌名** ★（类型）：..." or "1. **卡牌名** ★：..."
NUMBERED_CARD_RE = re.compile(
    r"^(\d+)\.\s*\*\*(.+?)\*\*\s*(★*)\s*(?:（(.+?)）)?[：:]"
)
# Compact numbered card without stars: "1. **卡牌名**（类型）：..."
NUMBERED_CARD_NO_STAR_RE = re.compile(
    r"^(\d+)\.\s*\*\*(.+?)\*\*\s*(?:（(.+?)）)?[：:]"
)

# Inline fields in numbered card format
INLINE_COST_RE = re.compile(r"(\d+)\s*SP")
INLINE_BASE_RE = re.compile(r"基础数值\s*[=＝]\s*(.+?)(?:[。，,\.]|$)")
INLINE_FORMULA_RE = re.compile(r"`(.+?)`")


def parse_card_table(table_text: str) -> dict:
    """Parse a markdown table containing card fields."""
    fields = {}
    lines = table_text.strip().split("\n")
    current_field = None
    current_value: list[str] = []

    for line in lines:
        m = TABLE_ROW_RE.match(line)
        if m:
            if current_field:
                fields[current_field] = "\n".join(current_value).strip()
            current_field = m.group(1).strip()
            current_value = [m.group(2).strip()]
        else:
            if current_field and line.strip() and not line.strip().startswith("|-"):
                if line.strip().startswith("|"):
                    sub_m = re.match(r"^\|\s*(.+?)\s*\|$", line)
                    if sub_m:
                        current_value.append(sub_m.group(1).strip())
                else:
                    current_value.append(line.strip())

    if current_field:
        fields[current_field] = "\n".join(current_value).strip()

    return fields


def parse_rarity(rarity_str: str) -> int:
    """Parse rarity string like '1 星' -> 1, or count ★ symbols."""
    m = RARITY_RE.search(rarity_str)
    if m:
        return int(m.group(1))
    stars = rarity_str.count("★")
    if stars > 0:
        return stars
    return 1


def parse_cost(cost_str: str) -> dict:
    """Parse cost string into structured form."""
    result = {"cost_type": "sp", "cost": 0, "condition": None, "usage_limit": None}

    if COST_PASSIVE_RE.search(cost_str):
        result["cost_type"] = "passive"
        result["cost"] = 0
        cond_m = re.search(r"[（(](.+?)[）)]", cost_str)
        if cond_m:
            result["condition"] = cond_m.group(1)
        return result

    m = COST_SP_RE.search(cost_str)
    if m:
        result["cost"] = int(m.group(1))

    # Trigger conditions
    cond_m = re.search(r"[（(]仅可(.+?)[）)]", cost_str)
    if cond_m:
        result["condition"] = "仅可" + cond_m.group(1)

    # Usage limits
    limit_m = re.search(r"每(.+?)[可]?使用\s*(\d+)\s*次", cost_str)
    if limit_m:
        result["usage_limit"] = {"scope": "每" + limit_m.group(1), "count": int(limit_m.group(2))}

    # Per-battle limits
    battle_m = re.search(r"每场遭遇战可使用\s*(\d+)\s*次", cost_str)
    if battle_m:
        result["usage_limit"] = {"scope": "每场遭遇战", "count": int(battle_m.group(1))}

    return result


def parse_base_value(base_str: str) -> dict:
    """Parse base value string like '**9**（公式：`xxx`）' or '16（公式：`xxx`）'."""
    result = {"base_value": None, "base_value_formula": None}
    # Try bold format first
    m = BASE_VALUE_BOLD_RE.search(base_str)
    if m:
        result["base_value"] = int(m.group(1))
        result["base_value_formula"] = m.group(2)
        return result
    # Try plain format
    m = BASE_VALUE_PLAIN_RE.search(base_str)
    if m:
        result["base_value"] = int(m.group(1))
        result["base_value_formula"] = m.group(2)
        return result
    # Try just bold number
    num_m = re.search(r"\*\*(\d+)\*\*", base_str)
    if num_m:
        result["base_value"] = int(num_m.group(1))
    return result


def parse_card_type(type_str: str) -> list[str]:
    """Parse type string like '攻击 / 法术 / 单体' into list."""
    return [p.strip() for p in type_str.split("/")]


def parse_check(check_str: str) -> dict | None:
    """Parse check/judgment string."""
    if not check_str or "无需判定" in check_str:
        return None
    result = {"description": check_str}
    d20_m = re.search(r"d20\s*\+\s*(.+?)\s+vs\s+(.+)", check_str)
    if d20_m:
        result["roll"] = "d20 + " + d20_m.group(1).strip()
        result["vs"] = d20_m.group(2).strip()
    return result


def parse_numbered_class_cards(lines: list[str], start_idx: int) -> tuple[list[dict], int]:
    """Parse numbered-list class card format (used by 临光, 瑕光, 砾 et al.).

    Formats:
      1. **架盾** ★（防御）：1 SP，基础数值 = 生理耐受 + 5。效果描述...
      1. **架盾** ★：1 SP。效果描述...
      1. **架盾**（防御）：1 SP。效果描述...  (compact, no rarity stars)
    """
    cards = []
    i = start_idx

    # Skip past blank lines and ### sub-headings
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith("### ")):
        i += 1

    while i < len(lines):
        line = lines[i]

        # Stop at next section or sub-heading (that isn't the initial one)
        if line.startswith("## "):
            break

        # Skip blank lines and ### sub-headings
        if not line.strip() or line.startswith("### "):
            i += 1
            continue

        m = NUMBERED_CARD_RE.match(line)
        if not m:
            m = NUMBERED_CARD_NO_STAR_RE.match(line)

        if not m:
            break

        name = m.group(2).strip()
        if m.re == NUMBERED_CARD_RE:
            stars = m.group(3)
            rarity = len(stars) if stars else 1
            card_type_str = m.group(4) or ""
        else:
            rarity = 1
            card_type_str = m.group(3) or ""

        rest = line[m.end():].strip()

        card = {
            "card_id": "",  # filled later
            "name": name,
            "rarity": rarity,
            "category": "class",
            "card_type": [card_type_str] if card_type_str else [],
            "cost_type": "sp",
            "cost": 0,
            "damage_type": "physical",
            "target": "SINGLE",
            "range": 1,
            "min_damage": 0,
            "max_damage": 0,
            "atk_scale": 0.0,
            "tier": "basic",
            "class_required": "any",
            "description": "",
            "effect": "",
            "base_value": None,
            "base_value_formula": None,
            "check": None,
            "plot_impact": None,
            "usage_limit": None,
            "condition": None,
            "tags": [],
            "_needs_review": False,
            "_review_reasons": [],
        }

        # Parse cost: "1 SP，..."
        cost_m = INLINE_COST_RE.search(rest)
        if cost_m:
            card["cost"] = int(cost_m.group(1))
        else:
            card["cost_type"] = "passive"
            card["cost"] = 0

        # Parse base value: "基础数值 = 生理耐受 + 5。"
        base_m = INLINE_BASE_RE.search(rest)
        if base_m:
            base_part = base_m.group(1).strip()
            # Extract formula
            formula_m = INLINE_FORMULA_RE.search(base_part)
            if formula_m:
                card["base_value_formula"] = formula_m.group(1)
            else:
                card["base_value_formula"] = base_part

        # The description is the rest after the base value
        if base_m:
            desc_start = base_m.end()
            effect_text = rest[desc_start:].strip().lstrip("。，,.").strip()
        else:
            effect_text = rest

        card["effect"] = effect_text
        card["description"] = effect_text
        card["_needs_review"] = True
        card["_review_reasons"].append("numbered list format - needs manual fill of damage/range/target")

        cards.append(card)
        i += 1

    return cards, i


def make_card_template(card_index: int, category: str, class_name: str | None) -> dict:
    """Create a card dict with default values."""
    return {
        "card_id": f"card_{card_index:03d}",
        "name": "",
        "rarity": 1,
        "category": category,
        "card_type": [],
        "cost_type": "sp",
        "cost": 0,
        "damage_type": "physical",
        "target": "SINGLE",
        "range": 1,
        "min_damage": 0,
        "max_damage": 0,
        "atk_scale": 0.0,
        "tier": "basic",
        "class_required": class_name or "any",
        "description": "",
        "effect": "",
        "base_value": None,
        "base_value_formula": None,
        "check": None,
        "plot_impact": None,
        "usage_limit": None,
        "condition": None,
        "tags": [],
        "_needs_review": False,
        "_review_reasons": [],
    }


def parse_table_card(lines: list[str], start_idx: int, char_name: str,
                     card_index: int, section: str, class_name: str | None) -> tuple[dict | None, int]:
    """Parse a single markdown table card starting at start_idx.

    Returns (card_dict or None, next_index).
    """
    heading_line = lines[start_idx]
    heading_m = CARD_HEADING_RE.match(heading_line)
    if not heading_m:
        return None, start_idx

    card_name = heading_m.group(1).strip()
    rarity = len(heading_m.group(2))

    # Collect table lines
    table_lines = []
    j = start_idx + 1
    while j < len(lines):
        if lines[j].startswith("### ") or lines[j].startswith("## "):
            break
        table_lines.append(lines[j])
        j += 1

    table_text = "\n".join(table_lines)
    fields = parse_card_table(table_text)

    card = make_card_template(card_index, section, class_name)
    card["card_id"] = f"{char_name}_{card_index:02d}"
    card["name"] = card_name

    # Rarity: from table field first, then from heading stars
    if "稀有度" in fields:
        card["rarity"] = parse_rarity(fields["稀有度"])
    else:
        card["rarity"] = rarity

    # Type
    if "类型" in fields:
        card["card_type"] = parse_card_type(fields["类型"])

    # Cost
    if "消耗" in fields:
        cost_info = parse_cost(fields["消耗"])
        card["cost_type"] = cost_info["cost_type"]
        card["cost"] = cost_info["cost"]
        if cost_info.get("condition"):
            card["condition"] = cost_info["condition"]
        if cost_info.get("usage_limit"):
            card["usage_limit"] = cost_info["usage_limit"]

    # Base value
    if "基础数值" in fields:
        bv = parse_base_value(fields["基础数值"])
        card["base_value"] = bv.get("base_value")
        card["base_value_formula"] = bv.get("base_value_formula")

    # Effect
    if "效果" in fields:
        card["effect"] = fields["效果"].strip()

    # Check
    if "判定" in fields:
        card["check"] = parse_check(fields["判定"])

    # Plot impact
    if "剧情影响" in fields:
        card["plot_impact"] = fields["剧情影响"].strip()

    # Notes
    if "备注" in fields:
        note = fields["备注"].strip()
        if card["effect"]:
            card["effect"] += "\n\n【备注】" + note
        else:
            card["effect"] = "【备注】" + note

    # Validation
    if not card["base_value"] and not card["base_value_formula"]:
        card["_needs_review"] = True
        card["_review_reasons"].append("无法解析基础数值")
    if not card["effect"]:
        card["_needs_review"] = True
        card["_review_reasons"].append("效果字段为空")

    card["description"] = card["effect"]

    # Determine tier from cost
    if card["cost_type"] != "passive" and card["cost"] >= 3:
        card["tier"] = "elite"
    elif card["cost_type"] == "passive":
        card["tier"] = "basic"

    return card, j


def get_class_name_from_section(line: str) -> str | None:
    """Extract class name from a section heading."""
    # "## 职业通用卡牌（术师）" or "## 通用卡牌池"
    m = re.search(r"[（(](.+?)[）)]", line)
    if m:
        return m.group(1)
    return None


def is_numbered_list_section(lines: list[str], heading_idx: int) -> bool:
    """Check if the section after a class heading uses numbered list format.

    Skips past blank lines and ### sub-headings.
    """
    for k in range(heading_idx + 1, min(heading_idx + 15, len(lines))):
        line = lines[k]
        if NUMBERED_CARD_RE.match(line) or NUMBERED_CARD_NO_STAR_RE.match(line):
            return True
        if line.startswith("## "):
            return False
    return False


def get_character_class(char_name: str) -> str | None:
    """Read the character's class from index.md frontmatter."""
    index_path = os.path.join(CHAR_DIR, char_name, "index.md")
    if not os.path.exists(index_path):
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Extract YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                fm_text = parts[1]
                for line in fm_text.split("\n"):
                    line = line.strip()
                    if line.startswith("class:"):
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def migrate_character(char_name: str) -> dict | None:
    """Parse a character's combat.md and return the combat.json structure."""
    combat_path = os.path.join(CHAR_DIR, char_name, "combat.md")
    if not os.path.exists(combat_path):
        print(f"  SKIP {char_name}: no combat.md")
        return None

    with open(combat_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Fallback: read class from index.md frontmatter
    fallback_class = get_character_class(char_name)
    result = {"version": 1, "exclusive_cards": [], "class_cards": [],
              "class_name": fallback_class}
    exclusive_cards = []
    class_cards = []
    current_section = None
    card_index = 0

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip HTML comments
        if line.strip().startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        # Section headings
        if line.startswith("## 专属卡牌"):
            current_section = "exclusive"
            i += 1
            continue
        elif line.startswith("## 职业通用卡牌") or line.startswith("## 通用卡牌池"):
            current_section = "class"
            class_name = get_class_name_from_section(line)
            if class_name:
                result["class_name"] = class_name

            # Check if this section uses numbered list format
            if is_numbered_list_section(lines, i):
                numbered_cards, next_i = parse_numbered_class_cards(lines, i + 1)
                for c in numbered_cards:
                    c["card_id"] = f"{char_name}_{card_index:02d}"
                    c["class_required"] = result.get("class_name") or "any"
                    card_index += 1
                class_cards.extend(numbered_cards)
                i = next_i
                current_section = None
                continue
            i += 1
            continue
        elif line.startswith("## "):
            current_section = None
            i += 1
            continue

        # Card headings (table format)
        if CARD_HEADING_RE.match(line) and current_section:
            card, next_i = parse_table_card(
                lines, i, char_name, card_index,
                current_section, result.get("class_name")
            )
            if card:
                if current_section == "exclusive":
                    exclusive_cards.append(card)
                else:
                    class_cards.append(card)
                card_index += 1
            i = next_i
            continue

        i += 1

    result["exclusive_cards"] = exclusive_cards
    result["class_cards"] = class_cards

    # Compute hash
    hash_input = json.dumps(
        {"exclusive_cards": exclusive_cards, "class_cards": class_cards},
        ensure_ascii=False, sort_keys=True
    )
    result["_hash"] = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    return result


def main():
    os.makedirs(CHAR_DIR, exist_ok=True)
    characters = sorted(os.listdir(CHAR_DIR))

    total = 0
    for name in characters:
        subdir = os.path.join(CHAR_DIR, name)
        if not os.path.isdir(subdir):
            continue
        index_path = os.path.join(subdir, "index.md")
        if not os.path.isfile(index_path):
            continue

        print(f"Processing: {name}")
        data = migrate_character(name)
        if data is None:
            continue

        needs_review = sum(
            1 for c in data["exclusive_cards"] + data["class_cards"]
            if c.get("_needs_review")
        )

        output_path = os.path.join(subdir, "combat.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"  -> {len(data['exclusive_cards'])} exclusive + "
              f"{len(data['class_cards'])} class cards"
              f"{' (' + str(needs_review) + ' need review)' if needs_review else ''}")
        total += 1

    print(f"\nDone. Processed {total} characters.")


if __name__ == "__main__":
    main()
