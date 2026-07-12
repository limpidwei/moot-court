"""
模拟法庭 v3.0 — FastAPI 后端（多 Agent + LangGraph）

启动： uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""

import os
import uuid
import json
import logging
import zipfile
import tempfile
import shutil
import threading
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import asyncio

from .models.case import CaseInput
from .models.database import User, Case
from .database import get_db
from .auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_optional_user
)
from .orchestration.workflow import (
    TrialSession, PHASE_LABELS, needs_confirmation,
    create_initial_state, TrialState,
)
from .agents.v2.compat import run_trial_compat as run_trial
from .services.parser import parse_text, parse_file
from .services.export_report import export_markdown
from .services.export_pdf import generate_case_report
from .services.insights import extract_phase_insights
from .services.unified_extraction import extract_phase_unified, apply_extraction
from .services.opponent_generator import generate_opponent_materials
from .llm import llm_meta_ctx
from .orchestration.analysis import CaseAnalysis
from .llm import LLMConfig
from fastapi.responses import FileResponse
from .routers import ontology as ontology_router
from .routers import agentic as agentic_router
from .ontology import service as ontology_service
from .agentic import service as agentic_service

# 证据模块导入（ALL_EXTRACTORS 延迟加载：避免 Pillow 等重依赖拖慢 uvicorn 端口绑定）
from .evidence.registry import (
    get_registry, save_registry, add_evidence_item,
    delete_evidence_item, analyze_all_evidence, analyze_conflicts,
    import_to_trial_session,
)
from .evidence.persistence import save_uploaded_file, delete_file, delete_case_evidence_files
from .evidence.schemas import EvidenceItem

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化数据库，关闭时清理资源"""
    # ---- Startup ----
    try:
        from .database import init_db
        init_db()
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")

    try:
        _migrate_legacy_sessions()
    except Exception as e:
        logger.error(f"旧数据迁移失败: {e}")

    try:
        _ensure_db_schema()
    except Exception as e:
        logger.error(f"Schema 检查失败: {e}")

    logger.info("应用启动完成")
    yield
    # ---- Shutdown ----
    logger.info("应用关闭")


app = FastAPI(title="模拟法庭 API v3.0", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        if o.strip()
    ],  # 生产环境必须通过 CORS_ALLOW_ORIGINS 指定确切域名，切勿用 "*"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ontology_router.router)
app.include_router(agentic_router.router)

# ---- 认证相关的数据模型 ----
_MIN_PASSWORD_LEN = 6


class UserRegister(BaseModel):
    email: str
    password: str
    name: str

    @field_validator("email")
    @classmethod
    def _check_email_format(cls, v: str) -> str:
        v = v.strip()
        if not v or "@" not in v or len(v) > 254:
            raise ValueError("请输入有效的邮箱地址")
        return v

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v: str) -> str:
        if len(v) < _MIN_PASSWORD_LEN:
            raise ValueError(f"密码长度不能少于 {_MIN_PASSWORD_LEN} 位")
        return v


class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    name: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# ---- 持久化配置 ----
DATA_DIR = os.path.join(os.path.dirname(__file__), "..")
SESSIONS_FILE = os.path.join(DATA_DIR, "data", "sessions.json")
_SAVE_LOCK = threading.Lock()  # 防止并发写入损坏 sessions.json


def _ensure_data_dir():
    data_dir = os.path.join(DATA_DIR, "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)


def _session_to_dict(session: TrialSession) -> dict:
    return session.to_dict()


def _dict_to_session(data: dict) -> TrialSession:
    return TrialSession.from_dict(data)


def _save_sessions():
    with _SAVE_LOCK:
        _ensure_data_dir()

        # 自动清理：只清理「已完结（phase>=8）且创建于 30 天前」的冷会话，
        # 绝不删除进行中的案件（避免用户数据静默丢失）。上限 200 触发清理。
        _AUTO_PURGE_MAX = 200
        _AUTO_PURGE_DAYS = 30
        if len(sessions) > _AUTO_PURGE_MAX:
            now = datetime.now()
            purge_candidates = []
            for case_id, session in sessions.items():
                if session.current_phase < 8:
                    continue  # 进行中的案件一律保留
                try:
                    created = datetime.fromisoformat(session.created_at)
                except (ValueError, TypeError):
                    continue
                if (now - created).days >= _AUTO_PURGE_DAYS:
                    purge_candidates.append((case_id, created))
            # 按创建时间从旧到新清理，直到降到上限以下
            purge_candidates.sort(key=lambda x: x[1])
            for case_id, created in purge_candidates:
                if len(sessions) <= _AUTO_PURGE_MAX:
                    break
                sessions.pop(case_id, None)
                logger.warning(
                    f"[audit] 自动清理已完结冷会话 case_id={case_id} "
                    f"created={created.isoformat()}（超 {_AUTO_PURGE_DAYS} 天）"
                )

        data = {k: _session_to_dict(v) for k, v in sessions.items()}
        # 原子写入：先写临时文件，再替换，避免并发或崩溃导致文件损坏
        tmp_file = SESSIONS_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, SESSIONS_FILE)

        # 同步元数据到 PostgreSQL（保证 /cases 列表查询可扩展）
        try:
            from .database import SessionLocal
            db = SessionLocal()
            for case_id, session in sessions.items():
                if session.user_id is not None:
                    try:
                        case_session_to_db(case_id, session, session.user_id, db)
                    except Exception:
                        db.rollback()
                        raise
            db.close()
        except Exception as e:
            logger.warning(f"同步 session 到数据库失败: {e}")


def _load_sessions() -> dict[str, TrialSession]:
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: _dict_to_session(v) for k, v in data.items()}
    except Exception as e:
        logger.error(f"加载 sessions 失败: {e}")
        return {}


# 启动时加载持久化数据
sessions: dict[str, TrialSession] = _load_sessions()
logger.info(f"已加载 {len(sessions)} 个庭审会话")

def _migrate_legacy_sessions():
    """将无 user_id 的旧案件关联到默认 admin 用户"""
    from .database import SessionLocal
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == 1).first()
        if not admin_user:
            logger.warning("默认 admin 用户不存在，跳过旧数据迁移")
            return
        migrated = 0
        for case_id, session in sessions.items():
            if session.user_id is None:
                session.user_id = admin_user.id
                existing_case = db.query(Case).filter(Case.id == case_id).first()
                if not existing_case:
                    case = Case(
                        id=case_id,
                        user_id=admin_user.id,
                        case_title=session.case_input.case_title,
                        case_input=session.case_input.__dict__,
                        current_phase=session.current_phase,
                        user_role=session.user_role,
                        created_at=session.created_at,
                    )
                    db.add(case)
                migrated += 1
        if migrated > 0:
            db.commit()
            _save_sessions()
            logger.info(f"已迁移 {migrated} 个旧案件到 admin 用户")
    except Exception as e:
        logger.error(f"旧数据迁移失败: {e}")
        db.rollback()
    finally:
        db.close()



def _ensure_db_schema():
    """确保新增的数据库表和列存在（简易 migration）"""
    try:
        from sqlalchemy import inspect, text
        from .database import engine
        from .models.database import LLMUsageRecord, CaseShare, Notification

        inspector = inspect(engine)

        # 创建新表（如果不存在）
        LLMUsageRecord.__table__.create(engine, checkfirst=True)
        CaseShare.__table__.create(engine, checkfirst=True)
        Notification.__table__.create(engine, checkfirst=True)

        # 为 users 表添加配额列（如果不存在）
        user_cols = [c["name"] for c in inspector.get_columns("users")]
        with engine.connect() as conn:
            if "daily_token_limit" not in user_cols:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN daily_token_limit INTEGER NOT NULL DEFAULT 1000000"
                ))
                conn.commit()
                logger.info("[migration] Added users.daily_token_limit")
            if "monthly_token_limit" not in user_cols:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN monthly_token_limit INTEGER NOT NULL DEFAULT 10000000"
                ))
                conn.commit()
                logger.info("[migration] Added users.monthly_token_limit")
    except Exception as e:
        logger.warning(f"[migration] Schema check failed: {e}")


# ============================================================
# TrialSession <-> TrialState 转换层
# ============================================================

