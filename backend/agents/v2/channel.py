"""
受控通信协议 —— CommChannel

Agent 不直接互相调用，所有消息经 CommChannel 路由。
ACL 硬编码控制谁能发什么，visibility 控制消息可见范围。
"""

from __future__ import annotations

import logging
from typing import Optional

from .schema import AgentMessageV2
from .memory import MemoryBank

logger = logging.getLogger(__name__)


class CommChannel:
    """
    受控通信信道

    核心规则：
    1. ACL: 检查 sender 是否有权向 recipient 发送该 content_type
    2. Visibility: 决定消息进入哪些 Agent 的 memory
    """

    ACL_RULES = {
        "plaintiff": {
            "defendant": ["document", "evidence_opinion", "question"],
            "judge":     ["document", "evidence_opinion", "procedural_move"],
            "all":       ["document", "evidence_opinion"],
        },
        "defendant": {
            "plaintiff": ["document", "evidence_opinion", "question"],
            "judge":     ["document", "evidence_opinion", "procedural_move"],
            "all":       ["document", "evidence_opinion"],
        },
        "judge": {
            "plaintiff": ["guidance", "ruling", "question"],
            "defendant": ["guidance", "ruling", "question"],
            "all":       ["guidance", "ruling"],
        },
    }

    def __init__(self):
        self.agents: dict[str, "BaseAgentV2"] = {}
        self.reporter: Optional["CourtReporterV2"] = None

    def register_agent(self, agent: "BaseAgentV2") -> None:
        self.agents[agent.name] = agent

    def register_reporter(self, reporter: "CourtReporterV2") -> None:
        self.reporter = reporter

    def dispatch(self, msg: AgentMessageV2) -> bool:
        """
        路由消息。返回 True 表示成功，False 表示被 ACL 拒绝。
        """
        # 1. ACL 检查
        allowed = self.ACL_RULES.get(msg.sender, {}).get(msg.recipient, [])
        if msg.content_type not in allowed:
            logger.warning(
                f"[CommChannel] ACL拒绝: {msg.sender} 不能向 {msg.recipient} 发送 {msg.content_type}"
            )
            return False

        # 2. 根据 visibility 路由
        if msg.visibility == "public":
            # 进入所有 Agent 的 shared 层 + Reporter 记录
            for agent in self.agents.values():
                agent.memory.shared.add(msg)
            if self.reporter:
                self.reporter.record(msg)
            logger.info(f"[CommChannel] public 消息: {msg.sender} -> {msg.recipient} ({msg.content_type})")

        elif msg.visibility == "peer":
            # 仅接收方可见，放入 inbox
            if msg.recipient in self.agents:
                self.agents[msg.recipient].memory.receive(msg)
            # 发送方自己归档到 private.sent_messages
            if msg.sender in self.agents:
                self.agents[msg.sender].memory.private.sent_messages.append(msg)
            logger.info(f"[CommChannel] peer 消息: {msg.sender} -> {msg.recipient} ({msg.content_type})")

        elif msg.visibility == "private_to_judge":
            # 仅法官可见
            if "judge" in self.agents:
                self.agents["judge"].memory.receive(msg)
            logger.info(f"[CommChannel] private_to_judge: {msg.sender} -> judge")

        return True

    def broadcast(self, sender: str, content: str, content_type: str, phase: int = 0) -> None:
        """便捷方法：向所有人发 public 消息"""
        msg = AgentMessageV2(
            sender=sender,
            recipient="all",
            msg_type="broadcast",
            content=content,
            visibility="public",
            content_type=content_type,
            phase=phase,
        )
        self.dispatch(msg)

    def send_peer(self, sender: str, recipient: str, content: str, content_type: str, phase: int = 0) -> bool:
        """便捷方法：发送 peer 消息"""
        msg = AgentMessageV2(
            sender=sender,
            recipient=recipient,
            msg_type="peer",
            content=content,
            visibility="peer",
            content_type=content_type,
            phase=phase,
        )
        return self.dispatch(msg)


class CourtReporterV2:
    """
    书记员 V2 —— 公共账本维护者

    只记录 public 消息，形成不可篡改的庭审记录。
    """

    def __init__(self):
        self.ledger: list[AgentMessageV2] = []
        self._recorded_keys: set[tuple] = set()

    def _msg_key(self, msg: AgentMessageV2) -> tuple:
        return (msg.sender, msg.recipient, msg.msg_type, msg.content, msg.phase, msg.evidence_ref)

    def record(self, msg: AgentMessageV2) -> None:
        key = self._msg_key(msg)
        if key in self._recorded_keys:
            return
        self._recorded_keys.add(key)
        self.ledger.append(msg)

    def get_by_phase(self, phase: int) -> list[AgentMessageV2]:
        return [m for m in self.ledger if m.phase == phase]

    def get_cross_exam_log(self) -> list[AgentMessageV2]:
        return [m for m in self.ledger if m.msg_type in ("question", "answer") and m.phase == 6]

    def to_dict(self) -> dict:
        return {"ledger": [m.to_dict() for m in self.ledger]}

    @classmethod
    def from_dict(cls, d: dict) -> "CourtReporterV2":
        reporter = cls()
        reporter.ledger = [AgentMessageV2.from_dict(m) for m in d.get("ledger", [])]
        for m in reporter.ledger:
            reporter._recorded_keys.add(reporter._msg_key(m))
        return reporter
