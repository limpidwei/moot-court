"""
RAG (Retrieval-Augmented Generation) 模块

提供法律知识库的检索增强生成功能：
- embeddings: DeepSeek 文本向量化服务
- indexer: 法律文档索引（分割+向量化+存储）
- retriever: 相似度检索服务
- prompts: RAG 增强提示词
"""

from .config import RAG_CONFIG
from .retriever import LegalKnowledgeRetriever

__all__ = ["RAG_CONFIG", "LegalKnowledgeRetriever"]
