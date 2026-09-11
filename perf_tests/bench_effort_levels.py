"""T6：DeepSeek 混合思考模型的 reasoning_effort 档位行为（none / low / 缺省）。

叙述型 prompt，max_tokens=2048，对比 reasoning chunks 数量、正文到达时间、总时长。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config  # noqa: E402

import httpx  # noqa: E402

cfg = load_config()
HEADERS = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}

MESSAGES = [
    {"role": "system", "content": "你是明日方舟文字冒险游戏的场景叙述者，负责推进剧情。每次叙述约300字。"},
    {"role": "user", "content": (
        "<scene_state>位置：罗德岛本舰·训练室  天气：晴  时间：上午</scene_state>\n"
        "<player>\n身份：博士\n操作：博士走进训练室，与临光交谈，询问近期特锦赛的传闻。\n</player>\n"
        "请基于以上场景信息继续推进剧情。"
    )},
]


def run(client, label, extra):
    p = {"model": cfg["cloud_model"], "messages": MESSAGES,
         "stream": True, "temperature": 0.5, "max_tokens": 2048,
         "stream_options": {"include_usage": True}}
    p.update(extra or {})
    t0 = time.monotonic()
    first_reasoning = first_content = None
    reasoning_chars = content_chars = 0
    finish = None
    usage = {}
    with client.stream("POST", "/chat/completions", json=p) as resp:
        if resp.status_code != 200:
            body = resp.read().decode("utf-8", "replace")[:200]
            print(json.dumps({"label": label, "http_status": resp.status_code, "body": body}), flush=True)
            return
        for line in resp.iter_lines():
            if not line:
                continue
            if line.startswith("data: "):
                line = line[6:]
            if line.strip() == "[DONE]":
                break
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            delta = j.get("choices", [{}])[0].get("delta", {}) or {}
            rc = delta.get("reasoning_content", "")
            cc = delta.get("content", "")
            if rc:
                reasoning_chars += len(rc)
                if first_reasoning is None:
                    first_reasoning = (time.monotonic() - t0) * 1000
            if cc:
                content_chars += len(cc)
                if first_content is None:
                    first_content = (time.monotonic() - t0) * 1000
            f = j.get("choices", [{}])[0].get("finish_reason")
            if f:
                finish = f
            if j.get("usage"):
                usage = j["usage"]
    total = (time.monotonic() - t0) * 1000
    r = {"label": label,
         "first_reasoning_ms": round(first_reasoning) if first_reasoning else None,
         "first_content_ms": round(first_content) if first_content else None,
         "total_ms": round(total),
         "reasoning_chars": reasoning_chars,
         "content_chars": content_chars,
         "finish_reason": finish,
         "completion_tokens": usage.get("completion_tokens"),
         "reasoning_tokens_field": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")}
    print(json.dumps(r, ensure_ascii=False), flush=True)
    return r


def main():
    client = httpx.Client(base_url=cfg["base_url"], timeout=120, headers=HEADERS)
    out = []
    out.append(run(client, "reasoning_effort=none", {"reasoning_effort": "none"}) or {})
    out.append(run(client, "reasoning_effort=low", {"reasoning_effort": "low"}) or {})
    out.append(run(client, "无参数(缺省)", {}))
    Path("perf_tests/results_effort_levels.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
