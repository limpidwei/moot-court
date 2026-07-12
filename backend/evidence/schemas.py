"""
证据数据模型 — 统一定义证据项、时间线事件、当事人关系、冲突报告

无论来源是文本/图片/音频，所有证据都归一化为 EvidenceItem。
这些模型同时服务于：
  1. 证据梳理产品（摄入 + 管理）
  2. 庭审可视化产品（图表渲染数据源）
  3. 证据冲突检测（矛盾发现）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EvidenceItem:
    """统一证据项"""
    id: str                          # 唯一标识
    source_file: str = ""            # 原始文件路径
    source_type: str = "text"        # text | docx | pdf | image | audio | contract
    content: str = ""                # 提取的文本内容
    summary: str = ""                # AI 摘要
    date: str | None = None          # 关联日期（ISO 格式，用于时间轴）
    parties: list[str] = field(default_factory=list)  # 涉及的当事人
    evidence_type: str = ""          # 书证 | 物证 | 电子数据 | 证人证言 | 鉴定意见
    relevance: list[str] = field(default_factory=list)  # 关联的法律要件/争议焦点
    confidence: float = 1.0          # 提取置信度 (0-1)
    raw_metadata: dict = field(default_factory=dict)   # 原始元数据

    # === 新增：处理状态与文件信息 ===
    status: str = "pending"          # pending | extracting | analyzing | completed | failed
    file_size: int = 0
    mime_type: str = ""
    storage_path: str = ""           # 服务器上的相对路径
    party: str = "unknown"           # 证据归属立场: plaintiff | defendant | third_party | unknown
    error_message: str = ""
    created_at: str = ""


@dataclass
class TimelineEvent:
    """时间线事件 — 可视化时间轴的数据单元"""
    id: str
    date: str                        # ISO 日期或日期范围
    label: str                       # 事件描述
    event_type: str = "fact"         # contract | breach | action | deadline | fact | evidence
    evidence_ids: list[str] = field(default_factory=list)  # 关联证据
    phase: int = 0                   # 来源阶段 (0=案件解析, 1-8=庭审阶段)
    party: str = ""                  # 关联当事人


@dataclass
class PartyRelation:
    """当事人关系 — 法律关系图的边"""
    from_party: str                  # 起始方
    to_party: str                    # 终止方
    relation_type: str = ""          # contract | tort | claim | defense | employment
    label: str = ""                  # 关系描述
    evidence_ids: list[str] = field(default_factory=list)


# ============================================================
# 冲突检测模型（新增）
# ============================================================

@dataclass
class ClaimDetail:
    """结构化主张 — 某条证据对某事实的具体说法"""
    evidence_id: str
    party: str                       # plaintiff | defendant | third_party | unknown
    original_text: str               # 证据中的原文片段
    extracted_claim: str             # 结构化主张


@dataclass
class ConflictReport:
    """
    证据冲突报告

    设计原则：系统不做真假判断，只发现矛盾并结构化呈现。
    律师/用户根据冲突报告做最终判断。
    """
    id: str
    case_id: str
    conflict_type: str               # temporal | factual | quantitative | party | stance
    severity: str = "medium"         # high | medium | low
    description: str = ""            # 冲突描述，如"关于签约日期的矛盾"
    involved_evidence_ids: list[str] = field(default_factory=list)
    involved_parties: list[str] = field(default_factory=list)
    claims: list[ClaimDetail] = field(default_factory=list)
    ai_note: str = ""                # LLM 分析备注（仅供参考）
    resolved: bool = False           # 律师是否已处理
    lawyer_note: str = ""            # 律师标注
    created_at: str = ""


# ============================================================
# 证据登记簿
# ============================================================

@dataclass
class EvidenceRegistry:
    """
    证据登记簿 — 所有摄入证据的统一管理

    未来接入证据梳理产品时，此对象负责：
    - 管理从文件夹/压缩包摄入的所有证据
    - 维护时间线和当事人关系数据
    - 通过 to_case_input() 转换为庭审系统可消费的格式
    """
    case_id: str
    items: list[EvidenceItem] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    party_relations: list[PartyRelation] = field(default_factory=list)
    conflicts: list[ConflictReport] = field(default_factory=list)  # 新增：冲突报告

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "items": [
                {
                    "id": item.id,
                    "source_file": item.source_file,
                    "source_type": item.source_type,
                    "content": item.content,
                    "summary": item.summary,
                    "date": item.date,
                    "parties": item.parties,
                    "evidence_type": item.evidence_type,
                    "relevance": item.relevance,
                    "confidence": item.confidence,
                    "raw_metadata": item.raw_metadata,
                    "status": item.status,
                    "file_size": item.file_size,
                    "mime_type": item.mime_type,
                    "storage_path": item.storage_path,
                    "party": item.party,
                    "error_message": item.error_message,
                    "created_at": item.created_at,
                }
                for item in self.items
            ],
            "timeline": [
                {
                    "id": e.id,
                    "date": e.date,
                    "label": e.label,
                    "event_type": e.event_type,
                    "evidence_ids": e.evidence_ids,
                    "phase": e.phase,
                    "party": e.party,
                }
                for e in self.timeline
            ],
            "party_relations": [
                {
                    "from_party": r.from_party,
                    "to_party": r.to_party,
                    "relation_type": r.relation_type,
                    "label": r.label,
                    "evidence_ids": r.evidence_ids,
                }
                for r in self.party_relations
            ],
            "conflicts": [
                {
                    "id": c.id,
                    "case_id": c.case_id,
                    "conflict_type": c.conflict_type,
                    "severity": c.severity,
                    "description": c.description,
                    "involved_evidence_ids": c.involved_evidence_ids,
                    "involved_parties": c.involved_parties,
                    "claims": [
                        {
                            "evidence_id": cl.evidence_id,
                            "party": cl.party,
                            "original_text": cl.original_text,
                            "extracted_claim": cl.extracted_claim,
                        }
                        for cl in c.claims
                    ],
                    "ai_note": c.ai_note,
                    "resolved": c.resolved,
                    "lawyer_note": c.lawyer_note,
                    "created_at": c.created_at,
                }
                for c in self.conflicts
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceRegistry":
        return cls(
            case_id=data.get("case_id", ""),
            items=[
                EvidenceItem(
                    id=item["id"],
                    source_file=item.get("source_file", ""),
                    source_type=item.get("source_type", "text"),
                    content=item.get("content", ""),
                    summary=item.get("summary", ""),
                    date=item.get("date"),
                    parties=item.get("parties", []),
                    evidence_type=item.get("evidence_type", ""),
                    relevance=item.get("relevance", []),
                    confidence=item.get("confidence", 1.0),
                    raw_metadata=item.get("raw_metadata", {}),
                    status=item.get("status", "completed"),
                    file_size=item.get("file_size", 0),
                    mime_type=item.get("mime_type", ""),
                    storage_path=item.get("storage_path", ""),
                    party=item.get("party", "unknown"),
                    error_message=item.get("error_message", ""),
                    created_at=item.get("created_at", ""),
                )
                for item in data.get("items", [])
            ],
            timeline=[
                TimelineEvent(
                    id=e["id"],
                    date=e["date"],
                    label=e["label"],
                    event_type=e.get("event_type", "fact"),
                    evidence_ids=e.get("evidence_ids", []),
                    phase=e.get("phase", 0),
                    party=e.get("party", ""),
                )
                for e in data.get("timeline", [])
            ],
            party_relations=[
                PartyRelation(
                    from_party=r["from_party"],
                    to_party=r["to_party"],
                    relation_type=r.get("relation_type", ""),
                    label=r.get("label", ""),
                    evidence_ids=r.get("evidence_ids", []),
                )
                for r in data.get("party_relations", [])
            ],
            conflicts=[
                ConflictReport(
                    id=c["id"],
                    case_id=c.get("case_id", data.get("case_id", "")),
                    conflict_type=c.get("conflict_type", "factual"),
                    severity=c.get("severity", "medium"),
                    description=c.get("description", ""),
                    involved_evidence_ids=c.get("involved_evidence_ids", []),
                    involved_parties=c.get("involved_parties", []),
                    claims=[
                        ClaimDetail(
                            evidence_id=cl["evidence_id"],
                            party=cl.get("party", "unknown"),
                            original_text=cl.get("original_text", ""),
                            extracted_claim=cl.get("extracted_claim", ""),
                        )
                        for cl in c.get("claims", [])
                    ],
                    ai_note=c.get("ai_note", ""),
                    resolved=c.get("resolved", False),
                    lawyer_note=c.get("lawyer_note", ""),
                    created_at=c.get("created_at", ""),
                )
                for c in data.get("conflicts", [])
            ],
        )

    def to_case_input_dict(self) -> dict:
        """
        转换为庭审系统可消费的 CaseInput 格式。
        未来证据梳理产品完成后，调用此方法无缝接入庭审流程。
        """
        facts_parts = []
        evidence_lines = []
        for item in self.items:
            if item.summary:
                facts_parts.append(item.summary)
            if item.content:
                evidence_lines.append(
                    f"{item.id}: {item.evidence_type or '证据'} - {item.content[:200]}"
                )

        return {
            "case_title": "",  # 需要上层填充
            "facts": "\n".join(facts_parts),
            "evidence": "\n".join(evidence_lines),
            "claims": "",  # 需要上层填充
        }
