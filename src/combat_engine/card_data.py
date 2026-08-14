"""
Card pools per class — each class has 8 cards (5 basic + 3 elite).

Cards are designed around class identity:
  - 术师: arts damage, medium range, AOE focus
  - 近卫: physical melee, high damage, self-sustain
  - 狙击: physical long range, single-target precision
  - 重装: mixed melee, DEF/RES buffs, threat management
  - 先锋: physical melee, fast, low cost
  - 医疗: healing arts, ally support
  - 辅助: mixed range, debuffs and control
  - 特种: mixed short range, high mobility, unique effects
"""

from combat_engine.card import Card

# ══════════════════════════════════════════════════════════════════════════════
#  术师 (Caster) — arts, medium range, AOE
# ══════════════════════════════════════════════════════════════════════════════

CASTER_CARDS = [
    Card("caster_bolt", "能量弹", "发射一枚源石能量弹",
         "arts", 4, 8, 0.4, "SINGLE", 3, 1, "basic", "术师"),
    Card("caster_shock", "法术冲击", "凝聚高密度源石能量",
         "arts", 7, 12, 0.6, "SINGLE", 3, 2, "basic", "术师"),
    Card("caster_nova", "冰霜新星", "以目标为中心释放冷冻能量",
         "arts", 4, 7, 0.4, "ADJACENT", 2, 2, "basic", "术师"),
    Card("caster_storm", "源石风暴", "召唤源石能量风暴覆盖区域",
         "arts", 5, 10, 0.5, "AREA_2X2", 2, 2, "basic", "术师"),
    Card("caster_burn", "法力灼烧", "燃烧法力，对十字范围内敌人造成伤害",
         "arts", 3, 6, 0.3, "CROSS", 2, 3, "basic", "术师",
         effects=[{"type": "burn", "value": 4, "duration": 2}]),
    # Elite
    Card("caster_missile", "奥术飞弹", "发射威力巨大的奥术飞弹",
         "arts", 10, 18, 1.0, "SINGLE", 4, 2, "elite", "术师"),
    Card("caster_void", "虚空风暴", "从虚空中召唤能量风暴",
         "arts", 8, 14, 0.8, "AREA_2X2", 3, 3, "elite", "术师"),
    Card("caster_inferno", "灵魂烈焰", "释放灵魂之力，灼烧所有敌人",
         "arts", 6, 10, 0.7, "GLOBAL", -1, 3, "elite", "术师"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  近卫 (Guard) — physical melee, high damage
# ══════════════════════════════════════════════════════════════════════════════

GUARD_CARDS = [
    Card("guard_slash", "斩击", "基础剑术斩击",
         "physical", 5, 9, 0.5, "SINGLE", 1, 1, "basic", "近卫"),
    Card("guard_wide", "横斩", "横向扫击面前敌人",
         "physical", 4, 7, 0.4, "ADJACENT", 1, 2, "basic", "近卫"),
    Card("guard_heavy", "重击", "蓄力后奋力一击",
         "physical", 8, 14, 0.8, "SINGLE", 1, 2, "basic", "近卫"),
    Card("guard_cleave", "剑刃风暴", "旋转剑刃攻击周围区域",
         "physical", 3, 6, 0.3, "AREA_2X2", 1, 2, "basic", "近卫"),
    Card("guard_pierce", "破甲斩", "瞄准弱点，无视部分防御",
         "physical", 6, 10, 0.6, "SINGLE", 1, 1, "basic", "近卫"),
    # Elite
    Card("guard_true_silver", "真银斩", "银灰的绝技，斩断一切",
         "physical", 12, 20, 1.2, "GLOBAL", -1, 3, "elite", "近卫"),
    Card("guard_iaido", "赤霄拔刀", "拔刀术·赤霄，一刀两断",
         "physical", 8, 12, 0.8, "CROSS", 1, 3, "elite", "近卫"),
    Card("guard_will", "不屈意志", "坚定意志，恢复生命力",
         "healing", 10, 18, 0.6, "SELF", 0, 1, "elite", "近卫"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  狙击 (Sniper) — physical, long range, precision
# ══════════════════════════════════════════════════════════════════════════════

SNIPER_CARDS = [
    Card("sniper_aim", "精准射击", "瞄准弱点精确射击",
         "physical", 5, 9, 0.5, "SINGLE", 5, 1, "basic", "狙击"),
    Card("sniper_rapid", "连射", "快速连续射击",
         "physical", 3, 6, 0.3, "SINGLE", 5, 1, "basic", "狙击"),
    Card("sniper_ap_round", "穿甲弹", "发射穿甲弹穿透直线上的敌人",
         "physical", 4, 7, 0.4, "LINE_3", 4, 2, "basic", "狙击"),
    Card("sniper_weakpoint", "狙击要害", "寻找并打击要害部位",
         "physical", 8, 13, 0.7, "SINGLE", 5, 2, "basic", "狙击"),
    Card("sniper_rain", "箭雨", "向区域倾泻箭矢",
         "physical", 3, 6, 0.3, "AREA_2X2", 4, 2, "basic", "狙击"),
    # Elite
    Card("sniper_extreme", "超远狙击", "极限距离的精准狙杀",
         "physical", 10, 15, 1.0, "GLOBAL", -1, 3, "elite", "狙击"),
    Card("sniper_explosive", "爆裂箭", "带有爆炸效果的箭矢",
         "physical", 8, 12, 0.8, "ADJACENT", 5, 2, "elite", "狙击"),
    Card("sniper_lethal", "致命一击", "瞄准即死弱点",
         "physical", 12, 22, 1.5, "SINGLE", 5, 3, "elite", "狙击"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  重装 (Defender) — mixed, tank
# ══════════════════════════════════════════════════════════════════════════════

DEFENDER_CARDS = [
    Card("defender_shield", "盾击", "用盾牌猛击敌人",
         "physical", 3, 6, 0.4, "SINGLE", 1, 1, "basic", "重装"),
    Card("defender_taunt", "嘲讽打击", "挑衅敌人使其注意力转移",
         "physical", 1, 4, 0.2, "ADJACENT", 1, 1, "basic", "重装"),
    Card("defender_bash", "重甲冲撞", "利用重甲冲撞目标",
         "physical", 5, 9, 0.5, "SINGLE", 1, 2, "basic", "重装"),
    Card("defender_wall", "防御阵线", "为全体友军提供防御支援",
         "healing", 0, 0, 0.0, "ALL_ALLIES", -1, 2, "basic", "重装",
         effects=[{"type": "shield", "value": 6}]),
    Card("defender_quake", "震荡锤击", "锤击地面造成范围伤害",
         "mixed", 3, 6, 0.3, "AREA_2X2", 1, 2, "basic", "重装"),
    # Elite
    Card("defender_breach", "不破壁垒", "极限防御姿态，大幅提升防御",
         "healing", 0, 0, 0.0, "SELF", 0, 2, "elite", "重装",
         effects=[{"type": "shield", "value": 12}]),
    Card("defender_quake_elite", "地震锤", "全力一击引发地震",
         "mixed", 6, 12, 0.7, "AREA_2X2", 1, 3, "elite", "重装"),
    Card("defender_fortress", "坚不可摧", "恢复大量生命力",
         "healing", 15, 25, 0.8, "SELF", 0, 1, "elite", "重装"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  先锋 (Vanguard) — physical, fast, low cost
# ══════════════════════════════════════════════════════════════════════════════

VANGUARD_CARDS = [
    Card("vang_stab", "突刺", "快速突刺攻击",
         "physical", 4, 7, 0.4, "SINGLE", 1, 1, "basic", "先锋"),
    Card("vang_dash", "冲锋", "高速冲锋攻击",
         "physical", 3, 6, 0.3, "LINE_3", 2, 1, "basic", "先锋"),
    Card("vang_flurry", "连续打击", "快速连续攻击",
         "physical", 3, 5, 0.3, "SINGLE", 1, 1, "basic", "先锋"),
    Card("vang_quick", "迅捷斩", "利用速度优势攻击",
         "physical", 5, 8, 0.5, "SINGLE", 1, 1, "basic", "先锋"),
    Card("vang_recon", "侦察标记", "标记敌方弱点",
         "physical", 2, 4, 0.2, "ADJACENT", 1, 1, "basic", "先锋"),
    # Elite
    Card("vang_blitz", "闪电突袭", "以闪电般的速度突击",
         "physical", 8, 12, 0.8, "SINGLE", 2, 2, "elite", "先锋"),
    Card("vang_formation", "先锋号令", "激励全体友军",
         "healing", 5, 10, 0.4, "ALL_ALLIES", -1, 2, "elite", "先锋"),
    Card("vang_decimate", "横扫千军", "扫荡前方所有敌人",
         "physical", 6, 10, 0.7, "ADJACENT", 1, 3, "elite", "先锋"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  医疗 (Medic) — healing
# ══════════════════════════════════════════════════════════════════════════════

MEDIC_CARDS = [
    Card("medic_heal", "治疗术", "基础治疗法术",
         "healing", 6, 12, 0.5, "SINGLE", 3, 1, "basic", "医疗"),
    Card("medic_group", "群体治疗", "治疗范围内多名友军",
         "healing", 4, 8, 0.3, "ADJACENT", 3, 2, "basic", "医疗"),
    Card("medic_cleanse", "净化术", "驱散负面效果并恢复生命",
         "healing", 3, 7, 0.3, "SINGLE", 3, 1, "basic", "医疗"),
    Card("medic_shield", "守护之盾", "为友军提供源石护盾",
         "healing", 5, 10, 0.4, "SINGLE", 3, 1, "basic", "医疗",
         effects=[{"type": "shield", "value": 8}]),
    Card("medic_regen", "生命恢复", "持续恢复目标生命力",
         "healing", 3, 6, 0.2, "SINGLE", 4, 2, "basic", "医疗"),
    # Elite
    Card("medic_miracle", "奇迹之愈", "释放强大的治愈奇迹",
         "healing", 12, 22, 1.0, "SINGLE", 4, 2, "elite", "医疗"),
    Card("medic_sanctuary", "圣域", "为大范围友军提供强力治疗",
         "healing", 8, 14, 0.7, "ALL_ALLIES", -1, 3, "elite", "医疗"),
    Card("medic_arts_atk", "源石惩戒", "以治愈之力转化为攻击",
         "arts", 8, 14, 0.8, "SINGLE", 3, 2, "elite", "医疗"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  辅助 (Supporter) — mixed, control/debuff
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTER_CARDS = [
    Card("supp_slow", "减速术", "减速敌人并造成微弱伤害",
         "arts", 2, 5, 0.2, "SINGLE", 3, 1, "basic", "辅助",
         effects=[{"type": "slow", "duration": 2}]),
    Card("supp_debuff", "削弱", "削弱目标防御",
         "arts", 1, 4, 0.2, "SINGLE", 3, 1, "basic", "辅助",
         effects=[{"type": "weaken", "duration": 2}]),
    Card("supp_bind", "束缚术", "束缚目标使其无法移动",
         "arts", 3, 6, 0.3, "SINGLE", 3, 1, "basic", "辅助",
         effects=[{"type": "bind", "duration": 2}]),
    Card("supp_zone", "领域展开", "在区域释放削弱力场",
         "mixed", 3, 6, 0.3, "AREA_2X2", 2, 2, "basic", "辅助"),
    Card("supp_disrupt", "干扰术", "干扰敌方行动",
         "arts", 4, 7, 0.4, "SINGLE", 3, 1, "basic", "辅助",
         effects=[{"type": "silence", "duration": 2}]),
    # Elite
    Card("supp_nullify", "源石沉默", "沉默区域内的源石技艺",
         "arts", 6, 10, 0.6, "AREA_2X2", 3, 3, "elite", "辅助",
         effects=[{"type": "silence", "duration": 2}]),
    Card("supp_overload", "增幅过载", "为全体友军增幅攻击",
         "healing", 0, 0, 0.0, "ALL_ALLIES", -1, 2, "elite", "辅助",
         effects=[{"type": "strengthen", "duration": 2}]),
    Card("supp_control", "精神操控", "强大的控制法术",
         "arts", 8, 12, 0.7, "CROSS", 3, 3, "elite", "辅助"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  特种 (Specialist) — mixed, short range, unique
# ══════════════════════════════════════════════════════════════════════════════

SPECIALIST_CARDS = [
    Card("spec_shift", "位移术", "快速位移到目标身边并攻击",
         "physical", 3, 6, 0.3, "SINGLE", 2, 1, "basic", "特种"),
    Card("spec_backstab", "背刺", "从背后突袭目标",
         "physical", 5, 9, 0.5, "SINGLE", 1, 1, "basic", "特种"),
    Card("spec_trap", "陷阱", "布置源石陷阱",
         "mixed", 4, 8, 0.4, "SINGLE", 2, 1, "basic", "特种"),
    Card("spec_shadow", "暗影步", "潜入暗影中接近目标",
         "physical", 3, 5, 0.3, "SINGLE", 2, 1, "basic", "特种"),
    Card("spec_evade", "闪避姿态", "提升闪避并反击",
         "physical", 2, 5, 0.3, "SINGLE", 1, 1, "basic", "特种"),
    # Elite
    Card("spec_execute", "处决", "对低生命值目标造成致命伤害",
         "physical", 10, 18, 1.0, "SINGLE", 1, 2, "elite", "特种"),
    Card("spec_smoke", "烟雾弹", "在区域释放烟雾掩护",
         "mixed", 5, 9, 0.5, "AREA_2X2", 2, 2, "elite", "特种"),
    Card("spec_ambush", "伏击", "从暗处发动致命伏击",
         "physical", 8, 14, 0.9, "SINGLE", 2, 3, "elite", "特种"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  Master Pool
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#  战术指挥 (Commander) — mixed, global range, support + strike
# ══════════════════════════════════════════════════════════════════════════════

COMMANDER_CARDS = [
    Card("cmd_order", "战术指令", "发出战术指令增强友军",
         "mixed", 3, 6, 0.3, "SINGLE", 4, 1, "basic", "战术指挥"),
    Card("cmd_strike", "精准打击", "指挥远程精准打击",
         "physical", 4, 8, 0.4, "SINGLE", 4, 1, "basic", "战术指挥"),
    Card("cmd_shell", "炮击指令", "呼叫炮火支援",
         "physical", 3, 7, 0.4, "ADJACENT", 4, 2, "basic", "战术指挥"),
    Card("cmd_rally", "集结号令", "激励友军恢复生命",
         "healing", 4, 8, 0.3, "SINGLE", 3, 1, "basic", "战术指挥"),
    Card("cmd_scan", "战场扫描", "扫描战场暴露敌人弱点",
         "arts", 2, 5, 0.2, "CROSS", 4, 1, "basic", "战术指挥"),
    # Elite
    Card("cmd_orbital", "轨道打击", "呼叫轨道炮火打击",
         "mixed", 8, 14, 0.8, "AREA_2X2", -1, 3, "elite", "战术指挥"),
    Card("cmd_banner", "战旗", "竖起罗德岛战旗鼓舞全军",
         "healing", 6, 12, 0.5, "ALL_ALLIES", -1, 2, "elite", "战术指挥"),
    Card("cmd_trap", "战术陷阱", "布置精心设计的战术陷阱",
         "physical", 10, 16, 0.9, "SINGLE", 4, 3, "elite", "战术指挥"),
]

CLASS_CARD_POOLS: dict[str, list[Card]] = {
    "术师": CASTER_CARDS,
    "近卫": GUARD_CARDS,
    "狙击": SNIPER_CARDS,
    "重装": DEFENDER_CARDS,
    "先锋": VANGUARD_CARDS,
    "医疗": MEDIC_CARDS,
    "辅助": SUPPORTER_CARDS,
    "特种": SPECIALIST_CARDS,
    "战术指挥": COMMANDER_CARDS,
}


def get_cards_for_class(char_class: str) -> list[Card]:
    """Get all cards available to a given class."""
    return CLASS_CARD_POOLS.get(char_class, [])


def get_starting_deck(char_class: str, count: int = 7) -> list[Card]:
    """Draw a starting deck for a character.

    Returns all basic cards from the class pool, supplemented with
    random elite cards if needed to reach `count`.

    Cards are deep-copied so each character gets independent instances —
    `add_player_unit` sets `card.owner`, which must not mutate the shared
    class pool or leak across characters.
    """
    import random
    import copy
    pool = get_cards_for_class(char_class)
    basics = [copy.deepcopy(c) for c in pool if c.tier == "basic"]
    elites = [copy.deepcopy(c) for c in pool if c.tier == "elite"]

    result = list(basics)
    if len(result) < count and elites:
        needed = min(count - len(result), len(elites))
        result.extend(random.sample(elites, needed))
    return result
