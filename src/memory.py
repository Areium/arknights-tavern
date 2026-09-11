import hashlib
import logging
import os
import re

logger = logging.getLogger(__name__)

# 本地 ONNX 嵌入单例（chromadb DefaultEmbeddingFunction）：
# 模型冷启动 ~1s，进程内共享；探测失败（如 onnxruntime 缺失）后不再重试。
_LOCAL_EMBED_FN = None
_LOCAL_EMBED_RESOLVED = False


def get_local_embed_fn():
    """返回本地 ONNX 嵌入函数（chromadb DefaultEmbeddingFunction），不可用时返回 None。

    单例缓存：首次调用触发模型加载并探测可用性；失败后进程内不再重试。
    """
    global _LOCAL_EMBED_FN, _LOCAL_EMBED_RESOLVED
    if not _LOCAL_EMBED_RESOLVED:
        _LOCAL_EMBED_RESOLVED = True
        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            fn = DefaultEmbeddingFunction()
            fn(["探测"])  # 触发 ONNX 模型加载，验证可用性
            _LOCAL_EMBED_FN = fn
            logger.info("本地 ONNX 嵌入可用，语义记忆可离线运行")
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "本地 ONNX 嵌入不可用（%s: %s），语义记忆依赖远端嵌入或降级为滑动窗口",
                type(e).__name__, e,
            )
    return _LOCAL_EMBED_FN


def resolve_embed_fn(llm=None):
    """解析语义记忆使用的嵌入函数。

    优先使用 LLM 后端提供的远端 embedding（构造时探测一次；DeepSeek 等
    无 /embeddings 端点的服务会在首次失败后短路返回 None）；远端不可用
    时回退本地 ONNX 嵌入；两者都不可用返回 None（纯滑动窗口）。

    同一 collection 的向量必须来自同一嵌入源（维度一致），因此在构造
    VectorMemory 前一次性定源，避免运行中混用不同维度的向量。
    """
    if llm is not None and hasattr(llm, "embed"):
        probe_ok = False
        try:
            probe_ok = llm.embed(["探测"]) is not None
        except Exception as e:  # noqa: BLE001
            logger.warning("远端 embedding 探测异常（%s: %s）", type(e).__name__, e)
        if probe_ok:
            logger.debug("语义记忆使用远端 embedding")
            return llm.embed
        logger.info("远端 embedding 不可用，语义记忆回退本地 ONNX 嵌入")
    return get_local_embed_fn()


class VectorMemory:
    """向量记忆：近期滑动窗口 + 远期语义检索。

    特征：
    - 近期对话全量保留（保证流畅性）
    - 远期对话存入 ChromaDB，按语义检索 Top-K 条
    - 数据持久化到磁盘，重启不丢失
    - embedding 不可用时自动降级为纯滑动窗口
    - 嵌入源在构造时经 resolve_embed_fn 一次性确定：
      远端可用用远端，否则本地 ONNX，均不可用则纯滑窗
    """

    def __init__(
        self,
        character_name: str,
        embed_fn=None,
        persist_dir: str = "data/memory",
        recent_turns: int = 10,
    ):
        """
        Args:
            character_name: 角色名称（用作 collection 标识）。
            embed_fn: 嵌入函数，签名 (list[str]) -> list[list[float]] | None。
                      为 None 时仅使用滑动窗口。
            persist_dir: ChromaDB 持久化目录。
            recent_turns: 保留的近期对话轮数。
        """
        self.character_name = character_name
        self.embed_fn = embed_fn

        # 相对路径锚定到仓库根目录：进程 cwd 不同（src/ 或根目录）时
        # 会产生两份分裂的记忆库，统一落盘到 <repo>/data/memory
        if not os.path.isabs(persist_dir):
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            persist_dir = os.path.join(repo_root, persist_dir)

        import chromadb
        from chromadb.config import Settings
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", character_name).strip("._-")
        if len(safe_name) < 3:
            safe_name = f"char_{hashlib.md5(character_name.encode('utf-8')).hexdigest()[:8]}"
        elif len(safe_name) > 512:
            safe_name = safe_name[:512]
        self.collection = self.client.get_or_create_collection(name=safe_name)

        # 滑动窗口：保留最近 N 轮完整消息
        self.recent_buffer: list[dict] = []
        self.recent_turns = recent_turns

        self._turn_counter = self.collection.count()

    def add(self, user_input: str, character_response: str):
        """存储一轮对话。"""
        doc = f"用户: {user_input}\n{self.character_name}: {character_response}"

        # 存入向量库（失败时降级：本轮仅进入滑动窗口，不阻断对话）
        if self.embed_fn is not None:
            embedding = None
            try:
                embedding = self.embed_fn([doc])
            except Exception as e:  # noqa: BLE001
                logger.warning("嵌入计算失败，本轮对话仅保留在滑动窗口: %s", e)
            if embedding is not None:
                try:
                    self.collection.add(
                        documents=[doc],
                        embeddings=embedding,
                        ids=[str(self._turn_counter)],
                    )
                    self._turn_counter += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("向量写入失败，本轮对话仅保留在滑动窗口: %s", e)

        # 更新滑动窗口
        self.recent_buffer.append({"role": "user", "content": user_input})
        self.recent_buffer.append({"role": "assistant", "content": character_response})

        max_msgs = self.recent_turns * 2
        if len(self.recent_buffer) > max_msgs:
            self.recent_buffer = self.recent_buffer[-max_msgs:]

    def retrieve(self, query: str, top_k: int = 3) -> list[str]:
        """按语义检索与 query 相关的远期记忆。"""
        if self.embed_fn is None or self.collection.count() == 0:
            return []

        try:
            query_embedding = self.embed_fn([query])
            if query_embedding is None:
                return []
            results = self.collection.query(
                query_embeddings=query_embedding,
                n_results=min(top_k, self.collection.count()),
            )
        except Exception as e:  # noqa: BLE001
            # 嵌入源切换导致维度不匹配、存储异常等：降级为滑窗而不是让对话链路崩溃
            logger.warning("语义检索失败，本轮降级为滑动窗口: %s", e)
            return []

        docs = results.get("documents", [[]])[0]

        recent_set = self._recent_as_docs()
        return [d for d in docs if d not in recent_set]

    def build_context(self, query: str) -> str:
        """构建注入 prompt 的记忆上下文。

        格式：
            【远期相关记忆】
            1. ...

            【近期对话记录】
            user: ...
            character: ...
        """
        relevant = self.retrieve(query)

        parts = []
        if relevant:
            parts.append("【远期相关记忆】")
            for i, doc in enumerate(relevant, 1):
                parts.append(f"{i}. {doc}")

        if self.recent_buffer:
            lines = []
            for msg in self.recent_buffer:
                speaker = "用户" if msg["role"] == "user" else self.character_name
                lines.append(f"{speaker}: {msg['content']}")
            parts.append("\n【近期对话记录】")
            parts.append("\n".join(lines))

        return "\n".join(parts)

    def reset(self):
        """清空当前角色的所有记忆。"""
        safe_name = self.collection.name
        self.client.delete_collection(safe_name)
        self.collection = self.client.create_collection(name=safe_name)
        self.recent_buffer.clear()
        self._turn_counter = 0

    def _recent_as_docs(self) -> set[str]:
        """将近期窗口转为文档集合，用于去重。"""
        docs = set()
        for i in range(0, len(self.recent_buffer), 2):
            pair = self.recent_buffer[i : i + 2]
            if len(pair) == 2:
                docs.add(
                    f"用户: {pair[0]['content']}\n{self.character_name}: {pair[1]['content']}"
                )
        return docs
