"""
Case Ontology 数据模型

参考 Palantir Ontology 的 Object/Link/Action 思想，将案件数据从平铺文本
抽象为可操作的「对象-关系」图，支撑决策中心工作台。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional
from datetime import datetime


@dataclass
class CaseObject:
    """案件对象：整个 Ontology 的根节点"""

    id: str
    title: str
    case_type: str = ""                 # 案由分类，如「民间借贷纠纷」
    mode: Literal["neutral", "asymmetric"] = "neutral"
    user_side: Literal["plaintiff", "defendant", ""] = ""
    status: Literal["draft", "running", "completed", "archived"] = "draft"
    raw_materials: str = ""             # 原始材料（双轨制保留）
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Party:
    """当事人"""

    id: str
    case_id: str
    role: Literal["plaintiff", "defendant", "third_party"]
    name: str
    party_type: Literal["natural_person", "enterprise", "organization", "unknown"] = "unknown"
    position_summary: str = ""          # 诉讼地位一句话总结


@dataclass
class Claim:
    """诉讼请求 / 主张"""

    id: str
    case_id: str
    party_id: str                       # 提出方
    claim_text: str                     # 原文
    claim_type: Literal["principal", "alternative", "procedural", "defense"] = "principal"
    legal_basis_ids: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    win_rate_contribution: float = 0.0   # 对整体胜率的贡献评估


@dataclass
class Fact:
    """案件事实节点"""

    id: str
    case_id: str
    description: str
    date: Optional[str] = None
    parties_involved: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    is_disputed: bool = False
    dispute_summary: str = ""


@dataclass
class Evidence:
    """证据对象"""

    id: str
    case_id: str
    party_id: str = ""                  # 提交方（若可知）
    name: str = ""
    source_type: Literal["txt", "docx", "pdf", "image", "audio", "manual", "unknown"] = "unknown"
    content: str = ""
    summary: str = ""
    evidence_type: Literal[
        "document", "physical", "electronic", "witness", "expert", "inspection", "audio_visual", "unknown"
    ] = "unknown"
    date: Optional[str] = None
    proves_fact_ids: list[str] = field(default_factory=list)
    proves_claim_ids: list[str] = field(default_factory=list)
    authenticity: float = 0.0            # 真实性 0-1
    legality: float = 0.0                # 合法性 0-1
    relevance: float = 0.0               # 关联性 0-1
    weaknesses: list[str] = field(default_factory=list)


@dataclass
class LegalNorm:
    """法条 / 司法解释 / 规范"""

    id: str
    case_id: str
    source: str                         # 法规名，如「中华人民共和国民法典」
    article: str                        # 条/款/项，如「第675条」
    text: str = ""
    role: Literal["principal", "auxiliary", "defensive"] = "principal"
    confidence: float = 0.0
    rag_source: Optional[str] = None    # RAG 检索来源文本


@dataclass
class Precedent:
    """判例 / 类案"""

    id: str
    case_id: str
    title: str = ""
    court: str = ""
    case_number: str = ""
    similarity_score: float = 0.0
    key_takeaway: str = ""
    source: str = ""


@dataclass
class Issue:
    """争议焦点"""

    id: str
    case_id: str
    title: str
    description: str = ""
    issue_type: Literal["fact", "law", "evidence", "procedure", "mixed"] = "mixed"
    party_positions: dict = field(default_factory=dict)  # {plaintiff: ..., defendant: ...}
    evidence_ids: list[str] = field(default_factory=list)
    legal_norm_ids: list[str] = field(default_factory=list)
    priority: int = 3                   # 1-5，5 最高
    status: Literal["open", "resolved", "disputed"] = "open"


@dataclass
class Decision:
    """律师/AI 做出的关键决策"""

    id: str
    case_id: str
    decision_type: Literal["strategy", "evidence", "issue", "action", "settlement"] = "strategy"
    title: str = ""
    options: list[dict] = field(default_factory=list)
    selected_option_id: Optional[str] = None
    rationale: str = ""
    made_by: Literal["ai", "user", "ai_suggested"] = "ai_suggested"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source_ref_ids: list[str] = field(default_factory=list)


@dataclass
class ActionItem:
    """行动项 / 待办任务"""

    id: str
    case_id: str
    title: str
    action_type: Literal[
        "supplement_evidence", "legal_research", "client_comm",
        "witness", "filing", "deadline", "settlement", "other"
    ] = "other"
    priority: Literal["high", "medium", "low"] = "medium"
    due_hint: str = ""                  # 如「举证期限前」
    status: Literal["open", "done", "dismissed"] = "open"
    source_decision_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CaseOntology:
    """完整案件本体：包含所有对象与关系"""

    case: CaseObject
    parties: list[Party] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    legal_norms: list[LegalNorm] = field(default_factory=list)
    precedents: list[Precedent] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为可 JSON 化的字典"""
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CaseOntology":
        return cls(
            case=CaseObject(**data["case"]),
            parties=[Party(**p) for p in data.get("parties", [])],
            claims=[Claim(**c) for c in data.get("claims", [])],
            facts=[Fact(**f) for f in data.get("facts", [])],
            evidence=[Evidence(**e) for e in data.get("evidence", [])],
            legal_norms=[LegalNorm(**l) for l in data.get("legal_norms", [])],
            precedents=[Precedent(**p) for p in data.get("precedents", [])],
            issues=[Issue(**i) for i in data.get("issues", [])],
            decisions=[Decision(**d) for d in data.get("decisions", [])],
            action_items=[ActionItem(**a) for a in data.get("action_items", [])],
        )
