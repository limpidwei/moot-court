"""
Agentic 执行器测试

覆盖 Proposal 生命周期、任务规划映射、审批执行（mock LLM）。
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.models.case import CaseInput
from backend.orchestration.workflow import TrialSession
from backend.ontology import service as ontology_service
from backend.agentic.executor import AgenticExecutor
from backend.agentic import service as proposal_service


@pytest.fixture
def sample_session():
    case_input = CaseInput(
        case_title="原告张三诉被告李四民间借贷纠纷",
        facts="2023年1月1日，被告向原告借款10万元，约定6月归还。原告银行转账支付。",
        evidence="1. 借条（书证）\n2. 银行转账记录（书证）",
        claims="1. 判令被告偿还本金10万元及利息（依据《中华人民共和国民法典》第675条）",
        mode="asymmetric",
        user_side="plaintiff",
    )
    session = TrialSession(case_input=case_input, user_id=1)
    # 先构建 Ontology
    ontology_service.build_and_save_from_case_input(case_input)
    return session


def test_agentic_plan_evidence_chain(sample_session):
    executor = AgenticExecutor()
    proposals = executor.plan(sample_session.case_input.case_title, "证据链缺口诊断")
    assert len(proposals) >= 1
    assert proposals[0].skill_name == "evidence_chain"
    assert proposals[0].status == "pending"


def test_agentic_plan_plea_bargain(sample_session):
    executor = AgenticExecutor()
    proposals = executor.plan(sample_session.case_input.case_title, "调解报价策略")
    assert any(p.skill_name == "plea_bargain" for p in proposals)


def test_agentic_plan_judge_questions(sample_session):
    executor = AgenticExecutor()
    proposals = executor.plan(sample_session.case_input.case_title, "预测法官可能追问的问题")
    assert any(p.skill_name == "judge_questions" for p in proposals)


@pytest.mark.asyncio
async def test_agentic_execute_approval_flow(sample_session):
    executor = AgenticExecutor()
    proposals = executor.plan(sample_session.case_input.case_title, "证据链缺口诊断")
    prop = proposals[0]

    # mock think_with_skill 避免真实 LLM 调用
    with patch.object(executor.agent, "think_with_skill", new=AsyncMock(return_value='{"gaps": [], "weak_evidence": [], "overall_health": 0.8}')):
        result = await executor.execute(prop)

    assert result.get("overall_health") == 0.8
    updated = proposal_service.get_proposal(prop.case_id, prop.id)
    assert updated is not None
    assert updated.status == "executed"


def test_proposal_reject(sample_session):
    executor = AgenticExecutor()
    proposals = executor.plan(sample_session.case_input.case_title, "执行风险评估")
    prop = proposals[0]
    proposal_service.update_proposal_status(prop.case_id, prop.id, "rejected", result={"rationale": "暂不评估"})
    updated = proposal_service.get_proposal(prop.case_id, prop.id)
    assert updated.status == "rejected"


def teardown_module():
    """清理测试产生的 Ontology 文件"""
    import shutil
    from pathlib import Path
    p = Path("data/ontologies")
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
