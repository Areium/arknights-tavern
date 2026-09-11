"""T3：记忆召回率实测——10 个跨轮事实，检索命中率 + 近期窗口去重 + 降级路径。

Embedding 说明：当前环境无在线 embedding 服务（DeepSeek 无 embedding 端点），
优先使用 ChromaDB 内置 ONNX 语义嵌入；不可用时退回字符 bigram 代理嵌入，
此时测的是检索机制正确性（召回管道），语义上限取决于嵌入质量。
"""
import json
import sys
import tempfile
from pathlib import Path

from common import ROOT  # 副作用：注入 src/ 到 sys.path

FACTS = [
    ("阿米娅脖子上的共鸣石坠是博士送的，它能感知源石浓度变化，夜里会微微发光。", "博士送给阿米娅的共鸣石坠会发光"),
    ("临光的旧铠甲在卡西米尔工坊修复过三次，肩甲处有一道试剑留下的划痕。", "临光的旧铠甲肩上有划痕"),
    ("银灰把喀兰铁路的设计图锁在会客厅书房的暗格里，只有灵知知道密码。", "铁路设计图藏在会客厅的书房暗格"),
    ("霜星小臂的源石结晶每月都会刺痛一次，她习惯在雪地里走一晚上来缓解。", "霜星的源石结晶每月刺痛一次"),
    ("瑕光设计的臂甲减震装置用了三块缓冲簧片，是临光帮她调到最顺手的。", "瑕光的臂甲用了三块缓冲簧片"),
    ("陈警官的桌上放着一枚旧怀表，是她在龙门退役的教官留下的遗物。", "陈警官的旧怀表是教官的遗物"),
    ("灵知的眼镜是他母亲留下的，镜腿内侧刻着一串看不懂的数字。", "灵知的眼镜镜腿内侧刻着数字"),
    ("大长老的念珠一共一百零八颗，其中三颗是耶拉冈德雪山的矿石磨的。", "大长老的念珠有三颗矿石磨的"),
    ("闪灵随身带着一支白色的草药香囊，里面的草药只有罗德岛药剂房有存货。", "闪灵的草药香囊里的药只有药剂房有"),
    ("崖心在雪山大典上戴的护腕是初雪亲手织的，边缘绣了两个人名字的首字母。", "崖心的护腕是初雪织的"),
]

# 每条查询隐式指向对应事实，跨轮提问口径
QUERIES = [
    "阿米娅脖子上挂着的那块会发光的石头是哪来的？",
    "临光那件修过好几次的铠甲上是不是有什么旧伤？",
    "喀兰铁路的图纸被银灰放在哪里了？",
    "霜星胳膊上的结晶是不是隔一阵就会疼？",
    "瑕光那个臂甲里的缓冲件是怎么设计的？",
    "陈警官桌上那个旧怀表是谁留给她的？",
    "灵知那副旧眼镜有什么特别的来历吗？",
    "大长老手里那串念珠是不是有什么讲究？",
    "闪灵随身带的那个白色香囊里装的是什么？",
    "崖心在大典上戴的护腕是谁做的？",
]


def _hash_embed(texts: list[str]) -> list[list[float]]:
    """字符 bigram 哈希代理嵌入（余弦可比的 128 维向量）。"""
    import hashlib
    import math

    dim = 128
    vecs = []
    for t in texts:
        v = [0.0] * dim
        tokens = set(t)
        tokens.update(t[i:i + 2] for i in range(len(t) - 1))
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            v[h % dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        vecs.append([x / norm for x in v])
    return vecs


_EMBED_MODE = {"name": "unknown"}


def _make_embed_fn():
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        fn = DefaultEmbeddingFunction()
        fn(["测试"])  # 探测 onnxruntime 是否可用
        _EMBED_MODE["name"] = "chromadb-onnx"
        return fn
    except Exception as e:  # noqa: BLE001
        print(f"embedding fallback: {type(e).__name__}: {e}")
        _EMBED_MODE["name"] = "hash-fallback"
        return _hash_embed


def run():
    from memory import VectorMemory

    tmp = Path(tempfile.mkdtemp(prefix="bench_memory_"))
    embed_fn = _make_embed_fn()

    # recent_turns=2 → 滑动窗口覆盖最后 2 条事实（4 条消息）
    vms = VectorMemory("__bench_recall_char__", embed_fn=embed_fn,
                       persist_dir=str(tmp), recent_turns=2)
    for user, resp in FACTS:
        vms.add(user, resp)

    # 1) 远期召回率：只统计窗口外事实（前 8 条）；窗口内 2 条由滑窗提供，不参与检索召回
    external = FACTS[:-2]
    window = FACTS[-2:]
    hits = 0
    misses = []
    for q, (user, resp) in zip(QUERIES, external):
        target = f"用户: {user}\n__bench_recall_char__: {resp}"
        got = vms.retrieve(q, top_k=3)
        if target in got:
            hits += 1
        else:
            misses.append({"query": q[:24], "got": [g[:30] for g in got]})

    # 2) 窗口内事实不应出现在检索结果（去重；其内容由滑窗单独注入）
    dedup_ok = True
    for user, resp in window:
        got = vms.retrieve(user, top_k=3)
        recent_docs = {f"用户: {u}\n__bench_recall_char__: {r}" for u, r in window}
        if recent_docs & set(got):
            dedup_ok = False

    # 3) 滑窗覆盖：窗口内事实必须出现在 build_context 的近期对话记录中
    ctx = vms.build_context(window[0][0])
    window_ok = all(
        f"用户: {u}" in ctx and f"__bench_recall_char__: {r[:20]}" in ctx
        for u, r in window
    )

    # 4) 降级路径：embed_fn 返回 None 时纯滑窗不抛异常
    vms2 = VectorMemory("__bench_recall_char2__", embed_fn=None,
                        persist_dir=str(tmp), recent_turns=1)
    vms2.add("你好", "你好，博士。")
    ctx2 = vms2.build_context("你好")
    degrade_ok = "近期对话记录" in ctx2

    print(json.dumps({
        "embedding_mode": _EMBED_MODE["name"],
        "window_external_facts": len(external),
        "retrieval_recall": f"{hits}/{len(external)}",
        "retrieval_recall_rate": round(hits / len(external), 3),
        "misses": misses,
        "window_covered_facts": len(window),
        "window_injection_ok": window_ok,
        "window_excluded_from_retrieval_ok": dedup_ok,
        "degrade_path_ok": degrade_ok,
        "methodology": "窗口外事实才计入检索召回；窗口内事实由滑动窗口注入作为对照项（去重是设计行为而非召回失败）",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()