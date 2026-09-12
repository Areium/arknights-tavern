"""100% 召回验证：修复后完整方案（可读遭遇名 + 快速决策指令 + 空/截断重试）。

14 例 = 12 个应触发战斗的正例 + 2 个不应触发的负例（言语对峙/口角），检验召回与误报。
走修复后的 extract_markers() 真实路径，记录 retried/degraded/finish_reason。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from collections import Counter

from common import build_llm

from SceneManager import SceneManager

POSITIVE = [
    "训练场的警报骤然响起。三名整合运动士兵从侧门涌入，其中一个举起了燃烧瓶。阿米娅立刻压低身形：「博士，交给我们！」银灰已经拔剑在手，霜星的指尖凝出寒气。",
    "车队在山道遭遇伏击。雪坡上十几支弩箭同时射出，两名护卫当场倒下。灵知的数据终端闪烁着红光：「敌袭，疑似佩尔罗契家族的山雪鬼。」银灰沉声道：「保护博士，向会客厅撤退。」",
    "竞技场通道里，三名无胄盟刺客从阴影中现身，匕首的寒光一闪而逝。砾早已挡在博士身前，反手抽出短刀：「三个，交给我。」",
    "博士推开会议室的门，两名戴兜帽的整合运动感染者正站在档案柜前。他们看见博士，立刻掏出了武器。阿米娅从走廊另一头飞速赶来：「博士，快退后！」",
    "雨夜，罗德岛车队在峡谷地段遭遇伏击，三名整合运动术师从两侧岩壁同时施法，火球照亮了整条山道。临光大喝一声举盾顶在前面：「法师交给我，博士往后撤！」",
    "竞技场地牢的铁门被撞开，数十名被囚的感染者骑士冲了出来，领头的血骑士举起锈剑指向出口：「今天，要么走出去，要么躺着出去！」",
    "喀兰贸易大楼的会客室突然传来爆炸声，浓烟从走廊尽头涌出。数名持刀的雇佣兵从烟中冲出，直奔银灰所在方向。锏已经拔刀挡在门前：「家主，交给我。」",
    "训练场的模拟战进入第二场：血骑士单枪匹马站在场地中央，向博士挑战：「罗德岛的战术家，敢接这场比试吗？」他手中的长枪重重顿地。",
    "码头集装箱区，一道寒光贴着阴影掠过——无胄盟的狙击手已经占好了位置。砾拉住博士闪进集装箱夹缝：「两个射手，一个观察位。别抬头。」",
    "圣山山路的岔口，一队山雪鬼巡逻兵拦住了博士一行的去路，为首的队长按着刀柄：「大典期间，圣山禁地，谁都不许过。」身后十几把刀同时出鞘。",
    "庆典广场的人群忽然骚动，一名感染者引爆了随身携带的源石炸弹，冲击波掀翻了两排摊位。守卫与暴徒在火光中扭打在一起，阿米娅的惊呼声被爆炸声淹没。",
    "罗德岛走廊的通风口突然被顶开，两只猎犬型的源石生物扑出，獠牙上滴着涎液。走廊里灯光闪烁，陈警官拔出配枪挡在博士身前：「别慌，交给我。」",
]

NEGATIVE = [
    "雪山大典的观礼台上，银灰与阿克托斯迎面而立，气氛骤然凝固。阿克托斯冷笑一声：「希瓦艾什家的家主，在这座圣山面前，你还能那么笃定吗？」银灰没有回答，只是静静地看着他。",
    "食堂里，两名干员因为训练场使用时间争执起来，声音越来越大，最后谁也不理谁。围观的人劝了几句，两人各自端着餐盘走开，留下一片尴尬的安静。",
]


def run():
    llm = build_llm()
    sm = SceneManager(llm, None, combat_mode="tactical")
    out = []
    for text in POSITIVE + NEGATIVE:
        expected = text in POSITIVE
        parsed = sm.extract_markers(text, choices_count=0, beat_state_active=True)
        combat = parsed.get("combat")
        triggered = combat is not None and isinstance(combat, dict)
        enc_valid = True
        if triggered:
            eid = combat.get("encounter_id", "")
            enc_valid = bool(eid) and eid in {c.split("（")[0] for c in sm._list_encounters().split("、")} or eid == "初遇整合运动"
        out.append({
            "narrative": text[:24],
            "expected_combat": expected,
            "triggered": triggered,
            "encounter_id": (combat or {}).get("encounter_id") if triggered else None,
            "encounter_valid": enc_valid,
            "ok": (triggered == expected) and enc_valid,
            "degraded": parsed.get("degraded"),
            "retried": parsed.get("retried"),
            "finish_reason": parsed.get("finish_reason"),
        })
    ok = sum(1 for c in out if c["ok"])
    triggered_expected = sum(1 for c in out if c["expected_combat"] and c["triggered"])
    fp = sum(1 for c in out if not c["expected_combat"] and c["triggered"])
    payload = {
        "total": len(out),
        "recall": f"{triggered_expected}/12",
        "recall_rate": round(triggered_expected / 12, 3),
        "false_positive": fp,
        "all_ok": ok == len(out),
        "retry_count": sum(1 for c in out if c["retried"]),
        "degraded_final": sum(1 for c in out if c["degraded"]),
        "cases": out,
        "finish_counter": dict(Counter(c["finish_reason"] for c in out)),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    save = Path(__file__).resolve().parent / "results_recall100.json"
    save.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[已保存] {save}")


if __name__ == "__main__":
    run()