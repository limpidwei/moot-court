"""
多 Agent V2 系统 —— 消息协议、策略模型与状态定义

基于真实法律工作流设计：
- 消息带 visibility + content_type，受控通信
- 诉讼策略引擎模型（策略自治、证据时序）
- 证据时序数据模型
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import datetime


# ── 消息协议 ──────────────────────────────────────────────

@dataclass
class AgentMessageV2:
    """Agent 间传递的消息（受控通信协议）"""

    sender: str
    recipient: str  # "all" / "judge" / "plaintiff" / "defendant"
    msg_type: str
    content: str

    # ── 可见性控制 ──
    visibility: Literal["public", "peer", "private_to_judge"] = "public"
    # public: 进入所有 Agent 的 shared 层 + CourtReporter 记录
    # peer: 仅收发双方可见
    # private_to_judge: 仅法官可见

    # ── 内容分类 ──
    content_type: Literal[
        "document",
        "evidence_opinion",
        "question",
        "answer",
        "guidance",
        "ruling",
        "strategy_note",
        "procedural_move",
    ] = "document"

    phase: int = 0
    evidence_ref: str = ""
    round_num: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "msg_type": self.msg_type,
            "content": self.content,
            "visibility": self.visibility,
            "content_type": self.content_type,
            "phase": self.phase,
            "evidence_ref": self.evidence_ref,
            "round_num": self.round_num,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentMessageV2":
        return cls(
            sender=d["sender"],
            recipient=d["recipient"],
            msg_type=d["msg_type"],
            content=d["content"],
            visibility=d.get("visibility", "public"),
            content_type=d.get("content_type", "document"),
            phase=d.get("phase", 0),
            evidence_ref=d.get("evidence_ref", ""),
            round_num=d.get("round_num", 0),
            timestamp=d.get("timestamp", datetime.now().isoformat()),
        )


# ── 诉讼策略引擎模型 ───────────────────────────────────────

@dataclass
class ProceduralMove:
    """程序性动作（如管辖权异议、延期举证、申请回避）"""

    move_type: Literal[
        "jurisdiction_objection",
        "extension_request",
        "recusal_request",
        "evidence_preservation",
        "property_preservation",
        "counterclaim",
    ]
    reason: str
    target_phase: int = 0
    status: Literal["pending", "granted", "denied", "withdrawn"] = "pending"


@dataclass
class EvidenceTiming:
    """证据提交时序策略"""

    strategy_type: Literal["full_disclosure", "staged_release"] = "full_disclosure"
    # full_disclosure: 举证期限内一次性提交全部证据（稳健型）
    # staged_release: 分阶段提交，先交核心，再视反应补交（试探型）

    primary_evidence: list[str] = field(default_factory=list)
    reserve_evidence: list[str] = field(default_factory=list)
    trigger_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_type": self.strategy_type,
            "primary_evidence": self.primary_evidence,
            "reserve_evidence": self.reserve_evidence,
            "trigger_conditions": self.trigger_conditions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvidenceTiming":
        st = d.get("strategy_type", "full_disclosure")
        # 兼容旧数据中可能存在的 ambush 类型，降级为 staged_release
        if st not in ("full_disclosure", "staged_release"):
            st = "staged_release"
        return cls(
            strategy_type=st,
            primary_evidence=d.get("primary_evidence", []),
            reserve_evidence=d.get("reserve_evidence", []),
            trigger_conditions=d.get("trigger_conditions", []),
        )


@dataclass
class LitigationStrategy:
    """单个案件的全局诉讼策略"""

    # 程序策略
    procedural_moves: list[ProceduralMove] = field(default_factory=list)

    # 实体策略
    core_theory: str = ""  # 核心诉讼/抗辩理论
    fallback_theories: list[str] = field(default_factory=list)  # 备选理论

    # 证据策略
    evidence_timing: EvidenceTiming = field(default_factory=EvidenceTiming)

    # 庭审策略
    cross_exam_focus: list[str] = field(default_factory=list)
    weakness_map: dict[str, str] = field(default_factory=dict)

    # 动态调整
    risk_assessment: str = ""
    adapt_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "procedural_moves": [
                {
                    "move_type": m.move_type,
                    "reason": m.reason,
                    "target_phase": m.target_phase,
                    "status": m.status,
                }
                for m in self.procedural_moves
            ],
            "core_theory": self.core_theory,
            "fallback_theories": self.fallback_theories,
            "evidence_timing": self.evidence_timing.to_dict(),
            "cross_exam_focus": self.cross_exam_focus,
            "weakness_map": self.weakness_map,
            "risk_assessment": self.risk_assessment,
            "adapt_notes": self.adapt_notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LitigationStrategy":
        moves = [
            ProceduralMove(
                move_type=m["move_type"],
                reason=m["reason"],
                target_phase=m.get("target_phase", 0),
                status=m.get("status", "pending"),
            )
            for m in d.get("procedural_moves", [])
        ]
        return cls(
            procedural_moves=moves,
            core_theory=d.get("core_theory", ""),
            fallback_theories=d.get("fallback_theories", []),
            evidence_timing=EvidenceTiming.from_dict(d.get("evidence_timing", {})),
            cross_exam_focus=d.get("cross_exam_focus", []),
            weakness_map=d.get("weakness_map", {}),
            risk_assessment=d.get("risk_assessment", ""),
            adapt_notes=d.get("adapt_notes", []),
        )


# ── 策略路线模型 ───────────────────────────────────────────

@dataclass
class StrategyRoute:
    """AI 生成的单条策略路线（供用户选择）"""

    route_id: str = "A"           # A / B / C
    title: str = ""               # 路线标题（如"主张被告违约"）
    is_recommended: bool = False  # 是否 AI 推荐

    core_theory: str = ""         # 核心主张
    legal_basis: str = ""         # 法律依据
    evidence_strategy: str = ""   # 证据策略
    risk_warning: str = ""        # 风险提示

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "title": self.title,
            "is_recommended": self.is_recommended,
            "core_theory": self.core_theory,
            "legal_basis": self.legal_basis,
            "evidence_strategy": self.evidence_strategy,
            "risk_warning": self.risk_warning,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyRoute":
        return cls(
            route_id=d.get("route_id", "A"),
            title=d.get("title", ""),
            is_recommended=d.get("is_recommended", False),
            core_theory=d.get("core_theory", ""),
            legal_basis=d.get("legal_basis", ""),
            evidence_strategy=d.get("evidence_strategy", ""),
            risk_warning=d.get("risk_warning", ""),
        )
