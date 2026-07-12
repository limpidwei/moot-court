"""
AI 增强与证据冲突检测

职责：
1. 对单条证据进行 LLM 摘要、分类、提取关键信息
2. 对多条证据进行冲突检测，发现矛盾点
3. 生成时间线事件

设计原则：
- 系统不做真假判断，只发现矛盾并结构化呈现
- 所有 LLM 输出均为 JSON，便于程序解析
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from backend.llm import llm_call
from .schemas import EvidenceItem, TimelineEvent, ConflictReport, ClaimDetail

logger = logging.getLogger(__name__)

# ============================================================
# Prompts
# ============================================================

_EVIDENCE_ANALYSIS_PROMPT = """你是一位法律证据分析助手。请分析以下证据内容，提取关键信息。

要求：
1. summary: 用1-2句话概括证据核心内容（中文）
2. evidence_type: 从 ["书证", "物证", "电子数据", "证人证言", "鉴定意见", "视听资料", "当事人陈述"] 中选择最匹配的类型
3. date: 提取证据中明确提到的日期（ISO格式 YYYY-MM-DD），如无则留空
4. parties: 提取涉及的当事人名称列表
5. relevance: 提取与哪些法律要件或争议焦点相关（如"合同成立", "违约事实", "损害赔偿"等）
6. confidence: 你对以上提取结果的置信度 (0.0-1.0)

必须以纯 JSON 格式输出，不要添加 markdown 代码块标记：
{
  "summary": "...",
  "evidence_type": "...",
  "date": "...",
  "parties": ["..."],
  "relevance": ["..."],
  "confidence": 0.95
}

证据内容：
"""

_CONFLICT_DETECTION_PROMPT = """你是一位法律证据审查助手。你的任务是发现以下证据之间的矛盾和冲突。

重要原则：
- 你不做真假判断，只发现"不同证据对同一事实的说法不一致"
- 输出结构化结果，供律师做最终判断

每条证据包含：
- evidence_id: 证据编号
- party: 证据归属立场 (plaintiff=原告, defendant=被告, third_party=第三方, unknown=未知)
- evidence_type: 证据类型
- summary: 证据摘要
- content: 证据原文（前500字）

请检查以下类型的冲突：
1. temporal (时间冲突): 同一事件在不同证据中的时间不一致
2. factual (事实冲突): 同一事件的描述相互矛盾
3. quantitative (数量冲突): 金额、数量等数字不一致
4. party (当事人冲突): 涉及的主体不一致
5. stance (立场冲突): 原被告对同一事件主张相反

对发现的每个冲突，输出：
- conflict_type: 冲突类型
- severity: high/medium/low (根据矛盾严重程度)
- description: 一句话描述矛盾点
- involved_evidence_ids: 涉及的证据编号列表
- involved_parties: 涉及的立场方
- claims: 各方具体主张（引用原文片段）
- ai_note: 你的分析备注（仅供参考）

必须以纯 JSON 数组格式输出，不要添加 markdown 代码块标记：
[
  {
    "conflict_type": "temporal",
    "severity": "high",
    "description": "...",
    "involved_evidence_ids": ["ev1", "ev2"],
    "involved_parties": ["plaintiff", "defendant"],
    "claims": [
      {"evidence_id": "ev1", "party": "plaintiff", "original_text": "...", "extracted_claim": "..."}
    ],
    "ai_note": "..."
  }
]

如果没有发现冲突，输出空数组 []。

证据列表：
"""

_TIMELINE_EXTRACTION_PROMPT = """你是一位法律案件梳理助手。请根据以下证据，提取关键时间节点，生成案件时间线。

要求：
- 每个事件必须有明确的日期（尽量精确到日，若只有月份则填该月1日）
- event_type 从 ["contract", "breach", "action", "deadline", "fact", "evidence"] 中选择
- label 用一句话描述事件
- party 填涉及的当事人

必须以纯 JSON 数组格式输出：
[
  {"date": "2023-05-01", "label": "...", "event_type": "contract", "party": "..."}
]

