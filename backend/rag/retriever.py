"""
法律知识检索器

负责：
1. 将用户查询转换为向量
2. 在 ChromaDB 中进行相似度检索
3. 返回最相关的法律条文和司法解释
"""

from typing import List, Dict, Any, Optional
import threading
import chromadb

from .config import RAG_CONFIG
from .embeddings import get_embeddings, EmbeddingError


class LegalKnowledgeRetriever:
    """法律知识检索器"""

    def __init__(self):
        """初始化检索器"""
        # 初始化 ChromaDB 客户端
        self.chroma_client = chromadb.PersistentClient(
            path=RAG_CONFIG["persist_directory"]
        )

        # 获取集合
        try:
            self.collection = self.chroma_client.get_collection(
                name=RAG_CONFIG["collection_name"]
            )
        except Exception:
            print("警告: ChromaDB 集合不存在，请先运行索引")
            self.collection = None

        # 初始化 Embedding 服务
        self.embeddings = get_embeddings()

        # 配置参数
        self.top_k = RAG_CONFIG["top_k"]
        self.similarity_threshold = RAG_CONFIG["similarity_threshold"]

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        domain: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        检索相关法律知识

        Args:
            query: 用户查询文本
            top_k: 返回的文档数量（默认使用配置值）
            domain: 限定法律领域（如 "civil"）
            doc_type: 限定文档类型（如 "law" 或 "judicial_interpretation"）

        Returns:
            相关文档列表，每个文档包含：
            - text: 文档内容
            - metadata: 元数据（法律名称、条款号等）
            - distance: 相似度距离（越小越相关）
        """
        if not self.collection:
            print("警告: ChromaDB 集合不存在")
            return []

        if not query or not query.strip():
            return []

        top_k = top_k or self.top_k

        # 向量化查询
        # H4：embed_text 失败时抛 EmbeddingError，此处捕获并返回空检索，
        # 避免零向量查询返回错误法律条文（法条幻觉），也不让 RAG 故障拖垮整个庭审。
        try:
            query_embedding = self.embeddings.embed_text(query)
        except EmbeddingError as e:
            print(f"RAG 查询向量化失败，跳过检索: {e}")
            return []

        # 构建过滤条件
        where_filter = {}
        if domain:
            where_filter["domain"] = domain
        if doc_type:
            where_filter["doc_type"] = doc_type

        # 执行查询
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_filter if where_filter else None,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            print(f"ChromaDB 查询失败: {e}")
            return []

        # 处理结果
        retrieved_docs = []
        if results and results["documents"] and results["documents"][0]:
            documents = results["documents"][0]
            metadatas = results["metadatas"][0]
            distances = results["distances"][0]

            for doc, metadata, distance in zip(documents, metadatas, distances):
                # 过滤低相似度结果
                # ChromaDB 使用 L2 距离，越小越相关
                # 转换为相似度分数（0-1）
                similarity = 1.0 / (1.0 + distance)

                if similarity >= self.similarity_threshold:
                    retrieved_docs.append({
                        "text": doc,
                        "metadata": metadata,
                        "distance": distance,
                        "similarity": similarity,
                    })

        return retrieved_docs

    def retrieve_for_phase(
        self,
        query: str,
        phase: int,
        domain: str = "civil",
    ) -> List[Dict[str, Any]]:
        """
        根据庭审阶段检索相关法律知识

        不同阶段需要不同类型的法律依据：
        - Phase 1 (请求权分析): 法律条文 + 司法解释
        - Phase 3 (答辩策略): 法律条文 + 司法解释
        - Phase 5 (争议焦点): 法律条文 + 司法解释
        - Phase 8 (判决): 法律条文 + 司法解释 + 类案

        Args:
            query: 查询文本（案件事实摘要）
            phase: 庭审阶段（1-8）
            domain: 法律领域

        Returns:
            相关文档列表
        """
        # 根据阶段调整检索策略
        if phase in [1, 3, 5, 8]:
            # 这些阶段需要法律依据
            return self.retrieve(query, domain=domain)
        else:
            # 其他阶段不需要检索
            return []

    def format_retrieved_docs(
        self,
        docs: List[Dict[str, Any]],
        max_docs: int = 5,
    ) -> str:
        """
        将检索结果格式化为文本（用于注入到 prompt）

        Args:
            docs: 检索到的文档列表
            max_docs: 最多包含的文档数量

        Returns:
            格式化后的文本
        """
        if not docs:
            return ""

        formatted_parts = []
        for i, doc in enumerate(docs[:max_docs], 1):
            metadata = doc["metadata"]
            doc_name = metadata.get("doc_name", "未知法律")
            doc_number = metadata.get("doc_number", "")

            # 构建标题
            if doc_number:
                title = f"{doc_name}（{doc_number}）"
            else:
                title = doc_name

            # 构建内容
            content = doc["text"].strip()

            # 添加到格式化部分
            formatted_parts.append(
                f"【{i}】{title}\n{content}"
            )

        return "\n\n".join(formatted_parts)


# 全局实例（延迟初始化，P3 修复：双重检查锁防并发重复初始化 ChromaDB 连接）
_retriever_instance = None
_retriever_lock = threading.Lock()


def get_retriever() -> LegalKnowledgeRetriever:
    """获取全局 Retriever 实例（线程安全）"""
    global _retriever_instance
    if _retriever_instance is None:
        with _retriever_lock:
            if _retriever_instance is None:
                _retriever_instance = LegalKnowledgeRetriever()
    return _retriever_instance


def retrieve_legal_knowledge(
    query: str,
    phase: Optional[int] = None,
    domain: str = "civil",
) -> str:
    """
    检索法律知识并格式化（便捷函数）

    Args:
        query: 查询文本
        phase: 庭审阶段（可选）
        domain: 法律领域

    Returns:
        格式化后的法律知识文本
    """
    retriever = get_retriever()

    if phase:
        docs = retriever.retrieve_for_phase(query, phase, domain)
    else:
        docs = retriever.retrieve(query, domain=domain)

    return retriever.format_retrieved_docs(docs)
