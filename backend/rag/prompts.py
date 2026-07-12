"""
RAG 增强提示词

定义如何将检索到的法律知识注入到 Agent 的提示词中
"""

from typing import Optional


def enhance_prompt_with_legal_knowledge(
    original_prompt: str,
    legal_knowledge: str,
    phase: Optional[int] = None,
) -> str:
    """
    将法律知识注入到原始提示词中

    Args:
        original_prompt: 原始提示词
        legal_knowledge: 检索到的法律知识（格式化文本）
        phase: 庭审阶段（用于定制化注入方式）

    Returns:
        增强后的提示词
    """
    if not legal_knowledge or not legal_knowledge.strip():
        return original_prompt

    # 根据阶段定制注入方式
    if phase == 1:
        injection = f"""

## 相关法律依据（参考）

以下是与本案相关的法律条文和司法解释，请在分析请求权基础时参考：

{legal_knowledge}

请在分析时：
1. 引用具体的法律条文编号（如"根据《民法典》第577条"）
2. 结合司法解释的具体规定
3. 说明法律依据与案件事实的对应关系
"""
    elif phase == 3:
        injection = f"""

## 相关法律依据（参考）

以下是与本案相关的法律条文和司法解释，请在制定答辩策略时参考：

{legal_knowledge}

请在答辩时：
1. 引用具体的法律条文进行抗辩
2. 结合司法解释寻找有利的法律依据
3. 指出原告请求权基础的薄弱环节
"""
    elif phase == 5:
        injection = f"""

## 相关法律依据（参考）

以下是与本案相关的法律条文和司法解释，请在归纳争议焦点时参考：

{legal_knowledge}

请在归纳争议焦点时：
1. 明确双方争议涉及的具体法律条文
2. 指出法律适用的分歧点
3. 结合司法解释分析各焦点的法律意义
"""
    elif phase == 8:
        injection = f"""

## 相关法律依据（参考）

以下是与本案相关的法律条文和司法解释，请在作出判决时参考：

{legal_knowledge}

请在判决时：
1. 准确引用法律条文作为判决依据
2. 结合司法解释进行法律适用分析
3. 在"法律适用及论证"部分详细说明法律依据
4. 引用具体的条文编号（如"依照《民法典》第XXX条"）
"""
    else:
        # 通用注入方式
        injection = f"""

## 相关法律依据（参考）

{legal_knowledge}
"""

    # 将法律知识注入到原始提示词的末尾
    enhanced_prompt = original_prompt + injection

    return enhanced_prompt


def build_case_summary_for_retrieval(
    case_title: str,
    facts: str,
    claims: str,
    current_phase: int,
) -> str:
    """
    构建用于检索的案件摘要

    根据当前阶段，提取案件的关键信息作为检索查询

    Args:
        case_title: 案由
        facts: 案件事实
        claims: 诉讼请求
        current_phase: 当前阶段

    Returns:
        用于检索的查询文本
    """
    # 截取关键信息（避免太长）
    facts_summary = facts[:500] if len(facts) > 500 else facts
    claims_summary = claims[:300] if len(claims) > 300 else claims

    # 构建查询
    query_parts = [f"案由：{case_title}"]

    if current_phase in [1, 3, 5]:
        # 这些阶段需要基于事实和请求权检索
        query_parts.append(f"案件事实：{facts_summary}")
        query_parts.append(f"诉讼请求：{claims_summary}")
    elif current_phase == 8:
        # 判决阶段需要全面信息
        query_parts.append(f"案件事实：{facts_summary}")
        query_parts.append(f"诉讼请求：{claims_summary}")
    else:
        # 其他阶段简化查询
        query_parts.append(f"案件事实摘要：{facts_summary[:300]}")

    return "\n".join(query_parts)
