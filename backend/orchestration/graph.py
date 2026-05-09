"""
LangGraph 庭审状态机

庭审流程（依照《中华人民共和国民事诉讼法》）：

    START
      │
      ▼
  [原告律师: 起诉策略 + 陈述]
      │
      ▼
  [被告律师: 答辩]
      │
      ▼
  [法官: 归纳争议焦点]
      │
      ▼
  [法官主持: 举证质证]
      │
      ▼
  [原告律师: 最后陈述]
      │
      ▼
  [被告律师: 最后陈述]
      │
      ▼
  [法官: 判决 + 胜率评估]
      │
      ▼
     END
"""

from typing import TypedDict
from langgraph.graph import StateGraph, END

from ..llm import llm_call
from ..models.case import CaseInput, TrialRecord
from .prompts import (
    PLAINTIFF_PROMPT, DEFENDANT_PROMPT, JUDGE_PROMPT,
    build_plaintiff_message, build_defendant_message,
    build_judge_issues_message, build_evidence_exam_message,
    build_judgment_message,
)


# ---- 状态定义 ----
class TrialState(TypedDict):
    case_title: str
    facts: str
    evidence: str
    claims: str

    # 各阶段产出
    plaintiff_opening: str
    defendant_response: str
    disputed_issues: str
    evidence_exam: str
    plaintiff_final: str
    defendant_final: str
    judgment: str
    win_rate: float


# ---- 节点函数 ----
def node_plaintiff_opening(state: TrialState) -> dict:
    """原告律师：起诉策略分析 + 陈述"""
    msg = build_plaintiff_message(
        state["case_title"], state["facts"],
        state["evidence"], state["claims"]
    )
    result = llm_call(PLAINTIFF_PROMPT, msg)
    return {"plaintiff_opening": result}


def node_defendant_response(state: TrialState) -> dict:
    """被告律师：答辩"""
    msg = build_defendant_message(
        state["case_title"], state["facts"],
        state["evidence"], state["claims"],
        state["plaintiff_opening"]
    )
    result = llm_call(DEFENDANT_PROMPT, msg)
    return {"defendant_response": result}


def node_judge_issues(state: TrialState) -> dict:
    """法官：归纳争议焦点"""
    msg = build_judge_issues_message(
        state["case_title"], state["facts"], state["claims"],
        state["plaintiff_opening"], state["defendant_response"]
    )
    result = llm_call(JUDGE_PROMPT, msg)
    return {"disputed_issues": result}


def node_evidence_exam(state: TrialState) -> dict:
    """法官主持：举证质证"""
    msg = build_evidence_exam_message(
        state["case_title"],
        state["plaintiff_opening"], state["defendant_response"],
        state["evidence"]
    )
    result = llm_call(JUDGE_PROMPT, msg)
    return {"evidence_exam": result}


def node_plaintiff_final(state: TrialState) -> dict:
    """原告律师：最后陈述"""
    msg = f"""请发表最后陈述（代理意见总结）。

【案由】{state["case_title"]}
【诉讼请求】{state["claims"]}

【你的起诉分析】
{state["plaintiff_opening"]}

【被告答辩】
{state["defendant_response"]}

【法官归纳的争议焦点】
{state["disputed_issues"]}

【举证质证情况】
{state["evidence_exam"]}

请综合庭审情况，发表最后陈述。总结己方核心论点，回应对方关键抗辩。"""
    result = llm_call(PLAINTIFF_PROMPT, msg)
    return {"plaintiff_final": result}


def node_defendant_final(state: TrialState) -> dict:
    """被告律师：最后陈述"""
    msg = f"""请发表最后陈述（答辩意见总结）。

【案由】{state["case_title"]}
【原告诉讼请求】{state["claims"]}

【原告起诉分析】
{state["plaintiff_opening"]}

【你的答辩分析】
{state["defendant_response"]}

【法官归纳的争议焦点】
{state["disputed_issues"]}

【举证质证情况】
{state["evidence_exam"]}

请综合庭审情况，发表最后陈述。总结己方核心抗辩论点。"""
    result = llm_call(DEFENDANT_PROMPT, msg)
    return {"defendant_final": result}


