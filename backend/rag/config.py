"""
RAG 模块配置
"""

import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 法律知识库目录
LEGAL_KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "legal_knowledge"

# ChromaDB 配置
CHROMA_PERSIST_DIR = PROJECT_ROOT / "data" / "chroma_db"

# RAG 配置
RAG_CONFIG = {
    # 向量检索配置
    "top_k": 5,  # 返回最相关的 K 个文档片段
    "similarity_threshold": 0.5,  # 相似度阈值（低于此值不返回）

    # 文档分割配置
    "chunk_size": 1000,  # 每个片段的最大字符数
    "chunk_overlap": 200,  # 片段之间的重叠字符数

    # ChromaDB 配置
    "collection_name": "legal_knowledge",  # 集合名称
    "persist_directory": str(CHROMA_PERSIST_DIR),

    # 支持的领域（可扩展）
    "supported_domains": ["civil", "criminal", "administrative", "ip"],

    # 当前激活的领域
    "active_domains": ["civil"],
}

# 民法领域文档清单
CIVIL_LAW_DOCUMENTS = [
    {
        "id": "minfadian",
        "name": "中华人民共和国民法典",
        "filename": "01_民法典.md",
        "effective_date": "2021-01-01",
        "type": "law",
    },
    {
        "id": "minfadian_shijianxiaoli",
        "name": "最高人民法院关于适用《中华人民共和国民法典》时间效力的若干规定",
        "filename": "02_民法典时间效力规定.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕15号",
    },
    {
        "id": "minfadian_zongze",
        "name": "最高人民法院关于适用《中华人民共和国民法典》总则编若干问题的解释",
        "filename": "03_民法典总则编解释.md",
        "effective_date": "2022-03-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2022〕6号",
    },
    {
        "id": "minfadian_wuquan",
        "name": "最高人民法院关于适用《中华人民共和国民法典》物权编的解释(一)",
        "filename": "04_民法典物权编解释一.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕24号",
    },
    {
        "id": "minfadian_hetong",
        "name": "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
        "filename": "05_民法典合同编通则解释.md",
        "effective_date": "2023-12-05",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2023〕13号",
    },
    {
        "id": "minfadian_danbao",
        "name": "最高人民法院关于适用《中华人民共和国民法典》有关担保制度的解释",
        "filename": "06_民法典担保制度解释.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕28号",
    },
    {
        "id": "minfadian_hunyin1",
        "name": "最高人民法院关于适用《中华人民共和国民法典》婚姻家庭编的解释(一)",
        "filename": "07_民法典婚姻家庭编解释一.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕22号",
    },
    {
        "id": "minfadian_hunyin2",
        "name": "最高人民法院关于适用《中华人民共和国民法典》婚姻家庭编的解释(二)",
        "filename": "08_民法典婚姻家庭编解释二.md",
        "effective_date": "2025-02-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2025〕1号",
    },
    {
        "id": "minfadian_jicheng",
        "name": "最高人民法院关于适用《中华人民共和国民法典》继承编的解释(一)",
        "filename": "09_民法典继承编解释一.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕23号",
    },
    {
        "id": "minfadian_qinquan",
        "name": "最高人民法院关于适用《中华人民共和国民法典》侵权责任编的解释(一)",
        "filename": "10_民法典侵权责任编解释一.md",
        "effective_date": "2024-09-27",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2024〕12号",
    },
    {
        "id": "minjian_jiedai",
        "name": "最高人民法院关于审理民间借贷案件适用法律若干问题的规定(2020第二次修正)",
        "filename": "11_民间借贷司法解释.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕17号",
    },
    {
        "id": "maimai_hetong",
        "name": "最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释(2020修正)",
        "filename": "12_买卖合同纠纷解释.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕17号",
    },
    {
        "id": "shangpinfang_maimai",
        "name": "最高人民法院关于审理商品房买卖合同纠纷案件适用法律若干问题的解释(2020修正)",
        "filename": "13_商品房买卖合同纠纷解释.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕17号",
    },
    {
        "id": "jianshe_gongcheng",
        "name": "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释(一)",
        "filename": "14_建设工程施工合同纠纷解释一.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕25号",
    },
    {
        "id": "laodong_zhengyi1",
        "name": "最高人民法院关于审理劳动争议案件适用法律问题的解释(一)",
        "filename": "15_劳动争议司法解释一.md",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2020〕26号",
    },
    {
        "id": "laodong_zhengyi2",
        "name": "最高人民法院关于审理劳动争议案件适用法律问题的解释(二)",
        "filename": "16_劳动争议司法解释二.md",
        "effective_date": "2025-09-01",
        "type": "judicial_interpretation",
        "doc_number": "法释〔2025〕12号",
    },
]
