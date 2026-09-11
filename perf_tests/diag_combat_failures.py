"""战斗触发不稳定归因实验（修复 max_tokens 后）：

实验 A：原提示词（遭遇列表为机器 ID）→ 检验空响应是否消失
实验 B：遭遇列表注入「id（中文名）」（如 enc_snow_ambush（矿道伏击））→ 检验触发召回是否提升

均走修复后的 extract_markers() 真实路径，记录 degraded/finish_reason 用于归因。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import frontmatter

from common import build_llm

from SceneManager import SceneManager

CASES = [
    ("训练场的警报骤然响起。三名整合运动士兵从侧门涌入，其中一个举起了燃烧瓶。阿米娅立刻压低身形：「博士，交给我们！」银灰已经拔剑在手，霜星的指尖凝出寒气。", True),
    ("车队在山道遭遇伏击。雪坡上十几支弩箭同时射出，两名护卫当场倒下。灵知的数据终端闪烁着红光：「敌袭，疑似佩尔罗契家族的山雪鬼。」银灰沉声道：「保护博士，向会客厅撤退。」", True),
    ("竞技场通道里，三名无胄盟刺客从阴影中现身，匕首的寒光一闪而逝。砾早已挡在博士身前，反手抽出短刀：「三个，交给我。」", True),
    ("博士推开会议室的门，两名戴兜帽的整合运动感染者正站在档案柜前。他们看见博士，立刻掏出了武器。阿米娅从走廊另一头飞速赶来：「博士，快退后！」", True),
    ("雨夜，罗德岛车队在峡谷地段遭遇伏击，三名整合运动术师从两侧岩壁同时施法，火球照亮了整条山道。临光大喝一声举盾顶在前面：「法师交给我，博士往后撤！」", True),
    ("竞技场地牢的铁门被撞开，数十名被囚的感染者骑士冲了出来，领头的血骑士举起锈剑指向出口：「今天，要么走出去，要么躺着出去！」", True),
    ("喀兰贸易大楼的会客室突然传来爆炸声，浓烟从走廊尽头涌出。数名持刀的雇佣兵从烟中冲出，直奔银灰所在方向。锏已经拔刀挡在门前：「家主，交给我。」", True),
    ("训练场的模拟战进入第二场：血骑士单枪匹马站在场地中央，向博士挑战：「罗德岛的战术家，敢接这场比试吗？」他手中的长枪重重顿地。", True),
    ("码头集装箱区，一道寒光贴着阴影掠过——无胄盟的狙击手已经占好了位置。砾拉住博士闪进集装箱夹缝：「两个射手，一个观察位。别抬头。」", True),
    ("圣山山路的岔口，一队山雪鬼巡逻兵拦住了博士一行的去路，为首的队长按着刀柄：「大典期间，圣山禁地，谁都不许过。」身后十几把刀同时出鞘。", True),
    ("庆典广场的人群忽然骚动，一名感染者引爆了随身携带的源石炸弹，冲击波掀翻了两排摊位。守卫与暴徒在火光中扭打在一起，阿米娅的惊呼声被爆炸声淹没。", True),
    ("罗德岛走廊的通风口突然被顶开，两只猎犬型的源石生物扑出，獠牙上滴着涎液。走廊里灯光闪烁，陈警官拔出配枪挡在博士身前：「别慌，交给我。」", True),
]


def _readable_encounters() -> str:
    """读取遭遇 frontmatter name，构造「id（中文名）」列表。"""
    enc_dir = Path(__file__).resolve().parent.parent / "data" / "combat" / "encounters"
    parts = []
    for p in sorted(enc_dir.glob("*.md")):
        try:
            meta = frontmatter.load(p).metadata
            eid = meta.get("encounter_id") or p.stem
            name = meta.get("name") or ""
            parts.append(f"{eid}（{name}）" if name else eid)
        except Exception:
            parts.append(p.stem)
    return "、".join(parts)


def run_experiment(label: str, sm: SceneManager, readable: bool):
    if readable:
        sm._list_encounters = lambda: _readable_encounters()  # 实例属性遮蔽类方法
    out = []
    for text, expected in CASES:
        parsed = sm.extract_markers(text, choices_count=0, beat_state_active=True)
        combat = parsed.get("combat")
        triggered = combat is not None and isinstance(combat, dict)
        raw_empty = parsed.get("degraded") is True
        fr = parsed.get("finish_reason")
        if triggered:
            cls = "triggered"
        elif raw_empty:
            cls = "empty"
        elif fr == "length" and not parsed.get("error"):
            cls = "truncated"
        else:
            cls = "json-null-combat"
        out.append({
            "narrative": text[:26],
            "class": cls,
            "expected_combat": expected,
            "combat": combat,
            "degraded": parsed.get("degraded"),
            "finish_reason": fr,
            "error": parsed.get("error"),
        })
    return out


def summarize(label: str, cases: list[dict]):
    from collections import Counter
    cls_count = Counter(c["class"] for c in cases)
    triggered = sum(1 for c in cases if c["class"] == "triggered" and c["expected_combat"])
    empty = cls_count.get("empty", 0)
    return {
        "label": label,
        "total": len(cases),
        "expected_combat": sum(1 for c in cases if c["expected_combat"]),
        "triggered": triggered,
        "trigger_recall": round(triggered / sum(1 for c in cases if c["expected_combat"]), 3),
        "classification": dict(cls_count),
        "finish_reasons": dict(Counter(c["finish_reason"] for c in cases)),
        "cases": cases,
    }


def run():
    llm = build_llm()
    sm = SceneManager(llm, None, combat_mode="tactical")
    exp_a = run_experiment("A-原提示词（机器ID遭遇列表）", sm, readable=False)
    exp_b = run_experiment("B-可读遭遇名（id+中文名）", sm, readable=True)
    payload = {
        "experiments": [
            summarize("A-原提示词（机器ID遭遇列表）", exp_a),
            summarize("B-可读遭遇名（id+中文名）", exp_b),
        ]
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    save = Path(__file__).resolve().parent / "results_combat_experiments.json"
    save.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[已保存] {save}")


if __name__ == "__main__":
    run()