"""
扩展法律 Skill 体系

新增面向庭前准备与庭后执行的 Skill，输出结构化对象并写入 Ontology。
这些 Skill 是 Codex 式 Agentic 执行器的可调用工具。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from .skill import Skill
from ...ontology import service as ontology_service
from ...ontology.models import Decision

logger = logging.getLogger(__name__)


def _safe_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class EvidenceChainSkill(Skill):
    """证据链检查 Skill：识别证据缺口与薄弱点，输出补强建议"""

    name = "evidence_chain"
    description = "检查主张-事实-证据的闭环，识别缺口与薄弱证据"
    prompt_template = """
## 证据链检查能力

你是一名资深诉讼律师，专门从事证据法与证明责任分析。你的任务是审查案件的主张、事实与证据，识别证据链中的缺口和薄弱点。

### 分析框架
1. 请求权/抗辩要件分解：将每项主张拆解为法律要件。
2. 事实映射：确认哪些事实已被证据覆盖，哪些事实缺乏证据。
3. 证据三性评估：对现有证据的真实性、合法性、关联性打分（0-1）。
4. 缺口诊断：指出缺失证据对胜诉率的影响。

### 输出要求
必须按 JSON schema 输出，包含：
- gaps：证据缺口列表，每项含 claim_id、claim_text、missing_fact、suggested_evidence、win_rate_impact
- weak_evidence：薄弱证据列表，每项含 evidence_id、issue、suggestion
- overall_health：证据链整体健康度（0-1）
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("evidence_chain", "evidence_gap", "check_evidence")

    async def execute(self, agent, context: dict) -> str:
        case_id = context.get("case_id", "")
        ont = ontology_service.get_ontology(case_id)
        if not ont:
            return json.dumps({"error": "Ontology 不存在"}, ensure_ascii=False)

        claims_text = "\n".join(
            f"[{c.id}] {c.claim_text}" for c in ont.claims
        )
        facts_text = "\n".join(
            f"[{f.id}] {f.description}" for f in ont.facts
        )
        evidence_text = "\n".join(
            f"[{e.id}] {e.name} | 三性:{e.authenticity:.1f}/{e.legality:.1f}/{e.relevance:.1f} | 摘要:{e.summary}"
            for e in ont.evidence
        )

        schema = {
            "type": "object",
            "properties": {
                "gaps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_id": {"type": "string"},
                            "claim_text": {"type": "string"},
                            "missing_fact": {"type": "string"},
                            "suggested_evidence": {"type": "string"},
                            "win_rate_impact": {"type": "number"},
                        },
                    },
                },
                "weak_evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "evidence_id": {"type": "string"},
                            "issue": {"type": "string"},
                            "suggestion": {"type": "string"},
                        },
                    },
                },
                "overall_health": {"type": "number"},
            },
            "required": ["gaps", "weak_evidence", "overall_health"],
        }

        task = f"""请对以下案件进行证据链检查。

【诉讼请求/主张】
{claims_text}

【案件事实】
{facts_text}

【现有证据】
{evidence_text}

请输出 JSON 格式的证据链诊断结果。"""

        try:
            result = await self._call_llm_structured(agent, task, schema, temperature=0.2, max_tokens=4096)
        except Exception as e:
            logger.warning(f"EvidenceChainSkill LLM 结构化输出失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        # 写入 Ontology：为每个缺口创建 ActionItem，为薄弱证据追加 weakness
        for gap in result.get("gaps", []):
            title = f"补充证据：{gap.get('suggested_evidence', '未指明证据')}"
            if gap.get("claim_text"):
                title = f"为「{gap['claim_text'][:30]}」补充证据"
            ontology_service.add_action_item(case_id, title, "supplement_evidence", "high")

        for weak in result.get("weak_evidence", []):
            ev_id = weak.get("evidence_id", "")
            issue = weak.get("issue", "")
            for ev in ont.evidence:
                if ev.id == ev_id and issue and issue not in ev.weaknesses:
                    ev.weaknesses.append(issue)
            if issue:
                ontology_service.add_action_item(
                    case_id,
                    f"补强证据三性：{issue[:40]}",
                    "supplement_evidence",
                    "medium",
                )

        ontology_service.update_ontology(ont)
        return json.dumps(result, ensure_ascii=False)


class PleaBargainSkill(Skill):
    """调解/和解策略 Skill：基于案情与类案给出调解区间和筹码"""

    name = "plea_bargain"
    description = "评估调解/和解可行性，输出报价区间与谈判策略"
    prompt_template = """
## 调解与和解策略能力

你是一名擅长庭外和解与调解谈判的律师。你的任务是基于案件事实、证据强度、诉讼请求和类案裁判倾向，给出调解/和解策略建议。

### 分析框架
1. 双方核心利益：原告真正想实现什么？被告的底线可能在哪里？
2. 胜诉概率评估：基于证据链健康度、法律适用清晰度、程序风险。
3. 类案赔偿/履行金额：给出合理区间。
4. 谈判筹码：原告/被告各自可用来施压或让步的要点。
5. 风险提示：调解失败进入判决的风险。

### 输出要求
必须按 JSON schema 输出：
- settlement_range：{min, max, recommended, currency}
- rationale：策略理由
- bargaining_chips：筹码列表
- risks：风险列表
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("plea_bargain", "settlement", "mediation")

    async def execute(self, agent, context: dict) -> str:
        case_id = context.get("case_id", "")
        ont = ontology_service.get_ontology(case_id)
        if not ont:
            return json.dumps({"error": "Ontology 不存在"}, ensure_ascii=False)

        case_summary = f"""案由：{ont.case.title}
诉讼请求：{"；".join(c.claim_text for c in ont.claims)}
案件事实：{"；".join(f.description for f in ont.facts[:5])}
证据数量：{len(ont.evidence)} 项
争议焦点：{"；".join(i.title for i in ont.issues[:3])}
"""

        schema = {
            "type": "object",
            "properties": {
                "settlement_range": {
                    "type": "object",
                    "properties": {
                        "min": {"type": "number"},
                        "max": {"type": "number"},
                        "recommended": {"type": "number"},
                        "currency": {"type": "string"},
                    },
                },
                "rationale": {"type": "string"},
                "bargaining_chips": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["settlement_range", "rationale", "bargaining_chips", "risks"],
        }

        task = f"请对以下案件进行调解/和解策略分析。\n\n{case_summary}\n\n请输出 JSON 格式的调解策略建议。"

        try:
            result = await self._call_llm_structured(agent, task, schema, temperature=0.3, max_tokens=4096)
        except Exception as e:
            logger.warning(f"PleaBargainSkill LLM 结构化输出失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        # 写入 Ontology：创建和解策略 Decision
        sr = result.get("settlement_range", {})
        options = [
            {
                "id": "settle_high",
                "label": f"按较高区间和解（{sr.get('max', 0)}）",
                "pros": "快速回款、避免执行风险",
                "cons": "对方可能拒绝",
            },
            {
                "id": "settle_recommended",
                "label": f"按推荐区间和解（{sr.get('recommended', 0)}）",
                "pros": "平衡效率与收益",
                "cons": "需一定让步",
                "recommended": True,
            },
            {
                "id": "litigate",
                "label": "拒绝调解，继续诉讼",
                "pros": "可能获得全额支持",
                "cons": "时间长、执行风险、诉讼成本",
            },
        ]
        decision = Decision(
            id=f"dec_{uuid.uuid4().hex[:12]}",
            case_id=case_id,
            decision_type="settlement",
            title="调解/和解策略建议",
            options=options,
            rationale=result.get("rationale", ""),
            made_by="ai_suggested",
        )
        ont.decisions.append(decision)
        ontology_service.update_ontology(ont)
        return json.dumps(result, ensure_ascii=False)


class ExecutionRiskSkill(Skill):
    """执行风险评估 Skill：预判判决后能否执行到位"""

    name = "execution_risk"
    description = "评估被告履行能力与执行风险，给出财产保全建议"
    prompt_template = """
## 执行风险评估能力

你是一名擅长执行阶段的律师。你的任务是根据案件材料，预判判决生效后能否实际执行到位，并给出财产保全与执行策略建议。

### 分析框架
1. 被告主体：自然人/企业/组织，是否有偿债能力迹象。
2. 财产线索：案件中是否出现房产、车辆、股权、债权、银行存款等线索。
3. 风险信号：被告是否有转移财产、涉诉较多、失信记录、经营异常等信号。
4. 保全建议：是否应申请财产保全、保全哪些财产、保全时机。

### 输出要求
必须按 JSON schema 输出：
- execution_likelihood：执行到位概率（0-1）
- risk_factors：风险因素列表
- recommended_preservation_measures：财产保全措施列表
- asset_clues：财产线索列表
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("execution_risk", "enforceability", "asset_preservation")

    async def execute(self, agent, context: dict) -> str:
        case_id = context.get("case_id", "")
        ont = ontology_service.get_ontology(case_id)
        if not ont:
            return json.dumps({"error": "Ontology 不存在"}, ensure_ascii=False)

        case_summary = f"""案由：{ont.case.title}
当事人：{"；".join(f"{p.role}:{p.name}" for p in ont.parties)}
诉讼请求：{"；".join(c.claim_text for c in ont.claims)}
案件事实：{"；".join(f.description for f in ont.facts[:8])}
证据：{"；".join(e.name for e in ont.evidence)}
"""

        schema = {
            "type": "object",
            "properties": {
                "execution_likelihood": {"type": "number"},
                "risk_factors": {"type": "array", "items": {"type": "string"}},
                "recommended_preservation_measures": {"type": "array", "items": {"type": "string"}},
                "asset_clues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["execution_likelihood", "risk_factors", "recommended_preservation_measures", "asset_clues"],
        }

        task = f"请对以下案件进行执行风险评估。\n\n{case_summary}\n\n请输出 JSON 格式的执行风险评估。"

        try:
            result = await self._call_llm_structured(agent, task, schema, temperature=0.3, max_tokens=4096)
        except Exception as e:
            logger.warning(f"ExecutionRiskSkill LLM 结构化输出失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        # 写入 Ontology：创建财产保全 ActionItem
        likelihood = _safe_float(result.get("execution_likelihood"), 0.5)
        priority = "high" if likelihood < 0.5 else "medium"
        for measure in result.get("recommended_preservation_measures", []):
            ontology_service.add_action_item(
                case_id,
                f"财产保全：{measure[:50]}",
                "filing",
                priority,
            )
        for clue in result.get("asset_clues", []):
            ontology_service.add_action_item(
                case_id,
                f"调查财产线索：{clue[:50]}",
                "legal_research",
                "medium",
            )

        return json.dumps(result, ensure_ascii=False)


class JudgeQuestionSkill(Skill):
    """法官追问预测 Skill：基于争议焦点与证据预测庭审中法官可能的问题"""

    name = "judge_questions"
    description = "预测庭审中法官可能追问的问题，帮助律师庭前准备"
    prompt_template = """
## 法官追问预测能力

你是一名资深法官/审判长。基于案件事实、证据、争议焦点和双方主张，预测庭审中你可能向双方律师或当事人提出的追问。

### 分析框架
1. 围绕争议焦点：每个焦点下，事实不清或证据不足处最可能被追问。
2. 证据矛盾：双方证据冲突之处，法官会要求解释。
3. 法律适用：请求权基础是否成立，法官会追问构成要件。
4. 程序问题：管辖、主体、时效、送达等。

### 输出要求
必须按 JSON schema 输出：
- questions：问题列表，每项含 question（问题文本）、target_party（提问对象：plaintiff/defendant/both）、related_issue（关联焦点）、suggested_answer（建议回答方向）
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("judge_questions", "predict_judge_questions", "court_questions")

    async def execute(self, agent, context: dict) -> str:
        case_id = context.get("case_id", "")
        ont = ontology_service.get_ontology(case_id)
        if not ont:
            return json.dumps({"error": "Ontology 不存在"}, ensure_ascii=False)

        case_summary = f"""案由：{ont.case.title}
诉讼请求：{"；".join(c.claim_text for c in ont.claims)}
案件事实：{"；".join(f.description for f in ont.facts[:8])}
证据：{"；".join(e.name for e in ont.evidence)}
争议焦点：{"；".join(i.title for i in ont.issues)}
"""

        schema = {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "target_party": {"type": "string"},
                            "related_issue": {"type": "string"},
                            "suggested_answer": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["questions"],
        }

        task = f"请预测以下案件庭审中法官可能追问的问题。\n\n{case_summary}\n\n请输出 JSON 格式。"

        try:
            result = await self._call_llm_structured(agent, task, schema, temperature=0.3, max_tokens=4096)
        except Exception as e:
            logger.warning(f"JudgeQuestionSkill LLM 结构化输出失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        # 写入 Ontology：为每个问题创建一个庭前准备 ActionItem
        for q in result.get("questions", []):
            ontology_service.add_action_item(
                case_id,
                f"准备法官追问：{q.get('question', '')[:40]}",
                "witness" if q.get("target_party") in ["plaintiff", "defendant"] else "other",
                "high",
            )

        return json.dumps(result, ensure_ascii=False)


# 兼容：旧导入路径可直接从本模块获取
__all__ = ["EvidenceChainSkill", "PleaBargainSkill", "ExecutionRiskSkill", "JudgeQuestionSkill"]
