"""
庭审流程关键路径回归测试

目标：确保庭审核心流程（状态创建、Agent 保存/恢复、各 Phase 推进）不被破坏。

覆盖场景：
1. TrialState 创建和基础字段完整性
2. Agent V2 状态保存/恢复循环
3. 各 Phase 节点在 mock LLM 下能正常执行
4. 单方对抗模式案件创建流程
5. 状态序列化兼容性（新旧字段）
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from backend.models.case import CaseInput
from backend.orchestration.workflow import TrialState, create_initial_state
from backend.orchestration.workflow_v2 import (
    _restore_agents_v2,
    _save_agents_v2,
    phase1_node_v2,
    phase2_node_v2,
    phase3_node_v2,
    phase4_node_v2,
    phase5_node_v2,
    phase7_node_v2,
    phase8_node_v2,
    cross_exam_round_node_v2,
    evidence_exam_batch_node_v2,
    build_trial_graph_v2,
    _ensure_case_input,
)


# ── 共享 mock LLM ──────────────────────────────────────────

async def _mock_llm_call(*args, **kwargs):
    """通用 mock LLM 响应"""
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
evidence_timing_strategy: staged_release
procedural_moves: 无
cross_exam_focus:
- 还款时间
weakness_map:
对方: 无书面还款凭证
risk_assessment: 中"""
    return f"【mock 响应】{task[:30]}..."


# ═══════════════════════════════════════════════════════════
# 测试 1：TrialState 基础行为
# ═══════════════════════════════════════════════════════════

class TestTrialStateBasics:
    """验证状态创建和字段完整性"""

    def test_create_initial_state(self, loan_case):
        state = create_initial_state(loan_case, user_role="neutral")
        assert state["case_input"] is not None
        assert state["current_phase"] == 0
        assert state["user_role"] == "neutral"

    def test_case_input_dict_deserialization(self, loan_case):
        """验证 dict 形式的 case_input 能被正确反序列化"""
        state = create_initial_state(loan_case, user_role="neutral")
        # 模拟 LangGraph checkpoint 序列化后的 dict
        state["case_input"] = {
            "case_title": loan_case.case_title,
            "facts": loan_case.facts,
            "evidence": loan_case.evidence,
            "claims": loan_case.claims,
        }
        _ensure_case_input(state)
        assert isinstance(state["case_input"], CaseInput)
        assert state["case_input"].case_title == "借款合同纠纷"


# ═══════════════════════════════════════════════════════════
# 测试 2：Agent V2 状态保存/恢复
# ═══════════════════════════════════════════════════════════

class TestAgentV2Persistence:
    """验证 Agent 状态序列化/反序列化不丢失数据"""

    def test_save_restore_cycle(self, initial_state):
        agents = _restore_agents_v2(initial_state)
        _save_agents_v2(initial_state, agents)

        assert "plaintiff_state" in initial_state
        assert "defendant_state" in initial_state
        assert "judge_state" in initial_state
        assert "reporter_state" in initial_state

        agents2 = _restore_agents_v2(initial_state)
        assert agents2["plaintiff"].name == "plaintiff"
        assert agents2["defendant"].name == "defendant"
        assert agents2["judge"].name == "judge"

    def test_restore_from_empty_state(self, initial_state):
        """从空状态恢复应能创建新 Agent"""
        for key in ["plaintiff_state", "defendant_state", "judge_state", "reporter_state"]:
            initial_state.pop(key, None)
        agents = _restore_agents_v2(initial_state)
        assert "plaintiff" in agents
        assert "defendant" in agents
        assert "judge" in agents


