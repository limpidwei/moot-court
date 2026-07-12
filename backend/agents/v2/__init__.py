"""
Agent V2 系统 —— 全阶段多 Agent 协作 + 独立记忆 + Skill 插件 + 策略自治

使用示例：
    from backend.agents.v2 import (
        PlaintiffAgentV2, DefendantAgentV2, JudgeAgentV2,
        CommChannel, CourtReporterV2,
    )

    channel = CommChannel()
    reporter = CourtReporterV2()
    channel.register_reporter(reporter)

    plaintiff = PlaintiffAgentV2(llm_config=cfg)
    defendant = DefendantAgentV2(llm_config=cfg)
    judge = JudgeAgentV2(llm_config=cfg)

    channel.register_agent(plaintiff)
    channel.register_agent(defendant)
    channel.register_agent(judge)
"""

from .schema import (
    AgentMessageV2,
    LitigationStrategy,
    EvidenceTiming,
    ProceduralMove,
)
from .memory import MemoryBank, PrivateMemory, SharedMemory
from .skill import (
    Skill,
    LegalResearchSkill,
    DraftingSkill,
    EvidenceAnalysisSkill,
    CrossExamSkill,
    ModerationSkill,
    AdjudicationSkill,
    ALL_SKILLS,
)
from .channel import CommChannel, CourtReporterV2
from .strategy import LitigationStrategyEngine
from .base import BaseAgentV2
from .plaintiff import PlaintiffAgentV2
from .defendant import DefendantAgentV2
from .judge import JudgeAgentV2
from .compat import run_trial_compat

__all__ = [
    # Schema
    "AgentMessageV2",
    "LitigationStrategy",
    "EvidenceTiming",
    "ProceduralMove",
    # Memory
    "MemoryBank",
    "PrivateMemory",
    "SharedMemory",
    # Skill
    "Skill",
    "LegalResearchSkill",
    "DraftingSkill",
    "EvidenceAnalysisSkill",
    "CrossExamSkill",
    "ModerationSkill",
    "AdjudicationSkill",
    "ALL_SKILLS",
    # Channel
    "CommChannel",
    "CourtReporterV2",
    # Strategy
    "LitigationStrategyEngine",
    # Base + Roles
    "BaseAgentV2",
    "PlaintiffAgentV2",
    "DefendantAgentV2",
    "JudgeAgentV2",
]
