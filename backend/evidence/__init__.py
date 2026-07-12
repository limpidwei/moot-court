"""
证据智能梳理模块

支持多模态证据上传、解析、AI 分析和冲突检测。

功能：
- 文本证据：txt, docx, pdf
- 图片证据：jpg, png（本地 OCR）
- AI 摘要、分类、时间线提取
- 证据冲突检测（时间/事实/数量/当事人/立场）
- 与庭审系统无缝对接
"""

from .schemas import EvidenceItem, EvidenceRegistry, TimelineEvent, ConflictReport, ClaimDetail
from .registry import (
    get_registry, save_registry, add_evidence_item,
    delete_evidence_item, analyze_all_evidence, analyze_conflicts,
    import_to_trial_session,
)
from .persistence import save_uploaded_file, delete_file

__all__ = [
    "EvidenceItem",
    "EvidenceRegistry",
    "TimelineEvent",
    "ConflictReport",
    "ClaimDetail",
    "get_registry",
    "save_registry",
    "add_evidence_item",
    "delete_evidence_item",
    "analyze_all_evidence",
    "analyze_conflicts",
    "import_to_trial_session",
    "save_uploaded_file",
    "delete_file",
]
