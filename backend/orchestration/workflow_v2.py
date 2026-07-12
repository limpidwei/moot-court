"""
LangGraph 多 Agent 庭审工作流 —— V2 版

基于 Actor-Memory-Skill 模型重构：
- Phase 1-5：真实多 Agent 交互（非单次 LLM）
- Phase 6：CommChannel 受控通信（peer visibility）
- Phase 7-8：Agent 自主 publish

兼容层：TrialState / TrialSession 字段不变，前端无感。
"""

import json
import logging
import re
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from ..models.case import CaseInput
from ..llm import LLMConfig
from ..streaming import put_event
from ..agents.v2 import (
    PlaintiffAgentV2,
    DefendantAgentV2,
    JudgeAgentV2,
    CommChannel,
    CourtReporterV2,
    AgentMessageV2,
)
from .workflow import (
    TrialState,
    PHASE_LABELS,
    needs_confirmation,
    _build_rag_context,
    _retry_async,
    _build_source_context,
)

logger = logging.getLogger(__name__)

# Phase 6 交叉询问安全上限（法官评估可在达到上限前自然结束）
MAX_CROSS_EXAM_ROUNDS = 8


def _get_case_attr(case, attr: str, default=""):
    """安全读取 case_input 的属性，兼容 dict 和 CaseInput 对象（LangGraph checkpoint 序列化后变为 dict）"""
    if case is None:
        return default
    if isinstance(case, dict):
        return case.get(attr, default)
    return getattr(case, attr, default)


def _ensure_case_input(state: TrialState) -> None:
    """确保 state['case_input'] 是 CaseInput 对象而非 dict（LangGraph checkpoint 会序列化 dataclass 为 dict）"""
    case = state.get("case_input")
    if isinstance(case, dict):
        state["case_input"] = CaseInput(**case)


# ============================================================
# Agent 恢复 / 保存（V2）
# ============================================================

def _restore_agents_v2(state: TrialState) -> dict:
    """从 state 恢复或新建 V2 Agent + CommChannel + Reporter"""
    llm_cfg = state.get("llm_config")

    plaintiff = PlaintiffAgentV2(llm_config=llm_cfg)
    defendant = DefendantAgentV2(llm_config=llm_cfg)
    judge = JudgeAgentV2(llm_config=llm_cfg)
    reporter = CourtReporterV2()
    channel = CommChannel()

    channel.register_reporter(reporter)
    channel.register_agent(plaintiff)
    channel.register_agent(defendant)
    channel.register_agent(judge)

    # 注入 channel
    plaintiff.channel = channel
    defendant.channel = channel
    judge.channel = channel

    # 恢复状态
    try:
        if state.get("plaintiff_state"):
            plaintiff.load_state(state["plaintiff_state"])
        if state.get("defendant_state"):
            defendant.load_state(state["defendant_state"])
        if state.get("judge_state"):
            judge.load_state(state["judge_state"])
        if state.get("reporter_state"):
            reporter = CourtReporterV2.from_dict(state["reporter_state"])
            channel.register_reporter(reporter)
    except Exception as e:
        logger.warning(f"恢复 V2 Agent 状态失败，将重新初始化: {e}")

    # 单方对抗模式：注入 AI 生成的对方材料到 opponent agent 的 private memory
    # H6 修复：load_state 已恢复含上次注入的 history，每次 _restore_agents_v2（8 阶段每阶段都会跑）
    # 若无条件 append 会重复注入 8+ 次导致 prompt 膿胀。仿 source_materials 写法加 already 去重。
    case = state.get("case_input")
    if case and case.mode == "asymmetric" and case.opponent_materials:
        _OPP_MARKER = "【庭前准备材料"
        if case.user_side == "plaintiff":
            already = any(
                msg.get("role") == "system" and _OPP_MARKER in msg.get("content", "")
                for msg in defendant.memory.private.history
            )
            if not already:
                defendant.memory.private.history.append({
                    "role": "system",
                    "content": f"【庭前准备材料：被告方诉讼策略与证据】\n\n{case.opponent_materials}",
                })
                logger.info("[V2] 注入对方材料到被告 agent private memory")
        elif case.user_side == "defendant":
            already = any(
                msg.get("role") == "system" and _OPP_MARKER in msg.get("content", "")
                for msg in plaintiff.memory.private.history
            )
            if not already:
                plaintiff.memory.private.history.append({
                    "role": "system",
                    "content": f"【庭前准备材料：原告方诉讼策略与证据】\n\n{case.opponent_materials}",
                })
                logger.info("[V2] 注入对方材料到原告 agent private memory")

    # 注入案卷原文到所有 Agent 的 private memory（双轨制）
    if case and case.source_materials:
        ctx = _build_source_context(case.source_materials)
        for agent in (plaintiff, defendant, judge):
            already = any(
                msg.get("role") == "system" and "【案卷原文】" in msg.get("content", "")
                for msg in agent.memory.private.history
            )
            if not already:
                agent.memory.private.history.append({"role": "system", "content": ctx})
        logger.info(f"[V2] 注入案卷原文到所有 Agent，长度={len(case.source_materials)}")

    return {
        "plaintiff": plaintiff,
        "defendant": defendant,
        "judge": judge,
        "reporter": reporter,
        "channel": channel,
    }


def _save_agents_v2(state: TrialState, agents: dict) -> None:
    state["plaintiff_state"] = agents["plaintiff"].to_state()
    state["defendant_state"] = agents["defendant"].to_state()
    state["judge_state"] = agents["judge"].to_state()
    state["reporter_state"] = agents["reporter"].to_dict()


