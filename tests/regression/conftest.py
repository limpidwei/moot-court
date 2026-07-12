"""
回归测试共享 fixtures

提供：
- 标准案件输入（借款合同、买卖合同、劳动争议）
- Mock LLM 通用响应
- 预构建的 FactLock
"""
from __future__ import annotations

import os
import sys
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

# 强制启用 V2
os.environ["USE_AGENT_V2"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-only-32bytes"
os.environ["JWT_EXPIRATION_HOURS"] = "24"

# 确保 backend 在路径中
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.models.case import CaseInput
from backend.agents.v2.evidence_constraint import FactLock
from backend.orchestration.workflow import create_initial_state


# ── 标准案件 fixtures ──────────────────────────────────────

@pytest.fixture
def loan_case() -> CaseInput:
    """借款合同纠纷 —— 用于测试还款凭证拦截、时间红线"""
    return CaseInput(
        case_title="借款合同纠纷",
        facts=(
            "2023年3月1日，原告张三通过银行转账借给被告李四人民币10万元，"
            "双方口头约定借款期限为6个月，月利率1.5%。"
            "2023年9月1日借款到期后，被告未归还本金及利息。"
            "原告多次催讨无果，遂起诉至法院。"
        ),
        evidence=(
            "1. 银行转账记录（2023年3月1日，张三转李四10万元）\n"
            "2. 微信聊天记录（张三催款记录，李四回复'再等等'）\n"
            "3. 证人王五证言（在场听到双方谈论借款）"
        ),
        claims=(
            "1. 判令被告归还借款本金10万元\n"
            "2. 判令被告支付利息（按月利率1.5%计算，自2023年3月1日至实际清偿之日）\n"
            "3. 被告承担本案诉讼费用。"
        ),
    )


@pytest.fixture
def sales_case() -> CaseInput:
    """买卖合同纠纷 —— 用于测试质量异议等场景"""
    return CaseInput(
        case_title="买卖合同纠纷",
        facts=(
            "2024年1月15日，原告A公司与被告B公司签订《购销合同》，"
            "约定原告向被告采购设备10台，总价50万元。"
            "2024年2月20日交货后，原告发现设备存在严重质量问题，"
            "多次要求退货退款未果。"
        ),
        evidence=(
            "1. 《购销合同》（2024年1月15日签订）\n"
            "2. 交货单（2024年2月20日）\n"
            "3. 质量问题照片及视频"
        ),
        claims=(
            "1. 判令解除合同\n"
            "2. 判令被告退还货款50万元并赔偿损失"
        ),
    )


@pytest.fixture
def labor_case() -> CaseInput:
    """劳动争议 —— 用于测试考勤、工资等场景"""
    return CaseInput(
        case_title="劳动争议",
        facts=(
            "原告于2022年6月1日入职被告公司，担任销售经理。"
            "2024年5月30日，被告以原告业绩不达标为由解除劳动合同。"
            "原告认为被告系违法解除，要求支付赔偿金。"
        ),
        evidence=(
            "1. 劳动合同\n"
            "2. 工资流水\n"
            "3. 解除劳动合同通知书"
        ),
        claims=(
            "1. 判令被告支付违法解除劳动合同赔偿金12万元\n"
            "2. 判令被告支付未休年假工资"
        ),
    )


@pytest.fixture
def loan_fact_lock(loan_case) -> FactLock:
    """基于 loan_case 的规则提取结果"""
    from backend.agents.v2.evidence_constraint import FactExtractor
    return FactExtractor().extract(loan_case)


@pytest.fixture
def initial_state(loan_case):
    """V2 庭审初始状态"""
    state = create_initial_state(loan_case, user_role="neutral")
    state["llm_config"] = None
    return state


# ── Mock LLM fixtures ─────────────────────────────────────

@pytest.fixture
def mock_llm():
    """Mock backend.agents.v2.skill.llm_call"""
    with patch("backend.agents.v2.skill.llm_call") as m:
        yield m


@pytest.fixture
def mock_constraint_llm():
    """Mock backend.agents.v2.evidence_constraint.llm_call"""
    with patch("backend.agents.v2.evidence_constraint.llm_call") as m:
        yield m


@pytest.fixture
def mock_insights_llm():
    """Mock backend.services.insights.llm_call"""
    with patch("backend.services.insights.llm_call") as m:
        yield m


# ── 辅助函数 ───────────────────────────────────────────────

def make_async_return(value: str):
    """构造一个可 await 的异步 mock 返回值"""
    async def _async_return(*args, **kwargs):
        return value
    return _async_return
