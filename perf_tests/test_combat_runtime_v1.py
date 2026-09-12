"""
P0 运行时语义回归测试（balance_version 1）—— 行动经济 / 敌人行动槽 / 保底抽牌 /
护盾语义 / 存档往返与迁移 / 遥测。

运行方式（纯标准库，无需 frontmatter / chromadb）：
    python perf_tests/test_combat_runtime_v1.py
"""
import os
import random
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from combat_engine.card import Card, CardPool                      # noqa: E402
from combat_engine.engine import CombatEngine                      # noqa: E402
from combat_engine.entity import CombatUnit                        # noqa: E402

BASE_ATTRS = {
    "physical_strength": 5, "mobility": 5, "physiological_tolerance": 5,
    "tactical_planning": 5, "combat_skill": 5,
    "originium_arts_assimilation": 5, "emotional_stability": 5, "charisma": 5,
}


def make_player(name: str, hp: int = 120, attrs: dict | None = None,
                char_class: str = "近卫") -> CombatUnit:
    return CombatUnit(unit_id=name, name=name, team="player",
                      char_class=char_class, max_hp=hp, hp=hp,
                      PATK=20, MATK=20, HEAL=20, DEF=6, RES=6,
                      SPD=10, HIT=10, EVA=5, AP=2, MAX_AP=2,
                      attributes=dict(attrs or BASE_ATTRS))


def make_enemy(name: str, hp: int = 90, max_ap: int = 3,
               action_slots: int = 1, ai_skills=None,
               ai_behavior: str = "aggressive",
               patk: int = 24, spd: int = 9) -> CombatUnit:
    return CombatUnit.create_enemy(
        name=name, char_class="", hp=hp, patk=patk, matk=16,
        defense=5, resist=4, spd=spd, hit=6, eva=5,
        max_ap=max_ap, ai_behavior=ai_behavior,
        ai_skills=ai_skills or ["enemy_atk"],
        action_slots=action_slots)


def build_engine(players: list[CombatUnit], player_cards: list[Card],
                 enemies: list[tuple[CombatUnit, tuple[int, int]]]) -> CombatEngine:
    eng = CombatEngine()
    for i, p in enumerate(players):
        eng.add_player_unit(p, pos=(i, 0))
    for card in player_cards:
        owner = next(u for u in players if u.name == card.owner)
        eng.shared_pool.deck.append(card)
    for u, pos in enemies:
        eng.add_enemy_unit(u, pos)
    return eng


def slash_cards(owner: str, count: int = 4, cost: int = 1) -> list[Card]:
    return [Card(f"{owner}_slash_{i}", "斩击", "测试斩击", "physical",
                 10, 10, 0.0, "SINGLE", 1, cost, "basic", "近卫",
                 owner=owner) for i in range(count)]