def _sync_state_to_memory(agent, state: TrialState) -> None:
    """将 state 中的历史文书同步到 agent.memory.shared（兼容旧数据）"""
    # 原告 Phase 1 分析
    if state.get("phase1_analysis"):
        if not agent.memory.shared.get_by_phase(1):
            msg = AgentMessageV2(
                sender="plaintiff", recipient="all", msg_type="publish",
                content=state["phase1_analysis"], visibility="public",
                content_type="document", phase=1,
            )
            agent.memory.publish(msg)

    # 原告 Phase 2 起诉状
    if state.get("phase2_complaint"):
        if not agent.memory.shared.get_by_phase(2):
            msg = AgentMessageV2(
                sender="plaintiff", recipient="all", msg_type="publish",
                content=state["phase2_complaint"], visibility="public",
                content_type="document", phase=2,
            )
            agent.memory.publish(msg)

    # 原告 Phase 2 证据目录
    if state.get("phase2_evidence_catalog"):
        if not agent.memory.shared.get_by_phase_and_type(2, "evidence_catalog"):
            msg = AgentMessageV2(
                sender="plaintiff", recipient="all", msg_type="publish",
                content=state["phase2_evidence_catalog"], visibility="public",
                content_type="evidence_catalog", phase=2,
            )
            agent.memory.publish(msg)

    # 被告 Phase 3 答辩策略
    if state.get("phase3_analysis"):
        if not agent.memory.shared.get_by_phase(3):
            msg = AgentMessageV2(
                sender="defendant", recipient="all", msg_type="publish",
                content=state["phase3_analysis"], visibility="public",
                content_type="document", phase=3,
            )
            agent.memory.publish(msg)

    # 被告 Phase 4 答辩状
    if state.get("phase4_answer"):
        if not agent.memory.shared.get_by_phase(4):
            msg = AgentMessageV2(
                sender="defendant", recipient="all", msg_type="publish",
                content=state["phase4_answer"], visibility="public",
                content_type="document", phase=4,
            )
            agent.memory.publish(msg)

    # 被告 Phase 4 证据目录
    if state.get("phase4_evidence_catalog"):
        if not agent.memory.shared.get_by_phase_and_type(4, "evidence_catalog"):
            msg = AgentMessageV2(
                sender="defendant", recipient="all", msg_type="publish",
                content=state["phase4_evidence_catalog"], visibility="public",
                content_type="evidence_catalog", phase=4,
            )
            agent.memory.publish(msg)

    # 法官 Phase 5 争议焦点
    if state.get("phase5_issues"):
        if not agent.memory.shared.get_by_phase(5):
            msg = AgentMessageV2(
                sender="judge", recipient="all", msg_type="publish",
                content=state["phase5_issues"], visibility="public",
                content_type="document", phase=5,
            )
            agent.memory.publish(msg)

    # Phase 6 交叉询问
    if state.get("phase6_cross_exam"):
        if not agent.memory.shared.get_by_phase(6):
            msg = AgentMessageV2(
                sender="judge", recipient="all", msg_type="publish",
                content=state["phase6_cross_exam"], visibility="public",
                content_type="document", phase=6,
            )
            agent.memory.publish(msg)

    # Phase 6 举证质证
    if state.get("phase6_evidence_exam"):
        if not any(d.phase == 6 and d.content_type == "evidence_exam" for d in agent.memory.shared.documents):
            msg = AgentMessageV2(
                sender="judge", recipient="all", msg_type="publish",
                content=state["phase6_evidence_exam"], visibility="public",
                content_type="evidence_exam", phase=6,
            )
            agent.memory.publish(msg)

    # Phase 7 最后陈述
    if state.get("phase7_plaintiff_final"):
        if not any(d.phase == 7 and d.sender == "plaintiff" for d in agent.memory.shared.documents):
            msg = AgentMessageV2(
                sender="plaintiff", recipient="all", msg_type="publish",
                content=state["phase7_plaintiff_final"], visibility="public",
                content_type="document", phase=7,
            )
            agent.memory.publish(msg)
    if state.get("phase7_defendant_final"):
        if not any(d.phase == 7 and d.sender == "defendant" for d in agent.memory.shared.documents):
            msg = AgentMessageV2(
                sender="defendant", recipient="all", msg_type="publish",
                content=state["phase7_defendant_final"], visibility="public",
                content_type="document", phase=7,
            )
            agent.memory.publish(msg)


def _phase_context(state: TrialState) -> str:
    """构建 Phase 6 通用庭审背景"""
    case = state["case_input"]
    complaint = state.get("phase2_complaint", "")
    answer = state.get("phase4_answer", "")
    return f"""案由：{case.case_title}
争议焦点：{state.get("phase5_issues", "")}
原告起诉状要点：{complaint[:2000] if len(complaint) > 2000 else complaint}
被告答辩状要点：{answer[:2000] if len(answer) > 2000 else answer}"""


# ============================================================
# Phase 1-2：原告庭前准备
# ============================================================