def node_judgment(state: TrialState) -> dict:
    """法官：判决 + 胜率评估"""
    msg = build_judgment_message(
        state["case_title"], state["facts"],
        state["evidence"], state["claims"],
        state["plaintiff_opening"], state["defendant_response"],
        state["evidence_exam"]
    )
    result = llm_call(JUDGE_PROMPT, msg, max_tokens=8192)
    return {"judgment": result, "win_rate": _extract_win_rate(result)}


def _extract_win_rate(judgment: str) -> float:
    """从判决文本中提取综合胜率"""
    import re
    # 匹配 "综合胜率" 后面的数字
    patterns = [
        r"综合胜率[^\d]*(\d+(?:\.\d+)?)\s*%",
        r"综合胜率.*?(\d+(?:\.\d+)?)\s*%",
        r"胜诉.*?(\d+(?:\.\d+)?)\s*%",
    ]
    for p in patterns:
        m = re.search(p, judgment)
        if m:
            return float(m.group(1))
    return 0.0


# ---- 构建图 ----
def build_trial_graph() -> StateGraph:
    graph = StateGraph(TrialState)

    graph.add_node("plaintiff_opening", node_plaintiff_opening)
    graph.add_node("defendant_response", node_defendant_response)
    graph.add_node("judge_issues", node_judge_issues)
    graph.add_node("evidence_exam", node_evidence_exam)
    graph.add_node("plaintiff_final", node_plaintiff_final)
    graph.add_node("defendant_final", node_defendant_final)
    graph.add_node("judgment", node_judgment)

    # 线性流程
    graph.set_entry_point("plaintiff_opening")
    graph.add_edge("plaintiff_opening", "defendant_response")
    graph.add_edge("defendant_response", "judge_issues")
    graph.add_edge("judge_issues", "evidence_exam")
    graph.add_edge("evidence_exam", "plaintiff_final")
    graph.add_edge("plaintiff_final", "defendant_final")
    graph.add_edge("defendant_final", "judgment")
    graph.add_edge("judgment", END)

    return graph.compile()


PHASE_ORDER = [
    "plaintiff_opening",
    "defendant_response",
    "judge_issues",
    "evidence_exam",
    "plaintiff_final",
    "defendant_final",
    "judgment",
]

PHASE_LABELS = {
    "plaintiff_opening": "原告律师：起诉策略分析",
    "defendant_response": "被告律师：答辩分析",
    "judge_issues": "法官：争议焦点归纳",
    "evidence_exam": "法官主持：举证质证",
    "plaintiff_final": "原告律师：最后陈述",
    "defendant_final": "被告律师：最后陈述",
    "judgment": "法官：判决与胜率评估",
}


def make_initial_state(case_input: CaseInput) -> TrialState:
    return {
        "case_title": case_input.case_title,
        "facts": case_input.facts,
        "evidence": case_input.evidence,
        "claims": case_input.claims,
        "plaintiff_opening": "",
        "defendant_response": "",
        "disputed_issues": "",
        "evidence_exam": "",
        "plaintiff_final": "",
        "defendant_final": "",
        "judgment": "",
        "win_rate": 0.0,
    }


# ---- 庭审执行器（同步，供 Streamlit 等非异步前端使用） ----
def run_trial_sync(case_input: CaseInput) -> list[dict]:
    """同步执行完整庭审，返回各阶段结果列表。
    每项: {phase, label, content}
    """
    graph = build_trial_graph()
    initial = make_initial_state(case_input)
    final = graph.invoke(initial)

    results = []
    for phase in PHASE_ORDER:
        content = final.get(phase, "")
        if content:
            results.append({
                "phase": phase,
                "label": PHASE_LABELS[phase],
                "content": content,
            })
    return results


# ---- 庭审执行器（异步流式，供 SSE 等实时推送前端使用） ----
async def run_trial_stream(case_input: CaseInput):
    """流式执行庭审，逐阶段 yield (phase_name, phase_label, content)"""
    graph = build_trial_graph()
    initial = make_initial_state(case_input)

    final_state = initial.copy()
    async for event in graph.astream(initial, stream_mode="updates"):
        for node_name, node_output in event.items():
            label = PHASE_LABELS.get(node_name, node_name)
            for key, value in node_output.items():
                if value:
                    final_state[key] = value
                    yield node_name, label, value
