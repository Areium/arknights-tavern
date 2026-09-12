"""T2b：JSON 结构化抽取成功率实测（52 次真实调用）——剧情模式 38 + 战术模式 14。

质量检查维度：解析成功率、字段类型、选项数量与长度、摘要长度、战斗触发召回/误报、遭遇 ID 合法性。
"""
import json
import statistics
import time

from common import build_llm, sanitize_usage

from SceneManager import SceneManager

STORY = [
    "阿米娅攥紧了拳头，低声说：「博士，源石的浓度在上升，这里不安全。」话音刚落，训练室另一侧传来金属碰撞的巨响，几具整合运动士兵的身影从烟雾中现身。临光踏前一步，将博士护在身后。",
    "银灰把茶杯轻轻放回桌面，起身走到落地窗前。窗外的大雪已经覆盖了整座山城。他转过身：「请转告罗德岛，喀兰贸易的大门始终敞开。」说完，他缓步离开了会客厅，走廊尽头传来关门声。",
    "灵知推了推眼镜，把数据终端转向博士：「增长停在了喀兰贸易的门槛上。」他调出一张图表，又补充道：「过去十年的对外贸易增长了，但圣山脚下的村镇收入没有变化。」窗外，夜色渐深，会客厅里只剩两个人。",
    "霜星捂住小臂上的源石结晶，眉头微蹙。她抬起头，望着远处的雪山：「我以前也以为，只要够强就不会有第二次离别。」风雪在她身后呼啸，她转身向着整合运动的营地方向走去。",
    "瑕光放下工具箱，兴奋地举起一件修复好的臂甲：「博士！这件的减震装置我改了三次，刚才测试完全没有卡顿！」她顿了顿，又小声说：「姐姐的旧铠甲我也顺便保养了一下。」",
    "陈警官敲了敲桌面，神色严肃：「龙门近卫局不会对感染者暴乱视而不见，但也不会让无辜者流血。」她合上案卷：「现在不是动手的时候。」墙上的时钟指向午夜，窗外细雨连绵。",
    "大长老缓缓睁开眼，枯瘦的手指摩挲着念珠：「耶拉冈德的山，不许修路。」他的声音平静却不容置疑：「这是祖制，也是雪山的意志。」堂内的烛火被穿堂风压得只剩下一点微光。",
    "闪灵为博士包扎好手臂的擦伤，轻轻吹了吹纱布边缘：「这里的草药充足，休息两日便无碍。」她收起医疗箱，沉吟片刻：「罗德岛的食堂晚上有热汤，如果您不嫌弃……我可以带路。」",
    "竞技场爆发出一阵惊呼。锈铜骑士的巨锤砸在护栏上，火星四溅。临光退后半步，护肩上的裂痕又深了一分，但她仍然稳稳地举着盾：「再来。」观众的呐喊声中，裁判的哨声久久没有响起。",
    "清晨的罗德岛走廊里，阿米娅抱着一叠文件快步走来：「博士，这是今天的日程安排——上午是训练场例行检查，下午会议室有一场关于龙门局势的简报会。」她想了想，补充道：「如果来得及，晚上食堂有火锅。」",
    "晚饭时间，阿米娅端着餐盘坐到博士对面，犹豫了一下才开口：「明天的作战会议，我想带崖心一起去。」她低头戳了戳碗里的菜：「她最近训练很努力，我想给她一个机会。」",
    "临近黄昏，罗德岛舰桥的窗外忽然乌云压城，豆大的雨点砸在舷窗上。广播响起：「全舰注意，强对流天气预计持续至明晨，露天训练场关闭。」走廊里，几个干员加快了脚步。",
    "博士在档案室的一角找到一份落满灰尘的任务记录，封面上印着罗德岛早期的徽记。翻开扉页，一行娟秀的字迹写着：愿每一位感染者，都能看见雪山的日出。",
    "训练结束，临光捂着右肩走进医疗舱，护甲上有明显的凹痕。闪灵检查后轻声道：「肌肉拉伤，三天内不要做重防御训练。」临光点了点头，难得地没有逞强。",
    "夜幕下的龙门夜市灯火通明，陈警官与博士并肩走在人流中。远处忽然传来警笛声，她下意识地摸了摸腰间的配枪，随后又松开：「不急，今晚先好好逛逛。」",
    "雪山大典的钟声响起，回荡在整座山城。祭坛前的广场上，人群安静下来，数千双眼睛望向圣山之巅。大长老登上祭坛，银灰站在观礼席的第一排，神情比任何一天都要专注。",
    "瑕光放下扳手，长长地舒了一口气：「修好了！这套动力甲可以重新上场了。」她擦了擦额头的汗，把工具一件件收回工具箱，脸上是藏不住的成就感。",
    "会客厅的门被轻轻敲响，一名侍从送来一封信。银灰拆开信纸，目光停留了很久，随后将信纸折好收进内袋：「今天的会议先到这里。博士，明天见。」",
    "崖心带着博士沿圣山山路上行，走到一半，前方传来沉闷的轰响——一小段山坡塌方了，碎石堵住了道路。崖心皱了皱眉：「绕道吧，多走半个时辰。」她抬头看了看天色，加快了脚步。",
    "雪原上的篝火噼啪作响，雪怪小队的成员围坐成一圈。霜星把烤好的干粮递给身边的队员，火光映在她脸上，难得地柔和下来：「轮流守夜，后半夜换岗。」",
    "医疗舱里灯光柔和，夜莺躺在床上安静地睡着。闪灵坐在床边，轻轻拉好被角，对博士做了个噤声的手势，用气声说：「她刚睡着。我们出去说。」",
    "祭坛上的香火缓缓升起，大长老闭目良久，终于开口：「雪山的山门，从今天起为喀兰铁路敞开。」堂内一片哗然，几位族老面面相觑，却无人敢出声反驳。",
    "灵知把方案书推到博士面前，语气少见地强硬起来：「铁路必须经过圣山脚下，这是最优解。你可以反对，但请先看完数据。」说完他抱起终端，快步离开了房间。",
    "回廊的阴影里，砾忽然停下脚步，耳朵微微一动。她按住博士的手臂，压低声音：「有人跟着我们，从刚才的转角起，已经跟了三条街。」",
    "阿米娅盯着桌上的检测报告，眉头慢慢拧紧：「源石结晶的活性比上周高了不少……这件事我要尽快上报凯尔希主任。」她把报告收进文件夹，脚步匆匆地离开。",
    "罗德岛的运输舰缓缓靠上龙门港口的泊位，舷外的城市灯光次第亮起。阿米娅站在甲板上深吸一口气：「龙门，我们又来了。」身后，罗德岛的旗帜在晚风中猎猎作响。",
    "初雪独自跪坐在圣山的雪地里，双手合十。风把她的祷词吹散在群山之间，她低声说：「姐姐，我守着的这座山，今年也要平安。」",
    "玛恩纳坐在竞技场最高的观众席上，一言不发地盯着场中央。周围的欢呼声震耳欲聋，他却像一座沉默的石像，只有攥紧扶手的手指露出青筋。",
    "布朗陶宅邸的议事厅里，菈塔托丝听完族老的禀报，指尖轻轻叩着桌面：「铁路修到哪里，我们的矿脉就封到哪里。这是布朗陶家的答复。」她起身，裙摆扫过门槛。",
    "靶场的枪声一声接一声，博士试射完最后一组子弹，摘下护目镜查看靶纸。成绩不错。瑕光从旁边探出头：「博士，这把试作枪的稳定器是我调的，手感如何？」",
    "阿米娅抱着一摞文件匆匆转过走廊拐角，迎面撞上博士，文件散了一地。她手忙脚乱地蹲下去捡：「啊，对不起！这是明天的预算表……」话音未落，一阵穿堂风吹过，纸页飞得更远了。",
    "深夜，罗德岛的走廊灯光忽明忽暗。博士值班巡逻时听见配电室传来轻微的敲击声，推开门却空无一人，只有指示灯在黑暗中一明一灭。",
    "工坊的灯还亮着，瑕光趴在桌上睡着了，手里还握着焊笔。临光轻手轻脚地走进来，把一件外套披在她肩上，又把凉掉的咖啡换成了热茶。",
    "车队在暮色中抵达雪山大典广场，人潮从四面八方涌向祭坛。博士下车时，银灰已经等在台阶前：「欢迎来到谢拉格最重要的夜晚。」他的声音被欢呼声淹没。",
    "书房里只点着一盏灯，银灰展开一叠泛黄的信纸，是父亲留下的旧信。窗外风雪呼啸，他看了很久，最后把信纸按原样折好，放回抽屉，锁上。",
    "清晨的训练场，博士带着新装备做例行巡检，护栏外的干员们三三两两地做着热身。扩音器里传来教官的声音：「今天上午是协同阵型演练，十点整开始。」",
    "港口仓库区，陈警官在货堆之间慢慢踱步，指尖抚过一只被撬开的木箱。箱底的痕迹让她眯起眼睛：「这手法……不是本地帮派。」她掏出通讯器，简短地说了三个字：「查码头。」",
    "罗德岛甲板上，晚霞烧红了大半片天空。阿米娅倚着栏杆，轻声对博士说：「明天就是特锦赛开幕日了。希望这趟旅程，能让更多人看见我们想守护的东西。」",
]