async def phase1_node_v2(state: TrialState) -> TrialState:
    """Phase 1: 原告请求权基础分析 + 策略制定"""
    if state.get("phase1_analysis") and state.get("phase1_confirmed"):
        return state

    put_event({"type": "phase_start", "phase": 1, "label": PHASE_LABELS[1]})
    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    plaintiff = agents["plaintiff"]
    case = state["case_input"]
    logger.info(f"[V2 Phase1] mode={case.mode} user_side={case.user_side} user_role={state.get('user_role')} phase1_confirmed={state.get('phase1_confirmed')}")

    try:
        # RAG
        legal_context = _build_rag_context(
            case.case_title, case.facts, case.claims, phase=1
        )
        if legal_context:
            plaintiff.memory.private.legal_notes = legal_context

        # 单方对抗模式：生成策略路线供用户选择
        if case.mode == "asymmetric" and case.user_side == "plaintiff":
            # 如果还没有生成策略路线，先生成
            if not state.get("phase1_strategy_routes"):
                routes = await plaintiff.generate_strategy_routes(case)
                state["phase1_strategy_routes"] = [r.to_dict() for r in routes]
                logger.info(f"[V2] 原告生成 {len(routes)} 条策略路线")

            # 如果还没有选择策略，暂停等待用户选择
            if not state.get("phase1_selected_route"):
                state["phase1_strategy_pending"] = True
                state["current_phase"] = 1  # 设置 current_phase 以便前端展示策略卡片
                put_event({
                    "type": "awaiting_strategy_selection",
                    "phase": 1,
                    "routes": state["phase1_strategy_routes"],
                })
                logger.info("[V2] Phase 1 等待用户选择策略路线")
                _save_agents_v2(state, agents)
                return state

            # 已选择策略，设置 strategy_notes
            routes_data = state.get("phase1_strategy_routes", [])
            selected_route_id = state.get("phase1_selected_route")
            selected = next((r for r in routes_data if r.get("route_id") == selected_route_id), None)
            if selected:
                plaintiff.memory.private.strategy_notes = (
                    f"选定策略路线 [{selected['route_id']}]：{selected['title']}\n"
                    f"核心主张：{selected['core_theory']}\n"
                    f"法律依据：{selected['legal_basis']}\n"
                    f"证据策略：{selected['evidence_strategy']}"
                )
                logger.info(f"[V2] 原告使用已选策略路线 {selected_route_id}")

        # 策略制定
        strategy = await plaintiff.formulate_strategy(case)
        logger.info(f"[V2] 原告策略: {strategy.core_theory[:60]}...")

        # 请求权基础分析
        result = await plaintiff.analyze_claims(case)
        state["phase1_analysis"] = result
        state["current_phase"] = 1
        state["phase1_strategy_pending"] = False

        # 发布到 shared
        plaintiff.publish(result, "document", phase=1)

    except Exception as e:
        logger.error(f"Phase 1 V2 error: {e}")
        state["error"] = f"Phase 1 失败: {e}"

    _save_agents_v2(state, agents)
    return state


async def phase2_node_v2(state: TrialState) -> TrialState:
    """Phase 2: 原告起诉状 + 证据目录"""
    if state.get("phase2_complaint") and state.get("phase2_confirmed"):
        return state

    put_event({"type": "phase_start", "phase": 2, "label": PHASE_LABELS[2]})
    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    plaintiff = agents["plaintiff"]
    case = state["case_input"]

    try:
        # 起诉状
        complaint = await plaintiff.draft_complaint(
            state["phase1_analysis"], case.claims, case.evidence
        )
        state["phase2_complaint"] = complaint
        plaintiff.publish(complaint, "document", phase=2)

        # 证据目录
        catalog = await plaintiff.draft_evidence_catalog(case.evidence)
        state["phase2_evidence_catalog"] = catalog
        plaintiff.publish(catalog, "evidence_catalog", phase=2)

        state["current_phase"] = 2
    except Exception as e:
        logger.error(f"Phase 2 V2 error: {e}")
        state["error"] = f"Phase 2 失败: {e}"

    _save_agents_v2(state, agents)
    return state


# ============================================================
# Phase 3-4：被告庭前准备
# ============================================================

async def phase3_node_v2(state: TrialState) -> TrialState:
    """Phase 3: 被告答辩策略分析

    被告从 memory.shared 读取原告已发布的起诉状，自主制定答辩策略。
    """
    if state.get("phase3_analysis") and state.get("phase3_confirmed"):
        return state

    put_event({"type": "phase_start", "phase": 3, "label": PHASE_LABELS[3]})
    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    defendant = agents["defendant"]
    case = state["case_input"]
    logger.info(f"[V2 Phase3] mode={case.mode} user_side={case.user_side} user_role={state.get('user_role')} phase3_confirmed={state.get('phase3_confirmed')}")

    try:
        # 兼容：将 state 中的历史文书同步到被告 memory.shared
        _sync_state_to_memory(defendant, state)

        # RAG
        legal_context = _build_rag_context(
            case.case_title, case.facts, case.claims, phase=3
        )
        if legal_context:
            defendant.memory.private.legal_notes = legal_context

        # 单方对抗模式：生成策略路线供用户选择
        if case.mode == "asymmetric" and case.user_side == "defendant":
            # 如果还没有生成策略路线，先生成
            if not state.get("phase3_strategy_routes"):
                routes = await defendant.generate_strategy_routes(case)
                state["phase3_strategy_routes"] = [r.to_dict() for r in routes]
                logger.info(f"[V2] 被告生成 {len(routes)} 条策略路线")

            # 如果还没有选择策略，暂停等待用户选择
            if not state.get("phase3_selected_route"):
                state["phase3_strategy_pending"] = True
                state["current_phase"] = 3  # 设置 current_phase 以便前端展示策略卡片
                put_event({
                    "type": "awaiting_strategy_selection",
                    "phase": 3,
                    "routes": state["phase3_strategy_routes"],
                })
                logger.info("[V2] Phase 3 等待用户选择策略路线")
                _save_agents_v2(state, agents)
                return state

            # 已选择策略，设置 strategy_notes
            routes_data = state.get("phase3_strategy_routes", [])
            selected_route_id = state.get("phase3_selected_route")
            selected = next((r for r in routes_data if r.get("route_id") == selected_route_id), None)
            if selected:
                defendant.memory.private.strategy_notes = (
                    f"选定策略路线 [{selected['route_id']}]：{selected['title']}\n"
                    f"核心主张：{selected['core_theory']}\n"
                    f"法律依据：{selected['legal_basis']}\n"
                    f"证据策略：{selected['evidence_strategy']}"
                )
                logger.info(f"[V2] 被告使用已选策略路线 {selected_route_id}")

        # 策略制定
        strategy = await defendant.formulate_strategy(case)
        logger.info(f"[V2] 被告策略: {strategy.core_theory[:60]}...")

        # 答辩策略分析：被告自主从 shared 读取原告起诉状
        result = await defendant.analyze_defense(case)
        state["phase3_analysis"] = result
        state["current_phase"] = 3
        state["phase3_strategy_pending"] = False

        defendant.publish(result, "document", phase=3)

    except Exception as e:
        logger.error(f"Phase 3 V2 error: {e}")
        state["error"] = f"Phase 3 失败: {e}"

    _save_agents_v2(state, agents)
    return state


