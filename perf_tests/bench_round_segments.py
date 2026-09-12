"""T4：一轮对话分段耗时实测（复现线上配置：enable_thinking=true, reasoning_effort=medium）。

按剧情模式真实链路测量：
  A. 阶段0 消息构建（纯 Python，无 LLM）
  B. Call 1 流式叙述：首 reasoning token / 首 content token(TTFT) / 总时长
  C. Call 2 标记提取（choices=3, beat_state_active=True，剧情模式+自动选项的默认形态）
  D. 回忆生成（generate_memory 同构 prompt）
  E. embedding 调用（自由模式每轮 2 次：query + add）
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import build_llm, sanitize_usage  # noqa: E402

from SceneManager import SceneManager  # noqa: E402

# 复现线上配置（llm_backend_manager.get_llm_for_endpoint 传入的参数）
ENABLE_THINKING = True
REASONING_EFFORT = "medium"

NARR_CASES = [
    {
        "label": "首轮叙述（冷 prompt，无历史）",
        "player_info": {"identity": "博士"},
        "env_context": "位置：罗德岛本舰·训练室  天气：晴  时间：上午",
        "user_action": "博士走进训练室，与临光交谈，询问近期特锦赛的传闻。",
        "is_first_turn": True,
        "conversation_history": "",
    },
    {
        "label": "稳态轮（约2400字历史）",
        "player_info": {"identity": "博士"},
        "env_context": "位置：喀兰贸易会客厅  天气：暴雪  时间：傍晚\n【剧情回顾】\n- 第1-5轮：博士抵达谢拉格，与银灰会面，喀兰铁路议题浮出水面。",
        "user_action": "博士追问银灰关于铁路蓝图的事。",
        "is_first_turn": False,
        "conversation_history": (
            "【对话历史】\n第1轮 — 玩家: 博士抵达谢拉格，与银灰在会客厅会面。\n叙述: "
            "会客厅很高，整面墙的落地窗正对着圣山……\n"
            + "\n\n".join(
                f"第{i}轮 — 玩家: 博士与{['银灰', '灵知', '锏'][i % 3]}交谈。\n叙述: "
                f"{['银灰谈起喀兰铁路与守旧派的冲突，语气从容。', '灵知调出贸易数据，指出增长停在了门槛上。', '锏站在门口，像一尊没有温度的雕像。'][i % 3]}"
                for i in range(2, 24)
            )[:2400]
        ),
    },
]

EXTRACT_CASES = [
    "阿米娅攥紧了拳头，低声说：「博士，源石的浓度在上升，这里不安全。」话音刚落，训练室另一侧传来金属碰撞的巨响，几具整合运动士兵的身影从烟雾中现身。临光踏前一步，将博士护在身后。",
    "银灰把茶杯轻轻放回桌面，起身走到落地窗前。窗外的大雪已经覆盖了整座山城。他转过身：「请转告罗德岛，喀兰贸易的大门始终敞开。」说完，他缓步离开了会客厅，走廊尽头传来关门声。",
    "瑕光放下工具箱，兴奋地举起一件修复好的臂甲：「博士！这件的减震装置我改了三次，刚才测试完全没有卡顿！」她顿了顿，又小声说：「姐姐的旧铠甲我也顺便保养了一下。」",
    "夜幕下的龙门夜市灯火通明，陈警官与博士并肩走在人流中。远处忽然传来警笛声，她下意识地摸了摸腰间的配枪，随后又松开：「不急，今晚先好好逛逛。」",
]

MEMORY_INPUT = "\n".join(
    f"[第{i}轮] 基于以下剧情对话记录，总结这段情节的进展。" for i in range(1, 6)
)


def fmt_ms(ms):
    return round(ms, 0) if ms is not None else None


def main():
    llm = build_llm()
    # ── 复现线上参数 ──
    llm.enable_thinking = ENABLE_THINKING
    llm.reasoning_effort = REASONING_EFFORT
    sm = SceneManager(llm, None)
    out = {"config": {"enable_thinking": ENABLE_THINKING,
                      "reasoning_effort": REASONING_EFFORT,
                      "model": getattr(llm.config, "model", "?")}, "segments": {}}

    # ── A. 消息构建（纯 Python）──
    t0 = time.monotonic()
    for spec in NARR_CASES:
        sm._build_narration_messages(
            spec["player_info"], spec["env_context"],
            user_action=spec["user_action"], is_first_turn=spec["is_first_turn"],
            conversation_history=spec["conversation_history"],
            word_limit=500, structured=False,
        )
    out["segments"]["A_build_messages_ms"] = fmt_ms((time.monotonic() - t0) * 1000 / len(NARR_CASES))

    # ── B. Call 1 流式叙述 ──
    narr_results = []
    for spec in NARR_CASES:
        t0 = time.monotonic()
        ttft = first_reasoning = None
        acc = ""
        usage = None

        def on_token(tok):
            nonlocal ttft, acc
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            acc += tok

        def on_reasoning(tok):
            nonlocal first_reasoning
            if first_reasoning is None:
                first_reasoning = (time.monotonic() - t0) * 1000

        messages = sm._build_narration_messages(
            spec["player_info"], spec["env_context"],
            user_action=spec["user_action"], is_first_turn=spec["is_first_turn"],
            conversation_history=spec["conversation_history"],
            word_limit=500, structured=False,
        )
        result = llm.chat(messages, stream=True, on_token=on_token,
                          on_reasoning=on_reasoning, max_tokens=8192)
        total = (time.monotonic() - t0) * 1000
        usage = result.get("usage") if isinstance(result, dict) else None
        narr_results.append({
            "label": spec["label"],
            "first_reasoning_ms": fmt_ms(first_reasoning),
            "ttft_content_ms": fmt_ms(ttft),
            "total_ms": fmt_ms(total),
            "reasoning_chars": len(result.get("reasoning") or "") if isinstance(result, dict) else 0,
            "content_chars": len(acc),
            "chars_per_sec": round(len(acc) / (total / 1000), 1) if total > 0 else 0,
            "usage": sanitize_usage(usage),
        })
        print(json.dumps(narr_results[-1], ensure_ascii=False), flush=True)
    out["segments"]["B_narrate"] = narr_results

    # ── C. Call 2 标记提取 ──
    ext_results = []
    for i, text in enumerate(EXTRACT_CASES):
        t0 = time.monotonic()
        parsed = sm.extract_markers(text, choices_count=3, beat_state_active=True)
        ms = (time.monotonic() - t0) * 1000
        ext_results.append({
            "case": i,
            "latency_ms": fmt_ms(ms),
            "retried": bool(parsed.get("retried")),
            "degraded": bool(parsed.get("degraded")),
            "finish_reason": parsed.get("finish_reason"),
            "usage": sanitize_usage(parsed.get("usage")),
        })
        print(json.dumps(ext_results[-1], ensure_ascii=False), flush=True)
    out["segments"]["C_extract_markers"] = ext_results

    # ── D. 回忆生成（同构 prompt）──
    history_text = "\n".join(
        f"[第{i}轮] 阿米娅带来训练日程；临光谈及特锦赛传闻；瑕光修复了臂甲；"
        f"博士与银灰讨论铁路蓝图；会客厅窗外大雪封城。 玩家选择: 追问细节"
        for i in range(1, 6)
    )
    prompt = (
        "基于以下剧情对话记录，总结这段情节的进展。"
        "输出 JSON 格式（不要输出其他内容）：\n"
        '{"title": "简短的章节标题（不超过15字）", "summary": "情节摘要（不超过300字，包含关键对话和事件细节）"}\n\n'
        f"剧情记录：\n---\n{history_text}\n---"
    )
    t0 = time.monotonic()
    resp = llm.chat([
        {"role": "system", "content": (
            "<role>你是专业TRPG剧情编辑，负责记录详尽的剧情摘要。</role>\n"
            "<output_format>\n"
            '强制 JSON：{"title": "标题≤15字", "summary": "摘要≤300字，含关键情节转折、角色互动和重要事件"}\n'
            "只输出 JSON，不要其他内容。\n"
            "</output_format>"
        )},
        {"role": "user", "content": prompt},
    ], stream=False)
    out["segments"]["D_generate_memory_ms"] = fmt_ms((time.monotonic() - t0) * 1000)
    out["segments"]["D_generate_memory_usage"] = sanitize_usage(resp.get("usage") if isinstance(resp, dict) else None)
    print(json.dumps({"D_generate_memory_ms": out["segments"]["D_generate_memory_ms"]}, ensure_ascii=False), flush=True)

    # ── E. embedding ──
    t0 = time.monotonic()
    emb = llm.embed(["用户: 博士走进训练室，与临光交谈，询问近期特锦赛的传闻。\n临光: 传闻属实，特锦赛的规则今年有变。"])
    out["segments"]["E_embed_ms"] = fmt_ms((time.monotonic() - t0) * 1000)
    out["segments"]["E_embed_ok"] = emb is not None
    print(json.dumps({"E_embed_ms": out["segments"]["E_embed_ms"], "ok": emb is not None}, ensure_ascii=False), flush=True)

    print("=== FINAL ===")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