class ActionEconomyTests(unittest.TestCase):
    """P0-1：战术卡只花共享 AP，移动只花个人 AP；非法操作不消费。"""

    def setUp(self):
        random.seed(7)
        self.p = make_player("A", hp=300)
        self.p.AP = 2
        self.p.MAX_AP = 2
        self.e = make_enemy("E1", hp=500)
        self.eng = build_engine([self.p], slash_cards("A", 8), [(self.e, (0, 1))])
        self.eng.start_battle()
        self.assertEqual(self.eng.shared_ap, 4)  # 战术规划 5 → 基础 4

    def test_card_costs_shared_ap_only(self):
        card = next(c for c in self.eng.shared_pool.hand if c.cost == 1)
        before_personal = self.p.AP
        before_shared = self.eng.shared_ap
        results = self.eng.play_card("A", card, (0, 1))
        self.assertTrue(results, "出牌应命中目标")
        self.assertEqual(self.p.AP, before_personal, "出牌不得消耗个人 AP")
        self.assertEqual(self.eng.shared_ap, before_shared - 1)

    def test_move_costs_personal_ap_only(self):
        before_personal = self.p.AP
        before_shared = self.eng.shared_ap
        ok = self.eng.move_unit("A", (1, 0))
        self.assertTrue(ok)
        self.assertEqual(self.p.AP, before_personal - 1)
        self.assertEqual(self.eng.shared_ap, before_shared, "移动不得消耗共享 AP")

    def test_invalid_target_no_consumption(self):
        card = next(c for c in self.eng.shared_pool.hand if c.cost == 1)
        shared_before = self.eng.shared_ap
        ap_before = self.p.AP
        results = self.eng.play_card("A", card, (0, 4))  # 空单元格
        self.assertEqual(results, [], "空目标应被拒绝")
        self.assertEqual(self.eng.shared_ap, shared_before, "非法目标不得消耗共享 AP")
        self.assertEqual(self.p.AP, ap_before)
        self.assertIn(card, self.eng.shared_pool.hand, "非法目标不得弃牌")

    def test_out_of_range_no_consumption(self):
        card = next(c for c in self.eng.shared_pool.hand if c.cost == 1)
        shared_before = self.eng.shared_ap
        results = self.eng.play_card("A", card, (6, 6))  # 距离远超 range 1
        self.assertEqual(results, [])
        self.assertEqual(self.eng.shared_ap, shared_before)
        self.assertIn(card, self.eng.shared_pool.hand)

    def test_shared_ap_exhaustion(self):
        for _ in range(4):
            card = next(c for c in self.eng.shared_pool.hand if c.cost == 1)
            self.assertTrue(self.eng.play_card("A", card, (0, 1)))
        self.assertEqual(self.eng.shared_ap, 0)
        card = next((c for c in self.eng.shared_pool.hand if c.cost == 1), None)
        self.assertIsNotNone(card)
        before = len(self.eng.shared_pool.hand)
        self.assertEqual(self.eng.play_card("A", card, (0, 1)), [], "共享 AP 耗尽应拒绝")
        self.assertEqual(self.eng.shared_ap, 0)
        self.assertEqual(len(self.eng.shared_pool.hand), before, "拒绝时不得弃牌")

    def test_tactical_planning_8_gives_5(self):
        self.p.attributes["tactical_planning"] = 8
        self.eng._recalc_shared_ap_max()
        self.assertEqual(self.eng.SHARED_AP_MAX, 5)
        self.p.attributes["tactical_planning"] = 12
        self.eng._recalc_shared_ap_max()
        self.assertEqual(self.eng.SHARED_AP_MAX, 5, "上限封顶 5")

    def test_move_personal_ap_exhaustion(self):
        self.p.AP = 1
        self.assertTrue(self.eng.move_unit("A", (1, 0)))
        self.assertFalse(self.eng.move_unit("A", (2, 0)), "个人 AP 耗尽后移动应失败")


