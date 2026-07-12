"""
统一提取服务 - 从阶段文本中提取结构化 insight 数据

核心目标：消除 insight 卡片为空的问题，通过轻量级 LLM 调用
从每个 phase 的文本中提炼关键决策信息。
"""

import json
import logging
import re
from typing import Any

from ..llm import llm_call, LLMConfig
from ..orchestration.analysis import CaseAnalysis

logger = logging.getLogger(__name__)

# ============================================================
# 统一提取 prompt（每阶段一个，输出 insight + structured）
# ============================================================

UNIFIED_PROMPTS: dict[int, str] = {
    1: """请从以下请求权基础分析中提取结构化数据，以 JSON 格式输出。

要求输出的 JSON 包含以下顶级字段：

1. "insight" — 策略卡片数据：
   - legal_relation: 法律关系定性（一句话，20字以内）
   - best_claim_basis: 最优请求权基础（条文号 + 匹配度说明）
   - win_rate_assessment: {level: "high"/"medium"/"low", reason: "一句话原因"}
   - key_risks: [{severity: "warning"/"danger", text: "风险描述"}]
   - next_action: 下一步动作建议

2. "structured" — 结构化字段（供后续阶段引用）：
   - legal_relationship: 法律关系定性（一句话）
   - claim_basis: 最优请求权基础描述
   - claim_basis_article: 法条编号（如"《民法典》第577条"）

只输出纯 JSON，不要 Markdown 代码块，不要其他说明。

原文：
{content}

{context}""",

    2: """请从以下起诉状和证据目录中提取结构化数据，以 JSON 格式输出。

要求输出的 JSON 包含以下顶级字段：

1. "insight" — 攻防卡片数据：
   - core_claims: 核心诉讼请求（数组，每项一句话）
   - evidence_strength: [{name: "证据名称", strength: "strong"/"medium"/"weak", reason: "原因"}]
   - likely_attacks: 对方最可能攻击的点（数组）

2. "structured" — 结构化字段：
   - core_claims: 核心请求数组
   - evidence_list: [{name: "证据名", type: "书证", purpose: "证明目的"}]

只输出纯 JSON。

原文：
{content}

{context}""",

    5: """请从以下争议焦点归纳中提取结构化数据，以 JSON 格式输出。

要求输出的 JSON 包含以下顶级字段：

1. "insight" — 焦点卡片数据：
   - key_issues: [{text: "焦点描述", favor: "plaintiff"/"defendant"/"neutral", reason: "原因"}]
   - likely_direction: 法官最可能采信的方向

2. "structured" — 结构化字段：
   - dispute_issues: [{text: "焦点描述", favor: "plaintiff"/"defendant"/"neutral"}]

只输出纯 JSON。

原文：
{content}

{context}""",

    8: """请从以下判决和胜率评估中提取结构化数据，以 JSON 格式输出。

要求输出的 JSON 包含以下顶级字段：

1. "insight" — 判决卡片数据：
   - verdict: {result: "support"/"partial"/"dismiss", summary: "一句话总结"}
   - win_rate: 胜率百分比（数字，必须与工具计算结果一致：{known_win_rate}）
   - key_reasons: 关键判决理由（数组）
   - appeal_suggestion: 上诉建议

2. "structured" — 结构化字段：
   - verdict_result: 判决结果
   - verdict_reasons: 判决理由数组

注意：win_rate 必须使用 {known_win_rate}，不要重新计算。

只输出纯 JSON。

原文：
{content}

{context}""",
}

# Phase 3-4, 6, 7 也支持提取但 schema 较简单
UNIFIED_PROMPTS[3] = """请从以下答辩策略分析中提取结构化数据，以 JSON 格式输出。

要求输出的 JSON 包含以下顶级字段：

1. "insight" — 答辩卡片数据：
   - defense_type: "substantive"/"procedural"/"evidence"
   - main_arguments: 主要抗辩理由（数组，每项一句话）
   - strength_assessment: {level: "strong"/"medium"/"weak", reason: "原因"}

2. "structured" — 结构化字段：
   - defense_strategy: 主要抗辩策略（一句话）

只输出纯 JSON。

原文：
{content}

{context}"""

UNIFIED_PROMPTS[4] = """请从以下被告答辩状与证据目录中提取结构化数据，以 JSON 格式输出。

要求输出的 JSON 包含以下顶级字段：

1. "insight" — 答辩卡片数据：
   - core_defenses: 核心抗辩理由（数组，每项一句话）
   - evidence_strength: [{name: "证据名称", strength: "strong"/"medium"/"weak", reason: "原因"}]
   - likely_counter_attacks: 原告最可能反击的点（数组）

2. "structured" — 结构化字段：
   - defense_points: 核心抗辩点数组
   - evidence_list: [{name: "证据名", type: "书证", purpose: "证明目的"}]

只输出纯 JSON。

原文：
{content}

{context}"""

UNIFIED_PROMPTS[6] = """请从以下法庭辩论记录中提取结构化数据，以 JSON 格式输出。

要求输出的 JSON 包含以下顶级字段：

1. "insight" — 交锋卡片数据：
   - favorable_points: 对我方有利的质证点（数组）
   - unfavorable_points: [{severity: "warning"/"danger", text: "风险点"}]
   - evidence_forecast: [{evidence: "证据名", forecast: "adopt"/"exclude"/"partial", reason: "原因"}]

2. "structured" — 结构化字段：
   - debate_highlights: 辩论要点数组

只输出纯 JSON。

原文：
{content}

{context}"""

