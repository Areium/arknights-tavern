"""T5：验证 httpx 伪流式假设 + thinking on/off 的 TTFT 对比。

1. client.post()（项目当前用法）→ iter_lines()：预期所有 chunk 一次性到达（伪流式）
2. client.stream()（正确用法）：预期首 chunk ~1-2s 到达（真流式）
3. enable_thinking=False 的叙述 TTFT：预期首 token 显著提前
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config  # noqa: E402

import httpx  # noqa: E402

cfg = load_config()
BASE_URL = cfg["base_url"]
HEADERS = {"Authorization": f"Bearer {cfg['api_key']}",
           "Content-Type": "application/json"}
MODEL = cfg["cloud_model"]

MESSAGES = [
    {"role": "system", "content": "你是明日方舟文字冒险游戏的场景叙述者，负责推进剧情。每次叙述约500字。"},
    {"role": "user", "content": (
        "<scene_state>位置：罗德岛本舰·训练室  天气：晴  时间：上午</scene_state>\n"
        "<characters>\n- 临光（近卫 干员） ← 对话中\n</characters>\n"
        "<player>\n身份：博士\n操作：博士走进训练室，与临光交谈，询问近期特锦赛的传闻。\n</player>\n"
        "请基于以上场景信息继续推进剧情。"
    )},
]


def payload(stream: bool, thinking: bool) -> dict:
    p = {
        "model": MODEL,
        "messages": MESSAGES,
        "stream": stream,
        "temperature": 0.5,
        "max_tokens": 4096,
    }
    if stream:
        p["stream_options"] = {"include_usage": True}
    if thinking:
        p["reasoning_effort"] = "medium"
    return p


def arrivals(client, use_stream_api: bool, thinking: bool, label: str):
    t0 = time.monotonic()
    first = None
    n_chunks = 0
    n_reasoning = 0
    n_content = 0
    content = ""
    if use_stream_api:
        with client.stream("POST", "/chat/completions", json=payload(True, thinking)) as resp:
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
                    n_reasoning += 1
                    if first is None:
                        first = (time.monotonic() - t0) * 1000
                if cc:
                    n_content += 1
                    content += cc
                    if first is None:
                        first = (time.monotonic() - t0) * 1000
                n_chunks += 1
    else:
        resp = client.post("/chat/completions", json=payload(True, thinking))
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
                n_reasoning += 1
                if first is None:
                    first = (time.monotonic() - t0) * 1000
            if cc:
                n_content += 1
                content += cc
                if first is None:
                    first = (time.monotonic() - t0) * 1000
            n_chunks += 1
    total = (time.monotonic() - t0) * 1000
    r = {"label": label, "first_chunk_ms": round(first) if first else None,
         "total_ms": round(total), "chunks": n_chunks,
         "reasoning_chunks": n_reasoning, "content_chunks": n_content,
         "content_chars": len(content),
         "content_stream_span_ms": round(total - (first or 0))}
    print(json.dumps(r, ensure_ascii=False), flush=True)
    return r


def main():
    client = httpx.Client(base_url=BASE_URL, timeout=120, headers=HEADERS)
    results = []

    # 1. 项目当前用法：client.post + iter_lines（thinking on）
    results.append(arrivals(client, use_stream_api=False, thinking=True,
                            label="当前用法 client.post()+iter_lines (thinking=on)"))
    # 2. 正确用法：client.stream()（thinking on）
    results.append(arrivals(client, use_stream_api=True, thinking=True,
                            label="正确用法 client.stream() (thinking=on)"))
    # 3. 正确用法 + thinking off
    results.append(arrivals(client, use_stream_api=True, thinking=False,
                            label="正确用法 client.stream() (thinking=off)"))

    Path("perf_tests/results_stream_verify.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
