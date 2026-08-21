"""
Agent V2 集成测试 —— mock LLM，端到端验证 Phase 1-8 图执行无报错

运行：
    cd /path/to/moot-court
    USE_AGENT_V2=true py -m pytest tests/test_v2_integration.py -v
"""

import os
import sys
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

# 强制启用 V2
os.environ["USE_AGENT_V2"] = "true"

from backend.models.case import CaseInput
from backend.orchestration.workflow import TrialState, create_initial_state
from backend.orchestration.workflow_v2 import (
    build_trial_graph_v2,
    _restore_agents_v2,
    _save_agents_v2,
    cross_exam_router_v2,
    evidence_exam_router_v2,
)


@pytest.fixture
def sample_case():
    return CaseInput(
        case_title="测试案件：借款合同纠纷",
        facts="原告借给被告10万元，被告逾期未还。",
        evidence="1. 借条\n2. 转账记录",
        claims="请求判令被告偿还借款本金10万元及利息。",
    )


@pytest.fixture
def initial_state(sample_case):
    state = create_initial_state(sample_case, user_role="neutral")
    state["llm_config"] = None
    return state


async def _mock_llm_call(*args, **kwargs):
    """通用 mock LLM 响应"""
    # 根据 system_prompt 或 task 内容返回不同 mock 结果
    task = ""
    if args:
        task = str(args[0])[:100]
    if kwargs.get("messages"):
        task = str(kwargs["messages"][-1].get("content", ""))[:100]

    if "起诉状" in task or "complaint" in task:
        return "【mock 起诉状】原被告于2023年签订借款合同..."
    if "答辩状" in task or "answer" in task:
        return "【mock 答辩状】被告承认借款事实，但主张已部分偿还..."
    if "争议焦点" in task or "summarize" in task:
        return "【mock 争议焦点】1. 借款本金是否已部分偿还 2. 利息计算标准"
    if "交叉询问" in task or "cross_exam" in task:
        return "【mock 交叉询问问题】被告，请确认2023年5月是否收到10万元？"
    if "判决" in task or "judgment" in task:
        return "【mock 判决书】本院认为...综合胜率：65.0%"
    if "最后陈述" in task or "statement" in task:
        return "【mock 最后陈述】坚持诉讼请求..."
    if "证据" in task and "目录" in task:
        return "【mock 证据目录】1. 借条（书证）..."
    if "质证" in task or "证据分析" in task:
        return "【mock 质证意见】对证据真实性无异议，对关联性有异议..."
    if "突袭" in task or "ambush" in task:
        return "【mock 突袭裁决】该证据逾期提交，但与基本事实有关，予以采纳并训诫。"
    if "策略" in task or "strategy" in task:
        return """core_theory: 借款合同成立且有效
fallback_theories:
- 不当得利返还
- 侵权损害赔偿
evidence_timing_strategy: staged_release
procedural_moves: 无
cross_exam_focus:
- 还款时间
- 还款金额
- 利息约定
weakness_map:
对方: 无书面还款凭证
risk_assessment: 中"""
    return f"【mock 响应】{task[:30]}..."


class TestV2GraphBuild:
    """验证 V2 图构建"""

    def test_build_graph(self):
        graph = build_trial_graph_v2()
        assert graph is not None


