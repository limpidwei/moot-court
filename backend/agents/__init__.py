"""
模拟法庭多 Agent 系统 — V2 架构

角色：
- PlaintiffAgentV2   原告律师
- DefendantAgentV2   被告律师
- JudgeAgentV2       法官
- CourtReporterV2    书记员

协议：
- AgentMessageV2     消息格式
- MemoryBank         私有/共享/收件箱记忆
- CommChannel        ACL 受控通信
"""

from .v2.schema import AgentMessageV2
from .v2.base import BaseAgentV2
from .v2.plaintiff import PlaintiffAgentV2
from .v2.defendant import DefendantAgentV2
from .v2.judge import JudgeAgentV2
from .v2.channel import CommChannel

__all__ = [
    "AgentMessageV2",
    "BaseAgentV2",
    "PlaintiffAgentV2",
    "DefendantAgentV2",
    "JudgeAgentV2",
    "CommChannel",
]