证据列表：
"""


# ============================================================
# 单条证据分析
# ============================================================

async def analyze_evidence(item: EvidenceItem) -> None:
    """
    对单条证据进行 AI 分析，结果直接修改 item 对象
    """
    if not item.content or len(item.content.strip()) < 10:
        item.summary = "（内容过短，无法分析）"
        item.status = "completed"
        return

    try:
        content_preview = item.content[:3000]  # 限制长度，避免 token 过多
        prompt = _EVIDENCE_ANALYSIS_PROMPT + content_preview

        response = await llm_call(
            system_prompt="你是一个严谨的法律证据分析助手，只输出 JSON。",
            user_message=prompt,
            temperature=0.1,  # 低温度保证输出稳定
            max_tokens=2048,
        )

        result = _extract_json(response)
        if result:
            item.summary = result.get("summary", "") or item.content[:200]
            item.evidence_type = result.get("evidence_type", "")
            item.date = result.get("date") or None
            item.parties = result.get("parties", []) or []
            item.relevance = result.get("relevance", []) or []
            item.confidence = result.get("confidence", 0.9)
            item.status = "completed"
        else:
            item.summary = item.content[:300]
            item.status = "completed"

    except Exception as e:
        logger.error(f"证据 AI 分析失败 {item.id}: {e}")
        item.summary = item.content[:300] if item.content else ""
        item.status = "failed"
        item.error_message = str(e)


# ============================================================
# 冲突检测
# ============================================================

async def detect_conflicts(evidence_items: list[EvidenceItem]) -> list[ConflictReport]:
    """
    对多条证据进行冲突检测，返回冲突报告列表

    设计原则：
    - 只分析已完成分析的证据（status == "completed"）
    - 证据少于 2 条时直接返回空列表
    - 每次最多分析 20 条证据（避免 token 超限）
    """
    items = [it for it in evidence_items if it.status == "completed"]
    if len(items) < 2:
        return []

    # 分批处理，每批最多 20 条
    all_conflicts: list[ConflictReport] = []
    batch_size = 20
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        conflicts = await _detect_conflicts_batch(batch)
        all_conflicts.extend(conflicts)

    return all_conflicts


async def _detect_conflicts_batch(items: list[EvidenceItem]) -> list[ConflictReport]:
    """对一批证据进行冲突检测"""
    evidence_texts = []
    for idx, it in enumerate(items):
        evidence_texts.append(
            f"【证据 {idx + 1}】\n"
            f"evidence_id: {it.id}\n"
            f"party: {it.party}\n"
            f"evidence_type: {it.evidence_type}\n"
            f"summary: {it.summary}\n"
            f"content: {it.content[:500]}\n"
        )

    prompt = _CONFLICT_DETECTION_PROMPT + "\n---\n".join(evidence_texts)

    try:
        response = await llm_call(
            system_prompt="你是一个法律证据审查助手，只发现矛盾，不做真假判断，只输出 JSON 数组。",
            user_message=prompt,
            temperature=0.2,
            max_tokens=4096,
        )

        results = _extract_json(response)
        if not isinstance(results, list):
            return []

        conflicts = []
        for r in results:
            claims = [
                ClaimDetail(
                    evidence_id=c.get("evidence_id", ""),
                    party=c.get("party", "unknown"),
                    original_text=c.get("original_text", ""),
                    extracted_claim=c.get("extracted_claim", ""),
                )
                for c in r.get("claims", [])
            ]

            conflict = ConflictReport(
                id=f"conf_{_now_str()}_{len(conflicts)}",
                case_id="",  # 由调用方填充
                conflict_type=r.get("conflict_type", "factual"),
                severity=r.get("severity", "medium"),
                description=r.get("description", ""),
                involved_evidence_ids=r.get("involved_evidence_ids", []),
                involved_parties=r.get("involved_parties", []),
                claims=claims,
                ai_note=r.get("ai_note", ""),
                created_at=_now_str(),
            )
            conflicts.append(conflict)

        return conflicts

    except Exception as e:
        logger.error(f"冲突检测失败: {e}")
        return []


# ============================================================
# 时间线提取
# ============================================================

async def extract_timeline(evidence_items: list[EvidenceItem]) -> list[TimelineEvent]:
    """从证据中提取时间线事件"""
    items = [it for it in evidence_items if it.status == "completed" and it.date]
    if not items:
        return []

    evidence_texts = []
    for it in items:
        evidence_texts.append(
            f"- 证据: {it.summary}\n  日期: {it.date}\n  当事人: {', '.join(it.parties)}\n"
        )

    prompt = _TIMELINE_EXTRACTION_PROMPT + "\n".join(evidence_texts)

    try:
        response = await llm_call(
            system_prompt="你是一个法律案件梳理助手，只输出 JSON 数组。",
            user_message=prompt,
            temperature=0.1,
            max_tokens=2048,
        )

        results = _extract_json(response)
        if not isinstance(results, list):
            return []

        events = []
        for idx, r in enumerate(results):
            event = TimelineEvent(
                id=f"evt_{_now_str()}_{idx}",
                date=r.get("date", ""),
                label=r.get("label", ""),
                event_type=r.get("event_type", "fact"),
                party=r.get("party", ""),
            )
            events.append(event)

        # 按日期排序
        events.sort(key=lambda e: e.date or "")
        return events

    except Exception as e:
        logger.error(f"时间线提取失败: {e}")
        return []


# ============================================================
# 工具函数
# ============================================================

def _extract_json(text: str) -> Optional[dict | list]:
    """从 LLM 响应中提取 JSON"""
    if not text:
        return None

    # 先尝试直接解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 尝试从 markdown 代码块中提取
    patterns = [
        r"```json\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue

    # 尝试找第一个 [ 或 { 到最后一个 ] 或 }
    try:
        start = min(text.index("["), text.index("{"))
        end = max(text.rindex("]"), text.rindex("}")) + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    logger.warning(f"无法从 LLM 响应中提取 JSON: {text[:200]}")
    return None


def _now_str() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")