UNIFIED_PROMPTS[7] = """请从以下双方最后陈述中提取结构化数据，以 JSON 格式输出。

要求输出的 JSON 包含以下顶级字段：

1. "insight" — 陈述卡片数据：
   - plaintiff_summary: 原告方核心主张总结（一句话）
   - defendant_summary: 被告方核心抗辩总结（一句话）
   - key_disputes: 双方最后分歧点（数组）

2. "structured" — 结构化字段：
   - plaintiff_final_arguments: 原告最后陈述要点数组
   - defendant_final_arguments: 被告最后陈述要点数组

只输出纯 JSON。

原文：
{content}

{context}"""


async def extract_phase_unified(
    phase: int,
    content: str,
    analysis: CaseAnalysis,
    llm_config: LLMConfig | None = None,
    known_win_rate: float | None = None,
) -> dict[str, Any]:
    """
    统一提取：从阶段文本中产出 insight + structured 数据。

    Args:
        phase: 阶段编号 (1-8)
        content: 阶段文本内容
        analysis: 当前 CaseAnalysis（用于注入上下文）
        llm_config: 可选的 LLM 配置
        known_win_rate: Phase 8 已知的胜率（来自工具计算）

    Returns:
        提取结果字典，包含 insight/structured 两个顶级字段。
        提取失败时返回空字典。
    """
    prompt_template = UNIFIED_PROMPTS.get(phase)
    if not prompt_template:
        return {}

    # 截断内容
    truncated = content[:5000] + ("\n...[内容已截断]" if len(content) > 5000 else "")

    # 注入结构化上下文（确保跨阶段一致性）
    context = analysis.get_structured_context(for_phase=phase)
    context_block = f"【先前阶段已确定的事实（必须保持一致）】\n{context}" if context else ""

    # 构建 prompt
    # 注意：模板里包含字面 JSON 示例（如 {level:"high", reason:"..."}），
    # 不能用 str.format——它会把字面花括号误当作占位符触发 KeyError/ValueError
    # （C5 根因：曾因此让全部 phase 的 insight 静默为空）。改用显式 replace 安全替换。
    known_win_rate_str = (
        str(known_win_rate) if known_win_rate is not None else "未知"
    ) if phase == 8 else ""
    prompt = (
        prompt_template
        .replace("{content}", truncated)
        .replace("{context}", context_block)
    )
    if "{known_win_rate}" in prompt:
        prompt = prompt.replace("{known_win_rate}", known_win_rate_str)

    system = (
        "你是一名法律文档分析助手，擅长从法律文书中提取结构化数据。"
        "严格按要求的 JSON 格式输出，不要添加额外字段，不要输出 Markdown 代码块。"
        "如果先前阶段已确定了某些事实（如法律关系、请求权基础），你的提取必须与之保持一致。"
    )

    try:
        result = await llm_call(system, prompt, max_tokens=4096, max_retries=2, config=llm_config)
    except Exception as e:
        logger.error(f"Phase {phase} insight extraction failed: {e}")
        return {}

    parsed = _try_parse_json(result)
    if parsed is None:
        logger.warning(f"Phase {phase} insight extraction JSON parse failed")
        return {}

    # 防御式规范化：将字符串类型的评估字段转为标准 dict
    if "insight" in parsed:
        _normalize_assessment(parsed["insight"], "win_rate_assessment")
        _normalize_assessment(parsed["insight"], "strength_assessment")

    # Phase 8: 强制覆盖 win_rate
    if phase == 8 and known_win_rate is not None:
        if "insight" in parsed:
            parsed["insight"]["win_rate"] = known_win_rate

    return parsed


def _normalize_assessment(insight: dict[str, Any], key: str) -> None:
    """将 'high' / 'strong' 等字符串评估规范化为 {level, reason} 对象"""
    if key not in insight:
        return
    value = insight[key]
    if isinstance(value, dict):
        value.setdefault("level", "medium")
        value.setdefault("reason", "")
    elif isinstance(value, str):
        insight[key] = {"level": value, "reason": ""}
    else:
        insight[key] = {"level": "medium", "reason": ""}


def apply_extraction(analysis: CaseAnalysis, phase: int, extracted: dict[str, Any]) -> None:
    """
    将提取结果应用到 CaseAnalysis。

    extracted 结构：
    {
        "insight": { ... },     -> insight_cards[phase]
        "structured": { ... }   -> update_from_phase()
    }
    """
    # 1. 缓存 insight
    if "insight" in extracted:
        insight = extracted["insight"]
        insight["_phase"] = phase
        analysis.insight_cards[phase] = insight

    # 2. 更新结构化字段
    if "structured" in extracted:
        analysis.update_from_phase(phase, extracted["structured"])


def _try_parse_json(text: str) -> dict | None:
    """尝试多种方式解析 JSON，包含 LLM 常见格式错误的清洗"""
    text = text.strip()
    if not text:
        return None

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 从 Markdown 代码块中提取
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 尝试提取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        inner = text[start : end + 1]
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
        # 4. 清洗常见 LLM JSON 错误后再试
        cleaned = _clean_llm_json(inner)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    return None


def _clean_llm_json(text: str) -> str:
    """清洗 LLM 输出的常见 JSON 格式错误"""
    # 去除 // 行注释
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        # 去除行内 // 注释（简单处理，不考虑字符串内的 //）
        idx = line.find("//")
        if idx != -1:
            line = line[:idx]
        lines.append(line)
    text = "\n".join(lines)

    # 去除 /* */ 块注释
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # 去除 trailing comma（对象和数组末尾的逗号）
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    # 将单引号替换为双引号（简单处理，不考虑字符串内的单引号）
    # 这一步比较激进，只在其他方法都失败后才用
    text = text.replace("'", '"')

    return text.strip()
