import hashlib
import os
import re


class VectorMemory:
    """向量记忆：近期滑动窗口 + 远期语义检索。

    特征：
    - 近期对话全量保留（保证流畅性）
    - 远期对话存入 ChromaDB，按语义检索 Top-K 条
    - 数据持久化到磁盘，重启不丢失
    - embedding 不可用时自动降级为纯滑动窗口
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

        # 存入向量库
        if self.embed_fn is not None:
            embedding = self.embed_fn([doc])
            if embedding is not None:
                self.collection.add(
                    documents=[doc],
                    embeddings=embedding,
                    ids=[str(self._turn_counter)],
                )
                self._turn_counter += 1

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

        query_embedding = self.embed_fn([query])
        if query_embedding is None:
            return []

        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, self.collection.count()),
        )
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
