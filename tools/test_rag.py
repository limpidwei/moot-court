"""
RAG 测试脚本

测试 RAG 系统的完整流程：
1. 检索法律知识
2. 格式化检索结果
3. 验证检索质量

使用方法：
    python tools/test_rag.py
"""

import os
import sys
# Fix Windows UTF-8 output
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.rag.retriever import get_retriever
from backend.rag.prompts import build_case_summary_for_retrieval


def test_basic_retrieval():
    """测试基本检索功能"""
    print("=" * 60)
    print("测试 1: 基本检索功能")
    print("=" * 60)

    retriever = get_retriever()

    # 测试查询
    test_queries = [
        "民间借贷利率上限",
        "合同违约责任",
        "夫妻共同债务",
        "房屋买卖合同纠纷",
        "劳动争议赔偿",
    ]

    for query in test_queries:
        print(f"\n查询: {query}")
        docs = retriever.retrieve(query, top_k=3, domain="civil")

        if docs:
            print(f"[OK] 检索到 {len(docs)} 个结果")
            for i, doc in enumerate(docs, 1):
                print(f"  [{i}] {doc['metadata'].get('doc_name', '未知')}")
                print(f"      相似度: {doc['similarity']:.3f}")
                print(f"      预览: {doc['text'][:100]}...")
        else:
            print("[FAIL] 未检索到结果")


def test_case_retrieval():
    """测试案件场景检索"""
    print("\n" + "=" * 60)
    print("测试 2: 案件场景检索")
    print("=" * 60)

    # 模拟一个民间借贷案件
    case_title = "民间借贷纠纷"
    facts = """
    原告张三与被告李四是朋友关系。2023年1月，李四因资金周转困难向张三借款50万元，
    双方签订借款协议，约定借款期限1年，年利率24%。张三通过银行转账将50万元支付给李四。
    借款到期后，李四未能按时还款。张三多次催要无果，遂诉至法院，要求李四偿还本金50万元
    及利息12万元。
    """
    claims = """
    1. 判令被告偿还借款本金50万元；
    2. 判令被告支付利息12万元（按年利率24%计算）；
    3. 本案诉讼费由被告承担。
    """

    # 构建检索查询
    query = build_case_summary_for_retrieval(
        case_title=case_title,
        facts=facts,
        claims=claims,
        current_phase=1,
    )

    print(f"案件摘要:\n{query}\n")

    # 检索
    retriever = get_retriever()
    docs = retriever.retrieve(query, top_k=5, domain="civil")

    if docs:
        print(f"✓ 检索到 {len(docs)} 个相关法律条文")
        formatted = retriever.format_retrieved_docs(docs, max_docs=3)
        print("\n格式化结果:")
        print(formatted[:1000] + "..." if len(formatted) > 1000 else formatted)
    else:
        print("✗ 未检索到结果")


def test_phase_specific_retrieval():
    """测试不同阶段的检索策略"""
    print("\n" + "=" * 60)
    print("测试 3: 不同阶段的检索策略")
    print("=" * 60)

    case_title = "买卖合同纠纷"
    facts = "原告与被告签订货物买卖合同，被告未按期交货"
    claims = "要求被告承担违约责任"

    retriever = get_retriever()

    for phase in [1, 3, 5, 8]:
        print(f"\nPhase {phase}:")
        docs = retriever.retrieve_for_phase(
            query=f"{case_title} {facts}",
            phase=phase,
            domain="civil",
        )

        if docs:
            print(f"  ✓ 检索到 {len(docs)} 个结果")
            top_doc = docs[0]
            print(f"    最佳匹配: {top_doc['metadata'].get('doc_name', '未知')}")
        else:
            print("  ✗ 未检索到结果")


def test_collection_stats():
    """测试集合统计信息"""
    print("\n" + "=" * 60)
    print("测试 4: ChromaDB 集合统计")
    print("=" * 60)

    try:
        import chromadb
        from backend.rag.config import RAG_CONFIG

        client = chromadb.PersistentClient(path=RAG_CONFIG["persist_directory"])
        collection = client.get_collection(name=RAG_CONFIG["collection_name"])

        count = collection.count()
        print(f"✓ 集合中的文档数量: {count}")

        if count > 0:
            # 获取一些样本
            sample = collection.peek(limit=5)
            print(f"\n样本数据:")
            for i, (doc_id, metadata) in enumerate(zip(sample['ids'], sample['metadatas']), 1):
                print(f"  [{i}] ID: {doc_id}")
                print(f"      文档: {metadata.get('doc_name', '未知')}")
                print(f"      类型: {metadata.get('chunk_type', '未知')}")
        else:
            print("⚠ 集合为空，请先运行索引")

    except Exception as e:
        print(f"✗ 获取统计信息失败: {e}")


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("RAG 系统测试")
    print("=" * 60)

    try:
        test_collection_stats()
        test_basic_retrieval()
        test_case_retrieval()
        test_phase_specific_retrieval()

        print("\n" + "=" * 60)
        print("所有测试完成")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
