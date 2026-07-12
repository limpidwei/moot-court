"""
本地文本向量化服务

使用 sentence-transformers 本地模型将文本转换为向量表示
使用 BAAI/bge-small-zh 模型，专门针对中文优化
"""

import os
import logging
import threading
from pathlib import Path
from typing import List
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """向量化失败。

    H4 修复：原先失败时静默返回零向量 [0.0]*dim，导致 indexer 把零向量入库污染
    整个 ChromaDB、retriever 用零向量查询返回错误法律条文（法条幻觉）。改为显式抛错，
    由上层（indexer 跳过该文档 / retriever 返回空检索）决定降级，绝不入库零向量。
    """


def _resolve_model_path(model_name: str) -> str:
    """
    获取模型的本地路径，避免联网检查。

    解析优先级：
    1. 项目根目录下的 models/<model_name>（把模型部署到项目里，离线可用）
    2. Hugging Face 本地缓存（HF_HUB_CACHE）
    3. 返回原始名称，让 sentence-transformers 自行下载（需要联网）
    """
    # 1. 项目内本地模型目录：backend/rag/embeddings.py -> ../../models/<model_name>
    project_root = Path(__file__).resolve().parent.parent.parent
    local_model_dir = project_root / "models" / model_name.replace("/", "--")
    if not local_model_dir.exists():
        local_model_dir = project_root / "models" / model_name.split("/")[-1]
    if local_model_dir.exists():
        print(f"使用项目内本地模型: {local_model_dir}")
        return str(local_model_dir)

    # 2. Hugging Face 本地缓存
    try:
        from huggingface_hub import snapshot_download

        local_path = snapshot_download(model_name, local_files_only=True)
        print(f"使用 HF 本地缓存: {local_path}")
        return local_path
    except Exception:
        pass

    # 3. 回退到原始名称（会联网下载）
    return model_name


class LocalEmbeddings:
    """本地 Embedding 服务封装"""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh-v1.5",
    ):
        """
        初始化本地 Embedding 服务

        Args:
            model_name: 使用的模型名称（默认使用中文优化的小模型）
        """
        print(f"正在加载 embedding 模型: {model_name}")
        # 优先使用本地缓存路径，避免联网超时
        model_path = _resolve_model_path(model_name)
        self.model = SentenceTransformer(model_path)
        self.dimension = self.model.get_sentence_embedding_dimension()
        print(f"模型加载完成，向量维度: {self.dimension}")

    def embed_text(self, text: str) -> List[float]:
        """
        将单个文本转换为向量

        Args:
            text: 输入文本

        Returns:
            向量列表（float 数组）

        Raises:
            EmbeddingError: 向量化失败（H4：不再返回零向量，由上层决定降级）
        """
        try:
            embedding = self.model.encode(text, normalize_embeddings=True)
            vec = embedding.tolist()
        except Exception as e:
            logger.error(f"Embedding 失败: {e}")
            raise EmbeddingError(f"单文本向量化失败: {e}") from e

        # 零向量（全 0）无语义、会污染检索，同样视为失败
        if not vec or all(v == 0.0 for v in vec):
            raise EmbeddingError("向量化结果为零向量，拒绝入库/检索")
        return vec

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量将文本转换为向量

        Args:
            texts: 输入文本列表

        Returns:
            向量列表的列表

        Raises:
            EmbeddingError: 向量化失败（H4：不再返回零向量列表）
        """
        if not texts:
            return []

        try:
            embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=True)
            vectors = [emb.tolist() for emb in embeddings]
        except Exception as e:
            logger.error(f"Batch embedding 失败: {e}")
            raise EmbeddingError(f"批量向量化失败: {e}") from e

        # 任一零向量都拒绝整批入库，避免污染 ChromaDB
        for vec in vectors:
            if not vec or all(v == 0.0 for v in vec):
                raise EmbeddingError("批量结果含零向量，拒绝入库/检索")
        return vectors


# 全局实例（延迟初始化）
_embeddings_instance = None
_embeddings_lock = threading.Lock()


def get_embeddings() -> LocalEmbeddings:
    """获取全局 Embeddings 实例（线程安全，双重检查锁）"""
    global _embeddings_instance
    if _embeddings_instance is None:
        with _embeddings_lock:
            if _embeddings_instance is None:
                _embeddings_instance = LocalEmbeddings()
    return _embeddings_instance
