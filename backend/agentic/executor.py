"""
Agentic Executor

Codex 式执行器：理解任务 → 生成 Proposal → 经律师审批后调用 Skill → 写入 Ontology。
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from .models import Proposal
from . import service as proposal_service
from ..agents.v2.base import BaseAgentV2
from ..agents.v2.skill import ALL_SKILLS
from ..llm import LLMConfig

logger = logging.getLogger(__name__)


def _build_analyst_agent(llm_config: Optional[LLMConfig] = None) -> BaseAgentV2:
    """创建通用分析 Agent，注册所有扩展 Skill"""
    from ..agents.v2.extended_skills import (
        EvidenceChainSkill,
        PleaBargainSkill,
        ExecutionRiskSkill,
        JudgeQuestionSkill,
    )

    agent = BaseAgentV2(
        name="analyst",
        system_prompt="你是一名资深法律分析师，擅长使用专业工具分析案件。",
        llm_config=llm_config,
    )
    agent.register_skill(EvidenceChainSkill())
    agent.register_skill(PleaBargainSkill())
    agent.register_skill(ExecutionRiskSkill())
    agent.register_skill(JudgeQuestionSkill())
    return agent


class AgenticExecutor:
    """Agentic 执行器"""

    def __init__(self, llm_config: Optional[LLMConfig] = None):
        self.agent = _build_analyst_agent(llm_config)

    def plan(self, case_id: str, task: str) -> list[Proposal]:
        """根据自然语言任务生成 Proposal 列表（规则映射版）"""
        task_lower = task.lower()

        proposals = []

        if any(k in task_lower for k in ["证据链", "证据缺口", "缺什么证据", "evidence_chain", "evidence gap"]):
            proposals.append(proposal_service.create_proposal(
                case_id=case_id,
                task=task,
                action_type="call_skill",
                skill_name="evidence_chain",
                params={"case_id": case_id},
                rationale="识别证据链缺口与薄弱证据，为律师提供补强建议。",
            ))

        if any(k in task_lower for k in ["调解", "和解", "报价", "settlement", "plea", "bargain"]):
            proposals.append(proposal_service.create_proposal(
                case_id=case_id,
                task=task,
                action_type="call_skill",
                skill_name="plea_bargain",
                params={"case_id": case_id},
                rationale="评估调解可行性，给出合理报价区间与谈判筹码。",
            ))

        if any(k in task_lower for k in ["执行风险", "执行", "财产保全", "execution", "enforce"]):
            proposals.append(proposal_service.create_proposal(
                case_id=case_id,
                task=task,
                action_type="call_skill",
                skill_name="execution_risk",
                params={"case_id": case_id},
                rationale="预判判决执行难度，给出财产保全建议。",
            ))

        if any(k in task_lower for k in ["法官", "追问", "庭审问题", "judge", "question"]):
            proposals.append(proposal_service.create_proposal(
                case_id=case_id,
                task=task,
                action_type="call_skill",
                skill_name="judge_questions",
                params={"case_id": case_id},
                rationale="预测法官在庭审中可能追问的问题，帮助律师庭前准备。",
            ))

        if not proposals:
            # 默认：证据链检查
            proposals.append(proposal_service.create_proposal(
                case_id=case_id,
                task=task,
                action_type="call_skill",
                skill_name="evidence_chain",
                params={"case_id": case_id},
                rationale="任务未明确匹配到具体 Skill，默认执行证据链检查。",
            ))

        return proposals

    async def execute(self, proposal: Proposal) -> dict:
        """执行单个 Proposal"""
        if proposal.action_type == "call_skill":
            return await self._execute_skill(proposal)
        return {"error": f"不支持的 action_type: {proposal.action_type}"}

    async def _execute_skill(self, proposal: Proposal) -> dict:
        skill_name = proposal.skill_name
        try:
            result_text = await self.agent.think_with_skill(skill_name, proposal.params)
            try:
                result = json.loads(result_text)
            except json.JSONDecodeError:
                result = {"raw": result_text}
            proposal_service.update_proposal_status(
                proposal.case_id,
                proposal.id,
                "executed",
                result=result,
            )
            return result
        except Exception as e:
            logger.error(f"Agentic 执行失败 proposal={proposal.id}: {e}")
            proposal_service.update_proposal_status(
                proposal.case_id,
                proposal.id,
                "failed",
                result={"error": str(e)},
            )
            return {"error": str(e)}


# 全局执行器实例（无状态，可复用）
_default_executor: Optional[AgenticExecutor] = None


def get_executor(llm_config: Optional[LLMConfig] = None) -> AgenticExecutor:
    """获取或创建默认 AgenticExecutor"""
    global _default_executor
    if _default_executor is None:
        _default_executor = AgenticExecutor(llm_config)
    return _default_executor