async def phase4_node_v2(state: TrialState) -> TrialState:
    """Phase 4: 被告答辩状 + 证据目录

    被告从 memory 读取自己的答辩策略和原告起诉状，自主撰写答辩状。
    """
    if state.get("phase4_answer") and state.get("phase4_confirmed"):
        return state

    put_event({"type": "phase_start", "phase": 4, "label": PHASE_LABELS[4]})
    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    defendant = agents["defendant"]

    try:
        # 兼容：确保被告 memory 中有自己的 Phase 3 策略和原告 Phase 2 起诉状
        _sync_state_to_memory(defendant, state)

        answer = await defendant.draft_answer(state["case_input"])
        state["phase4_answer"] = answer
        defendant.publish(answer, "document", phase=4)

        intensity = getattr(state["case_input"], "adversarial_intensity", 3)
        catalog = await defendant.draft_evidence_catalog(
            state["case_input"].evidence,
            case_input=state["case_input"],
            intensity=intensity,
        )
        state["phase4_evidence_catalog"] = catalog
        defendant.publish(catalog, "evidence_catalog", phase=4)

        state["current_phase"] = 4
    except Exception as e:
        logger.error(f"Phase 4 V2 error: {e}")
        state["error"] = f"Phase 4 失败: {e}"

    _save_agents_v2(state, agents)
    return state


# ============================================================
# Phase 5：法官归纳争议焦点
# ============================================================

async def phase5_node_v2(state: TrialState) -> TrialState:
    """Phase 5: 法官读取双方 shared 后归纳争议焦点

    法官自主从 memory.shared 读取双方已公开的起诉状和答辩状。
    """
    if state.get("phase5_issues") and state.get("phase5_confirmed"):
        return state

    put_event({"type": "phase_start", "phase": 5, "label": PHASE_LABELS[5]})
    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    judge = agents["judge"]
    case = state["case_input"]

    try:
        # 兼容：将 state 中的历史文书同步到法官 memory.shared
        _sync_state_to_memory(judge, state)

        # RAG
        legal_context = _build_rag_context(
            case.case_title, case.facts, case.claims, phase=5
        )
        if legal_context:
            judge.memory.private.legal_notes = legal_context

        # 法官自主从 shared 读取双方文书
        result = await judge.summarize_issues()
        state["phase5_issues"] = result
        state["current_phase"] = 5

        judge.publish(result, "document", phase=5)

    except Exception as e:
        logger.error(f"Phase 5 V2 error: {e}")
        state["error"] = f"Phase 5 失败: {e}"

    _save_agents_v2(state, agents)
    return state


# ============================================================
# 辅助函数：限制 LLM 输出长度与问题数量
# ============================================================

def _extract_first_question(text: str) -> str:
    """从 LLM 输出中提取第一个有效问题，防止一次输出多个问题。"""
    text = text.strip()
    if not text:
        return text
    # 按常见分隔符分割（换行、数字编号、项目符号）
    parts = re.split(r'\n+|(?:\d+[.．、]|\([\d一二三四五六七八九十]+\)|[一二三四五六七八九十][、．])\s+', text)
    for part in parts:
        part = part.strip()
        # 有效问题至少 8 个字符且包含问号
        if len(part) >= 8 and ('？' in part or '?' in part):
            return part
    # 回退：返回第一段非空文本
    for part in parts:
        part = part.strip()
        if len(part) >= 8:
            return part
    return text[:200]


# ============================================================
# Phase 6A：交叉询问（CommChannel peer 通信）
# ============================================================

def _format_cross_exam_json(reporter: CourtReporterV2) -> str:
    """将 cross exam log 转为前端可用的 JSON 数组"""
    logs = reporter.get_cross_exam_log()
    entries = []
    for m in logs:
        entries.append({
            "speaker": m.sender,
            "type": m.msg_type,
            "content": m.content,
            "round": m.round_num,
        })
    return json.dumps(entries, ensure_ascii=False)


