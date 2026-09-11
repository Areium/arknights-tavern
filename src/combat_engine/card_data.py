"""
Card pools per class — 战术卡单一真相源（design 方案 §10.1 / P0-4）。

硬编码卡表已迁移到 data/classes/<职业>/cards.json：
- `get_cards_for_class` 从 JSON 读取（card_json_loader 缓存）；
- 迁移前旧表快照见 perf_tests/cards_python_snapshot.json，
  等价性由 perf_tests/test_card_json_roundtrip.py 验证；
- 卡牌编辑通过 blueprints/cards.py 写回 JSON，保存后调用
  card_json_loader.clear_cache() 刷新运行时缓存。

Card 主体字段保留：伤害类型、基础区间、攻击缩放、目标形状、射程、费用、
层级、职业、效果、穿甲、净化；新增 rank/upgrade_branch/exhaust/power_tier/
cv_budget/cv_estimated/balance_version（见 Card 定义）。
"""

import copy
import random

from combat_engine.card import Card
from combat_engine.card_json_loader import load_class_cards


def get_cards_for_class(char_class: str) -> list[Card]:
    """Get all cards available to a given class (from the JSON source of truth)."""
    return load_class_cards(char_class)


def get_starting_deck(char_class: str, count: int = 7) -> list[Card]:
    """Draw a starting deck for a character.

    Returns all basic cards from the class pool, supplemented with
    random elite cards if needed to reach `count`.

    Cards are deep-copied so each character gets independent instances —
    `add_player_unit` sets `card.owner`, which must not mutate the shared
    class pool or leak across characters.
    """
    pool = get_cards_for_class(char_class)
    basics = [copy.deepcopy(c) for c in pool if c.tier == "basic"]
    elites = [copy.deepcopy(c) for c in pool if c.tier == "elite"]

    result = list(basics)
    if len(result) < count and elites:
        needed = min(count - len(result), len(elites))
        result.extend(random.sample(elites, needed))
    return result