def _session_to_state(session: TrialSession) -> TrialState:
    """把 TrialSession 转成 LangGraph 用的 TrialState"""
    return TrialState(
        case_input=session.case_input,
        current_phase=session.current_phase,
        user_role=session.user_role,
        phase1_analysis=session.phase1_analysis,
        phase2_complaint=session.phase2_complaint,
        phase2_evidence_catalog=session.phase2_evidence_catalog,
        phase3_analysis=session.phase3_analysis,
        phase4_answer=session.phase4_answer,
        phase4_evidence_catalog=session.phase4_evidence_catalog,
        phase5_issues=session.phase5_issues,
        phase6_cross_exam=session.phase6_cross_exam,
        phase6_evidence_exam=session.phase6_evidence_exam,
        phase7_plaintiff_final=session.phase7_plaintiff_final,
        phase7_defendant_final=session.phase7_defendant_final,
        phase8_judgment=session.phase8_judgment,
        phase8_win_rate=session.phase8_win_rate,
        phase1_confirmed=session.phase1_confirmed,
        phase2_confirmed=session.phase2_confirmed,
        phase3_confirmed=session.phase3_confirmed,
        phase4_confirmed=session.phase4_confirmed,
        phase5_confirmed=session.phase5_confirmed,
        phase6_confirmed=session.phase6_confirmed,
        phase7_confirmed=session.phase7_confirmed,
        phase1_strategy_routes=session.phase1_strategy_routes,
        phase1_selected_route=session.phase1_selected_route,
        phase3_strategy_routes=session.phase3_strategy_routes,
        phase3_selected_route=session.phase3_selected_route,
        phase1_strategy_pending=session.phase1_strategy_pending,
        phase3_strategy_pending=session.phase3_strategy_pending,
        plaintiff_state=getattr(session, "plaintiff_state", {}) or {},
        defendant_state=getattr(session, "defendant_state", {}) or {},
        judge_state=getattr(session, "judge_state", {}) or {},
        reporter_state=getattr(session, "reporter_state", {}) or {},
        cross_exam_round=session.cross_exam_round,
        cross_exam_context="",
        current_evidence_index=session.current_evidence_index,
        evidence_list=session.evidence_list,
        llm_config=session.llm_config,
        error="",
    )


def _state_to_session(state: TrialState, session: TrialSession):
    """把 TrialState 结果写回 TrialSession"""
    session.current_phase = state.get("current_phase", session.current_phase)
    session.phase1_analysis = state.get("phase1_analysis", session.phase1_analysis)
    session.phase2_complaint = state.get("phase2_complaint", session.phase2_complaint)
    session.phase2_evidence_catalog = state.get("phase2_evidence_catalog", session.phase2_evidence_catalog)
    session.phase3_analysis = state.get("phase3_analysis", session.phase3_analysis)
    session.phase4_answer = state.get("phase4_answer", session.phase4_answer)
    session.phase4_evidence_catalog = state.get("phase4_evidence_catalog", session.phase4_evidence_catalog)
    session.phase5_issues = state.get("phase5_issues", session.phase5_issues)
    session.phase6_cross_exam = state.get("phase6_cross_exam", session.phase6_cross_exam)
    session.phase6_evidence_exam = state.get("phase6_evidence_exam", session.phase6_evidence_exam)
    session.phase7_plaintiff_final = state.get("phase7_plaintiff_final", session.phase7_plaintiff_final)
    session.phase7_defendant_final = state.get("phase7_defendant_final", session.phase7_defendant_final)
    session.phase8_judgment = state.get("phase8_judgment", session.phase8_judgment)
    session.phase8_win_rate = state.get("phase8_win_rate", session.phase8_win_rate)
    session.phase1_confirmed = state.get("phase1_confirmed", session.phase1_confirmed)
    session.phase2_confirmed = state.get("phase2_confirmed", session.phase2_confirmed)
    session.phase3_confirmed = state.get("phase3_confirmed", session.phase3_confirmed)
    session.phase4_confirmed = state.get("phase4_confirmed", session.phase4_confirmed)
    session.phase5_confirmed = state.get("phase5_confirmed", session.phase5_confirmed)
    session.phase6_confirmed = state.get("phase6_confirmed", session.phase6_confirmed)
    session.phase7_confirmed = state.get("phase7_confirmed", session.phase7_confirmed)
    session.phase1_strategy_routes = state.get("phase1_strategy_routes", session.phase1_strategy_routes)
    session.phase1_selected_route = state.get("phase1_selected_route", session.phase1_selected_route)
    session.phase3_strategy_routes = state.get("phase3_strategy_routes", session.phase3_strategy_routes)
    session.phase3_selected_route = state.get("phase3_selected_route", session.phase3_selected_route)
    session.phase1_strategy_pending = state.get("phase1_strategy_pending", session.phase1_strategy_pending)
    session.phase3_strategy_pending = state.get("phase3_strategy_pending", session.phase3_strategy_pending)
    session.cross_exam_round = state.get("cross_exam_round", session.cross_exam_round)
    session.current_evidence_index = state.get("current_evidence_index", session.current_evidence_index)
    session.evidence_list = state.get("evidence_list", session.evidence_list)
    session.llm_config = state.get("llm_config", session.llm_config)
    session.plaintiff_state = state.get("plaintiff_state", {})
    session.defendant_state = state.get("defendant_state", {})
    session.judge_state = state.get("judge_state", {})
    session.reporter_state = state.get("reporter_state", {})


def _get_analysis(session: TrialSession) -> CaseAnalysis:
    """从 session 获取或创建 CaseAnalysis"""
    if session.case_analysis_data:
        return CaseAnalysis.from_dict(session.case_analysis_data)
    return CaseAnalysis()


def _save_analysis(session: TrialSession, analysis: CaseAnalysis):
    """将 CaseAnalysis 保存到 session"""
    session.case_analysis_data = analysis.to_dict()


# P2 修复：存储后台 insight 提取 task，避免 asyncio.create_task 返回的 task 被 GC 取消
_insight_tasks: set[asyncio.Task] = set()


def _warm_insights(session: TrialSession):
    """
    预热洞察卡片：从当前阶段文本中提取结构化 insight 数据。
    在后台异步执行，避免阻塞前端响应。
    """
    phase = session.current_phase
    if phase < 1 or phase > 8:
        return

    analysis = _get_analysis(session)

    # 如果已有该阶段的 insight 数据，跳过
    if phase in analysis.insight_cards:
        return

    content_map = {
        1: session.phase1_analysis or "",
        2: (session.phase2_complaint or "") + "\n\n" + (session.phase2_evidence_catalog or ""),
        3: session.phase3_analysis or "",
        4: (session.phase4_answer or "") + "\n\n" + (session.phase4_evidence_catalog or ""),
        5: session.phase5_issues or "",
        6: (session.phase6_cross_exam or "") + "\n\n" + (session.phase6_evidence_exam or ""),
        7: (session.phase7_plaintiff_final or "") + "\n\n" + (session.phase7_defendant_final or ""),
        8: session.phase8_judgment or "",
    }
    content = content_map.get(phase, "")
    if not content:
        return

    known_win_rate = session.phase8_win_rate if phase == 8 else None

    async def _do():
        try:
            extracted = await extract_phase_unified(
                phase, content, analysis,
                llm_config=session.llm_config,
                known_win_rate=known_win_rate,
            )
            if extracted:
                apply_extraction(analysis, phase, extracted)
                # Phase 8: 强制同步胜率
                if phase == 8 and session.phase8_win_rate > 0:
                    analysis.set_win_rate(session.phase8_win_rate, analysis.win_rate_dimensions)
                _save_analysis(session, analysis)
                # 同步旧缓存（兼容）
                if phase in analysis.insight_cards:
                    session.insights_cache[str(phase)] = analysis.insight_cards[phase]
                _save_sessions()
                # 通知前端洞察已就绪
                put_event({"type": "insights_ready", "phase": phase})
        except Exception as e:
            logger.warning(f"Insight extraction phase {phase} failed: {e}", exc_info=True)

    task = asyncio.create_task(_do())
    _insight_tasks.add(task)
    task.add_done_callback(_insight_tasks.discard)