async def cross_exam_round_node_v2(state: TrialState) -> TrialState:
    """V2 交叉询问：通过 CommChannel 发送 peer 消息"""
    if state.get("cross_exam_round", 0) >= MAX_CROSS_EXAM_ROUNDS:
        return state

    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    plaintiff = agents["plaintiff"]
    defendant = agents["defendant"]
    judge = agents["judge"]
    reporter = agents["reporter"]
    channel = agents["channel"]

    r = state["cross_exam_round"] + 1
    state["cross_exam_round"] = r
    put_event({"type": "phase_progress", "phase": 6, "label": f"交叉询问 第{r}轮", "round": r})

    context = _phase_context(state)

    try:
        if r <= 2:
            # --- Round 1-2: 原告提问 → 被告回答 ---
            q_text_raw = await _retry_async(plaintiff.cross_exam_question, 2, context, r)
            q_text = _extract_first_question(q_text_raw)
            msg_q = AgentMessageV2(
                sender="plaintiff", recipient="defendant",
                msg_type="question", content=q_text,
                visibility="peer", content_type="question",
                phase=6, round_num=r,
            )
            channel.dispatch(msg_q)
            reporter.record(msg_q)
            put_event({"type": "agent_step", "phase": 6, "round": r, "speaker": "plaintiff", "msg_type": "question", "content": q_text})

            g1_text = await _retry_async(judge.moderate_cross_exam, 2, msg_q, context)
            msg_g1 = AgentMessageV2(
                sender="judge", recipient="all",
                msg_type="guidance", content=g1_text,
                visibility="public", content_type="guidance",
                phase=6, round_num=r,
            )
            channel.dispatch(msg_g1)
            reporter.record(msg_g1)
            put_event({"type": "agent_step", "phase": 6, "round": r, "speaker": "judge", "msg_type": "guidance", "content": g1_text})

            a_text = await _retry_async(defendant.cross_exam_answer, 2)
            msg_a = AgentMessageV2(
                sender="defendant", recipient="plaintiff",
                msg_type="answer", content=a_text,
                visibility="peer", content_type="answer",
                phase=6, round_num=r,
            )
            channel.dispatch(msg_a)
            reporter.record(msg_a)
            put_event({"type": "agent_step", "phase": 6, "round": r, "speaker": "defendant", "msg_type": "answer", "content": a_text})

            g2_text = await _retry_async(judge.moderate_cross_exam, 2, msg_a, context)
            msg_g2 = AgentMessageV2(
                sender="judge", recipient="all",
                msg_type="guidance", content=g2_text,
                visibility="public", content_type="guidance",
                phase=6, round_num=r,
            )
            channel.dispatch(msg_g2)
            reporter.record(msg_g2)
            put_event({"type": "agent_step", "phase": 6, "round": r, "speaker": "judge", "msg_type": "guidance", "content": g2_text})
        else:
            # --- Round 3-4: 被告提问 → 原告回答 ---
            q_text_raw = await _retry_async(defendant.cross_exam_question, 2, context, r)
            q_text = _extract_first_question(q_text_raw)
            msg_q = AgentMessageV2(
                sender="defendant", recipient="plaintiff",
                msg_type="question", content=q_text,
                visibility="peer", content_type="question",
                phase=6, round_num=r,
            )
            channel.dispatch(msg_q)
            reporter.record(msg_q)
            put_event({"type": "agent_step", "phase": 6, "round": r, "speaker": "defendant", "msg_type": "question", "content": q_text})

            g1_text = await _retry_async(judge.moderate_cross_exam, 2, msg_q, context)
            msg_g1 = AgentMessageV2(
                sender="judge", recipient="all",
                msg_type="guidance", content=g1_text,
                visibility="public", content_type="guidance",
                phase=6, round_num=r,
            )
            channel.dispatch(msg_g1)
            reporter.record(msg_g1)
            put_event({"type": "agent_step", "phase": 6, "round": r, "speaker": "judge", "msg_type": "guidance", "content": g1_text})

            a_text = await _retry_async(plaintiff.cross_exam_answer, 2)
            msg_a = AgentMessageV2(
                sender="plaintiff", recipient="defendant",
                msg_type="answer", content=a_text,
                visibility="peer", content_type="answer",
                phase=6, round_num=r,
            )
            channel.dispatch(msg_a)
            reporter.record(msg_a)
            put_event({"type": "agent_step", "phase": 6, "round": r, "speaker": "plaintiff", "msg_type": "answer", "content": a_text})

            g2_text = await _retry_async(judge.moderate_cross_exam, 2, msg_a, context)
            msg_g2 = AgentMessageV2(
                sender="judge", recipient="all",
                msg_type="guidance", content=g2_text,
                visibility="public", content_type="guidance",
                phase=6, round_num=r,
            )
            channel.dispatch(msg_g2)
            reporter.record(msg_g2)
            put_event({"type": "agent_step", "phase": 6, "round": r, "speaker": "judge", "msg_type": "guidance", "content": g2_text})

        state["phase6_cross_exam"] = _format_cross_exam_json(reporter)
        put_event({"type": "agent_step_done", "phase": 6, "round": r})

        # 自适应停止：内容重复/空洞
        if r >= 2:
            recent_q = [
                m.content for m in reporter.ledger
                if m.phase == 6 and m.content_type == "question"
            ][-2:]
            if len(recent_q) == 2:
                q1, q2 = recent_q
                if len(q2.strip()) < 20 or q1.strip() == q2.strip():
                    logger.info(f"Adaptive stop at round {r} (duplicate/empty)")
                    state["cross_exam_round"] = MAX_CROSS_EXAM_ROUNDS

        # 法官全局评估：每 2 轮评估一次是否还有新议题
        if r >= 2 and r % 2 == 0 and r < MAX_CROSS_EXAM_ROUNDS:
            recent_log = []
            for m in reporter.ledger:
                if m.phase == 6 and m.round_num >= r - 1:
                    recent_log.append(f"{m.sender} ({m.msg_type}): {m.content[:300]}")
            if recent_log:
                try:
                    should_continue = await judge.should_continue_cross_exam(recent_log, context)
                    if not should_continue:
                        logger.info(f"Judge global stop at round {r}")
                        state["cross_exam_round"] = MAX_CROSS_EXAM_ROUNDS
                        put_event({"type": "phase_progress", "phase": 6, "label": f"交叉询问结束（第{r}轮）", "round": r})
                except Exception as eval_err:
                    logger.warning(f"Judge continue evaluation failed at round {r}: {eval_err}")
    except Exception as e:
        logger.exception(f"Cross exam round {r} V2 error: {e}")
        state["error"] = f"交叉询问第{r}轮失败: {e}"
        put_event({"type": "error", "phase": 6, "round": r, "message": str(e)})

    _save_agents_v2(state, agents)
    return state


