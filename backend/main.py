"""
模拟法庭 — FastAPI 后端

启动： uvicorn backend.main:app --reload --port 8000
"""

import uuid
import json
import asyncio
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .models.case import CaseInput, TrialRecord
from .orchestration.graph import run_trial_stream, run_trial_sync

app = FastAPI(title="模拟法庭 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 简易内存存储
trials: dict[str, TrialRecord] = {}


# ---- 请求模型 ----
class CreateCaseRequest(BaseModel):
    case_title: str
    facts: str
    evidence: str
    claims: str


# ---- API 端点 ----
@app.post("/case/create")
async def create_case(req: CreateCaseRequest):
    """提交案卷，返回 case_id"""
    case_id = uuid.uuid4().hex[:12]
    case_input = CaseInput(
        case_title=req.case_title,
        facts=req.facts,
        evidence=req.evidence,
        claims=req.claims,
    )
    trials[case_id] = TrialRecord(
        case_id=case_id,
        case_input=case_input,
    )
    return {"case_id": case_id, "message": "案卷已提交，可开始模拟庭审"}


@app.get("/trial/stream/{case_id}")
async def stream_trial(case_id: str):
    """SSE 流式庭审 —— 逐阶段推送各 Agent 输出"""
    if case_id not in trials:
        raise HTTPException(status_code=404, detail="案卷不存在")

    record = trials[case_id]

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for phase_name, phase_label, content in run_trial_stream(
                record.case_input
            ):
                # 更新庭审记录
                if phase_name == "plaintiff_opening":
                    record.plaintiff_opening = content
                elif phase_name == "defendant_response":
                    record.defendant_response = content
                elif phase_name == "judge_issues":
                    record.disputed_issues = content
                elif phase_name == "evidence_exam":
                    record.evidence_examination = content
                elif phase_name == "plaintiff_final":
                    record.plaintiff_final = content
                elif phase_name == "defendant_final":
                    record.defendant_final = content
                elif phase_name == "judgment":
                    record.judgment = content

                # 构造 SSE 事件
                event_data = json.dumps({
                    "phase": phase_name,
                    "label": phase_label,
                    "content": content,
                }, ensure_ascii=False)
                yield f"data: {event_data}\n\n"
                await asyncio.sleep(0.1)

            # 审判结束
            yield f"data: {json.dumps({'phase': 'done', 'label': '庭审结束', 'content': ''}, ensure_ascii=False)}\n\n"

        except Exception as e:
            error_data = json.dumps({
                "phase": "error",
                "label": "错误",
                "content": str(e),
            }, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/trial/run/{case_id}")
async def run_trial(case_id: str):
    """同步执行庭审，返回完整结果（供 Streamlit 等前端使用）"""
    if case_id not in trials:
        raise HTTPException(status_code=404, detail="案卷不存在")

    record = trials[case_id]
    results = run_trial_sync(record.case_input)

    # 更新庭审记录
    for r in results:
        phase = r["phase"]
        content = r["content"]
        if phase == "plaintiff_opening":
            record.plaintiff_opening = content
        elif phase == "defendant_response":
            record.defendant_response = content
        elif phase == "judge_issues":
            record.disputed_issues = content
        elif phase == "evidence_exam":
            record.evidence_examination = content
        elif phase == "plaintiff_final":
            record.plaintiff_final = content
        elif phase == "defendant_final":
            record.defendant_final = content
        elif phase == "judgment":
            record.judgment = content

    return {"case_id": case_id, "phases": results}


@app.get("/case/{case_id}")
async def get_case(case_id: str):
    """获取庭审记录"""
    if case_id not in trials:
        raise HTTPException(status_code=404, detail="案卷不存在")
    record = trials[case_id]
    return {
        "case_id": record.case_id,
        "case_title": record.case_input.case_title,
        "facts": record.case_input.facts,
        "evidence": record.case_input.evidence,
        "claims": record.case_input.claims,
        "plaintiff_opening": record.plaintiff_opening,
        "defendant_response": record.defendant_response,
        "disputed_issues": record.disputed_issues,
        "evidence_examination": record.evidence_examination,
        "plaintiff_final": record.plaintiff_final,
        "defendant_final": record.defendant_final,
        "judgment": record.judgment,
        "created_at": record.created_at,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