class GuaranteeDrawTests(unittest.TestCase):
    """P0-2：保底抽牌绝不取 exhaust，不换掉另一存活角色的唯一手牌。"""

    def _engine(self):
        random.seed(11)
        self.a = make_player("A", hp=300)
        self.b = make_player("B", hp=300)
        self.c = make_player("C", hp=300)
        eng = CombatEngine()
        for i, p in enumerate((self.a, self.b, self.c)):
            eng.add_player_unit(p, pos=(i, 0))
        return eng

    def test_never_pulls_from_exhaust(self):
        eng = self._engine()
        elite = Card("b_elite", "精英技", "测试精英", "physical", 10, 10, 0.0,
                     "SINGLE", 1, 2, "elite", "近卫", owner="B")
        # 手牌全是 A 的卡；B 的卡只剩 exhaust 里的精英卡
        eng.shared_pool.hand = slash_cards("A", 6)
        eng.shared_pool.deck = []
        eng.shared_pool.discard = []
        eng.shared_pool.exhaust = [elite]
        eng._character_guarantee()
        self.assertEqual(eng.shared_pool.exhaust, [elite], "耗竭区卡牌不得被保底捞回")
        self.assertFalse(any(c.owner == "B" for c in eng.shared_pool.hand),
                         "B 无牌可保底时不应从 exhaust 取卡")

    def test_keeps_sole_card_of_other_owner(self):
        eng = self._engine()
        a1, a2 = slash_cards("A", 2)
        b1 = slash_cards("B", 1)[0]
        c1 = slash_cards("C", 1)[0]
        eng.shared_pool.hand = [a1, a2, b1]  # C 缺卡；B 只有唯一一张
        eng.shared_pool.deck = [c1]
        eng.shared_pool.discard = []
        eng.shared_pool.exhaust = []
        eng._character_guarantee()
        self.assertIn(c1, eng.shared_pool.hand, "C 应获得保底卡")
        self.assertIn(b1, eng.shared_pool.hand, "不得换掉 B 的唯一手牌")
        self.assertEqual(sum(1 for c in eng.shared_pool.hand if c.owner == "B"), 1)

    def test_empty_piles_ok(self):
        eng = self._engine()
        eng.shared_pool.hand = slash_cards("A", 3)
        eng.shared_pool.deck = []
        eng.shared_pool.discard = []
        eng.shared_pool.exhaust = []
        eng._character_guarantee()  # 不应抛异常
        self.assertEqual(len(eng.shared_pool.hand), 3)

    def test_draw_from_empty_deck_when_discard_absent(self):
        eng = self._engine()
        eng.shared_pool.hand = slash_cards("A", 3)
        eng.shared_pool.deck = []
        eng.shared_pool.discard = [slash_cards("B", 1)[0]]
        eng.shared_pool.exhaust = []
        eng._character_guarantee()
        self.assertTrue(any(c.owner == "B" for c in eng.shared_pool.hand),
                        "应从弃牌堆保底补 B 的卡")


class EnemyActionSlotTests(unittest.TestCase):
    """P0-3：敌人每轮循环至 action_slots 或 AP 耗尽；预告与执行同一决策。"""

    def _setup(self, slots: int, max_ap: int = 3, dist: int = 1):
        random.seed(23)
        self.p = make_player("A", hp=600)
        self.p.MAX_AP = 3
        self.p.AP = 3
        self.e = make_enemy("E1", max_ap=max_ap, action_slots=slots, spd=20)
        eng = build_engine([self.p], slash_cards("A", 8), [(self.e, (0, dist))])
        eng.start_battle()
        return eng

    def test_one_slot_one_action(self):
        eng = self._setup(slots=1)
        intent = eng.state.enemy_intents["E1"]
        self.assertEqual(intent["action_slots"], 1)
        eng.end_player_round()
        self.assertEqual(eng.telemetry["rounds"]["1"]["enemy_actions"], 1,
                         "声明 1 槽必须恰好执行 1 次动作")

    def test_two_slots_two_actions(self):
        eng = self._setup(slots=2)
        intent = eng.state.enemy_intents["E1"]
        self.assertEqual(len(intent["actions"]), 2, "预告应列出 2 个动作")
        eng.end_player_round()
        self.assertEqual(eng.telemetry["rounds"]["1"]["enemy_actions"], 2,
                         "声明 2 槽必须执行 2 次动作")

    def test_ap_budget_limits_actions(self):
        eng = self._setup(slots=2, max_ap=1)
        intent = eng.state.enemy_intents["E1"]
        self.assertEqual(len(intent["actions"]), 1, "AP=1 只够 1 个动作")
        eng.end_player_round()
        self.assertEqual(eng.telemetry["rounds"]["1"]["enemy_actions"], 1)

    def test_preview_matches_execution(self):
        eng = self._setup(slots=2)
        planned = [a["card_id"] for a in eng.state.enemy_intents["E1"]["actions"]]
        self.assertTrue(planned, "预告应有出牌计划")
        eng.end_player_round()
        used = eng.telemetry["totals"]["cards_used"]
        for cid in planned:
            self.assertGreaterEqual(used.get(cid, 0), 1, f"预告的 {cid} 应被执行")

    def test_out_of_range_moves_per_slots(self):
        eng = self._setup(slots=2, dist=3)  # 距离 3，近战卡 range 1 → 移动
        intent = eng.state.enemy_intents["E1"]
        self.assertEqual([a["type"] for a in intent["actions"]], ["move", "move"],
                         "打不到时应预告 2 次移动")
        eng.end_player_round()
        self.assertEqual(self.e.pos, (0, 1), "2 个移动动作应前进 2 格")
        self.assertEqual(eng.telemetry["rounds"]["1"]["enemy_actions"], 2)

    def test_defensive_enemy_holds(self):
        random.seed(31)
        p = make_player("A", hp=600)
        e = make_enemy("E1", max_ap=3, action_slots=2, ai_behavior="defensive")
        eng = build_engine([p], slash_cards("A", 8), [(e, (0, 3))])
        eng.start_battle()
        self.assertEqual(eng.state.enemy_intents["E1"]["actions"], [],
                         "坚守型敌人出范围应无动作")
        eng.end_player_round()
        self.assertEqual(eng.telemetry["rounds"]["1"]["enemy_actions"], 0)

    def test_silenced_enemy_replans(self):
        random.seed(37)
        p = make_player("A", hp=600)
        e = make_enemy("E1", max_ap=3, action_slots=2, ai_skills=["enemy_bolt"])
        eng = build_engine([p], slash_cards("A", 8), [(e, (0, 1))])
        eng.start_battle()
        e.status["silence"] = 1  # arts 卡被禁（开局 tick 之后设置）
        eng.state.enemy_intents = eng._compute_enemy_intents()
        # 计划里不应出现 arts 出牌；执行也不应出牌（移动或防守）
        planned = eng.state.enemy_intents["E1"]["actions"]
        self.assertFalse(any(a.get("type") not in ("move", "defend")
                             for a in planned), "沉默敌人预告不得含 arts 出牌")
        eng.end_player_round()
        used = eng.telemetry["totals"]["cards_used"]
        self.assertFalse(any("bolt" in k for k in used), "沉默敌人不得实际施放 arts 卡")


