"""
庭审洞察提取服务

为每个 phase 的输出内容提取关键决策卡片信息，
供律师快速扫读，无需阅读全文。
"""

import json
import logging
import re

from ..llm import llm_call

logger = logging.getLogger(__name__)

_PHASE_PROMPTS = {
    1: """请从以下请求权基础分析中提取关键决策信息，以 JSON 格式输出。

要求字段：
- legal_relation: 法律关系定性（一句话，20 字以内）
- best_claim_basis: 最优请求权基础（条文号 + 一句话匹配度说明）
- win_rate_assessment: 胜诉概率评估，含两个子字段：level（"high"/"medium"/"low"）、reason（一句话原因）
- key_risks: 关键风险提示（数组，每项含 severity（"warning"/"danger"）、text（提示内容））
- next_action: 下一步动作建议（一句话）

只输出纯 JSON，不要 Markdown 代码块，不要其他说明。

原文：
{content}""",
    2: """请从以下起诉状和证据目录中提取攻防摘要，以 JSON 格式输出。

要求字段：
- core_claims: 核心诉讼请求（数组，每项一句话结论）
- evidence_strength: 证据强弱分析（数组，每项含 name（证据名称）、strength（"strong"/"medium"/"weak"）、reason（一句话原因））
- likely_attacks: 对方最可能攻击的点（数组，每项一句话）

只输出纯 JSON，不要 Markdown 代码块，不要其他说明。

原文：
{content}""",
    5: """请从以下争议焦点归纳中提取关键信息，以 JSON 格式输出。

要求字段：
- key_issues: 争议焦点清单（数组，每项含 text（焦点描述）、favor（"plaintiff"/"defendant"/"neutral"）、reason（一句话原因））
- likely_direction: 法官最可能采信的方向（一句话）

只输出纯 JSON，不要 Markdown 代码块，不要其他说明。

原文：
{content}""",
    6: """请从以下交叉询问和举证质证记录中提取交锋摘要，以 JSON 格式输出。

要求字段：
- favorable_points: 对我方最有利的质证点（数组，每项一句话）
- unfavorable_points: 对我方最不利的风险点（数组，每项含 severity（"warning"/"danger"）、text（内容））
- evidence_forecast: 证据采纳预测（数组，每项含 evidence（证据名称）、forecast（"adopt"/"exclude"/"partial"）、reason（一句话））

只输出纯 JSON，不要 Markdown 代码块，不要其他说明。

原文：
{content}""",
    8: """请从以下判决和胜率评估中提取关键信息，以 JSON 格式输出。

要求字段：
- verdict: 判决结果速览，含两个子字段：result（"support"/"partial"/"dismiss"）、summary（一句话总结）
- win_rate: 胜率百分比（数字，如 72.5）
- key_reasons: 关键判决理由（数组，每项一句话）
- appeal_suggestion: 上诉建议（一句话，如无显著上诉价值写"无显著上诉价值"）

只输出纯 JSON，不要 Markdown 代码块，不要其他说明。

原文：
{content}""",
}


async def extract_phase_insights(phase: int, content: str, known_win_rate: float | None = None) -> dict:
    """提取指定 phase 的洞察卡片数据"""
    prompt_template = _PHASE_PROMPTS.get(phase)
    if not prompt_template:
        return {"error": "该阶段暂不支持洞察提取"}

    # 截断内容避免超出上下文
    truncated = content[:4000] + ("\n...[内容已截断]" if len(content) > 4000 else "")
    prompt = prompt_template.format(content=truncated)

    if phase == 8 and known_win_rate is not None:
        prompt = prompt.replace(
            "- win_rate: 胜率百分比（数字，如 72.5）",
            f"- win_rate: 胜率百分比（数字，如 72.5） 必须使用以下精确数值：{known_win_rate}，不要重新计算或估算。"
        )

    system = "你是一名法律文档分析助手，擅长从法律文书中提取关键决策信息。严格按要求的 JSON 字段输出，不要添加额外字段。"

    try:
        result = await llm_call(system, prompt, max_tokens=2048, max_retries=2)
    except Exception as e:
        logger.error(f"提取 phase {phase} insights 失败: {e}")
        return {"error": f"提取失败: {e}"}

    # 尝试解析 JSON
    parsed = _try_parse_json(result)
    if parsed is None:
        logger.warning(f"Phase {phase} insights JSON 解析失败，返回原始文本")
        return {"raw": result, "error": "JSON 解析失败"}

    # 注入元数据
    parsed["_phase"] = phase
    return parsed


def _try_parse_json(text: str) -> dict | None:
    """尝试多种方式解析 JSON"""
    text = text.strip()

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
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None