def _build_phases_response(state: TrialState) -> list[dict]:
    """从 TrialState 构建前端需要的 phases 列表

    注意：仅返回 public 层内容（正式法律文书与庭审记录），
    Agent 的 private 策略笔记、思考过程永不暴露给前端。

    单方对抗模式：渐进式揭示过滤 — 用户只能看到自己扮演角色的
    策略路线（strategy_routes），对方的策略路线被隐藏。
    """
    phases = []
    case_input = state.get("case_input")
    # 防御：case_input 可能是 dict（LangGraph checkpoint 序列化后）
    if isinstance(case_input, dict):
        mode = case_input.get("mode", "neutral")
        user_side = case_input.get("user_side", "")
    elif case_input is not None:
        mode = getattr(case_input, "mode", "neutral")
        user_side = getattr(case_input, "user_side", "")
    else:
        mode = "neutral"
        user_side = ""
    user_role = state.get("user_role", "neutral")

    # 诊断日志：策略选择相关的关键状态
    current_phase = state.get("current_phase", 0)
    p1_routes = state.get("phase1_strategy_routes", [])
    p3_routes = state.get("phase3_strategy_routes", [])
    p1_pending = state.get("phase1_strategy_pending", False)
    p3_pending = state.get("phase3_strategy_pending", False)
    if mode == "asymmetric":
        logger.info(
            f"[_build_phases_response] mode=asymmetric user_role={user_role} "
            f"current_phase={current_phase} p1_pending={p1_pending} p3_pending={p3_pending} "
            f"p1_routes={len(p1_routes)} p3_routes={len(p3_routes)}"
        )

    for phase_num in range(1, current_phase + 1):
        content = ""
        if phase_num == 1:
            content = state.get("phase1_analysis", "")
        elif phase_num == 2:
            content = state.get("phase2_complaint", "")
        elif phase_num == 3:
            content = state.get("phase3_analysis", "")
        elif phase_num == 4:
            content = state.get("phase4_answer", "")
        elif phase_num == 5:
            content = state.get("phase5_issues", "")
        elif phase_num == 6:
            content = {
                "cross_exam": state.get("phase6_cross_exam", ""),
                "evidence_exam": state.get("phase6_evidence_exam", ""),
            }
        elif phase_num == 7:
            content = {
                "plaintiff_final": state.get("phase7_plaintiff_final", ""),
                "defendant_final": state.get("phase7_defendant_final", ""),
            }
        elif phase_num == 8:
            content = state.get("phase8_judgment", "")

        entry = {
            "phase": phase_num,
            "label": PHASE_LABELS.get(phase_num, ""),
            "content": content,
            "needs_confirm": needs_confirmation(phase_num, user_role),
        }
        # 策略路线渐进式揭示过滤
        if mode == "asymmetric" and user_role != "neutral":
            if user_role == "plaintiff" and phase_num == 1 and p1_routes:
                entry["strategy_routes"] = p1_routes
                entry["selected_route"] = state.get("phase1_selected_route", "")
                logger.info(f"[_build_phases_response] 附加 phase1 strategy_routes ({len(p1_routes)} 条)")
            elif user_role == "defendant" and phase_num == 3 and p3_routes:
                entry["strategy_routes"] = p3_routes
                entry["selected_route"] = state.get("phase3_selected_route", "")
                logger.info(f"[_build_phases_response] 附加 phase3 strategy_routes ({len(p3_routes)} 条)")
        else:
            # 中立模式：双方策略路线都可见
            if phase_num == 1 and p1_routes:
                entry["strategy_routes"] = p1_routes
                entry["selected_route"] = state.get("phase1_selected_route", "")
            if phase_num == 3 and p3_routes:
                entry["strategy_routes"] = p3_routes
                entry["selected_route"] = state.get("phase3_selected_route", "")
        phases.append(entry)
    return phases


# ============================================================
# 数据模型
# ============================================================
class LLMConfigRequest(BaseModel):
    provider: str
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.6


class CreateCaseRequest(BaseModel):
    case_title: str
    facts: str
    evidence: str
    claims: str
    mode: str = "neutral"            # "neutral" | "asymmetric"
    user_side: str = ""              # "plaintiff" | "defendant" | ""
    user_strategy_hint: str = ""     # 用户策略倾向提示（可选）
    source_materials: str = ""       # 案卷原始材料全文（双轨制保留）
    adversarial_intensity: int = 3   # AI 对手对抗强度（1-5）
    llm_config: LLMConfigRequest | None = None


class StartTrialRequest(BaseModel):
    case_id: str
    user_role: str = "neutral"


class ContinueTrialRequest(BaseModel):
    case_id: str
    confirmed_phase: int
    edited_content: str = ""


class JudgeQARequest(BaseModel):
    case_id: str
    question: str


class TrialStreamRequest(BaseModel):
    case_id: str
    action: str  # "start" | "continue"
    user_role: str = "neutral"
    confirmed_phase: int = 0
    edited_content: str = ""
    llm_config: LLMConfigRequest | None = None


class SelectStrategyRequest(BaseModel):
    phase: int  # 1 | 3
    route_id: str


# ============================================================
# 快照与回退辅助
# ============================================================

_PHASE_FIELDS = {
    1: ["phase1_analysis"],
    2: ["phase2_complaint", "phase2_evidence_catalog"],
    3: ["phase3_analysis"],
    4: ["phase4_answer", "phase4_evidence_catalog"],
    5: ["phase5_issues"],
    6: ["phase6_cross_exam", "phase6_evidence_exam"],
    7: ["phase7_plaintiff_final", "phase7_defendant_final"],
    8: ["phase8_judgment", "phase8_win_rate"],
}


def _make_snapshot(session: TrialSession) -> dict:
    """为当前阶段生成快照"""
    phase = session.current_phase
    content = ""
    if phase == 1:
        content = session.phase1_analysis
    elif phase == 2:
        content = session.phase2_complaint
    elif phase == 3:
        content = session.phase3_analysis
    elif phase == 4:
        content = session.phase4_answer
    elif phase == 5:
        content = session.phase5_issues
    elif phase == 6:
        content = session.phase6_cross_exam
    elif phase == 7:
        content = session.phase7_plaintiff_final
    elif phase == 8:
        content = session.phase8_judgment

    return {
        "phase": phase,
        "timestamp": datetime.now().isoformat(),
        "label": PHASE_LABELS.get(phase, ""),
        "preview": (content[:200] + "...") if len(content) > 200 else content,
    }


def _reset_to_phase(session: TrialSession, to_phase: int):
    """回退到指定阶段，清空后续所有产出"""
    session.current_phase = to_phase
    # 取消当前阶段的确认状态
    setattr(session, f"phase{to_phase}_confirmed", False)
    # 清空后续阶段的所有产出和确认状态
    for p in range(to_phase + 1, 9):
        for field in _PHASE_FIELDS.get(p, []):
            default = 0.0 if field == "phase8_win_rate" else ""
            setattr(session, field, default)
        setattr(session, f"phase{p}_confirmed", False)


# ============================================================
# 健康检查
# ============================================================
@app.get("/health")
async def health_check():
    """返回服务状态，用于前端检测后端是否存活"""
    return {"status": "ok", "version": "3.0.0"}


# ============================================================
# 用户认证 API
# ============================================================

@app.post("/auth/register", response_model=TokenResponse)
async def register(req: UserRegister, db: Session = Depends(get_db)):
    """用户注册"""
    # 检查邮箱是否已存在
    existing_user = db.query(User).filter(User.email == req.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该邮箱已被注册"
        )

    # 创建新用户
    user = User(
        email=req.email,
        name=req.name,
        password_hash=hash_password(req.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 生成访问令牌
    access_token = create_access_token(user_id=user.id, email=user.email)

    logger.info(f"新用户注册: {user.email}")

    return TokenResponse(
        access_token=access_token,
        user=UserResponse(id=user.id, email=user.email, name=user.name)
    )


@app.post("/auth/login", response_model=TokenResponse)
async def login(req: UserLogin, db: Session = Depends(get_db)):
    """用户登录"""
    # 查找用户
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误"
        )

    # 验证密码
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误"
        )

    # 生成访问令牌
    access_token = create_access_token(user_id=user.id, email=user.email)

    logger.info(f"用户登录: {user.email}")

    return TokenResponse(
        access_token=access_token,
        user=UserResponse(id=user.id, email=user.email, name=user.name)
    )


@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name
    )