# ═══════════════════════════════════════════════════════════
# 测试 3：各 Phase 节点 mock 执行
# ═══════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_llm")
class TestPhaseNodesMock:
    """逐个节点 mock 测试，验证执行无异常且产出关键字段"""

    @pytest.fixture(autouse=True)
    def setup_mock(self, mock_llm):
        mock_llm.side_effect = _mock_llm_call
        yield

    @pytest.mark.asyncio
    async def test_phase1(self, initial_state):
        s1 = await phase1_node_v2(initial_state.copy())
        assert "error" not in s1 or not s1["error"]
        assert s1.get("phase1_analysis")

    @pytest.mark.asyncio
    async def test_phase2(self, initial_state):
        initial_state["phase1_analysis"] = "mock analysis"
        s2 = await phase2_node_v2(initial_state.copy())
        assert s2.get("phase2_complaint")
        assert s2.get("phase2_evidence_catalog")

    @pytest.mark.asyncio
    async def test_phase3(self, initial_state):
        initial_state["phase1_analysis"] = "mock"
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase2_evidence_catalog"] = "mock catalog"
        s3 = await phase3_node_v2(initial_state.copy())
        assert s3.get("phase3_analysis")

    @pytest.mark.asyncio
    async def test_phase4(self, initial_state):
        initial_state["phase1_analysis"] = "mock"
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase3_analysis"] = "mock strategy"
        s4 = await phase4_node_v2(initial_state.copy())
        assert s4.get("phase4_answer")
        assert s4.get("phase4_evidence_catalog")

    @pytest.mark.asyncio
    async def test_phase5(self, initial_state):
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"
        s5 = await phase5_node_v2(initial_state.copy())
        assert s5.get("phase5_issues")

    @pytest.mark.asyncio
    async def test_cross_exam_round(self, initial_state):
        initial_state["cross_exam_round"] = 0
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"
        initial_state["phase5_issues"] = "mock issues"
        s6 = await cross_exam_round_node_v2(initial_state.copy())
        assert s6["cross_exam_round"] == 1
        assert s6.get("phase6_cross_exam")

    @pytest.mark.asyncio
    async def test_evidence_exam_batch(self, initial_state):
        initial_state["evidence_list"] = ["借条", "转账记录"]
        initial_state["current_evidence_index"] = 0
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"
        initial_state["phase5_issues"] = "mock issues"
        s6b = await evidence_exam_batch_node_v2(initial_state.copy())
        assert s6b["current_evidence_index"] == 2
        assert s6b.get("phase6_evidence_exam")

    @pytest.mark.asyncio
    async def test_phase7(self, initial_state):
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"
        initial_state["phase5_issues"] = "mock issues"
        initial_state["phase6_cross_exam"] = "[]"
        initial_state["phase6_evidence_exam"] = "[]"
        s7 = await phase7_node_v2(initial_state.copy())
        assert s7.get("phase7_plaintiff_final")
        assert s7.get("phase7_defendant_final")

    @pytest.mark.asyncio
    async def test_phase8(self, initial_state):
        initial_state["phase2_complaint"] = "mock complaint"
        initial_state["phase4_answer"] = "mock answer"
        initial_state["phase5_issues"] = "mock issues"
        initial_state["phase6_cross_exam"] = "[]"
        initial_state["phase6_evidence_exam"] = "[]"
        initial_state["phase7_plaintiff_final"] = "mock final"
        initial_state["phase7_defendant_final"] = "mock final"
        s8 = await phase8_node_v2(initial_state.copy())
        assert s8.get("phase8_judgment")


# ═══════════════════════════════════════════════════════════
# 测试 4：图构建与全图运行
# ═══════════════════════════════════════════════════════════

class TestTrialGraph:
    """验证图结构完整性和全图 mock 运行"""

    def test_graph_build(self):
        graph = build_trial_graph_v2()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_full_graph_mock(self, initial_state):
        from backend.orchestration.workflow_v2 import run_trial_v2

        with patch("backend.agents.v2.skill.llm_call", new=_mock_llm_call):
            with patch("backend.agents.v2.base.llm_call", new=_mock_llm_call):
                with patch("backend.agents.v2.strategy.llm_call", new=_mock_llm_call):
                    state = initial_state.copy()
                    for _ in range(15):
                        state = await run_trial_v2(state)
                        cp = state["current_phase"]
                        if cp >= 8:
                            break
                        state[f"phase{cp}_confirmed"] = True
                    assert state["current_phase"] == 8
                    assert state.get("phase8_judgment")
                    assert "error" not in state or not state["error"]


# ═══════════════════════════════════════════════════════════
# 测试 5：单方对抗模式创建
# ═══════════════════════════════════════════════════════════

class TestAsymmetricModeCreation:
    """验证单方对抗模式案件创建流程"""

    def test_asymmetric_plaintiff_triggers_opponent_gen(self, client, auth_headers):
        with patch("backend.main.generate_opponent_materials", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "【mock 被告材料】核心主张：借款已还清..."
            resp = client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
                "case_title": "借款纠纷",
                "facts": "原告借给被告10万元。",
                "evidence": "借条",
                "claims": "归还借款",
                "mode": "asymmetric",
                "user_side": "plaintiff",
            })
            assert resp.status_code == 200
            assert "case_id" in resp.json()
            mock_gen.assert_awaited_once()

    def test_neutral_mode_no_opponent_gen(self, client, auth_headers):
        with patch("backend.main.generate_opponent_materials", new_callable=AsyncMock) as mock_gen:
            resp = client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
                "case_title": "借款纠纷",
                "facts": "原告借给被告10万元。",
                "evidence": "借条",
                "claims": "归还借款",
                "mode": "neutral",
            })
            assert resp.status_code == 200
            mock_gen.assert_not_awaited()

    def test_state_returns_mode_and_user_side(self, client, auth_headers):
        resp = client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
            "case_title": "测试",
            "facts": "f",
            "evidence": "e",
            "claims": "c",
            "mode": "asymmetric",
            "user_side": "plaintiff",
        })
        case_id = resp.json()["case_id"]
        state_resp = client.get(f"/trial/state/{case_id}", headers=auth_headers)
        assert state_resp.status_code == 200
        data = state_resp.json()
        assert data["mode"] == "asymmetric"
        assert data["user_side"] == "plaintiff"
