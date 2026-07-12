"""
Case Ontology 服务层

提供 Ontology 的构建、缓存、查询与更新。
首期采用内存缓存 + JSON 文件持久化，与现有 sessions.json 同目录，
避免引入新数据库表的迁移成本；后续可迁移到 PostgreSQL。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from ..models.case import CaseInput
from ..orchestration.workflow import TrialSession
from .extractor import build_ontology, build_ontology_from_case_input, _uid
from .models import CaseOntology, Decision, ActionItem

logger = logging.getLogger(__name__)

# 内存缓存：case_id -> CaseOntology
_ontology_cache: dict[str, CaseOntology] = {}
_lock = threading.Lock()


def _ontology_path(case_id: str) -> Path:
    """Ontology 文件路径：data/ontologies/{case_id}.json"""
    root = Path("data/ontologies")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{case_id}.json"


def _save_ontology_to_disk(ontology: CaseOntology) -> None:
    path = _ontology_path(ontology.case.id)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ontology.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_ontology_from_disk(case_id: str) -> Optional[CaseOntology]:
    path = _ontology_path(case_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return CaseOntology.from_dict(data)
    except Exception as e:
        logger.warning(f"加载 Ontology 失败 {case_id}: {e}")
        return None


def get_ontology(case_id: str) -> Optional[CaseOntology]:
    """优先读内存缓存，其次磁盘"""
    with _lock:
        if case_id in _ontology_cache:
            return _ontology_cache[case_id]
    ont = _load_ontology_from_disk(case_id)
    if ont:
        with _lock:
            _ontology_cache[case_id] = ont
    return ont


def build_and_save_ontology(session: TrialSession) -> CaseOntology:
    """从 TrialSession 构建并持久化 Ontology"""
    ontology = build_ontology(session)
    with _lock:
        _ontology_cache[ontology.case.id] = ontology
    _save_ontology_to_disk(ontology)
    return ontology


def build_and_save_from_case_input(case: CaseInput) -> CaseOntology:
    """从 CaseInput 构建基础 Ontology 并持久化"""
    ontology = build_ontology_from_case_input(case)
    with _lock:
        _ontology_cache[ontology.case.id] = ontology
    _save_ontology_to_disk(ontology)
    return ontology


def update_ontology(ontology: CaseOntology) -> None:
    """更新并持久化 Ontology"""
    with _lock:
        _ontology_cache[ontology.case.id] = ontology
    _save_ontology_to_disk(ontology)


def delete_ontology(case_id: str) -> None:
    """删除 Ontology 缓存与文件"""
    with _lock:
        _ontology_cache.pop(case_id, None)
    path = _ontology_path(case_id)
    if path.exists():
        try:
            path.unlink()
        except Exception as e:
            logger.warning(f"删除 Ontology 文件失败 {case_id}: {e}")


def record_decision(
    case_id: str,
    decision_id: str,
    selected_option_id: str,
    rationale: str = "",
    made_by: str = "user",
) -> Optional[Decision]:
    """记录律师对某个决策的选择"""
    ont = get_ontology(case_id)
    if not ont:
        return None
    for d in ont.decisions:
        if d.id == decision_id:
            d.selected_option_id = selected_option_id
            d.rationale = rationale or d.rationale
            d.made_by = made_by  # type: ignore[assignment]
            update_ontology(ont)
            return d
    return None


def update_action_item(
    case_id: str,
    action_id: str,
    status: str,
) -> Optional[ActionItem]:
    """更新行动项状态"""
    ont = get_ontology(case_id)
    if not ont:
        return None
    for a in ont.action_items:
        if a.id == action_id:
            a.status = status  # type: ignore[assignment]
            update_ontology(ont)
            return a
    return None


def add_action_item(
    case_id: str,
    title: str,
    action_type: str = "other",
    priority: str = "medium",
    source_decision_id: Optional[str] = None,
) -> Optional[ActionItem]:
    """向指定案件的 Ontology 添加行动项"""
    ont = get_ontology(case_id)
    if not ont:
        return None
    action = ActionItem(
        id=_uid("act_"),
        case_id=case_id,
        title=title,
        action_type=action_type,  # type: ignore[arg-type]
        priority=priority,  # type: ignore[arg-type]
        source_decision_id=source_decision_id,
    )
    ont.action_items.append(action)
    update_ontology(ont)
    return action


def get_dashboard_summary(case_id: str) -> Optional[dict]:
    """获取工作台 Dashboard 所需汇总数据"""
    ont = get_ontology(case_id)
    if not ont:
        return None

    open_issues = [i for i in ont.issues if i.status == "open"]
    disputed_facts = [f for f in ont.facts if f.is_disputed]
    weak_evidence = [e for e in ont.evidence if e.authenticity < 0.5 or e.legality < 0.5 or e.relevance < 0.5]
    open_actions = [a for a in ont.action_items if a.status == "open"]
    pending_decisions = [d for d in ont.decisions if d.selected_option_id is None]

    # 证据链健康度：有证据支持的关键事实比例（简化）
    covered_facts = sum(1 for f in ont.facts if f.evidence_ids)
    fact_health = round(covered_facts / max(len(ont.facts), 1), 2)

    return {
        "case": {
            "id": ont.case.id,
            "title": ont.case.title,
            "case_type": ont.case.case_type,
            "mode": ont.case.mode,
            "status": ont.case.status,
        },
        "parties": [{"role": p.role, "name": p.name} for p in ont.parties],
        "stats": {
            "claims_count": len(ont.claims),
            "facts_count": len(ont.facts),
            "evidence_count": len(ont.evidence),
            "issues_count": len(ont.issues),
            "open_issues_count": len(open_issues),
            "disputed_facts_count": len(disputed_facts),
            "weak_evidence_count": len(weak_evidence),
            "open_actions_count": len(open_actions),
            "pending_decisions_count": len(pending_decisions),
            "fact_health": fact_health,
        },
        "top_issues": [
            {"id": i.id, "title": i.title, "priority": i.priority, "status": i.status}
            for i in sorted(ont.issues, key=lambda x: x.priority, reverse=True)[:3]
        ],
        "top_actions": [
            {"id": a.id, "title": a.title, "priority": a.priority}
            for a in sorted(open_actions, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.priority, 3))[:5]
        ],
        "pending_decisions": [
            {"id": d.id, "title": d.title, "decision_type": d.decision_type}
            for d in pending_decisions[:3]
        ],
    }