# ---- 权限验证辅助函数 ----

def get_user_case_or_404(case_id: str, user_id: int, db: Session) -> Case:
    """获取用户自己的案件，不存在或无权限则抛出 404"""
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == user_id
    ).first()

    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在或无权访问"
        )

    return case


def _require_session_access(case_id: str, current_user: User) -> TrialSession:
    """校验当前用户对指定 case_id 的 session 有访问权限"""
    if case_id not in sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在或无权访问"
        )
    session = sessions[case_id]
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在或无权访问"
        )
    return session



def case_session_to_db(case_id: str, session: TrialSession, user_id: int, db: Session):
    """将 TrialSession 元数据同步到数据库 Case 表。

    C4 修复：原先此函数试图将阶段内容（phase1_content 等）写入 CasePhase 表，
    但字段映射与 TrialSession 实际属性完全错位（getattr(session, 'phase1_content') 恒为 None），
    CasePhase 内容双写永久失效。现按「JSON 为唯一权威源、DB 仅存案件元数据索引」策略，
    仅同步 Case 表（id / title / phase / role / mode / created_at），删除 CasePhase 内容循环。
    """
    # 查找或创建 Case
    case = db.query(Case).filter(Case.id == case_id).first()

    if not case:
        case = Case(
            id=case_id,
            user_id=user_id,
            case_title=session.case_input.case_title,
            case_input=session.case_input.__dict__,
            current_phase=session.current_phase,
            user_role=session.user_role,
            created_at=session.created_at,
        )
        db.add(case)
    else:
        # 更新现有案件元数据
        case.case_title = session.case_input.case_title
        case.case_input = session.case_input.__dict__
        case.current_phase = session.current_phase
        case.user_role = session.user_role

    db.commit()
    db.refresh(case)

    return case


