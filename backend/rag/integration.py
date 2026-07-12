"""
RAG 集成模块

将 RAG 检索功能集成到现有的 Agent 工作流中
"""

from typing import Optional
from .retriever import retrieve_legal_knowledge
from .prompts import enhance_prompt_with_legal_knowledge, build_case_summary_for_retrieval


def enhance_agent_prompt(
    original_prompt: str,
    case_title: str,
    facts: str,
    claims: str,
    current_phase: int,
    use_rag: bool = True,
) -> str:
    """
    使用 RAG 增强 Agent 提示词

    Args:
        original_prompt: 原始提示词
        case_title: 案由
        facts: 案件事实
        claims: 诉讼请求
        current_phase: 当前庭审阶段
        use_rag: 是否启用 RAG（可关闭用于调试）

    Returns:
        增强后的提示词
    """
    if not use_rag:
        return original_prompt

    # 只对特定阶段启用 RAG
    rag_enabled_phases = [1, 3, 5, 8]
    if current_phase not in rag_enabled_phases:
        return original_prompt

    try:
        # 构建检索查询
        query = build_case_summary_for_retrieval(
            case_title=case_title,
            facts=facts,
            claims=claims,
            current_phase=current_phase,
        )

        # 检索法律知识
        legal_knowledge = retrieve_legal_knowledge(
            query=query,
            phase=current_phase,
            domain="civil",
        )

        if not legal_knowledge:
            print(f"Phase {current_phase}: 未检索到相关法律知识")
            return original_prompt

        # 增强提示词
        enhanced_prompt = enhance_prompt_with_legal_knowledge(
            original_prompt=original_prompt,
            legal_knowledge=legal_knowledge,
            phase=current_phase,
        )

        print(f"Phase {current_phase}: 已注入 RAG 法律知识")
        return enhanced_prompt

    except Exception as e:
        print(f"RAG 增强失败: {e}")
        # 失败时返回原始提示词，不影响正常运行
        return original_prompt


def get_legal_context_for_case(
    case_title: str,
    facts: str,
    claims: str,
    current_phase: int,
) -> str:
    """
    获取案件的法律上下文（用于调试和日志）

    Args:
        case_title: 案由
        facts: 案件事实
        claims: 诉讼请求
        current_phase: 当前庭审阶段

    Returns:
        法律上下文文本
    """
    query = build_case_summary_for_retrieval(
        case_title=case_title,
        facts=facts,
        claims=claims,
        current_phase=current_phase,
    )

    return retrieve_legal_knowledge(
        query=query,
        phase=current_phase,
        domain="civil",
    )
