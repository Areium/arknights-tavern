"""
Buff/Debuff 随机抽取池系统。

从 data/rules/buff-pool/ 加载 buff/debuff 条目，
d20 掷骰决定稀有度后随机抽取，支持修正值和降级回退。
"""

import os
import re
import random
import logging

logger = logging.getLogger(__name__)

# 稀有度映射：d20 结果 → (星级, 稀有度名)
_RARITY_TABLE = [
    (range(1, 6), 1, "★ 普通"),
    (range(6, 11), 2, "★★ 稀有"),
    (range(11, 15), 3, "★★★ 精良"),
    (range(15, 18), 4, "★★★★ 史诗"),
    (range(18, 20), 5, "★★★★★ 传说"),
    (range(20, 21), 6, "★★★★★★ 神话"),
]

DRAW_KEYWORDS = [
    "抽buff", "抽debuff", "抽取buff", "抽取debuff",
    "抽个buff", "抽个debuff", "抽一个buff", "抽一个debuff",
    "buff池", "debuff池", "抽奖", "抽卡",
    "draw buff", "draw debuff",
]


class BuffPool:
    """Buff/Debuff 随机抽取系统。"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "data", "rules", "buff-pool",
            )
        self._data_dir = data_dir
        self._cache: dict[str, dict[int, list[dict]]] = {}

    def _load_pool(self, filename: str) -> dict[int, list[dict]]:
        """解析 buff/debuff 池 markdown 文件，返回 {星级: [条目列表]}。"""
        if filename in self._cache:
            return self._cache[filename]

        path = os.path.join(self._data_dir, filename)
        pool: dict[int, list[dict]] = {s: [] for s in range(1, 7)}
        if not os.path.isfile(path):
            return pool

        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        entries = re.split(r"\n(?=### [A-Z]+-\d+:)", text)
        for block in entries:
            m = re.match(r"### ([A-Z]+-\d+): (.+?)(?:\((.+?)\))?\s*$", block, re.MULTILINE)
            if not m:
                continue
            entry_id = m.group(1).strip()
            name = m.group(2).strip()

            def _extract(key: str) -> str:
                mm = re.search(rf"- \*\*{key}\*\*[:：](.+?)$", block, re.MULTILINE)
                return mm.group(1).strip() if mm else ""

            category = _extract("类别")
            effect = _extract("效果")
            duration = _extract("持续")
            narrative = _extract("叙事")
            if narrative.startswith('"') and narrative.endswith('"'):
                narrative = narrative[1:-1]

            entry = {
                "id": entry_id, "name": name, "category": category,
                "effect": effect, "duration": duration, "narrative": narrative,
            }

            block_start = text.find(block)
            if block_start > 0:
                before = text[:block_start]
                stars_match = re.findall(
                    r"## (★+)\s*(?:[^(\n]+?)(?:\s*\([^)]*d20: (\d+)-?(\d+)?\))", before
                )
                if stars_match:
                    star_count = len(stars_match[-1][0])
                    if star_count in pool:
                        pool[star_count].append(entry)
                    continue

            for star_count in range(6, 0, -1):
                if "★" * star_count in block[:200]:
                    pool[star_count].append(entry)
                    break

        self._cache[filename] = pool
        return pool

    @staticmethod
    def _rarity_for_roll(roll: int) -> tuple[int, str]:
        for rng, stars, name in _RARITY_TABLE:
            if roll in rng:
                return stars, name
        return 1, "★ 普通"

    def draw(self, pool_name: str, modifier: int = 0) -> str:
        """从指定池中抽取一个 buff/debuff，返回格式化的结果。"""
        filename = "buffs.md" if pool_name == "buff" else "debuffs.md"
        pool = self._load_pool(filename)

        roll = random.randint(1, 20)
        adjusted = min(20, max(1, roll + modifier))
        stars, rarity_name = self._rarity_for_roll(adjusted)

        if modifier != 0 and adjusted != roll:
            mod_str = f"+{modifier}" if modifier > 0 else str(modifier)
            roll_info = f"d20 = {roll} (修正 {mod_str} → {adjusted})"
        else:
            roll_info = f"d20 = {roll}"

        available = pool.get(stars, [])
        if not available:
            for s in range(stars - 1, 0, -1):
                if pool.get(s):
                    available = pool[s]
                    stars = s
                    rarity_name = self._rarity_for_roll(
                        {1: 3, 2: 8, 3: 12, 4: 16, 5: 18, 6: 20}[s]
                    )[1]
                    break

        if not available:
            return f"🎲 {roll_info} → {rarity_name}\n该档位暂无可用条目。"

        entry = random.choice(available)
        return "\n".join([
            f"🎲 {roll_info}",
            f"📦 稀有度：{rarity_name} ({'★' * stars})",
            f"📛 {entry['id']}: {entry['name']}",
            f"📂 类别：{entry['category']}",
            f"📐 效果：{entry['effect']}",
            f"⏱ 持续：{entry['duration']}",
            f"💬 {entry['narrative']}",
        ])

    def draw_buff(self, modifier: int = 0) -> str:
        return self.draw("buff", modifier)

    def draw_debuff(self, modifier: int = 0) -> str:
        return self.draw("debuff", modifier)

    @staticmethod
    def is_draw_request(text: str) -> bool:
        return any(kw in text.lower().strip() for kw in DRAW_KEYWORDS)

    @staticmethod
    def parse_draw_request(text: str) -> tuple[bool, int]:
        """解析抽取请求，返回 (is_debuff, modifier)。"""
        is_debuff = any(kw in text.lower() for kw in ["debuff", "debuff池"])
        modifier = 0
        mod_match = re.search(r"\+(\d+)", text)
        if mod_match:
            modifier = int(mod_match.group(1))
        mod_match_neg = re.search(r"\-(\d+)", text)
        if mod_match_neg:
            modifier = -int(mod_match_neg.group(1))
        return is_debuff, modifier

    def reload(self):
        """清除缓存，下次抽取时重新加载文件。"""
        self._cache.clear()
