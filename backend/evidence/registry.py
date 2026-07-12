"""
证据登记簿管理（增强版）

管理 EvidenceRegistry 的 CRUD 操作，
以及与其他模块的数据交换。

增强内容：
- 持久化到数据库
- AI 分析与冲突检测
- 与庭审系统对接
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .schemas import EvidenceRegistry, EvidenceItem, TimelineEvent, PartyRelation, ConflictReport
from .persistence import (
    load_registry_from_db,
    save_registry_to_db,
    save_conflict_reports_to_db,
    delete_evidence_from_db,
    delete_file,
)
from .ai_enrichment import analyze_evidence, detect_conflicts, extract_timeline

logger = logging.getLogger(__name__)

# 内存缓存（加速读取）
_registries: dict[str, EvidenceRegistry] = {}


def get_registry(case_id: str, db: Optional[Session] = None) -> EvidenceRegistry:
    """获取指定案件的证据登记簿（优先内存缓存）"""
    if case_id in _registries:
        return _registries[case_id]

    if db:
        registry = load_registry_from_db(case_id, db)
        _registries[case_id] = registry
        return registry

    # 无数据库时创建空登记簿
    registry = EvidenceRegistry(case_id=case_id)
    _registries[case_id] = registry
    return registry


def save_registry(registry: EvidenceRegistry, user_id: int, db: Optional[Session] = None) -> None:
    """保存证据登记簿"""
    _registries[registry.case_id] = registry
    if db:
        save_registry_to_db(registry, user_id, db)


def delete_registry(case_id: str, db: Optional[Session] = None) -> None:
    """删除指定案件的证据登记簿"""
    _registries.pop(case_id, None)
    if db:
        # 删除数据库中的证据记录和冲突报告
        from backend.models.database import EvidenceItemModel, ConflictReportModel
        db.query(EvidenceItemModel).filter(EvidenceItemModel.case_id == case_id).delete()
        db.query(ConflictReportModel).filter(ConflictReportModel.case_id == case_id).delete()
        db.commit()


def add_evidence_item(
    case_id: str,
    item: EvidenceItem,
    user_id: int,
    db: Optional[Session] = None,
) -> None:
    """向登记簿添加一条证据"""
    registry = get_registry(case_id, db)
    registry.items.append(item)
    save_registry(registry, user_id, db)


def delete_evidence_item(
    case_id: str,
    evidence_id: str,
    db: Optional[Session] = None,
) -> bool:
    """删除单条证据，返回是否成功"""
    registry = get_registry(case_id, db)
    original_len = len(registry.items)
    registry.items = [it for it in registry.items if it.id != evidence_id]

    if len(registry.items) < original_len:
        # 同时删除关联的冲突报告
        registry.conflicts = [
            c for c in registry.conflicts
            if evidence_id not in c.involved_evidence_ids
        ]
        save_registry(registry, 0, db)

        # 删除文件和数据库记录
        if db:
            storage_path = delete_evidence_from_db(evidence_id, db)
            if storage_path:
                delete_file(storage_path)
        return True

    return False


# ============================================================
# AI 分析
# ============================================================

async def analyze_all_evidence(case_id: str, user_id: int, db: Optional[Session] = None) -> EvidenceRegistry:
    """
    对案件中所有未分析的证据进行 AI 分析
    """
    registry = get_registry(case_id, db)

    pending_items = [it for it in registry.items if it.status in ("pending", "extracting")]
    if not pending_items:
        logger.info(f"案件 {case_id} 没有待分析的证据")
        return registry

    logger.info(f"开始分析案件 {case_id} 的 {len(pending_items)} 条证据")

    for item in pending_items:
        item.status = "analyzing"
        try:
            await analyze_evidence(item)
        except Exception as e:
            logger.error(f"分析证据 {item.id} 失败: {e}")
            item.status = "failed"
            item.error_message = str(e)

    save_registry(registry, user_id, db)
    logger.info(f"案件 {case_id} 证据分析完成")
    return registry


async def analyze_conflicts(case_id: str, user_id: int, db: Optional[Session] = None) -> EvidenceRegistry:
    """
    对案件中的所有证据进行冲突检测
    """
    registry = get_registry(case_id, db)

    conflicts = await detect_conflicts(registry.items)
    for conflict in conflicts:
        conflict.case_id = case_id

    registry.conflicts = conflicts

    # 同时提取时间线
    timeline = await extract_timeline(registry.items)
    registry.timeline = timeline

    save_registry(registry, user_id, db)
    if db:
        save_conflict_reports_to_db(registry, user_id, db)

    logger.info(f"案件 {case_id} 冲突检测完成，发现 {len(conflicts)} 个冲突")
    return registry


# ============================================================
# 与庭审系统对接
# ============================================================

def import_to_trial_session(case_id: str, session) -> dict:
    """
    将证据登记簿导入庭审系统的 case_input 格式

    Args:
        case_id: 案件 ID
        session: TrialSession 对象

    Returns:
        {"evidence_text": "...", "evidence_catalog": "...", "item_count": N}
    """
    registry = get_registry(case_id)

    # 生成证据文本（用于 case_input.evidence）
    evidence_lines = []
    for item in registry.items:
        if item.status == "completed":
            line = f"【{item.evidence_type or '证据'}】{item.source_file}"
            if item.summary:
                line += f"：{item.summary}"
            evidence_lines.append(line)

    evidence_text = "\n".join(evidence_lines)

    # 生成证据目录（用于 phase2/phase4）
    catalog_lines = []
    for idx, item in enumerate(registry.items, 1):
        if item.status == "completed":
            catalog_lines.append(
                f"{idx}. {item.source_file} ({item.evidence_type or '未分类'})\n"
                f"   内容摘要：{item.summary or item.content[:100]}"
            )

    evidence_catalog = "\n\n".join(catalog_lines)

    # 写入 session（如果 session 对象提供了这些字段）
    if hasattr(session, "evidence"):
        session.evidence = evidence_text
    if hasattr(session, "phase2_evidence_catalog"):
        session.phase2_evidence_catalog = evidence_catalog
    if hasattr(session, "phase4_evidence_catalog"):
        session.phase4_evidence_catalog = evidence_catalog

    return {
        "evidence_text": evidence_text,
        "evidence_catalog": evidence_catalog,
        "item_count": len([it for it in registry.items if it.status == "completed"]),
    }


