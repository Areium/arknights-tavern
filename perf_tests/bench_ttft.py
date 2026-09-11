"""T1：首Token延迟（TTFT）与叙述总耗时实测——复用项目自身 SceneManager 消息构建 + ApiLLM 流式通道。"""
import json
import statistics
import time

from common import build_llm, sanitize_usage

from SceneManager import SceneManager

PROMPTS = [
    {
        "label": "首轮叙述（无历史，冷 prompt）",
        "player_info": {"identity": "博士"},
        "env_context": "位置：罗德岛本舰·训练室  天气：晴  时间：上午",
        "user_action": "博士走进训练室，与临光交谈，询问近期特锦赛的传闻。",
        "is_first_turn": True,
        "conversation_history": "",
    },
    {
        "label": "同 prompt 复述（warm，模拟前缀缓存命中）",
        "player_info": {"identity": "博士"},
        "env_context": "位置：罗德岛本舰·训练室  天气：晴  时间：上午",
        "user_action": "博士走进训练室，与临光交谈，询问近期特锦赛的传闻。",
        "is_first_turn": True,
        "conversation_history": "",
    },
    {
        "label": "带对话历史的稳态轮（约2500字历史）",
        "player_info": {"identity": "博士"},
        "env_context": "位置：喀兰贸易会客厅  天气：暴雪  时间：傍晚",
        "user_action": "博士追问银灰关于铁路蓝图的事。",
        "is_first_turn": False,
        "conversation_history": (
            "【对话历史】\n第1轮 — 玩家: 博士抵达谢拉格，与银灰在会客厅会面。\n叙述: "
            "会客厅很高，整面墙的落地窗正对着圣山……\n"
            + "\n\n".join(
                f"第{i}轮 — 玩家: 博士与{ ['银灰','灵知','锏'][i % 3] }交谈。\n叙述: "
                f"{ ['银灰谈起喀兰铁路与守旧派的冲突，语气从容。','灵知调出贸易数据，'
                   '指出增长停在了门槛上。','锏站在门口，像一尊没有温度的雕像。'][i % 3] }"
                for i in range(2, 30)
            )[:2400]
        ),
    },
]


def run():
    llm = build_llm()
    sm = SceneManager(llm, None)
    results = []
    for spec in PROMPTS:
        messages = sm._build_narration_messages(
            spec["player_info"],
            spec["env_context"],
            user_action=spec["user_action"],
            is_first_turn=spec["is_first_turn"],
            conversation_history=spec["conversation_history"],
            word_limit=500,
            structured=False,
        )
        t0 = time.monotonic()
        ttft = None
        t_first_reasoning = None
        accumulated = ""
        usage = None

        def on_token(tok):
            nonlocal ttft
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            nonlocal accumulated
            accumulated += tok

        def on_reasoning(tok):
            nonlocal t_first_reasoning
            if t_first_reasoning is None:
                t_first_reasoning = (time.monotonic() - t0) * 1000

        result = llm.chat(messages, stream=True, on_token=on_token,
                          on_reasoning=on_reasoning, max_tokens=900)
        total_ms = (time.monotonic() - t0) * 1000
        usage = result.get("usage") if isinstance(result, dict) else None
        results.append({
            "label": spec["label"],
            "ttft_ms": round(ttft, 1) if ttft is not None else None,
            "first_reasoning_ms": round(t_first_reasoning, 1) if t_first_reasoning is not None else None,
            "total_ms": round(total_ms, 1),
            "out_chars": len(accumulated),
            "chars_per_sec": round(len(accumulated) / (total_ms / 1000), 1) if total_ms > 0 else 0,
            "usage": sanitize_usage(usage),
            "prompt_tokens_est": sum(
                _est(m["content"]) + _est(m.get("content", "") or "")
                for m in messages if m["role"] == "user"
            ) + _est(messages[0]["content"]) if messages else 0,
        })
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))


def _est(text: str) -> int:
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + (len(text) - cjk) // 4


if __name__ == "__main__":
    run()