def cross_exam_router_v2(state: TrialState) -> str:
    if state.get("error"):
        return "end_cross_exam"
    if state["cross_exam_round"] >= MAX_CROSS_EXAM_ROUNDS:
        return "end_cross_exam"
    return "next_round"


# ============================================================
# Phase 6B：举证质证（CommChannel peer 通信）
# ============================================================

def _format_evidence_exam_json(reporter: CourtReporterV2) -> str:
    """将 evidence exam log 转为前端可用的 JSON 数组"""
    logs = [m for m in reporter.ledger if m.phase == 6 and m.evidence_ref]
    entries = []
    seen = set()
    for m in logs:
        if m.msg_type == "guidance" and m.sender == "judge":
            msg_type = "focus"
        elif m.msg_type == "evidence_opinion" and m.sender == "plaintiff":
            msg_type = "comment"
        elif m.msg_type == "evidence_opinion" and m.sender == "defendant":
            msg_type = "cross_examine"
        elif m.msg_type == "ruling" and m.sender == "judge":
            msg_type = "ruling"
        else:
            continue
        key = (m.evidence_ref, m.sender, msg_type)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "item": m.evidence_ref,
            "speaker": m.sender,
            "type": msg_type,
            "content": m.content,
        })
    return json.dumps(entries, ensure_ascii=False)