# ============================================================
# 案卷管理
# ============================================================
@app.post("/case/create")
async def create_case(
    req: CreateCaseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    case_id = uuid.uuid4().hex[:12]
    llm_cfg = None
    if req.llm_config:
        llm_cfg = LLMConfig(
            base_url=req.llm_config.base_url,
            api_key=req.llm_config.api_key,
            model=req.llm_config.model,
            temperature=req.llm_config.temperature,
        )
    # 对抗强度 clamp 到 1-5
    intensity = max(1, min(5, req.adversarial_intensity))

    case_input = CaseInput(
        case_title=req.case_title,
        facts=req.facts,
        evidence=req.evidence,
        claims=req.claims,
        mode=req.mode,
        user_side=req.user_side,
        user_strategy_hint=req.user_strategy_hint,
        source_materials=req.source_materials,
        adversarial_intensity=intensity,
    )
    sessions[case_id] = TrialSession(
        case_input=case_input,
        llm_config=llm_cfg,
        user_id=current_user.id,
        user_role=req.user_side if req.mode == "asymmetric" else "neutral",
    )

    # 单方对抗模式：AI 生成对方材料
    if req.mode == "asymmetric" and req.user_side:
        meta_token = llm_meta_ctx.set({"user_id": current_user.id, "case_id": case_id})
        try:
            opponent_materials = await generate_opponent_materials(case_input, llm_cfg)
            sessions[case_id].case_input.opponent_materials = opponent_materials
            logger.info(f"[create_case] case_id={case_id} 生成对方材料，长度={len(opponent_materials)}")
        finally:
            llm_meta_ctx.reset(meta_token)

    # 同步写入数据库（作为权限索引），处理极端情况下的主键冲突
    original_case_id = case_id
    max_retries = 3
    for attempt in range(max_retries):
        try:
            case = Case(
                id=case_id,
                user_id=current_user.id,
                case_title=req.case_title,
                case_input=sessions[case_id].case_input.__dict__,
                current_phase=0,
                user_role=req.user_side if req.mode == "asymmetric" else "neutral",
            )
            db.add(case)
            db.commit()
            break
        except IntegrityError as ie:
            db.rollback()
            logger.warning(
                f"[create_case] case_id={case_id} 主键冲突，尝试重新生成 ({attempt + 1}/{max_retries}): {ie}"
            )
            old_id = case_id
            case_id = uuid.uuid4().hex[:12]
            # 同步更新内存中的 session key
            if old_id in sessions:
                sessions[case_id] = sessions.pop(old_id)
            if attempt == max_retries - 1:
                raise HTTPException(500, "创建案件失败，无法生成唯一标识")
        except Exception:
            db.rollback()
            raise

    if original_case_id != case_id:
        logger.info(f"[create_case] case_id 从 {original_case_id} 重命名为 {case_id}")

    # 构建基础 Ontology（Palantir 式案件对象图）
    try:
        ontology_service.build_and_save_from_case_input(sessions[case_id].case_input)
        logger.info(f"[create_case] case_id={case_id} 基础 Ontology 已构建")
    except Exception as e:
        logger.warning(f"[create_case] 构建 Ontology 失败 case_id={case_id}: {e}")

    _save_sessions()
    return {"case_id": case_id, "message": "案卷已提交"}


@app.post("/case/parse-text")
async def parse_case_text(
    text: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    meta_token = llm_meta_ctx.set({"user_id": current_user.id})
    try:
        result = await parse_text(text)
        return result
    except Exception as e:
        logger.error(f"parse-text error: {e}")
        raise HTTPException(503, f"AI 解析服务暂时不可用: {str(e)}")
    finally:
        llm_meta_ctx.reset(meta_token)


@app.post("/case/parse-file")
async def parse_case_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    meta_token = llm_meta_ctx.set({"user_id": current_user.id})
    try:
        content = await file.read()
        result = await parse_file(file.filename, content)
        return result
    except Exception as e:
        logger.error(f"parse-file error: {e}")
        raise HTTPException(503, f"AI 解析服务暂时不可用: {str(e)}")
    finally:
        llm_meta_ctx.reset(meta_token)


# ============================================================
# 庭审控制（多 Agent 工作流）
# ============================================================
@app.post("/trial/start")
async def start_trial(
    req: StartTrialRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _require_session_access(req.case_id, current_user)
    # 单方对抗模式下 user_role 由创建时固定，不允许前端篡改
    if session.case_input.mode != "asymmetric":
        session.user_role = req.user_role

    # 构造初始 state
    state = _session_to_state(session)

    meta_token = llm_meta_ctx.set({"user_id": current_user.id, "case_id": req.case_id})
    try:
        result_state = await run_trial(state)
    except Exception as e:
        logger.error(f"trial/start error: {e}")
        raise HTTPException(503, f"庭审生成服务暂时不可用，请稍后重试。详情: {str(e)}")
    finally:
        llm_meta_ctx.reset(meta_token)

    _state_to_session(result_state, session)
    _save_sessions()

    # 预热洞察卡片，使前端页面加载时可直接展示
    _warm_insights(session)

    # 庭审全部完成时发送通知
    if session.current_phase == 8:
        _create_notification(
            db, current_user.id, "trial_complete",
            "庭审已结束",
            f"案件「{session.case_input.case_title or '未命名案件'}」的模拟庭审已全部完成。",
            {"case_id": req.case_id},
        )

    return {
        "case_id": req.case_id,
        "phases": _build_phases_response(result_state),
        "current_phase": session.current_phase,
        "awaiting_confirm": (
            needs_confirmation(session.current_phase, session.user_role)
            and not getattr(session, f"phase{session.current_phase}_confirmed", False)
        ),
    }


@app.post("/trial/continue")
async def continue_trial(
    req: ContinueTrialRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _require_session_access(req.case_id, current_user)

    # 标记已确认并应用用户编辑
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
    elif req.confirmed_phase == 5:
        session.phase5_confirmed = True
        if req.edited_content:
            session.phase5_issues = req.edited_content
    elif req.confirmed_phase == 6:
        session.phase6_confirmed = True
        if req.edited_content:
            session.phase6_cross_exam = req.edited_content
    elif req.confirmed_phase == 7:
        session.phase7_confirmed = True
        if req.edited_content:
            session.phase7_plaintiff_final = req.edited_content

    # 把当前 session 转成 state 继续运行
    state = _session_to_state(session)

    meta_token = llm_meta_ctx.set({"user_id": current_user.id, "case_id": req.case_id})
    try:
        result_state = await run_trial(state)
    except Exception as e:
        logger.error(f"trial/continue error: {e}")
        raise HTTPException(503, f"庭审生成服务暂时不可用，请稍后重试。详情: {str(e)}")
    finally:
        llm_meta_ctx.reset(meta_token)

    _state_to_session(result_state, session)
    _warm_insights(session)

    # 保存快照（用于历史回退）
    if session.current_phase > 0:
        session.snapshots.append(_make_snapshot(session))

    _save_sessions()

    # 庭审全部完成时发送通知
    if session.current_phase == 8:
        _create_notification(
            db, current_user.id, "trial_complete",
            "庭审已结束",
            f"案件「{session.case_input.case_title or '未命名案件'}」的模拟庭审已全部完成。",
            {"case_id": req.case_id},
        )

    return {
        "case_id": req.case_id,
        "phases": _build_phases_response(result_state),
        "current_phase": session.current_phase,
        "awaiting_confirm": (
            needs_confirmation(session.current_phase, session.user_role)
            and not getattr(session, f"phase{session.current_phase}_confirmed", False)
        ),
    }


@app.post("/trial/select-strategy/{case_id}")
async def select_strategy(
    case_id: str,
    req: SelectStrategyRequest,
    current_user: User = Depends(get_current_user),
):
    """单方对抗模式：用户选择诉讼策略路线"""
    session = _require_session_access(case_id, current_user)

    if req.phase not in (1, 3):
        raise HTTPException(400, "phase 必须为 1 或 3")

    # 验证 route_id 是否存在于已生成的路线中
    routes_attr = f"phase{req.phase}_strategy_routes"
    selected_attr = f"phase{req.phase}_selected_route"
    pending_attr = f"phase{req.phase}_strategy_pending"

    routes = getattr(session, routes_attr, [])
    valid_route_ids = {r.get("route_id") for r in routes if isinstance(r, dict)}
    if req.route_id not in valid_route_ids:
        raise HTTPException(400, f"无效的策略路线 ID: {req.route_id}")

    # 设置选择并清除等待标志
    setattr(session, selected_attr, req.route_id)
    setattr(session, pending_attr, False)

    # 恢复 agent 并注入策略笔记（供后续 formulate_strategy 使用）
    from .orchestration.workflow_v2 import _restore_agents_v2
    state = _session_to_state(session)
    agents = _restore_agents_v2(state)

    if req.phase == 1:
        agent = agents["plaintiff"]
    else:
        agent = agents["defendant"]

    selected = next((r for r in routes if r.get("route_id") == req.route_id), None)
    if selected:
        agent.memory.private.strategy_notes = (
            f"选定策略路线 [{selected['route_id']}]：{selected['title']}\n"
            f"核心主张：{selected['core_theory']}\n"
            f"法律依据：{selected['legal_basis']}\n"
            f"证据策略：{selected['evidence_strategy']}"
        )

    # 保存 agent 状态回 session
    from .orchestration.workflow_v2 import _save_agents_v2
    _save_agents_v2(state, agents)
    _state_to_session(state, session)
    _save_sessions()

    return {
        "case_id": case_id,
        "phase": req.phase,
        "route_id": req.route_id,
        "message": "策略路线已选择",
    }


@app.get("/trial/state/{case_id}")
async def get_trial_state(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(case_id, current_user)
    state = _session_to_state(session)
    return {
        "case_id": case_id,
        "current_phase": session.current_phase,
        "user_role": session.user_role,
        "mode": session.case_input.mode,
        "user_side": session.case_input.user_side,
        "phase1_confirmed": session.phase1_confirmed,
        "phase2_confirmed": session.phase2_confirmed,
        "phase3_confirmed": session.phase3_confirmed,
        "phase4_confirmed": session.phase4_confirmed,
        "phase5_confirmed": session.phase5_confirmed,
        "phase6_confirmed": session.phase6_confirmed,
        "phase7_confirmed": session.phase7_confirmed,
        "phase1_strategy_pending": session.phase1_strategy_pending,
        "phase3_strategy_pending": session.phase3_strategy_pending,
        "phase1_strategy_routes": session.phase1_strategy_routes,
        "phase3_strategy_routes": session.phase3_strategy_routes,
        "phase1_selected_route": session.phase1_selected_route,
        "phase3_selected_route": session.phase3_selected_route,
        "phase_labels": PHASE_LABELS,
        "win_rate": session.phase8_win_rate,
        "phases": _build_phases_response(state),
    }


@app.get("/cases")
async def list_cases(
    q: str = "",
    mode: str = "",
    phase: int = -1,
    sort: str = "created_at_desc",
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回当前用户的庭审会话摘要，支持搜索、过滤、排序和分页"""
    from sqlalchemy import asc, desc

    query = db.query(Case).filter(Case.user_id == current_user.id)

    # 阶段过滤（DB 层）
    if phase >= 0:
        query = query.filter(Case.current_phase == phase)

    # 排序（DB 层）
    if sort == "created_at_asc":
        query = query.order_by(asc(Case.created_at))
    elif sort == "title_asc":
        query = query.order_by(asc(Case.case_title))
    else:  # created_at_desc
        query = query.order_by(desc(Case.created_at))

    db_cases = query.all()

    # Python 层过滤（mode + 全文搜索，兼容 SQLite/PostgreSQL）
    result = []
    for case in db_cases:
        case_input = case.case_input or {}

        # 模式过滤
        if mode and (case_input.get("mode") or "neutral") != mode:
            continue

        # 全文搜索（标题、事实、证据、诉讼请求）
        if q:
            searchable_text = " ".join([
                case.case_title or "",
                case_input.get("facts", ""),
                case_input.get("evidence", ""),
                case_input.get("claims", ""),
            ]).lower()
            if q.lower() not in searchable_text:
                continue

        result.append({
            "case_id": case.id,
            "case_title": case.case_title,
            "current_phase": case.current_phase,
            "created_at": case.created_at.isoformat() if case.created_at else "",
            "mode": case_input.get("mode") or "neutral",
            "user_side": case_input.get("user_side") or "",
        })

    total = len(result)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": result[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/usage/summary")
async def get_usage_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回当前用户的 LLM 用量汇总（今日、本月、总计）"""
    from sqlalchemy import func
    from .models.database import LLMUsageRecord

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 日用量
    today_usage = (
        db.query(func.sum(LLMUsageRecord.total_tokens))
        .filter(LLMUsageRecord.user_id == current_user.id, LLMUsageRecord.created_at >= today_start)
        .scalar()
        or 0
    )
    # 月用量
    month_usage = (
        db.query(func.sum(LLMUsageRecord.total_tokens))
        .filter(LLMUsageRecord.user_id == current_user.id, LLMUsageRecord.created_at >= month_start)
        .scalar()
        or 0
    )
    # 总用量
    total_usage = (
        db.query(func.sum(LLMUsageRecord.total_tokens))
        .filter(LLMUsageRecord.user_id == current_user.id)
        .scalar()
        or 0
    )
    # 总调用次数
    total_calls = (
        db.query(func.count(LLMUsageRecord.id))
        .filter(LLMUsageRecord.user_id == current_user.id)
        .scalar()
        or 0
    )

    return {
        "daily": {
            "used": int(today_usage),
            "limit": current_user.daily_token_limit,
            "remaining": max(0, current_user.daily_token_limit - int(today_usage)),
        },
        "monthly": {
            "used": int(month_usage),
            "limit": current_user.monthly_token_limit,
            "remaining": max(0, current_user.monthly_token_limit - int(month_usage)),
        },
        "total": {
            "tokens": int(total_usage),
            "calls": int(total_calls),
        },
    }


@app.get("/usage")
async def get_usage_records(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回当前用户的 LLM 用量明细"""
    from .models.database import LLMUsageRecord

    query = db.query(LLMUsageRecord).filter(LLMUsageRecord.user_id == current_user.id)
    total = query.count()
    records = (
        query.order_by(LLMUsageRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            {
                "id": r.id,
                "case_id": r.case_id,
                "model": r.model,
                "endpoint": r.endpoint,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "latency_ms": r.latency_ms,
                "success": r.success,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.delete("/cases/{case_id}")
async def delete_case(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除指定庭审会话 —— 级联删 JSON session、DB 元数据、证据文件、LLM 用量记录"""
    _require_session_access(case_id, current_user)

    # 1. 从内存删除 session
    session = sessions.pop(case_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail="案件不存在")

    # 2. 持久化 JSON
    _save_sessions()

    # 3. 删除证据磁盘文件
    try:
        delete_case_evidence_files(case_id)
    except Exception as e:
        logger.warning(f"删除证据文件失败 case_id={case_id}: {e}")

    # 4. 级联删除 DB 行：Case（外键 CASCADE 自动删 CasePhase/CaseAnalysis/EvidenceItem/CaseShare）
    try:
        from .database import SessionLocal
        from .models.database import LLMUsageRecord
        db = SessionLocal()
        try:
            case_row = db.query(Case).filter(Case.id == case_id).first()
            if case_row:
                db.delete(case_row)
            # LLMUsageRecord.case_id 无 FK，手动清理
            db.query(LLMUsageRecord).filter(LLMUsageRecord.case_id == case_id).delete()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"删除 DB 记录失败 case_id={case_id}: {e}")

    # 5. 删除 Ontology 缓存与文件
    try:
        ontology_service.delete_ontology(case_id)
    except Exception as e:
        logger.warning(f"删除 Ontology 失败 case_id={case_id}: {e}")

    # 6. 删除 Agentic Proposal
    try:
        agentic_service.delete_proposals_by_case(case_id)
    except Exception as e:
        logger.warning(f"删除 Agentic Proposal 失败 case_id={case_id}: {e}")

    return {"case_id": case_id, "message": "已删除（含证据文件与数据库记录）"}


class RenameCaseRequest(BaseModel):
    case_title: str


@app.patch("/cases/{case_id}")
async def rename_case(
    case_id: str,
    req: RenameCaseRequest,
    current_user: User = Depends(get_current_user),
):
    """重命名指定庭审会话"""
    session = _require_session_access(case_id, current_user)
    session.case_input.case_title = req.case_title
    _save_sessions()
    return {"case_id": case_id, "case_title": req.case_title, "message": "已重命名"}


@app.get("/trial/content/{case_id}/{phase}")
async def get_phase_content(
    case_id: str,
    phase: int,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(case_id, current_user)
    phase_content_map = {
        1: session.phase1_analysis,
        2: session.phase2_complaint,
        3: session.phase3_analysis,
        4: session.phase4_answer,
        5: session.phase5_issues,
        6: {
            "cross_exam": session.phase6_cross_exam,
            "evidence_exam": session.phase6_evidence_exam,
        },
        7: {
            "plaintiff_final": session.phase7_plaintiff_final,
            "defendant_final": session.phase7_defendant_final,
        },
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
async def export_report(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(case_id, current_user)
    md = export_markdown(session)

    return {
        "case_id": case_id,
        "format": "markdown",
        "content": md,
    }


@app.get("/trial/export-pdf/{case_id}")
async def export_report_pdf(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(case_id, current_user)
    analysis = _get_analysis(session)

    # 创建临时 PDF 文件
    import tempfile
    temp_dir = tempfile.gettempdir()
    pdf_path = os.path.join(temp_dir, f"case_report_{case_id}.pdf")

    try:
        # 生成 PDF
        generate_case_report(session, analysis, pdf_path)

        # 返回文件下载
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=f"模拟法庭报告_{session.case_input.case_title}_{case_id}.pdf"
        )
    except Exception as e:
        logger.error(f"PDF export error: {e}", exc_info=True)
        raise HTTPException(500, f"PDF 生成失败: {str(e)}")


@app.post("/trial/judge-qa")
async def judge_qa(
    req: JudgeQARequest,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(req.case_id, current_user)
    if not session.phase8_judgment:
        raise HTTPException(400, "庭审尚未完成，无法进行庭后问答")

    # 多 Agent 版本：直接使用 JudgeAgent
    from .agents import JudgeAgent
    judge = JudgeAgent()

    trial_record = f"""【起诉状】\n{session.phase2_complaint}\n\n【答辩状】\n{session.phase4_answer}"""

    try:
        answer = await judge.answer_question(
            session.phase8_judgment, trial_record, req.question
        )
    except Exception as e:
        logger.error(f"judge-qa error: {e}")
        raise HTTPException(503, f"AI 回答服务暂时不可用，请稍后重试。")

    return {"question": req.question, "answer": answer}


# ============================================================
# SSE 流式庭审（混合粒度：Phase 1-5/7-8 token 级，Phase 6 agent 步骤级）
# ============================================================

@app.post("/trial/stream")
async def trial_stream(
    req: TrialStreamRequest,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(req.case_id, current_user)

    if req.action == "start":
        # 单方对抗模式下 user_role 由创建时固定，不允许前端篡改
        if session.case_input.mode != "asymmetric":
            session.user_role = req.user_role
        if req.llm_config:
            session.llm_config = LLMConfig(
                base_url=req.llm_config.base_url,
                api_key=req.llm_config.api_key,
                model=req.llm_config.model,
                temperature=req.llm_config.temperature,
            )
    elif req.action == "continue":
        # 应用确认和编辑
        cp = req.confirmed_phase
        if 1 <= cp <= 7:
            setattr(session, f"phase{cp}_confirmed", True)
            if req.edited_content:
                field_map = {
                    1: "phase1_analysis",
                    2: "phase2_complaint",
                    3: "phase3_analysis",
                    4: "phase4_answer",
                    5: "phase5_issues",
                    6: "phase6_cross_exam",
                    7: "phase7_plaintiff_final",
                }
                if field_map.get(cp):
                    setattr(session, field_map[cp], req.edited_content)

    state = _session_to_state(session)
    queue: asyncio.Queue = asyncio.Queue()

    async def run_graph():
        from .streaming import stream_queue_ctx

        meta_token = llm_meta_ctx.set({"user_id": current_user.id, "case_id": req.case_id})
        stream_queue_ctx.set(queue)
        try:
            result_state = await run_trial(state)
            _state_to_session(result_state, session)
            _warm_insights(session)
            if session.current_phase > 0:
                session.snapshots.append(_make_snapshot(session))
            _save_sessions()

            # 庭审全部完成时发送通知
            if session.current_phase == 8:
                notif_db = None  # P4 修复：前置初始化避免 SessionLocal() 抛错时 finally NameError
                try:
                    from .database import SessionLocal
                    notif_db = SessionLocal()
                    _create_notification(
                        notif_db, current_user.id, "trial_complete",
                        "庭审已结束",
                        f"案件「{session.case_input.case_title or '未命名案件'}」的模拟庭审已全部完成。",
                        {"case_id": req.case_id},
                    )
                except Exception as ne:
                    logger.warning(f"通知创建失败: {ne}")
                finally:
                    if notif_db is not None:
                        notif_db.close()

            # 构建等待策略选择信息
            awaiting_strategy = None
            if session.phase1_strategy_pending and session.current_phase == 1:
                awaiting_strategy = {"phase": 1, "routes": session.phase1_strategy_routes}
            elif session.phase3_strategy_pending and session.current_phase == 3:
                awaiting_strategy = {"phase": 3, "routes": session.phase3_strategy_routes}

            queue.put_nowait(
                {
                    "type": "done",
                    "current_phase": session.current_phase,
                    "phases": _build_phases_response(result_state),
                    "awaiting_confirm": (
                        needs_confirmation(session.current_phase, session.user_role)
                        and not getattr(
                            session, f"phase{session.current_phase}_confirmed", False
                        )
                    ),
                    "awaiting_strategy_selection": awaiting_strategy,
                }
            )
        except Exception as e:
            logger.error(f"trial/stream error: {e}")
            queue.put_nowait({"type": "error", "message": str(e)})
        finally:
            llm_meta_ctx.reset(meta_token)
            stream_queue_ctx.set(None)

    async def event_generator():
        task = asyncio.create_task(run_graph())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ============================================================
# 洞察卡片（优先读 CaseAnalysis 缓存）
# ============================================================
@app.get("/trial/insights/{case_id}/{phase}")
async def get_phase_insights(
    case_id: str,
    phase: int,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(case_id, current_user)
    if not 1 <= phase <= 8:
        raise HTTPException(400, "阶段编号必须在 1-8 之间")

    # 优先从 CaseAnalysis（单一事实源）读取
    analysis = _get_analysis(session)
    if phase in analysis.insight_cards:
        return {"case_id": case_id, "phase": phase, "insights": analysis.insight_cards[phase]}

    # 兼容旧缓存
    cached = session.insights_cache.get(str(phase))
    if cached is not None:
        return {"case_id": case_id, "phase": phase, "insights": cached}

    # 都没有，触发统一提取（防御 None 拼接）
    content_map = {
        1: session.phase1_analysis or "",
        2: session.phase2_complaint or "",
        3: session.phase3_analysis or "",
        4: session.phase4_answer or "",
        5: session.phase5_issues or "",
        6: (session.phase6_cross_exam or "") + "\n\n" + (session.phase6_evidence_exam or ""),
        7: (session.phase7_plaintiff_final or "") + "\n\n" + (session.phase7_defendant_final or ""),
        8: session.phase8_judgment or "",
    }
    content = content_map.get(phase, "")
    if not content:
        return {"case_id": case_id, "phase": phase, "insights": None, "message": "该阶段尚无内容"}

    known_win_rate = session.phase8_win_rate if phase == 8 else None
    meta_token = llm_meta_ctx.set({"user_id": current_user.id, "case_id": case_id})
    try:
        extracted = await extract_phase_unified(
            phase, content, analysis,
            llm_config=session.llm_config,
            known_win_rate=known_win_rate,
        )
    except Exception as e:
        logger.error(f"get_phase_insights extraction error: {e}", exc_info=True)
        return {"case_id": case_id, "phase": phase, "insights": None, "message": f"提取失败: {str(e)}"}
    finally:
        llm_meta_ctx.reset(meta_token)

    if extracted:
        apply_extraction(analysis, phase, extracted)
        if phase == 8 and session.phase8_win_rate > 0:
            analysis.set_win_rate(session.phase8_win_rate, analysis.win_rate_dimensions)
        _save_analysis(session, analysis)
        # 同步旧缓存
        if phase in analysis.insight_cards:
            session.insights_cache[str(phase)] = analysis.insight_cards[phase]
        _save_sessions()
        return {"case_id": case_id, "phase": phase, "insights": analysis.insight_cards.get(phase)}

    return {"case_id": case_id, "phase": phase, "insights": None, "message": "提取失败"}


# ============================================================
# 证据模块（多模态证据处理）
# ============================================================

def _get_extractor_for_file(filename: str):
    """根据文件名查找合适的提取器"""
    from .evidence.extractors import ALL_EXTRACTORS as _extractors
    for extractor in _extractors:
        if extractor.can_handle(filename):
            return extractor
    return None


async def _process_zip_upload(
    case_id: str,
    zip_filename: str,
    zip_bytes: bytes,
    party: str,
    evidence_type: str,
    current_user: User,
    db: Session,
) -> list[dict]:
    """处理 ZIP 批量上传：解压后逐文件处理"""
    results = []
    temp_dir = tempfile.mkdtemp(prefix="evidence_upload_")

    try:
        # 保存 ZIP 到临时目录
        zip_path = os.path.join(temp_dir, zip_filename)
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)

        # 解压
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        extract_dir_real = os.path.realpath(extract_dir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Zip Slip 防护：逐个 entry 校验解压目标仍在 extract_dir 内，
            # 拒绝含 ".."、绝对路径或盘符的恶意条目。
            for member in zf.namelist():
                target = os.path.realpath(os.path.join(extract_dir, member))
                if target != extract_dir_real and not target.startswith(extract_dir_real + os.sep):
                    logger.warning(f"[security] 拒绝越界 ZIP 条目: {member}")
                    continue
                zf.extract(member, extract_dir)

        # 遍历解压后的文件
        inner_files = []
        for root, _dirs, files in os.walk(extract_dir):
            for fname in files:
                inner_files.append(os.path.join(root, fname))

        for inner_path in inner_files:
            inner_name = os.path.relpath(inner_path, extract_dir)
            with open(inner_path, "rb") as f:
                inner_bytes = f.read()

            if len(inner_bytes) == 0:
                results.append({"filename": inner_name, "status": "error", "message": "空文件"})
                continue

            # 保存到正式上传目录
            storage_path = save_uploaded_file(case_id, inner_name, inner_bytes)

            # 查找提取器
            extractor = _get_extractor_for_file(inner_name)
            if not extractor:
                results.append({
                    "filename": inner_name,
                    "status": "unsupported",
                    "message": "不支持的文件格式",
                })
                continue

            abs_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "data", "uploads", storage_path
            )
            try:
                item = await extractor.extract(abs_path, metadata={
                    "upload_time": datetime.now().isoformat(),
                    "original_filename": inner_name,
                    "zip_source": zip_filename,
                })
            except Exception as e:
                logger.error(f"提取失败 {inner_name}: {e}")
                results.append({"filename": inner_name, "status": "error", "message": str(e)})
                continue

            item.id = f"ev_{uuid.uuid4().hex[:10]}"
            item.storage_path = storage_path
            item.file_size = len(inner_bytes)
            item.mime_type = "application/octet-stream"
            item.party = party if party in ("plaintiff", "defendant", "third_party", "unknown") else "unknown"
            item.evidence_type = evidence_type
            item.status = "pending"
            item.created_at = datetime.now().isoformat()

            add_evidence_item(case_id, item, current_user.id, db)

            results.append({
                "filename": inner_name,
                "status": "success",
                "evidence_id": item.id,
                "source_type": item.source_type,
                "preview": item.content[:200] if item.content else "",
            })
    except Exception as e:
        logger.error(f"ZIP 处理失败 {zip_filename}: {e}")
        results.append({"filename": zip_filename, "status": "error", "message": f"ZIP 处理失败: {e}"})
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return results


@app.post("/evidence/upload")
async def evidence_upload(
    case_id: str = Form(...),
    files: list[UploadFile] = File(...),
    party: str = Form("unknown"),
    evidence_type: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    上传证据文件（支持多文件）

    - case_id: 关联的案件 ID
    - files: 文件列表
    - party: 证据归属立场 (plaintiff/defendant/third_party/unknown)
    - evidence_type: 证据类型（可选，留空则由 AI 自动判断）
    """
    # 验证案件所有权
    _require_session_access(case_id, current_user)

    logger.info(f"收到上传请求: case_id={case_id}, files数量={len(files)}, party={party}")
    results = []
    for upload_file in files:
        filename = upload_file.filename or "unnamed"
        file_bytes = await upload_file.read()
        logger.info(f"处理文件: {filename}, 大小={len(file_bytes)} bytes")

        if len(file_bytes) == 0:
            results.append({"filename": filename, "status": "error", "message": "空文件"})
            continue

        # 保存到磁盘
        storage_path = save_uploaded_file(case_id, filename, file_bytes)

        # ZIP 批量处理：解压后逐文件处理
        if filename.lower().endswith(".zip"):
            zip_results = await _process_zip_upload(
                case_id, filename, file_bytes, party, evidence_type, current_user, db
            )
            results.extend(zip_results)
            continue

        # 查找提取器
        extractor = _get_extractor_for_file(filename)
        if not extractor:
            results.append({
                "filename": filename,
                "status": "unsupported",
                "message": "不支持的文件格式",
            })
            continue

        # 提取内容
        abs_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "uploads", storage_path
        )
        try:
            item = await extractor.extract(abs_path, metadata={
                "upload_time": datetime.now().isoformat(),
                "original_filename": filename,
            })
        except Exception as e:
            logger.error(f"提取失败 {filename}: {e}")
            results.append({"filename": filename, "status": "error", "message": str(e)})
            continue

        # 填充元数据
        item.id = f"ev_{uuid.uuid4().hex[:10]}"
        item.storage_path = storage_path
        item.file_size = len(file_bytes)
        item.mime_type = upload_file.content_type or "application/octet-stream"
        item.party = party if party in ("plaintiff", "defendant", "third_party", "unknown") else "unknown"
        item.evidence_type = evidence_type
        item.status = "pending"  # 等待 AI 分析
        item.created_at = datetime.now().isoformat()

        # 保存到登记簿
        add_evidence_item(case_id, item, current_user.id, db)

        results.append({
            "filename": filename,
            "status": "success",
            "evidence_id": item.id,
            "source_type": item.source_type,
            "preview": item.content[:200] if item.content else "",
        })

    return {
        "case_id": case_id,
        "uploaded": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "error"]),
        "results": results,
    }


@app.get("/evidence/{case_id}")
async def get_evidence(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取案件的完整证据登记簿"""
    _require_session_access(case_id, current_user)
    registry = get_registry(case_id, db)
    return registry.to_dict()


@app.post("/evidence/{case_id}/analyze")
async def analyze_evidence_endpoint(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    触发证据 AI 分析（摘要 + 分类 + 冲突检测）

    这是一个异步操作，可能需要几秒钟到几分钟（取决于证据数量和 LLM 响应速度）。
    """
    session = _require_session_access(case_id, current_user)

    meta_token = llm_meta_ctx.set({"user_id": current_user.id, "case_id": case_id})
    try:
        # Step 1: 单条证据分析（摘要、分类、提取信息）
        registry = await analyze_all_evidence(case_id, current_user.id, db)

        # Step 2: 冲突检测 + 时间线提取
        registry = await analyze_conflicts(case_id, current_user.id, db)
    finally:
        llm_meta_ctx.reset(meta_token)

    # 证据分析完成通知
    _create_notification(
        db, current_user.id, "evidence_ready",
        "证据分析完成",
        f"案件「{session.case_input.case_title or '未命名案件'}」的证据分析已完成，共分析 {len(registry.items)} 条证据。",
        {"case_id": case_id},
    )

    return {
        "case_id": case_id,
        "item_count": len(registry.items),
        "analyzed_count": len([it for it in registry.items if it.status == "completed"]),
        "conflict_count": len(registry.conflicts),
        "timeline_count": len(registry.timeline),
        "conflicts": [c.to_dict() if hasattr(c, "to_dict") else {
            "id": c.id,
            "conflict_type": c.conflict_type,
            "severity": c.severity,
            "description": c.description,
            "involved_evidence_ids": c.involved_evidence_ids,
            "claims": [{"evidence_id": cl.evidence_id, "party": cl.party, "extracted_claim": cl.extracted_claim} for cl in c.claims],
        } for c in registry.conflicts],
    }


@app.post("/evidence/{case_id}/import-to-trial")
async def import_evidence_to_trial(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """将证据导入庭审系统，更新 TrialSession 的证据字段"""
    session = _require_session_access(case_id, current_user)

    result = import_to_trial_session(case_id, session)

    # 保存 session（import_to_trial_session 已直接修改 session 对象）
    _save_sessions()

    return {
        "case_id": case_id,
        "imported_count": result["item_count"],
        "evidence_preview": result["evidence_text"][:500] if result["evidence_text"] else "",
    }


@app.delete("/evidence/{case_id}/{evidence_id}")
async def delete_evidence(
    case_id: str,
    evidence_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除单条证据"""
    _require_session_access(case_id, current_user)

    success = delete_evidence_item(case_id, evidence_id, db)
    if not success:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "证据不存在")

    return {"case_id": case_id, "evidence_id": evidence_id, "deleted": True}


# ============================================================
# 庭审历史与回退
# ============================================================
@app.get("/trial/history/{case_id}")
async def get_trial_history(
    case_id: str,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(case_id, current_user)
    return {
        "case_id": case_id,
        "snapshots": session.snapshots,
        "current_phase": session.current_phase,
    }


@app.post("/trial/reset/{case_id}/{to_phase}")
async def reset_trial(
    case_id: str,
    to_phase: int,
    current_user: User = Depends(get_current_user),
):
    session = _require_session_access(case_id, current_user)
    if not 1 <= to_phase <= 8:
        raise HTTPException(400, "阶段编号必须在 1-8 之间")

    session = sessions[case_id]
    _reset_to_phase(session, to_phase)
    _save_sessions()

    # 重新构建 phases 响应
    state = _session_to_state(session)
    return {
        "case_id": case_id,
        "message": f"已回退到 Phase {to_phase}",
        "phases": _build_phases_response(state),
        "current_phase": session.current_phase,
        "awaiting_confirm": (
            needs_confirmation(session.current_phase, session.user_role)
            and not getattr(session, f"phase{session.current_phase}_confirmed", False)
        ),
    }


# ============================================================
# 通知辅助函数
# ============================================================
def _create_notification(
    db: Session,
    user_id: int,
    type: str,
    title: str,
    message: str,
    data: dict | None = None,
):
    from .models.database import Notification
    db.add(Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        data=data or {},
    ))
    db.commit()


# ============================================================
# 案件分享
# ============================================================
@app.post("/cases/{case_id}/share")
async def create_share(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建案件的只读分享链接"""
    _require_session_access(case_id, current_user)
    from .models.database import CaseShare

    share_id = uuid.uuid4().hex[:12]
    token = uuid.uuid4().hex[:16]
    db.add(CaseShare(
        id=share_id,
        case_id=case_id,
        created_by=current_user.id,
        token=token,
        permission="read",
    ))
    db.commit()

    return {
        "share_id": share_id,
        "token": token,
        "url": f"/shared/{token}",
    }


@app.get("/cases/{case_id}/shares")
async def list_shares(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出案件的所有分享链接"""
    _require_session_access(case_id, current_user)
    from .models.database import CaseShare

    shares = db.query(CaseShare).filter(CaseShare.case_id == case_id).order_by(CaseShare.created_at.desc()).all()
    return {
        "shares": [
            {
                "id": s.id,
                "token": s.token,
                "url": f"/shared/{s.token}",
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in shares
        ]
    }


@app.delete("/cases/{case_id}/share/{share_id}")
async def delete_share(
    case_id: str,
    share_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """撤销分享链接"""
    _require_session_access(case_id, current_user)
    from .models.database import CaseShare

    share = db.query(CaseShare).filter(CaseShare.id == share_id, CaseShare.case_id == case_id).first()
    if not share:
        raise HTTPException(404, "分享链接不存在")
    db.delete(share)
    db.commit()
    return {"message": "分享链接已撤销"}


@app.get("/shared/{token}")
async def get_shared_case(
    token: str,
    db: Session = Depends(get_db),
):
    """通过分享 token 访问案件（只读，无需登录）"""
    from .models.database import CaseShare

    share = db.query(CaseShare).filter(CaseShare.token == token).first()
    if not share:
        raise HTTPException(404, "分享链接不存在或已失效")

    session = sessions.get(share.case_id)
    if not session:
        raise HTTPException(404, "案件不存在")

    state = _session_to_state(session)
    return {
        "case_id": share.case_id,
        "case_title": session.case_input.case_title,
        "current_phase": session.current_phase,
        "phases": _build_phases_response(state),
        "shared_at": share.created_at.isoformat() if share.created_at else None,
    }


# ============================================================
# 通知系统
# ============================================================
@app.get("/notifications")
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50,
):
    """获取当前用户的通知列表"""
    from .models.database import Notification

    items = db.query(Notification).filter(
        Notification.user_id == current_user.id
    ).order_by(Notification.created_at.desc()).limit(limit).all()

    return {
        "items": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "data": n.data,
                "read": n.read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in items
        ],
        "unread_count": sum(1 for n in items if not n.read),
    }


@app.post("/notifications/{notif_id}/read")
async def mark_notification_read(
    notif_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """标记通知为已读"""
    from .models.database import Notification

    notif = db.query(Notification).filter(
        Notification.id == notif_id,
        Notification.user_id == current_user.id,
    ).first()
    if not notif:
        raise HTTPException(404, "通知不存在")
    notif.read = True
    db.commit()
    return {"message": "已标记为已读"}


@app.post("/notifications/read-all")
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """标记所有通知为已读"""
    from .models.database import Notification

    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.read == False,
    ).update({"read": True})
    db.commit()
    return {"message": "全部标记为已读"}


@app.delete("/notifications/{notif_id}")
async def delete_notification(
    notif_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除通知"""
    from .models.database import Notification

    notif = db.query(Notification).filter(
        Notification.id == notif_id,
        Notification.user_id == current_user.id,
    ).first()
    if not notif:
        raise HTTPException(404, "通知不存在")
    db.delete(notif)
    db.commit()
    return {"message": "已删除"}


# ============================================================
# 健康检查
# ============================================================
@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.0.0", "architecture": "multi-agent"}
