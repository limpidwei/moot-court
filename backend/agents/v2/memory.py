"""
Agent 记忆银行 —— 三层记忆结构

设计原则：
- 私有记忆（private）永不外泄
- 共享记忆（shared）需显式 publish() 后才对他人可见
- 收件箱（inbox）接收外部定向消息，消费后归档
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .schema import AgentMessageV2, LitigationStrategy


@dataclass
class PrivateMemory:
    """私有记忆层 —— 永不外泄"""

    # LLM 对话历史（该 Agent 的完整上下文）
    history: list[dict] = field(default_factory=list)

    # 策略相关
    strategy: Optional[LitigationStrategy] = None
    strategy_notes: str = ""  # 策略笔记、内部推理链
    legal_notes: str = ""  # 法条检索笔记
    fact_timeline: str = ""  # 按时间脉络整理的事实大事记

    # 论点与证据
    key_arguments: list[str] = field(default_factory=list)
    evidence_opinions: dict[str, str] = field(default_factory=dict)  # {evidence_id: 意见}
    weakness_analysis: str = ""  # 对对方弱点的分析

    # 通信归档
    sent_messages: list[AgentMessageV2] = field(default_factory=list)
    consumed_messages: list[AgentMessageV2] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "history": self.history,
            "strategy": self.strategy.to_dict() if self.strategy else None,
            "strategy_notes": self.strategy_notes,
            "legal_notes": self.legal_notes,
            "fact_timeline": self.fact_timeline,
            "key_arguments": self.key_arguments,
            "evidence_opinions": self.evidence_opinions,
            "weakness_analysis": self.weakness_analysis,
            "sent_messages": [m.to_dict() for m in self.sent_messages],
            "consumed_messages": [m.to_dict() for m in self.consumed_messages],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PrivateMemory":
        strategy = None
        if d.get("strategy"):
            strategy = LitigationStrategy.from_dict(d["strategy"])
        return cls(
            history=d.get("history", []),
            strategy=strategy,
            strategy_notes=d.get("strategy_notes", ""),
            legal_notes=d.get("legal_notes", ""),
            fact_timeline=d.get("fact_timeline", ""),
            key_arguments=d.get("key_arguments", []),
            evidence_opinions=d.get("evidence_opinions", {}),
            weakness_analysis=d.get("weakness_analysis", ""),
            sent_messages=[AgentMessageV2.from_dict(m) for m in d.get("sent_messages", [])],
            consumed_messages=[AgentMessageV2.from_dict(m) for m in d.get("consumed_messages", [])],
        )


@dataclass
class SharedMemory:
    """共享记忆层 —— 经 publish() 后对所有 Agent 可见"""

    documents: list[AgentMessageV2] = field(default_factory=list)
    # 已发布的法律文书：起诉状、答辩状、证据目录、判决书等

    def add(self, msg: AgentMessageV2) -> None:
        self.documents.append(msg)

    def get_by_phase(self, phase: int) -> list[AgentMessageV2]:
        return [d for d in self.documents if d.phase == phase]

    def get_by_type(self, content_type: str) -> list[AgentMessageV2]:
        return [d for d in self.documents if d.content_type == content_type]

    def get_by_phase_and_type(self, phase: int, content_type: str) -> list[AgentMessageV2]:
        return [d for d in self.documents if d.phase == phase and d.content_type == content_type]

    def get_latest_by_phase(self, phase: int) -> AgentMessageV2 | None:
        docs = [d for d in self.documents if d.phase == phase]
        return docs[-1] if docs else None

    def to_dict(self) -> dict:
        return {"documents": [m.to_dict() for m in self.documents]}

    @classmethod
    def from_dict(cls, d: dict) -> "SharedMemory":
        return cls(documents=[AgentMessageV2.from_dict(m) for m in d.get("documents", [])])


@dataclass
class MemoryBank:
    """
    Agent 记忆银行

    三层结构：
    - private: 私有记忆，仅本 Agent 可访问
    - shared: 共享记忆，publish() 后对所有 Agent 可见
    - inbox: 收件箱，来自其他 Agent 的定向消息
    """

    private: PrivateMemory = field(default_factory=PrivateMemory)
    shared: SharedMemory = field(default_factory=SharedMemory)
    inbox: list[AgentMessageV2] = field(default_factory=list)

    # ── 核心操作 ──

    def publish(self, msg: AgentMessageV2) -> AgentMessageV2:
        """
        将消息提升为共享记忆。
        调用方需自行通过 CommChannel 广播。
        这里仅将该消息加入本 Agent 的 shared 层并归档到 sent_messages。
        """
        msg.visibility = "public"
        self.shared.add(msg)
        self.private.sent_messages.append(msg)
        return msg

    def receive(self, msg: AgentMessageV2) -> None:
        """收到外部消息，放入 inbox"""
        self.inbox.append(msg)

    def consume_inbox(self, tag: str = "") -> list[AgentMessageV2]:
        """
        消费 inbox 中的消息。
        若 tag 为空，消费全部；否则按 content_type 过滤。
        消费后移入 private.consumed_messages。
        """
        if tag:
            matched = [m for m in self.inbox if m.content_type == tag or m.msg_type == tag]
        else:
            matched = list(self.inbox)

        for m in matched:
            self.inbox.remove(m)
            self.private.consumed_messages.append(m)
            # 关键庭审互动自动归档到事实时间线，确保 P6 交锋记录能被 P7 最后陈述看到
            if m.phase == 6 and m.content_type in ("question", "answer", "evidence_opinion"):
                self.private.fact_timeline += f"\n\n[{m.sender}] {m.content_type}:\n{m.content[:500]}"

        return matched

    def peek_inbox(self, tag: str = "") -> list[AgentMessageV2]:
        """查看 inbox 但不消费"""
        if tag:
            return [m for m in self.inbox if m.content_type == tag or m.msg_type == tag]
        return list(self.inbox)

    def build_context(self, include_private: bool = True) -> str:
        """
        组装供 LLM 使用的上下文字符串。
        按优先级：system prompt → private.strategy_notes → shared.documents → inbox(unread)
        """
        parts = []

        if include_private and self.private.strategy_notes:
            parts.append(f"【内部策略笔记】\n{self.private.strategy_notes}")

        if include_private and self.private.fact_timeline:
            parts.append(f"【案件大事记】\n{self.private.fact_timeline}")

        if include_private and self.private.legal_notes:
            parts.append(f"【法条检索笔记】\n{self.private.legal_notes}")

        if self.shared.documents:
            docs = "\n\n".join(
                f"[{d.content_type}] {d.content[:500]}"
                for d in self.shared.documents[-5:]  # 最近 5 份共享文档
            )
            parts.append(f"【已公开文书】\n{docs}")

        if self.inbox:
            msgs = "\n\n".join(
                f"[来自 {m.sender}] {m.content[:300]}"
                for m in self.inbox
            )
            parts.append(f"【未读消息】\n{msgs}")

        # 兜底：近期已消费的关键 peer 消息（防止 P6 交锋记录遗漏）
        recent_consumed = [
            m for m in self.private.consumed_messages[-5:]
            if m.phase == 6 and m.content_type in ("question", "answer", "evidence_opinion")
        ]
        if recent_consumed:
            msgs = "\n\n".join(
                f"[{m.sender}] {m.content_type}: {m.content[:300]}"
                for m in recent_consumed
            )
            parts.append(f"【近期交锋记录】\n{msgs}")

        return "\n\n---\n\n".join(parts)

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "private": self.private.to_dict(),
            "shared": self.shared.to_dict(),
            "inbox": [m.to_dict() for m in self.inbox],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryBank":
        return cls(
            private=PrivateMemory.from_dict(d.get("private", {})),
            shared=SharedMemory.from_dict(d.get("shared", {})),
            inbox=[AgentMessageV2.from_dict(m) for m in d.get("inbox", [])],
        )
