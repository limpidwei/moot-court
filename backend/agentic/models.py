"""
Agentic 执行器模型

Codex 式 Agentic 执行的核心数据结构：提案（Proposal）。
每个关键动作先生成提案，等待律师审批后执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class Proposal:
    """Agentic 执行提案"""

    id: str
    case_id: str
    task: str
    action_type: Literal["call_skill", "update_ontology", "generate_report"]
    skill_name: str = ""           # call_skill 时使用
    params: dict = field(default_factory=dict)
    rationale: str = ""            # AI 为什么要执行这个动作
    status: Literal["pending", "approved", "rejected", "executed", "failed"] = "pending"
    result: dict = field(default_factory=dict)
    created_by: Literal["ai", "user"] = "ai"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Proposal":
        return cls(**data)
