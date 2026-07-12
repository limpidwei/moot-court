"""
Agentic 执行器 API

Codex 式 Agentic 工作流 + Human-in-the-Loop 审批门。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import get_current_user
from ..models.database import User
from ..ontology import service as ontology_service
from ..agentic import service as proposal_service
from ..agentic.executor import AgenticExecutor, get_executor

router = APIRouter(prefix="/agent", tags=["agentic"])


class RunRequest(BaseModel):
    task: str


class ApproveRequest(BaseModel):
    rationale: str = ""


class RejectRequest(BaseModel):
    rationale: str = ""


def _get_session_or_404(case_id: str, current_user: User):
    from .. import main as main_module
    if case_id not in main_module.sessions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="案件不存在或无权访问")
    session = main_module.sessions[case_id]
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="案件不存在或无权访问")
    return session


@router.post("/{case_id}/run")
async def agent_run(
    case_id: str,
    req: RunRequest,
    current_user: User = Depends(get_current_user),
):
    """提交任务，AI 生成 Proposal 列表（待律师审批）"""
    session = _get_session_or_404(case_id, current_user)
    executor = get_executor(session.llm_config)
    proposals = executor.plan(case_id, req.task)
    return {
        "case_id": case_id,
        "task": req.task,
        "proposals": [p.to_dict() for p in proposals],
    }


@router.get("/{case_id}/proposals")
async def list_proposals(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_session_or_404(case_id, current_user)
    proposals = proposal_service.list_proposals(case_id)
    return {"items": [p.to_dict() for p in proposals]}


@router.post("/{case_id}/proposals/{proposal_id}/approve")
async def approve_proposal(
    case_id: str,
    proposal_id: str,
    req: ApproveRequest,
    current_user: User = Depends(get_current_user),
):
    """律师审批通过，执行 Proposal"""
    session = _get_session_or_404(case_id, current_user)
    proposal = proposal_service.get_proposal(case_id, proposal_id)
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提案不存在")
    if proposal.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提案已处理")

    executor = get_executor(session.llm_config)
    result = await executor.execute(proposal)

    return {
        "proposal_id": proposal_id,
        "status": "executed",
        "result": result,
    }


@router.post("/{case_id}/proposals/{proposal_id}/reject")
async def reject_proposal(
    case_id: str,
    proposal_id: str,
    req: RejectRequest,
    current_user: User = Depends(get_current_user),
):
    """律师驳回 Proposal"""
    _get_session_or_404(case_id, current_user)
    proposal = proposal_service.get_proposal(case_id, proposal_id)
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提案不存在")
    if proposal.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提案已处理")

    proposal_service.update_proposal_status(case_id, proposal_id, "rejected", result={"rationale": req.rationale})
    return {"proposal_id": proposal_id, "status": "rejected"}


# ============================================================
# 杀手场景直接 API（也走 Agentic 审批门）
# ============================================================

@router.post("/{case_id}/analysis/evidence-chain")
async def analyze_evidence_chain(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    """证据链缺口诊断"""
    return await agent_run(case_id, RunRequest(task="证据链缺口诊断"), current_user)


@router.post("/{case_id}/analysis/plea-bargain")
async def analyze_plea_bargain(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    """调解/和解策略与报价建议"""
    return await agent_run(case_id, RunRequest(task="调解报价策略"), current_user)


@router.post("/{case_id}/analysis/execution-risk")
async def analyze_execution_risk(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    """执行风险评估与财产保全建议"""
    return await agent_run(case_id, RunRequest(task="执行风险评估"), current_user)


@router.post("/{case_id}/analysis/judge-questions")
async def analyze_judge_questions(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    """法官可能追问预测"""
    return await agent_run(case_id, RunRequest(task="预测法官可能追问的问题"), current_user)
