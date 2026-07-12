"""
Agentic 执行器服务层

管理 Proposal 的生命周期：创建、查询、审批、执行。
执行结果写入 Ontology，实现 Codex 式 Agentic 工作流 + Human-in-the-Loop。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Optional

from .models import Proposal
from ..ontology import service as ontology_service
from ..ontology.models import CaseOntology

logger = logging.getLogger(__name__)

# 内存提案库：case_id -> list[Proposal]
_proposal_db: dict[str, list[Proposal]] = {}
_lock = threading.Lock()


def _uid() -> str:
    return f"prop_{uuid.uuid4().hex[:12]}"


def list_proposals(case_id: str) -> list[Proposal]:
    with _lock:
        return list(_proposal_db.get(case_id, []))


def get_proposal(case_id: str, proposal_id: str) -> Optional[Proposal]:
    with _lock:
        for p in _proposal_db.get(case_id, []):
            if p.id == proposal_id:
                return p
    return None


def create_proposal(
    case_id: str,
    task: str,
    action_type: str,
    skill_name: str = "",
    params: Optional[dict] = None,
    rationale: str = "",
    created_by: str = "ai",
) -> Proposal:
    prop = Proposal(
        id=_uid(),
        case_id=case_id,
        task=task,
        action_type=action_type,  # type: ignore[arg-type]
        skill_name=skill_name,
        params=params or {},
        rationale=rationale,
        created_by=created_by,  # type: ignore[arg-type]
    )
    with _lock:
        _proposal_db.setdefault(case_id, []).append(prop)
    return prop


def update_proposal_status(
    case_id: str,
    proposal_id: str,
    status: str,
    result: Optional[dict] = None,
) -> Optional[Proposal]:
    with _lock:
        for p in _proposal_db.get(case_id, []):
            if p.id == proposal_id:
                p.status = status  # type: ignore[assignment]
                if result is not None:
                    p.result = result
                return p
    return None


def delete_proposals_by_case(case_id: str) -> None:
    with _lock:
        _proposal_db.pop(case_id, None)
