"""
证据持久化层

职责：
- 文件存储管理（保存上传文件到磁盘）
- ORM 与 dataclass 之间的转换
- EvidenceRegistry 的加载和保存
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.database import EvidenceItemModel, ConflictReportModel
from .schemas import EvidenceItem, ConflictReport, ClaimDetail, EvidenceRegistry

# 上传文件存储根目录
UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "uploads")
# 真实的绝对根路径，用于边界校验（解析符号链接与 ".."）
_UPLOAD_ROOT_REAL = os.path.realpath(UPLOAD_ROOT)

# case_id 合法字符：创建时用 uuid.uuid4().hex[:12]，禁止任何路径分隔符与 ".."
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


class PathTraversalError(ValueError):
    """文件路径越界（试图逃出 UPLOAD_ROOT）或 case_id 非法时抛出"""


def _validate_case_id(case_id: str) -> str:
    """校验 case_id 仅含安全字符，杜绝 `../` / 绝对路径注入。"""
    if not case_id or not _CASE_ID_RE.match(case_id):
        raise PathTraversalError(f"非法 case_id: {case_id!r}")
    return case_id


def _safe_abs_under_root(storage_path: str) -> str:
    """
    把相对 UPLOAD_ROOT 的 storage_path 解析为绝对路径，并确保仍在 UPLOAD_ROOT 内。
    storage_path 内部允许子目录（如 ZIP 解压后的相对路径），但绝不允许逃逸到根之外。
    """
    # 显式拒绝绝对路径与 Windows 盘符
    if os.path.isabs(storage_path) or re.match(r"^[A-Za-z]:", storage_path):
        raise PathTraversalError(f"非法 storage_path（绝对路径）: {storage_path!r}")
    abs_path = os.path.realpath(os.path.join(UPLOAD_ROOT, storage_path))
    # 必须是 UPLOAD_ROOT 本身或其子目录
    if abs_path != _UPLOAD_ROOT_REAL and not abs_path.startswith(_UPLOAD_ROOT_REAL + os.sep):
        raise PathTraversalError(f"storage_path 越界: {storage_path!r} -> {abs_path}")
    return abs_path


def get_case_upload_dir(case_id: str) -> str:
    """获取某个案件的上传目录"""
    _validate_case_id(case_id)
    path = os.path.join(UPLOAD_ROOT, case_id)
    _ensure_dir(path)
    return path


def save_uploaded_file(case_id: str, filename: str, file_content: bytes) -> str:
    """
    保存上传的文件到磁盘

    Returns:
        storage_path: 相对于 UPLOAD_ROOT 的路径，如 "abc123/借条.pdf"
    """
    case_dir = get_case_upload_dir(case_id)
    # 安全：仅取文件名 basename，丢弃任何目录成分，防止 `../` 注入
    safe_name = os.path.basename(filename) or "unnamed"
    if safe_name in ("", ".", ".."):
        safe_name = "unnamed"
    # 处理重名：追加数字
    base, ext = os.path.splitext(safe_name)
    dest = os.path.join(case_dir, safe_name)
    counter = 1
    while os.path.exists(dest):
        dest = os.path.join(case_dir, f"{base}_{counter}{ext}")
        counter += 1

    # 写入前再次校验目标路径仍在 case_dir 内（防御 symlink / 边界）
    dest_real = os.path.realpath(dest)
    case_dir_real = os.path.realpath(case_dir)
    if dest_real != case_dir_real and not dest_real.startswith(case_dir_real + os.sep):
        raise PathTraversalError(f"目标文件路径越界: {dest!r}")

    with open(dest, "wb") as f:
        f.write(file_content)

    # 返回相对路径
    return os.path.relpath(dest, UPLOAD_ROOT)


def delete_file(storage_path: str) -> None:
    """删除磁盘上的文件"""
    abs_path = _safe_abs_under_root(storage_path)
    if os.path.exists(abs_path) and os.path.isfile(abs_path):
        os.remove(abs_path)


def read_file(storage_path: str) -> bytes:
    """读取文件内容"""
    abs_path = _safe_abs_under_root(storage_path)
    with open(abs_path, "rb") as f:
        return f.read()


def get_file_path(storage_path: str) -> str:
    """获取文件的绝对路径"""
    return _safe_abs_under_root(storage_path)


# ============================================================
# ORM <-> Dataclass 转换
# ============================================================

def evidence_item_to_model(item: EvidenceItem, user_id: int) -> EvidenceItemModel:
    """将 EvidenceItem dataclass 转为 ORM 模型（用于新建）"""
    return EvidenceItemModel(
        id=item.id,
        case_id="",  # 由调用方填充或通过关联设置
        user_id=user_id,
        filename=item.source_file,
        storage_path=item.storage_path,
        source_type=item.source_type,
        mime_type=item.mime_type,
        file_size=item.file_size,
        evidence_type=item.evidence_type,
        party=item.party,
        content=item.content,
        summary=item.summary,
        extracted_date=item.date,
        parties=item.parties,
        relevance=item.relevance,
        confidence=item.confidence,
        status=item.status,
        error_message=item.error_message,
        raw_metadata=item.raw_metadata,
    )


def evidence_item_from_model(model: EvidenceItemModel) -> EvidenceItem:
    """将 ORM 模型转为 EvidenceItem dataclass"""
    return EvidenceItem(
        id=model.id,
        source_file=model.filename,
        source_type=model.source_type,
        content=model.content or "",
        summary=model.summary or "",
        date=model.extracted_date,
        parties=model.parties or [],
        evidence_type=model.evidence_type or "",
        relevance=model.relevance or [],
        confidence=model.confidence or 1.0,
        raw_metadata=model.raw_metadata or {},
        status=model.status,
        file_size=model.file_size or 0,
        mime_type=model.mime_type or "",
        storage_path=model.storage_path or "",
        party=model.party or "unknown",
        error_message=model.error_message or "",
        created_at=model.created_at.isoformat() if model.created_at else "",
    )


def conflict_report_to_model(report: ConflictReport, user_id: int) -> ConflictReportModel:
    return ConflictReportModel(
        id=report.id,
        case_id=report.case_id,
        user_id=user_id,
        conflict_type=report.conflict_type,
        severity=report.severity,
        description=report.description,
        involved_evidence_ids=report.involved_evidence_ids,
        involved_parties=report.involved_parties,
        claims=[
            {
                "evidence_id": c.evidence_id,
                "party": c.party,
                "original_text": c.original_text,
                "extracted_claim": c.extracted_claim,
            }
            for c in report.claims
        ],
        ai_note=report.ai_note,
        resolved=report.resolved,
        lawyer_note=report.lawyer_note,
    )


def conflict_report_from_model(model: ConflictReportModel) -> ConflictReport:
    return ConflictReport(
        id=model.id,
        case_id=model.case_id,
        conflict_type=model.conflict_type,
        severity=model.severity,
        description=model.description,
        involved_evidence_ids=model.involved_evidence_ids or [],
        involved_parties=model.involved_parties or [],
        claims=[
            ClaimDetail(
                evidence_id=c["evidence_id"],
                party=c.get("party", "unknown"),
                original_text=c.get("original_text", ""),
                extracted_claim=c.get("extracted_claim", ""),
            )
            for c in (model.claims or [])
        ],
        ai_note=model.ai_note or "",
        resolved=model.resolved or False,
        lawyer_note=model.lawyer_note or "",
        created_at=model.created_at.isoformat() if model.created_at else "",
    )


# ============================================================
# Registry 持久化（数据库读写）
# ============================================================

def load_registry_from_db(case_id: str, db: Session) -> EvidenceRegistry:
    """从数据库加载 EvidenceRegistry"""
    registry = EvidenceRegistry(case_id=case_id)

    items = db.query(EvidenceItemModel).filter(EvidenceItemModel.case_id == case_id).all()
    registry.items = [evidence_item_from_model(m) for m in items]

    conflicts = db.query(ConflictReportModel).filter(ConflictReportModel.case_id == case_id).all()
    registry.conflicts = [conflict_report_from_model(m) for m in conflicts]

    return registry


def save_registry_to_db(registry: EvidenceRegistry, user_id: int, db: Session) -> None:
    """将 EvidenceRegistry 写入数据库（增量更新：不删除已有记录）"""
    existing_ids = {m.id for m in db.query(EvidenceItemModel.id).filter(
        EvidenceItemModel.case_id == registry.case_id
    ).all()}

    for item in registry.items:
        if item.id in existing_ids:
            # 更新现有记录
            model = db.query(EvidenceItemModel).filter(EvidenceItemModel.id == item.id).first()
            if model:
                model.filename = item.source_file
                model.source_type = item.source_type
                model.content = item.content
                model.summary = item.summary
                model.extracted_date = item.date
                model.parties = item.parties
                model.evidence_type = item.evidence_type
                model.relevance = item.relevance
                model.confidence = item.confidence
                model.status = item.status
                model.error_message = item.error_message
                model.raw_metadata = item.raw_metadata
                model.file_size = item.file_size
                model.mime_type = item.mime_type
                model.storage_path = item.storage_path
                model.party = item.party
        else:
            # 新建
            model = evidence_item_to_model(item, user_id)
            model.case_id = registry.case_id
            db.add(model)

    db.commit()


def delete_evidence_from_db(evidence_id: str, db: Session) -> Optional[str]:
    """
    从数据库删除证据，返回 storage_path 以便删除文件
    """
    model = db.query(EvidenceItemModel).filter(EvidenceItemModel.id == evidence_id).first()
    if not model:
        return None
    storage_path = model.storage_path
    db.delete(model)
    db.commit()
    return storage_path


def save_conflict_reports_to_db(registry: EvidenceRegistry, user_id: int, db: Session) -> None:
    """保存冲突报告到数据库（先删除旧报告再写入新报告）"""
    db.query(ConflictReportModel).filter(
        ConflictReportModel.case_id == registry.case_id
    ).delete()

    for report in registry.conflicts:
        model = conflict_report_to_model(report, user_id)
        db.add(model)

    db.commit()


def delete_case_evidence_files(case_id: str) -> None:
    """删除某个案件的所有上传文件（用于案件删除时清理）"""
    _validate_case_id(case_id)
    case_dir = os.path.realpath(os.path.join(UPLOAD_ROOT, case_id))
    # 安全：确认目标目录确实是 UPLOAD_ROOT 的直接子目录，避免 rmtree 越界
    if case_dir == _UPLOAD_ROOT_REAL or not case_dir.startswith(_UPLOAD_ROOT_REAL + os.sep):
        raise PathTraversalError(f"case_id 目录越界，拒绝删除: {case_id!r}")
    if os.path.exists(case_dir):
        shutil.rmtree(case_dir)
