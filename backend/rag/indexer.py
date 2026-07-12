"""
法律文档索引器

负责：
1. 读取法律文档（Markdown 格式）
2. 智能分割文档为片段（按条款分割）
3. 向量化片段
4. 存储到 ChromaDB
"""

import re
from pathlib import Path
from typing import List, Dict, Any
import chromadb
from chromadb.config import Settings

from .config import RAG_CONFIG, LEGAL_KNOWLEDGE_DIR, CIVIL_LAW_DOCUMENTS
from .embeddings import get_embeddings


class LegalDocumentIndexer:
    """法律文档索引器"""

    def __init__(self):
        """初始化索引器"""
        # 初始化 ChromaDB 客户端
        self.chroma_client = chromadb.PersistentClient(
            path=RAG_CONFIG["persist_directory"]
        )

        # 获取或创建集合
        self.collection = self.chroma_client.get_or_create_collection(
            name=RAG_CONFIG["collection_name"],
            metadata={"description": "中国法律知识库"},
        )

        # 初始化 Embedding 服务
        self.embeddings = get_embeddings()

        # 配置参数
        self.chunk_size = RAG_CONFIG["chunk_size"]
        self.chunk_overlap = RAG_CONFIG["chunk_overlap"]

    def split_legal_document(
        self, content: str, doc_metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        智能分割法律文档

        策略：
        1. 优先按"第X条"分割（法律条文）
        2. 其次按"第X章"、"第X编"分割（大段落）
        3. 最后按 chunk_size 强制分割

        Args:
            content: 文档内容
            doc_metadata: 文档元数据

        Returns:
            分割后的片段列表
        """
        chunks = []

        # 尝试按"第X条"分割
        article_pattern = r"(第[一二三四五六七八九十百千零\d]+条\s*[^\n]*\n(?:.*?\n)*?)(?=第[一二三四五六七八九十百千零\d]+条|\Z)"
        articles = re.findall(article_pattern, content, re.MULTILINE)

        if articles:
            # 成功按条款分割
            for i, article in enumerate(articles):
                article = article.strip()
                if len(article) > 50:  # 过滤太短的片段
                    chunks.append({
                        "text": article,
                        "metadata": {
                            **doc_metadata,
                            "chunk_type": "article",
                            "chunk_index": i,
                        }
                    })
        else:
            # 回退到按 chunk_size 分割
            lines = content.split("\n")
            current_chunk = []
            current_length = 0

            for line in lines:
                line_length = len(line)

                if current_length + line_length > self.chunk_size and current_chunk:
                    # 当前块已满，保存并开始新块
                    chunk_text = "\n".join(current_chunk).strip()
                    if chunk_text:
                        chunks.append({
                            "text": chunk_text,
                            "metadata": {
                                **doc_metadata,
                                "chunk_type": "paragraph",
                                "chunk_index": len(chunks),
                            }
                        })

                    # 保留 overlap
                    overlap_lines = []
                    overlap_length = 0
                    for prev_line in reversed(current_chunk):
                        if overlap_length + len(prev_line) > self.chunk_overlap:
                            break
                        overlap_lines.insert(0, prev_line)
                        overlap_length += len(prev_line)

                    current_chunk = overlap_lines
                    current_length = overlap_length

                current_chunk.append(line)
                current_length += line_length

            # 保存最后一个块
            if current_chunk:
                chunk_text = "\n".join(current_chunk).strip()
                if chunk_text:
                    chunks.append({
                        "text": chunk_text,
                        "metadata": {
                            **doc_metadata,
                            "chunk_type": "paragraph",
                            "chunk_index": len(chunks),
                        }
                    })

        return chunks

    def index_document(self, doc_config: Dict[str, Any], domain: str = "civil") -> int:
        """
        索引单个法律文档

        Args:
            doc_config: 文档配置（来自 CIVIL_LAW_DOCUMENTS）
            domain: 法律领域

        Returns:
            索引的片段数量
        """
        doc_path = LEGAL_KNOWLEDGE_DIR / domain / doc_config["filename"]

        if not doc_path.exists():
            print(f"警告: 文档不存在 {doc_path}")
            return 0

        # 读取文档内容
        content = doc_path.read_text(encoding="utf-8")

        # 准备元数据
        doc_metadata = {
            "doc_id": doc_config["id"],
            "doc_name": doc_config["name"],
            "doc_type": doc_config["type"],
            "domain": domain,
            "effective_date": doc_config.get("effective_date", ""),
            "doc_number": doc_config.get("doc_number", ""),
        }

        # 分割文档
        chunks = self.split_legal_document(content, doc_metadata)

        if not chunks:
            print(f"警告: 文档分割后无内容 {doc_config['name']}")
            return 0

        # 向量化
        texts = [chunk["text"] for chunk in chunks]
        embeddings = self.embeddings.embed_texts(texts)

        # 存储到 ChromaDB
        ids = [f"{doc_config['id']}_{i}" for i in range(len(chunks))]
        metadatas = [chunk["metadata"] for chunk in chunks]

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        print(f"已索引: {doc_config['name']} ({len(chunks)} 个片段)")
        return len(chunks)

    def index_all_documents(self, domain: str = "civil") -> Dict[str, int]:
        """
        索引指定领域的所有文档

        Args:
            domain: 法律领域

        Returns:
            每个文档索引的片段数量
        """
        # 根据 domain 选择文档清单
        if domain == "civil":
            documents = CIVIL_LAW_DOCUMENTS
        else:
            print(f"警告: 未支持的领域 {domain}")
            return {}

        results = {}
        for doc_config in documents:
            try:
                count = self.index_document(doc_config, domain)
                results[doc_config["id"]] = count
            except Exception as e:
                # H4：embed_texts 失败（含零向量拒绝）时跳过该文档，
                # 不让单个文档的向量化故障中断整批索引，也杜绝零向量入库。
                print(f"[index] 跳过文档 {doc_config.get('name')}: {e}")
                results[doc_config["id"]] = 0

        total = sum(results.values())
        print(f"\n总计索引: {total} 个片段（来自 {len(results)} 个文档）")

        return results

    def clear_collection(self):
        """清空集合（重新索引前使用）"""
        self.chroma_client.delete_collection(RAG_CONFIG["collection_name"])
        self.collection = self.chroma_client.get_or_create_collection(
            name=RAG_CONFIG["collection_name"],
            metadata={"description": "中国法律知识库"},
        )
        print("已清空 ChromaDB 集合")


def index_legal_knowledge(domain: str = "civil", clear_first: bool = False):
    """
    索引法律知识库的入口函数

    Args:
        domain: 法律领域
        clear_first: 是否先清空集合
    """
    indexer = LegalDocumentIndexer()

    if clear_first:
        indexer.clear_collection()

    results = indexer.index_all_documents(domain)
    return results


if __name__ == "__main__":
    # 命令行运行
    import sys

    clear = "--clear" in sys.argv
    domain = "civil"

    for arg in sys.argv:
        if arg.startswith("--domain="):
            domain = arg.split("=")[1]

    print(f"开始索引法律知识库（领域: {domain}）...")
    results = index_legal_knowledge(domain, clear_first=clear)
    print(f"\n索引完成: {results}")