class ShieldSemanticsTests(unittest.TestCase):
    """P0-4：全体护盾含施法者；def_scale；限时护盾到期消失。"""

    def setUp(self):
        random.seed(41)
        self.a = make_player("A", hp=300)
        self.b = make_player("B", hp=300)
        self.a.DEF = 8
        far = make_enemy("E_FAR", hp=999, max_ap=1, ai_behavior="defensive")
        self.eng = build_engine([self.a, self.b], slash_cards("A", 6), [(far, (6, 6))])
        self.eng.start_battle()

    def test_all_allies_shield_includes_caster(self):
        card = Card("wall", "防御阵线", "全体护盾", "healing", 0, 0, 0.0,
                    "ALL_ALLIES", -1, 2, "basic", "any", owner="A",
                    effects=[{"type": "shield", "value": 6, "def_scale": 0.25}])
        self.eng.shared_pool.hand.append(card)
        results = self.eng.play_card("A", card, self.a.pos)
        self.assertTrue(results)
        self.assertEqual(self.a.status_amount("shield"), 8, "施法者应获得 6+0.25×8 护盾")
        self.assertEqual(self.b.status_amount("shield"), 8)

    def test_timed_shield_expires(self):
        card = Card("wall2", "防御阵线", "限时护盾", "healing", 0, 0, 0.0,
                    "ALL_ALLIES", -1, 2, "basic", "any", owner="A",
                    effects=[{"type": "shield", "value": 5, "duration": 1}])
        self.eng.shared_pool.hand.append(card)
        self.eng.play_card("A", card, self.a.pos)
        self.assertEqual(self.a.status_amount("shield"), 5)
        self.eng._start_round()  # 下回合开始 → 限时护盾到期
        self.assertEqual(self.a.status_amount("shield"), 0)

    def test_untimed_shield_persists(self):
        card = Card("wall3", "防御阵线", "永久护盾", "healing", 0, 0, 0.0,
                    "ALL_ALLIES", -1, 2, "basic", "any", owner="A",
                    effects=[{"type": "shield", "value": 5}])
        self.eng.shared_pool.hand.append(card)
        self.eng.play_card("A", card, self.a.pos)
        self.eng._start_round()
        self.assertEqual(self.a.status_amount("shield"), 5, "无 duration 的护盾不衰减")

    def test_shield_absorbs_burn_then_expires(self):
        self.a.apply_status("shield", 4, duration=1)
        self.a.apply_burn(10, 2)
        self.eng._start_round()  # burn 先结算（护盾吸收 4），随后护盾到期
        self.assertGreaterEqual(self.a.hp, 300 - 6)
        self.assertEqual(self.a.status_amount("shield"), 0)


