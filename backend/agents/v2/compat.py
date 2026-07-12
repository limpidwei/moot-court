"""
V2 兼容桥接

所有庭审流程统一走 V2 路径。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...orchestration.workflow import TrialState


async def run_trial_compat(state: "TrialState") -> "TrialState":
    """统一路由到 V2 工作流"""
    from ...orchestration.workflow_v2 import run_trial_v2
    return await run_trial_v2(state)
