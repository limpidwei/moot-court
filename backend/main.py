"""
模拟法庭 v2.0 — FastAPI 后端

启动： uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""

import uuid
import json
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .models.case import CaseInput
from .orchestration.graph import (
    TrialSession, run_phase, run_all_phases,
    PHASE_LABELS, needs_confirmation,
)
from .services.parser import parse_text, parse_file
from .services.export_report import export_markdown

app = FastAPI(title="模拟法庭 API v2.0", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: dict[str, TrialSession] = {}
"""内存存储所有庭审会话"""


# ============================================================
# 数据模型
# ============================================================
class CreateCaseRequest(BaseModel):
    case_title: str
    facts: str
    evidence: str
    claims: str


class StartTrialRequest(BaseModel):
    case_id: str
    user_role: str = "neutral"  # plaintiff | defendant | neutral


class ContinueTrialRequest(BaseModel):
    case_id: str
    confirmed_phase: int  # 确认完成第几阶段
    edited_content: str = ""  # 用户修改后的内容（可选）


class JudgeQARequest(BaseModel):
    case_id: str
    question: str


# ============================================================
# 案卷管理
# ============================================================
@app.post("/case/create")
async def create_case(req: CreateCaseRequest):
    """提交结构化案卷，返回 case_id"""
    case_id = uuid.uuid4().hex[:12]
    sessions[case_id] = TrialSession(
        case_input=CaseInput(
            case_title=req.case_title,
            facts=req.facts,
            evidence=req.evidence,
            claims=req.claims,
        )
    )
    return {"case_id": case_id, "message": "案卷已提交"}


@app.post("/case/parse-text")
async def parse_case_text(text: str = Form(...)):
    """粘贴大段文本，AI 自动解析为结构化案卷"""
    result = parse_text(text)
    return result


@app.post("/case/parse-file")
async def parse_case_file(file: UploadFile = File(...)):
    """上传文件，AI 自动解析为结构化案卷"""
    content = await file.read()
    result = parse_file(file.filename, content)
    return result


# ============================================================
# 庭审控制
# ============================================================
@app.post("/trial/start")
async def start_trial(req: StartTrialRequest):
    """
    启动庭审，从 Phase 1 开始执行。
    如果用户是原告律师，执行 Phase 1 后暂停等待确认。
    否则连续执行直到下一个需要确认的阶段。
    """
    if req.case_id not in sessions:
        raise HTTPException(404, "案卷不存在")

    session = sessions[req.case_id]
    session.user_role = req.user_role

    results = run_all_phases(session, start_phase=1, user_role=req.user_role)

    return {
        "case_id": req.case_id,
        "phases": results,
        "current_phase": session.current_phase,
        "awaiting_confirm": (
            results[-1]["needs_confirm"] if results else False
        ),
    }


@app.post("/trial/continue")
async def continue_trial(req: ContinueTrialRequest):
    """
    用户确认当前阶段后继续执行后续阶段。
    如果用户修改了内容，替换对应阶段的产出。
    """
    if req.case_id not in sessions:
        raise HTTPException(404, "案卷不存在")

    session = sessions[req.case_id]

    # 标记已确认
    if req.confirmed_phase == 1:
        session.phase1_confirmed = True
        if req.edited_content:
            session.phase1_analysis = req.edited_content
    elif req.confirmed_phase == 2:
        session.phase2_confirmed = True
        if req.edited_content:
            session.phase2_complaint = req.edited_content
    elif req.confirmed_phase == 3:
        session.phase3_confirmed = True
        if req.edited_content:
            session.phase3_analysis = req.edited_content
    elif req.confirmed_phase == 4:
        session.phase4_confirmed = True
        if req.edited_content:
            session.phase4_answer = req.edited_content

    # 从下一阶段继续执行
    next_phase = session.current_phase + 1
    results = run_all_phases(session, start_phase=next_phase,
                             user_role=session.user_role)

    return {
        "case_id": req.case_id,
        "phases": results,
        "current_phase": session.current_phase,
        "awaiting_confirm": (
            results[-1]["needs_confirm"] if results else False
        ),
    }


@app.get("/trial/state/{case_id}")
async def get_trial_state(case_id: str):
    """获取当前庭审状态（不含阶段内容）"""
    if case_id not in sessions:
        raise HTTPException(404, "案卷不存在")

    session = sessions[case_id]
    return {
        "case_id": case_id,
        "current_phase": session.current_phase,
        "user_role": session.user_role,
        "phase1_confirmed": session.phase1_confirmed,
        "phase2_confirmed": session.phase2_confirmed,
        "phase3_confirmed": session.phase3_confirmed,
        "phase4_confirmed": session.phase4_confirmed,
        "phase_labels": PHASE_LABELS,
        "win_rate": session.phase8_win_rate,
    }


@app.get("/trial/content/{case_id}/{phase}")
async def get_phase_content(case_id: str, phase: int):
    """获取指定阶段的完整内容"""
    if case_id not in sessions:
        raise HTTPException(404, "案卷不存在")

    session = sessions[case_id]
    phase_content_map = {
        1: session.phase1_analysis,
        2: session.phase2_complaint,
        3: session.phase3_analysis,
        4: session.phase4_answer,
        5: session.phase5_issues,
        6: json.dumps({
            "cross_exam": session.phase6_cross_exam,
            "evidence_exam": session.phase6_evidence_exam,
        }, ensure_ascii=False),
        7: json.dumps({
            "plaintiff_final": session.phase7_plaintiff_final,
            "defendant_final": session.phase7_defendant_final,
        }, ensure_ascii=False),
        8: session.phase8_judgment,
    }

    content = phase_content_map.get(phase, "")
    label = PHASE_LABELS.get(phase, "")

    return {
        "phase": phase,
        "label": label,
        "content": content,
    }


# ============================================================
# 导出 & 庭后问答
# ============================================================
@app.get("/trial/export/{case_id}")
async def export_report(case_id: str):
    """导出完整庭审报告（Markdown）"""
    if case_id not in sessions:
        raise HTTPException(404, "案卷不存在")

    session = sessions[case_id]
    md = export_markdown(session)

    return {
        "case_id": case_id,
        "format": "markdown",
        "content": md,
    }


@app.post("/trial/judge-qa")
async def judge_qa(req: JudgeQARequest):
    """庭后向法官提问"""
    if req.case_id not in sessions:
        raise HTTPException(404, "案卷不存在")

    session = sessions[req.case_id]
    if not session.phase8_judgment:
        raise HTTPException(400, "庭审尚未完成，无法进行庭后问答")

    from .llm import llm_call
    from .orchestration.prompts import JUDGE_SYSTEM

    context = f"""你刚审结了一起案件。以下是完整庭审记录：

【判决书】
{session.phase8_judgment}

【起诉状】
{session.phase2_complaint}

【答辩状】
{session.phase4_answer}

现在有人向你提问：
{req.question}

请基于庭审记录和你的判决，做出专业、中立的回答。
如果问题超出庭审范围，诚实说明。"""

    answer = llm_call(JUDGE_SYSTEM, context, max_tokens=2048)

    return {"question": req.question, "answer": answer}


# ============================================================
# 健康检查
# ============================================================
@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