# 说明：原先的 SaveRoundTripTests（to_dict/from_dict 往返与 v0→v1 迁移）已随
# 「战斗态只在内存、不跨进程保存」的简化一并删除。若将来需要战斗中恢复，
# 应以「节点 spec + 命令流重放」实现，并在那时补对应的重放测试。


class TelemetryTests(unittest.TestCase):
    """P0-6：伤害来源 / 有效治疗与溢出 / 抽牌使用 / 玩家 AP 记账。"""

    def test_damage_by_source_and_healing_overflow(self):
        random.seed(61)
        a = make_player("A", hp=300)
        b = make_player("B", hp=300)
        e = make_enemy("E1", max_ap=3, action_slots=1)
        eng = build_engine([a, b], slash_cards("A", 8), [(e, (0, 1))])
        eng.start_battle()

        heal_card = Card("heal1", "治疗术", "治疗", "healing", 30, 30, 0.0,
                         "SINGLE", 3, 1, "basic", "any", owner="A")
        eng.shared_pool.hand.append(heal_card)
        eng.play_card("A", heal_card, a.pos)  # A 满血 → 溢出

        eng.end_player_round()  # 敌人攻击最近玩家
        totals = eng.telemetry["totals"]
        self.assertGreater(totals["damage_by_source"].get("E1", 0), 0,
                           "敌人伤害应按来源记账")
        self.assertGreater(totals["healing_overflow"], 0, "满血治疗应计溢出")
        self.assertEqual(totals["player_card_ap"], 1)

    def test_move_ap_and_cards_drawn(self):
        random.seed(67)
        a = make_player("A", hp=300)
        e = make_enemy("E1", hp=500, ai_behavior="defensive")
        eng = build_engine([a], slash_cards("A", 10), [(e, (0, 1))])
        eng.start_battle()
        eng.move_unit("A", (1, 0))
        totals = eng.telemetry["totals"]
        self.assertEqual(totals["player_move_ap"], 1)
        self.assertEqual(totals["player_moves"], 1)
        self.assertEqual(sum(totals["cards_drawn"].values()),
                         len(eng.shared_pool.hand),
                         "手牌每张都应计一次抽牌")

    def test_elite_card_exhausts_and_not_reusable(self):
        random.seed(71)
        a = make_player("A", hp=300)
        elite = Card("A_elite", "精英技", "测试精英", "physical", 10, 10, 0.0,
                     "SINGLE", 1, 2, "elite", "近卫", owner="A")
        e = make_enemy("E1")
        eng = build_engine([a], slash_cards("A", 6) + [elite], [(e, (0, 1))])
        eng.start_battle()
        if elite not in eng.shared_pool.hand:
            # 保底不保证精英入牌组；直接注入手牌验证耗竭语义
            eng.shared_pool.hand.append(elite)
        eng.play_card("A", elite, (0, 1))
        self.assertIn(elite, eng.shared_pool.exhaust)
        self.assertNotIn(elite, eng.shared_pool.hand)
        self.assertNotIn(elite, eng.shared_pool.discard)
        eng._draw_shared_hand()
        eng._character_guarantee()
        self.assertNotIn(elite, eng.shared_pool.hand, "耗竭卡不得被再次抽入")


if __name__ == "__main__":
    unittest.main(verbosity=2)
