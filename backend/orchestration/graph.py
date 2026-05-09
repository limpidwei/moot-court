"""
LangGraph 庭审状态机 v2.0

8 阶段 + 分步确认 + 交叉询问 + 证据目录

流程：

Phase 1  ─ 原告律师：请求权基础分析    [用户确认]
Phase 2  ─ 原告律师：起诉状 + 证据目录   [用户确认]
Phase 3  ─ 被告律师：答辩策略分析        [用户确认]
Phase 4  ─ 被告律师：答辩状 + 证据目录   [用户确认]
Phase 5  ─ 法官：争议焦点归纳
Phase 6  ─ 法庭辩论（交叉询问 + 举证质证）
Phase 7  ─ 双方最后陈述
Phase 8  ─ 法官：判决 + 胜率评估
"""

from typing import TypedDict, Optional
from dataclasses import dataclass, field
from ..llm import llm_call
from ..models.case import CaseInput
from .prompts import (
    PLAINTIFF_SYSTEM, DEFENDANT_SYSTEM, JUDGE_SYSTEM,
    build_plaintiff_phase1_msg, build_plaintiff_phase2_msg,
    build_defendant_phase3_msg, build_defendant_phase4_msg,
    build_judge_phase5_msg, build_cross_exam_msg,
    build_evidence_exam_msg, build_final_statement_plaintiff_msg,
    build_final_statement_defendant_msg, build_judgment_msg,
)


# ---- 状态定义 ----
@dataclass
class TrialSession:
    """庭审会话状态，在内存中持久化"""
    case_input: CaseInput
    current_phase: int = 0  # 0=未开始, 1-8=各阶段
    user_role: str = "neutral"  # plaintiff / defendant / neutral

    # Phase 1-2 产出
    phase1_analysis: str = ""
    phase2_complaint: str = ""
    phase2_evidence_catalog: str = ""

    # Phase 3-4 产出
    phase3_analysis: str = ""
    phase4_answer: str = ""
    phase4_evidence_catalog: str = ""

    # Phase 5
    phase5_issues: str = ""

    # Phase 6
    phase6_cross_exam: str = ""     # JSON 字符串
    phase6_evidence_exam: str = ""

    # Phase 7
    phase7_plaintiff_final: str = ""
    phase7_defendant_final: str = ""

    # Phase 8
    phase8_judgment: str = ""
    phase8_win_rate: float = 0.0

    # 控制
    phase1_confirmed: bool = False
    phase2_confirmed: bool = False
    phase3_confirmed: bool = False
    phase4_confirmed: bool = False


PHASE_LABELS = {
    1: "原告律师：请求权基础分析",
    2: "原告律师：起诉状与证据目录",
    3: "被告律师：答辩策略分析",
    4: "被告律师：答辩状与证据目录",
    5: "法官：争议焦点归纳",
    6: "法庭辩论：交叉询问与举证质证",
    7: "双方最后陈述",
    8: "法官：判决与胜率评估",
}


def needs_confirmation(phase: int, user_role: str) -> bool:
    """判断该阶段是否需要用户确认"""
    if user_role == "plaintiff" and phase in (1, 2):
        return True
    if user_role == "defendant" and phase in (3, 4):
        return True
    return False


# ---- 各阶段执行函数 ----
def run_phase1(session: TrialSession) -> str:
    """Phase 1: 原告律师请求权基础分析"""
    msg = build_plaintiff_phase1_msg(
        session.case_input.case_title,
        session.case_input.facts,
        session.case_input.evidence,
        session.case_input.claims,
    )
    result = llm_call(PLAINTIFF_SYSTEM, msg)
    session.phase1_analysis = result
    session.current_phase = 1
    return result


def run_phase2(session: TrialSession) -> str:
    """Phase 2: 原告律师撰写起诉状和证据目录"""
    msg = build_plaintiff_phase2_msg(
        session.phase1_analysis,
        session.case_input.claims,
        session.case_input.evidence,
    )
    result = llm_call(PLAINTIFF_SYSTEM, msg, max_tokens=8192)
    session.phase2_complaint = result
    session.current_phase = 2
    return result


def run_phase3(session: TrialSession) -> str:
    """Phase 3: 被告律师答辩策略分析"""
    msg = build_defendant_phase3_msg(
        session.case_input.case_title,
        session.case_input.facts,
        session.case_input.evidence,
        session.case_input.claims,
        session.phase2_complaint,
        "",  # plaintiff_evidence_catalog - embedded in complaint
    )
    result = llm_call(DEFENDANT_SYSTEM, msg)
    session.phase3_analysis = result
    session.current_phase = 3
    return result


def run_phase4(session: TrialSession) -> str:
    """Phase 4: 被告律师撰写答辩状和证据目录"""
    msg = build_defendant_phase4_msg(
        session.phase3_analysis,
        session.phase2_complaint,
    )
    result = llm_call(DEFENDANT_SYSTEM, msg, max_tokens=8192)
    session.phase4_answer = result
    session.current_phase = 4
    return result


