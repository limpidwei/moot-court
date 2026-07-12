"""
Ontology API Router

提供案件本体（Case Ontology）的读取、构建与决策/行动项更新。
所有端点均需登录。
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import get_current_user
from ..models.database import User
from ..orchestration.workflow import TrialSession
from ..ontology import service as ontology_service
from ..ontology.models import CaseOntology

router = APIRouter(prefix="/ontology", tags=["ontology"])


class DecisionUpdateRequest(BaseModel):
    selected_option_id: str
    rationale: str = ""


class ActionItemUpdateRequest(BaseModel):
    status: str


def _get_session_or_404(case_id: str, current_user: User) -> TrialSession:
    """校验当前用户对指定 case_id 的 session 有访问权限（延迟导入避免循环依赖）"""
    from .. import main as main_module
    if case_id not in main_module.sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在或无权访问",
        )
    session = main_module.sessions[case_id]
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在或无权访问",
        )
    return session


@router.get("/{case_id}")
async def get_ontology(case_id: str, current_user: User = Depends(get_current_user)):
    """获取完整案件本体"""
    _get_session_or_404(case_id, current_user)
    ont = ontology_service.get_ontology(case_id)
    if not ont:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ontology 不存在，请先提取")
    return ont.to_dict()


@router.post("/{case_id}/extract")
async def extract_ontology(case_id: str, current_user: User = Depends(get_current_user)):
    """从当前 TrialSession 重新提取/更新 Ontology"""
    session = _get_session_or_404(case_id, current_user)
    ontology = ontology_service.build_and_save_ontology(session)
    return ontology.to_dict()


@router.get("/{case_id}/dashboard")
async def get_dashboard(case_id: str, current_user: User = Depends(get_current_user)):
    """获取工作台 Dashboard 汇总"""
    _get_session_or_404(case_id, current_user)
    summary = ontology_service.get_dashboard_summary(case_id)
    if not summary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ontology 不存在，请先提取")
    return summary


@router.get("/{case_id}/issues")
async def get_issues(case_id: str, current_user: User = Depends(get_current_user)):
    _get_session_or_404(case_id, current_user)
    ont = ontology_service.get_ontology(case_id)
    if not ont:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ontology 不存在")
    return {"items": [i.__dict__ for i in ont.issues]}


@router.get("/{case_id}/evidence-chain")
async def get_evidence_chain(case_id: str, current_user: User = Depends(get_current_user)):
    _get_session_or_404(case_id, current_user)
    ont = ontology_service.get_ontology(case_id)
    if not ont:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ontology 不存在")
    return {
        "facts": [f.__dict__ for f in ont.facts],
        "evidence": [e.__dict__ for e in ont.evidence],
        "claims": [c.__dict__ for c in ont.claims],
    }


@router.get("/{case_id}/legal-basis")
async def get_legal_basis(case_id: str, current_user: User = Depends(get_current_user)):
    _get_session_or_404(case_id, current_user)
    ont = ontology_service.get_ontology(case_id)
    if not ont:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ontology 不存在")
    return {
        "legal_norms": [ln.__dict__ for ln in ont.legal_norms],
        "precedents": [p.__dict__ for p in ont.precedents],
    }


@router.get("/{case_id}/decisions")
async def get_decisions(case_id: str, current_user: User = Depends(get_current_user)):
    _get_session_or_404(case_id, current_user)
    ont = ontology_service.get_ontology(case_id)
    if not ont:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ontology 不存在")
    return {"items": [d.__dict__ for d in ont.decisions]}


@router.post("/{case_id}/decisions/{decision_id}")
async def update_decision(
    case_id: str,
    decision_id: str,
    req: DecisionUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    _get_session_or_404(case_id, current_user)
    updated = ontology_service.record_decision(
        case_id=case_id,
        decision_id=decision_id,
        selected_option_id=req.selected_option_id,
        rationale=req.rationale,
        made_by="user",
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="决策不存在")
    return updated.__dict__


@router.get("/{case_id}/action-items")
async def get_action_items(case_id: str, current_user: User = Depends(get_current_user)):
    _get_session_or_404(case_id, current_user)
    ont = ontology_service.get_ontology(case_id)
    if not ont:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ontology 不存在")
    return {"items": [a.__dict__ for a in ont.action_items]}


@router.post("/{case_id}/action-items/{action_id}")
async def update_action_item(
    case_id: str,
    action_id: str,
    req: ActionItemUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    _get_session_or_404(case_id, current_user)
    updated = ontology_service.update_action_item(case_id, action_id, req.status)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="行动项不存在")
    return updated.__dict__