async def evidence_exam_batch_node_v2(state: TrialState) -> TrialState:
    """V2 举证质证：法官 focus → 原告 comment → 被告 cross → 法官 ruling"""
    evidence_items = state.get("evidence_list", [])
    if evidence_items and state.get("current_evidence_index", 0) >= len(evidence_items):
        return state

    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    plaintiff = agents["plaintiff"]
    defendant = agents["defendant"]
    judge = agents["judge"]
    reporter = agents["reporter"]
    channel = agents["channel"]
    case = state["case_input"]
    idx = state.get("current_evidence_index", 0)

    if not evidence_items:
        # 改进证据解析：支持换行、编号列表、逗号/分号分隔
        raw = case.evidence or ""
        # 先尝试按编号列表分割（1. 2. 3. / 一、二、三、/ (1) (2) 等）
        import re
        numbered = re.split(r'\n\s*(?:\d+[.．、]|\([\d一二三四五六七八九十]+\)|[一二三四五六七八九十][、．])\s*', raw)
        if len(numbered) > 2:
            items = [s.strip() for s in numbered if s.strip()]
        else:
            # 回退到换行分割，并尝试逗号/分号二次分割（针对单行密集输入）
            lines = [s.strip() for s in raw.split("\n") if s.strip()]
            items = []
            for line in lines:
                if len(line) > 40 and ("，" in line or "；" in line or "," in line):
                    # 单行过长且含分隔符，尝试二次分割
                    split_by_sep = re.split(r'[,，;；、]\s*', line)
                    items.extend(s.strip() for s in split_by_sep if len(s.strip()) > 2)
                else:
                    items.append(line)
        evidence_items = list(dict.fromkeys(items))
        state["evidence_list"] = evidence_items

    if idx >= len(evidence_items):
        _save_agents_v2(state, agents)
        return state

    BATCH_SIZE = 3
    batch = evidence_items[idx : idx + BATCH_SIZE]
    batch_num = (idx // BATCH_SIZE) + 1
    total_batches = (len(evidence_items) + BATCH_SIZE - 1) // BATCH_SIZE
    put_event({"type": "phase_progress", "phase": 6, "label": f"举证质证 批次{batch_num}/{total_batches}", "item": idx})

    context = _phase_context(state)

    def _is_evidence_fully_recorded(evidence_item: str) -> bool:
        steps = {("judge", "guidance"), ("plaintiff", "evidence_opinion"), ("defendant", "evidence_opinion"), ("judge", "ruling")}
        recorded = {(m.sender, m.msg_type) for m in reporter.ledger if m.phase == 6 and m.evidence_ref == evidence_item}
        return steps.issubset(recorded)

    async def process_one(evidence_item: str, item_idx: int):
        if _is_evidence_fully_recorded(evidence_item):
            logger.info(f"Evidence '{evidence_item[:30]}...' already fully processed, skipping")
            return
        # 法官 focus
        focus_text = await _retry_async(judge.summarize_evidence_focus, 2, evidence_item, context)
        msg_focus = AgentMessageV2(
            sender="judge", recipient="all",
            msg_type="guidance", content=focus_text,
            visibility="public", content_type="guidance",
            phase=6, evidence_ref=evidence_item,
        )
        channel.dispatch(msg_focus)
        reporter.record(msg_focus)
        put_event({"type": "agent_step", "phase": 6, "item": item_idx + 1, "speaker": "judge", "msg_type": "guidance", "content": focus_text})

        # 原告 comment（作为 peer 消息发给被告）
        p_text = await _retry_async(plaintiff.comment_on_evidence, 2, evidence_item, context)
        msg_p = AgentMessageV2(
            sender="plaintiff", recipient="defendant",
            msg_type="evidence_opinion", content=p_text,
            visibility="peer", content_type="evidence_opinion",
            phase=6, evidence_ref=evidence_item,
        )
        channel.dispatch(msg_p)
        reporter.record(msg_p)
        put_event({"type": "agent_step", "phase": 6, "item": item_idx + 1, "speaker": "plaintiff", "msg_type": "evidence_opinion", "content": p_text})

        # 被告 cross examine（作为 peer 消息发给原告；被告从 inbox 读取原告 comment）
        d_text = await _retry_async(defendant.cross_examine_evidence, 2, evidence_item, context)
        msg_d = AgentMessageV2(
            sender="defendant", recipient="plaintiff",
            msg_type="evidence_opinion", content=d_text,
            visibility="peer", content_type="evidence_opinion",
            phase=6, evidence_ref=evidence_item,
        )
        channel.dispatch(msg_d)
        reporter.record(msg_d)
        put_event({"type": "agent_step", "phase": 6, "item": item_idx + 1, "speaker": "defendant", "msg_type": "evidence_opinion", "content": d_text})

        # 法官 ruling（public）
        ruling_text = await _retry_async(judge.ruling_on_evidence, 2, evidence_item, False)
        msg_r = AgentMessageV2(
            sender="judge", recipient="all",
            msg_type="ruling", content=ruling_text,
            visibility="public", content_type="ruling",
            phase=6, evidence_ref=evidence_item,
        )
        channel.dispatch(msg_r)
        reporter.record(msg_r)
        put_event({"type": "agent_step", "phase": 6, "item": item_idx + 1, "speaker": "judge", "msg_type": "ruling", "content": ruling_text})

    # H7 修复：原先 asyncio.gather 并行处理多证据项共享 agent/channel/state，
    # 协程交错 await 期间相互改写共享 memory/state 且 _save_agents_v2 并发写导致竞态。
    # 改为串行逐项，保持「真实 Agent 逐项交互」设计原意。
    for i, item in enumerate(batch):
        try:
            await process_one(item, idx + i)
        except Exception as e:
            logger.exception(f"Evidence exam item {idx + i} error: {e}")
            put_event({"type": "error", "phase": 6, "item": idx + i, "message": str(e)})
    # 即使单条失败也推进进度、保存状态，避免整个批次阻塞
    state["current_evidence_index"] = idx + len(batch)
    state["phase6_evidence_exam"] = _format_evidence_exam_json(reporter)
    put_event({"type": "agent_step_done", "phase": 6, "item": idx + len(batch)})

    _save_agents_v2(state, agents)
    return state


def evidence_exam_router_v2(state: TrialState) -> str:
    if state.get("error"):
        return "end_evidence_exam"
    evidence_items = state.get("evidence_list", [])
    if not evidence_items:
        return "next_item"
    if state["current_evidence_index"] >= len(evidence_items):
        return "end_evidence_exam"
    return "next_item"


# ============================================================
# Phase 7-8
# ============================================================

async def phase7_node_v2(state: TrialState) -> TrialState:
    """Phase 7: 双方最后陈述（顺序多 Agent 交互）

    1. 原告 Agent 先生成最后陈述
    2. 通过 CommChannel 广播到所有 Agent 的 shared 层
    3. 被告 Agent 读取原告陈述后，生成自己的最后陈述（可针对性回应）
    """
    put_event({"type": "phase_start", "phase": 7, "label": PHASE_LABELS[7]})
    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    plaintiff = agents["plaintiff"]
    defendant = agents["defendant"]
    reporter = agents["reporter"]
    channel = agents["channel"]
    case = state["case_input"]

    try:
        # 同步 Phase 6 庭审记录到双方 memory，确保最后陈述能看到完整庭审上下文
        _sync_state_to_memory(plaintiff, state)
        _sync_state_to_memory(defendant, state)

        # Step 1: 原告最后陈述
        pf = await plaintiff.final_statement(case.case_title, case.claims)
        state["phase7_plaintiff_final"] = pf
        msg_pf = AgentMessageV2(
            sender="plaintiff", recipient="all",
            msg_type="statement", content=pf,
            visibility="public", content_type="document",
            phase=7,
        )
        channel.dispatch(msg_pf)
        reporter.record(msg_pf)

        # Step 2: 被告最后陈述（基于原告陈述，通过 shared memory 感知）
        df = await defendant.final_statement(case.case_title, case.claims)
        state["phase7_defendant_final"] = df
        msg_df = AgentMessageV2(
            sender="defendant", recipient="all",
            msg_type="statement", content=df,
            visibility="public", content_type="document",
            phase=7,
        )
        channel.dispatch(msg_df)
        reporter.record(msg_df)

        state["current_phase"] = 7
    except Exception as e:
        logger.error(f"Phase 7 V2 error: {e}")
        state["error"] = f"Phase 7 失败: {e}"

    _save_agents_v2(state, agents)
    return state


async def phase8_node_v2(state: TrialState) -> TrialState:
    """Phase 8: 法官判决

    法官自主从 memory.shared 读取庭审全部材料。
    """
    put_event({"type": "phase_start", "phase": 8, "label": PHASE_LABELS[8]})
    _ensure_case_input(state)
    agents = _restore_agents_v2(state)
    judge = agents["judge"]
    reporter = agents["reporter"]
    channel = agents["channel"]
    case = state["case_input"]

    try:
        # 兼容：将 state 中的历史文书同步到法官 memory.shared
        _sync_state_to_memory(judge, state)

        legal_context = _build_rag_context(
            case.case_title, case.facts, case.claims, phase=8
        )
        if legal_context:
            judge.memory.private.legal_notes = legal_context

        result = await judge.render_judgment()
        state["phase8_judgment"] = result
        state["current_phase"] = 8

        # 胜率提取（同 V1 逻辑）
        import re
        for p in [
            r"综合胜率[^\d]*(\d+(?:\.\d+)?)\s*%",
            r"综合胜率.*?(\d+(?:\.\d+)?)\s*%",
        ]:
            m = re.search(p, result)
            if m:
                state["phase8_win_rate"] = float(m.group(1))
                break

        msg_j = AgentMessageV2(
            sender="judge", recipient="all",
            msg_type="document", content=result,
            visibility="public", content_type="document",
            phase=8,
        )
        channel.dispatch(msg_j)
        reporter.record(msg_j)

    except Exception as e:
        logger.error(f"Phase 8 V2 error: {e}")
        state["error"] = f"Phase 8 失败: {e}"

    _save_agents_v2(state, agents)
    return state


# ============================================================
# Phase 6 完成节点
# ============================================================

async def phase6_complete_node_v2(state: TrialState) -> TrialState:
    state["current_phase"] = 6
    return state


def should_pause_after_phase1_v2(state: TrialState) -> str:
    if state.get("phase1_strategy_pending"):
        return "pause"
    if needs_confirmation(1, state["user_role"]) and not state.get("phase1_confirmed"):
        return "pause"
    return "continue"


def should_pause_after_phase2_v2(state: TrialState) -> str:
    if needs_confirmation(2, state["user_role"]) and not state.get("phase2_confirmed"):
        return "pause"
    return "continue"


def should_pause_after_phase3_v2(state: TrialState) -> str:
    if state.get("phase3_strategy_pending"):
        return "pause"
    if needs_confirmation(3, state["user_role"]) and not state.get("phase3_confirmed"):
        return "pause"
    return "continue"


def should_pause_after_phase4_v2(state: TrialState) -> str:
    if needs_confirmation(4, state["user_role"]) and not state.get("phase4_confirmed"):
        return "pause"
    return "continue"


def should_pause_after_phase5_v2(state: TrialState) -> str:
    if needs_confirmation(5, state["user_role"]) and not state.get("phase5_confirmed"):
        return "pause"
    return "continue"


def should_pause_after_phase6_v2(state: TrialState) -> str:
    if needs_confirmation(6, state["user_role"]) and not state.get("phase6_confirmed"):
        return "pause"
    return "continue"


def should_pause_after_phase7_v2(state: TrialState) -> str:
    if needs_confirmation(7, state["user_role"]) and not state.get("phase7_confirmed"):
        return "pause"
    return "continue"


# ============================================================
# 构建 StateGraph
# ============================================================

def build_trial_graph_v2() -> StateGraph:
    """构建 V2 版 StateGraph"""
    builder = StateGraph(TrialState)

    builder.add_node("phase1", phase1_node_v2)
    builder.add_node("phase2", phase2_node_v2)
    builder.add_node("phase3", phase3_node_v2)
    builder.add_node("phase4", phase4_node_v2)
    builder.add_node("phase5", phase5_node_v2)
    builder.add_node("cross_exam_round", cross_exam_round_node_v2)
    builder.add_node("evidence_exam_batch", evidence_exam_batch_node_v2)
    builder.add_node("phase7", phase7_node_v2)
    builder.add_node("phase8", phase8_node_v2)

    # 顺序边 Phase 1-5
    builder.add_edge(START, "phase1")
    builder.add_conditional_edges(
        "phase1", should_pause_after_phase1_v2,
        {"pause": END, "continue": "phase2"}
    )
    builder.add_conditional_edges(
        "phase2", should_pause_after_phase2_v2,
        {"pause": END, "continue": "phase3"}
    )
    builder.add_conditional_edges(
        "phase3", should_pause_after_phase3_v2,
        {"pause": END, "continue": "phase4"}
    )
    builder.add_conditional_edges(
        "phase4", should_pause_after_phase4_v2,
        {"pause": END, "continue": "phase5"}
    )
    builder.add_conditional_edges(
        "phase5", should_pause_after_phase5_v2,
        {"pause": END, "continue": "cross_exam_round"}
    )

    # Phase 6 循环
    builder.add_conditional_edges(
        "cross_exam_round", cross_exam_router_v2,
        {"next_round": "cross_exam_round", "end_cross_exam": "evidence_exam_batch"},
    )
    builder.add_conditional_edges(
        "evidence_exam_batch", evidence_exam_router_v2,
        {"next_item": "evidence_exam_batch", "end_evidence_exam": "phase6_complete"},
    )
    builder.add_node("phase6_complete", phase6_complete_node_v2)
    builder.add_conditional_edges(
        "phase6_complete", should_pause_after_phase6_v2,
        {"pause": END, "continue": "phase7"}
    )

    # Phase 7-8
    builder.add_conditional_edges(
        "phase7", should_pause_after_phase7_v2,
        {"pause": END, "continue": "phase8"}
    )
    builder.add_edge("phase8", END)

    return builder


# 编译图
_trial_graph_v2 = build_trial_graph_v2().compile()


async def run_trial_v2(state: TrialState) -> TrialState:
    """运行 V2 庭审工作流"""
    _ensure_case_input(state)
    try:
        result = await _trial_graph_v2.ainvoke(state)
        return result
    except Exception as e:
        logger.error(f"V2 Graph execution error: {e}")
        state["error"] = str(e)
        return state