# (文本, 期望是否触发战斗)
TACTICAL = [
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
    ("雪山大典的观礼台上，银灰与阿克托斯迎面而立，气氛骤然凝固。阿克托斯冷笑一声：「希瓦艾什家的家主，在这座圣山面前，你还能那么笃定吗？」银灰没有回答，只是静静地看着他。", False),
    ("食堂里，两名干员因为训练场使用时间争执起来，声音越来越大，最后谁也不理谁。围观的人劝了几句，两人各自端着餐盘走开，留下一片尴尬的安静。", False),
]


def run():
    llm = build_llm()
    results = []

    def check_quality(sm, parsed, expected_combat):
        q = {}
        beat = parsed.get("beat_complete")
        choices = parsed.get("choices")
        summary = parsed.get("summary")
        combat = parsed.get("combat")
        env = parsed.get("environment")
        q["beat_is_bool"] = isinstance(beat, bool)
        q["choices_is_list"] = choices is None or isinstance(choices, list)
        q["choices_count_ok"] = (choices is None) or (len(choices) == 3)
        q["choices_len_ok"] = (choices is None) or all(isinstance(c, str) and len(c) <= 30 for c in choices)
        q["summary_ok"] = (summary is None) or (isinstance(summary, str) and len(summary) <= 60)
        q["env_ok"] = (env is None) or isinstance(env, dict)
        q["combat_ok"] = True
        if expected_combat is not None:
            triggered = combat is not None and isinstance(combat, dict)
            q["combat_ok"] = triggered == expected_combat
            if triggered:
                enc = combat.get("encounter_id", "")
                q["encounter_valid"] = enc in (sm._list_encounters() or "") and bool(enc)
            else:
                q["encounter_valid"] = True
        return all(q.values()), q

    def collect(label, sm, items, choices: int, expected_flag):
        stats = {
            "label": label, "total": 0, "parse_ok": 0, "field_ok": 0, "quality_ok": 0,
            "latency_ms": [], "usage": [], "errors": [], "quality_fail": [],
            "combat_expected": 0, "combat_triggered": 0, "fp_combat": 0,
        }
        for text, exp_combat in items:
            t0 = time.monotonic()
            expected = expected_flag if expected_flag is not None else exp_combat
            parsed = sm.extract_markers(text, choices_count=choices, beat_state_active=True)
            stats["total"] += 1
            stats["latency_ms"].append((time.monotonic() - t0) * 1000)
            if expected:
                stats["combat_expected"] += 1
            is_err = bool(parsed.get("error"))
            q_ok, detail = check_quality(sm, parsed, expected)
            fields_ok = (
                isinstance(parsed.get("beat_complete"), bool)
                and (parsed.get("combat") is None or isinstance(parsed.get("combat"), dict))
                and (parsed.get("choices") is None or isinstance(parsed.get("choices"), list))
                and (parsed.get("summary") is None or isinstance(parsed.get("summary"), str))
                and (parsed.get("environment") is None or isinstance(parsed.get("environment"), dict))
            )
            if not is_err and fields_ok:
                stats["parse_ok"] += 1
                stats["field_ok"] += 1
            else:
                stats["errors"].append({"text": text[:36], "detail": parsed.get("error") or "字段类型异常"})
            if q_ok:
                stats["quality_ok"] += 1
            else:
                stats["quality_fail"].append({"text": text[:36], "detail": detail})
            combat = parsed.get("combat")
            if combat is not None and isinstance(combat, dict):
                stats["combat_triggered"] += 1
                if expected is False:
                    stats["fp_combat"] += 1
            if parsed.get("usage"):
                stats["usage"].append(sanitize_usage(parsed["usage"]))
        return stats

    sm_story = SceneManager(llm, None)
    story_items = [(t, None) for t in STORY]
    results.append(collect("剧情模式（38 条，choices=3）", sm_story, story_items, 3, None))

    sm_tactical = SceneManager(llm, None, combat_mode="tactical")
    results.append(collect("战术模式（14 条，含战斗触发标注）", sm_tactical, TACTICAL, 0, None))

    out = []
    for r in results:
        latency = sorted(r["latency_ms"])
        n = len(latency)
        combat_recall = (
            round(r["combat_triggered"] / r["combat_expected"], 3)
            if r["combat_expected"] else None
        )
        out.append({
            "label": r["label"],
            "total": r["total"],
            "parse_ok": r["parse_ok"],
            "field_ok": r["field_ok"],
            "quality_ok": r["quality_ok"],
            "success_rate": round(r["parse_ok"] / r["total"], 3),
            "quality_rate": round(r["quality_ok"] / r["total"], 3),
            "latency_mean_ms": round(statistics.mean(r["latency_ms"]), 1),
            "latency_p90_ms": round(latency[int(n * 0.9) - 1], 1) if n >= 10 else None,
            "combat_expected": r["combat_expected"],
            "combat_triggered": r["combat_triggered"],
            "combat_recall": combat_recall,
            "combat_false_positive": r["fp_combat"],
            "usage_in_avg": round(statistics.mean(u["prompt_tokens"] for u in r["usage"]), 1) if r["usage"] else None,
            "usage_out_avg": round(statistics.mean(u["completion_tokens"] for u in r["usage"]), 1) if r["usage"] else None,
            "errors": r["errors"],
            "quality_fail": r["quality_fail"],
        })
    total_calls = sum(r["total"] for r in results)
    total_ok = sum(r["parse_ok"] for r in results)
    total_q = sum(r["quality_ok"] for r in results)
    summary = {
        "total_calls": total_calls,
        "overall_success_rate": round(total_ok / total_calls, 3),
        "overall_quality_rate": round(total_q / total_calls, 3),
    }
    payload = {"summary": summary, "results": out}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    out_path = __import__("pathlib").Path(__file__).resolve().parent / "results_extract_52.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[已保存] {out_path}")


if __name__ == "__main__":
    run()