def run_phase5(session: TrialSession) -> str:
    """Phase 5: 法官归纳争议焦点"""
    msg = build_judge_phase5_msg(
        session.case_input.case_title,
        session.case_input.claims,
        session.phase2_complaint,
        session.phase4_answer,
    )
    result = llm_call(JUDGE_SYSTEM, msg)
    session.phase5_issues = result
    session.current_phase = 5
    return result


def run_phase6a(session: TrialSession) -> str:
    """Phase 6A: 交叉询问（返回 JSON）"""
    msg = build_cross_exam_msg(
        session.case_input.case_title,
        session.phase2_complaint,
        session.phase4_answer,
        "",  # plaintiff evidence catalog
        "",
        session.phase5_issues,
    )
    result = llm_call(JUDGE_SYSTEM, msg, max_tokens=8192)
    session.phase6_cross_exam = result
    return result


def run_phase6b(session: TrialSession) -> str:
    """Phase 6B: 举证质证"""
    msg = build_evidence_exam_msg(
        session.case_input.evidence,
        "",  # plaintiff evidence catalog
        "",
    )
    result = llm_call(JUDGE_SYSTEM, msg, max_tokens=8192)
    session.phase6_evidence_exam = result
    return result


def run_phase6(session: TrialSession) -> dict:
    """Phase 6 完整：交叉询问 + 举证质证"""
    cross_exam = run_phase6a(session)
    evidence_exam = run_phase6b(session)
    session.current_phase = 6
    return {
        "cross_exam": cross_exam,
        "evidence_exam": evidence_exam,
    }


def run_phase7(session: TrialSession) -> dict:
    """Phase 7: 双方最后陈述"""
    pf = run_phase7_plaintiff(session)
    df = run_phase7_defendant(session)
    session.current_phase = 7
    return {"plaintiff_final": pf, "defendant_final": df}


def run_phase7_plaintiff(session: TrialSession) -> str:
    msg = build_final_statement_plaintiff_msg(
        session.case_input.case_title,
        session.case_input.claims,
        session.phase2_complaint,
        session.phase6_cross_exam,
        session.phase6_evidence_exam,
    )
    result = llm_call(PLAINTIFF_SYSTEM, msg)
    session.phase7_plaintiff_final = result
    return result


def run_phase7_defendant(session: TrialSession) -> str:
    msg = build_final_statement_defendant_msg(
        session.case_input.case_title,
        session.case_input.claims,
        session.phase4_answer,
        session.phase6_cross_exam,
        session.phase6_evidence_exam,
    )
    result = llm_call(DEFENDANT_SYSTEM, msg)
    session.phase7_defendant_final = result
    return result


def run_phase8(session: TrialSession) -> str:
    """Phase 8: 判决 + 胜率评估"""
    msg = build_judgment_msg(
        session.case_input.case_title,
        session.case_input.facts,
        session.case_input.claims,
        session.phase2_complaint,
        session.phase4_answer,
        session.phase6_cross_exam,
        session.phase6_evidence_exam,
        session.phase7_plaintiff_final,
        session.phase7_defendant_final,
    )
    result = llm_call(JUDGE_SYSTEM, msg, max_tokens=8192)
    session.phase8_judgment = result
    session.phase8_win_rate = _extract_win_rate(result)
    session.current_phase = 8
    return result


def _extract_win_rate(judgment: str) -> float:
    import re
    for p in [
        r"综合胜率[^\d]*(\d+(?:\.\d+)?)\s*%",
        r"综合胜率.*?(\d+(?:\.\d+)?)\s*%",
        r"胜诉.*?(\d+(?:\.\d+)?)\s*%",
    ]:
        m = re.search(p, judgment)
        if m:
            return float(m.group(1))
    return 0.0


# ---- 阶段调度器 ----
def run_phase(session: TrialSession, phase: int) -> dict:
    """执行指定阶段，返回 {phase, label, content, needs_confirm}"""
    runners = {
        1: run_phase1,
        2: run_phase2,
        3: run_phase3,
        4: run_phase4,
        5: run_phase5,
        6: run_phase6,
        7: run_phase7,
        8: run_phase8,
    }
    if phase not in runners:
        return {"error": f"Invalid phase: {phase}"}

    result = runners[phase](session)
    return {
        "phase": phase,
        "label": PHASE_LABELS[phase],
        "content": result,
        "needs_confirm": needs_confirmation(phase, session.user_role),
    }


def run_all_phases(session: TrialSession, start_phase: int = 1,
                   user_role: str = "neutral") -> list[dict]:
    """
    从 start_phase 开始连续执行所有阶段。
    遇到需要确认的阶段时暂停，返回已执行的阶段列表。
    调用方可以检查最后一个阶段的 needs_confirm 来决定是否继续。
    """
    session.user_role = user_role
    results = []
    for phase in range(start_phase, 9):
        result = run_phase(session, phase)
        results.append(result)

        # 如果需要确认，暂停
        if result.get("needs_confirm"):
            break

    return results
