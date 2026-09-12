"""失败案例原始输出诊断：地牢暴动（截断）/ 血骑士挑战（null）/ 码头狙击（null），附控制组正常触发案例。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from common import build_llm, sanitize_usage

from SceneManager import SceneManager

CASES = [
    ("地牢暴动（截断）", "竞技场地牢的铁门被撞开，数十名被囚的感染者骑士冲了出来，领头的血骑士举起锈剑指向出口：「今天，要么走出去，要么躺着出去！」"),
    ("血骑士比武挑战（null）", "训练场的模拟战进入第二场：血骑士单枪匹马站在场地中央，向博士挑战：「罗德岛的战术家，敢接这场比试吗？」他手中的长枪重重顿地。"),
    ("码头狙击手（null，A组）", "码头集装箱区，一道寒光贴着阴影掠过——无胄盟的狙击手已经占好了位置。砾拉住博士闪进集装箱夹缝：「两个射手，一个观察位。别抬头。」"),
    ("车队伏击（控制组-正常触发）", "车队在山道遭遇伏击。雪坡上十几支弩箭同时射出，两名护卫当场倒下。灵知的数据终端闪烁着红光：「敌袭，疑似佩尔罗契家族的山雪鬼。」银灰沉声道：「保护博士，向会客厅撤退。」"),
]


def run():
    llm = build_llm()
    sm = SceneManager(llm, None, combat_mode="tactical")
    out = []
    for label, text in CASES:
        msgs = sm._build_extraction_messages(text, choices_count=0, beat_state_active=True)
        r = llm.chat(msgs, stream=False, max_tokens=2048)
        raw = (r.get("content") or "").strip()
        out.append({
            "label": label,
            "raw": raw,
            "raw_len": len(raw),
            "finish_reason": r.get("finish_reason"),
            "usage": sanitize_usage(r.get("usage")),
            "reasoning_tail": (r.get("reasoning") or "")[-200:],
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()