class TestV2PhaseNodes:
    """逐个节点 mock 测试"""

    @pytest.mark.asyncio
    async def test_phase1_2(self, initial_state):
        from backend.orchestration.workflow_v2 import phase1_node_v2, phase2_node_v2

        with patch("backend.agents.v2.skill.llm_call", new=_mock_llm_call):
            with patch("backend.agents.v2.base.llm_call", new=_mock_llm_call):
                with patch("backend.agents.v2.strategy.llm_call", new=_mock_llm_call):
                    s1 = await phase1_node_v2(initial_state.copy())
                    assert "error" not in s1 or not s1["error"]
                    assert s1.get("phase1_analysis")

                    s2 = await phase2_node_v2(s1)
                    assert s2.get("phase2_complaint")
                    assert s2.get("phase2_evidence_catalog")

    @pytest.mark.asyncio
    async def test_phase3_4(self, initial_state):
        from backend.orchestration.workflow_v2 import phase3_node_v2, phase4_node_v2

        # 预置 Phase 1-2 结果
        initial_state["phase1_analysis"] = "mock analysis"
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase2_evidence_catalog"] = "mock catalog"

        with patch("backend.agents.v2.skill.llm_call", new=_mock_llm_call):
            with patch("backend.agents.v2.base.llm_call", new=_mock_llm_call):
                with patch("backend.agents.v2.strategy.llm_call", new=_mock_llm_call):
                    s3 = await phase3_node_v2(initial_state.copy())
                    assert s3.get("phase3_analysis")

                    s4 = await phase4_node_v2(s3)
                    assert s4.get("phase4_answer")
                    assert s4.get("phase4_evidence_catalog")

    @pytest.mark.asyncio
    async def test_phase5(self, initial_state):
        from backend.orchestration.workflow_v2 import phase5_node_v2

        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"

        with patch("backend.agents.v2.skill.llm_call", new=_mock_llm_call):
            with patch("backend.agents.v2.base.llm_call", new=_mock_llm_call):
                s5 = await phase5_node_v2(initial_state.copy())
                assert s5.get("phase5_issues")

    @pytest.mark.asyncio
    async def test_cross_exam_round(self, initial_state):
        from backend.orchestration.workflow_v2 import cross_exam_round_node_v2

        initial_state["cross_exam_round"] = 0
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"
        initial_state["phase5_issues"] = "mock issues"

        with patch("backend.agents.v2.skill.llm_call", new=_mock_llm_call):
            with patch("backend.agents.v2.base.llm_call", new=_mock_llm_call):
                s6 = await cross_exam_round_node_v2(initial_state.copy())
                assert s6["cross_exam_round"] == 1
                assert s6.get("phase6_cross_exam")
                assert "error" not in s6 or not s6["error"]

    @pytest.mark.asyncio
    async def test_evidence_exam_batch(self, initial_state):
        from backend.orchestration.workflow_v2 import evidence_exam_batch_node_v2

        initial_state["evidence_list"] = ["借条", "转账记录"]
        initial_state["current_evidence_index"] = 0
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"
        initial_state["phase5_issues"] = "mock issues"

        with patch("backend.agents.v2.skill.llm_call", new=_mock_llm_call):
            with patch("backend.agents.v2.base.llm_call", new=_mock_llm_call):
                s6b = await evidence_exam_batch_node_v2(initial_state.copy())
                assert s6b["current_evidence_index"] == 2
                assert s6b.get("phase6_evidence_exam")
                assert "error" not in s6b or not s6b["error"]

    @pytest.mark.asyncio
    async def test_phase7_8(self, initial_state):
        from backend.orchestration.workflow_v2 import phase7_node_v2, phase8_node_v2

        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"
        initial_state["phase5_issues"] = "mock issues"
        initial_state["phase6_cross_exam"] = "[]"
        initial_state["phase6_evidence_exam"] = "[]"

        with patch("backend.agents.v2.skill.llm_call", new=_mock_llm_call):
            with patch("backend.agents.v2.base.llm_call", new=_mock_llm_call):
                s7 = await phase7_node_v2(initial_state.copy())
                assert s7.get("phase7_plaintiff_final")
                assert s7.get("phase7_defendant_final")

                s8 = await phase8_node_v2(s7)
                assert s8.get("phase8_judgment")


class TestV2FullGraph:
    """全图 mock 运行（模拟前端逐步确认）"""

    @pytest.mark.asyncio
    async def test_full_graph_mock(self, initial_state):
        from backend.orchestration.workflow_v2 import run_trial_v2

        with patch("backend.agents.v2.skill.llm_call", new=_mock_llm_call):
            with patch("backend.agents.v2.base.llm_call", new=_mock_llm_call):
                with patch("backend.agents.v2.strategy.llm_call", new=_mock_llm_call):
                    state = initial_state.copy()
                    # 模拟前端逐步确认，每 phase 最多 15 次迭代（防死循环）
                    for _ in range(15):
                        state = await run_trial_v2(state)
                        cp = state["current_phase"]
                        if cp >= 8:
                            break
                        # 自动确认当前阶段
                        state[f"phase{cp}_confirmed"] = True
                    assert state["current_phase"] == 8
                    assert state.get("phase8_judgment")
                    assert "error" not in state or not state["error"]


class TestV2AgentPersistence:
    """验证 Agent 状态序列化/反序列化"""

    def test_save_load_cycle(self, initial_state):
        agents = _restore_agents_v2(initial_state)
        _save_agents_v2(initial_state, agents)

        assert "plaintiff_state" in initial_state
        assert "defendant_state" in initial_state
        assert "judge_state" in initial_state
        assert "reporter_state" in initial_state

        # 反序列化应不报错
        agents2 = _restore_agents_v2(initial_state)
        assert agents2["plaintiff"].name == "plaintiff"
        assert agents2["defendant"].name == "defendant"
        assert agents2["judge"].name == "judge"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
