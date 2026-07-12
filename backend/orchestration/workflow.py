"""
LangGraph 多 Agent 庭审工作流

用 StateGraph 编排 8 阶段庭审，核心改造：
- Phase 6 交叉询问：真实 Agent 循环交互（非单次 LLM 扮演）
- Phase 6B 举证质证：逐项真实 Agent 交互
- Phase 1-4：顺序执行 + 可选 human confirm（interrupt）
"""

import asyncio
import logging
from typing import TypedDict, Optional
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime

from langgraph.graph import StateGraph, START, END

from ..models.case import CaseInput
from ..llm import LLMConfig
from ..streaming import put_event
# 注意：retrieve_legal_knowledge 在 _build_rag_context 内延迟导入。
# 若在此处顶层 import 会拖慢 uvicorn 启动（ChromaDB + sentence-transformers 加载 30-60s），
# 导致前端在启动期间误报「后端未启动」。
logger = logging.getLogger(__name__)


async def _retry_async(func, max_retries: int = 2, *args, **kwargs):
    """带重试的异步调用包装器"""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            logger.warning(f"Retry {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(1)
    raise last_error


def _build_rag_context(case_title: str, facts: str, claims: str, phase: int, max_length: int = 3000) -> str:
    """
    使用 RAG 检索相关法律知识并构建上下文

    Args:
        case_title: 案由
        facts: 案件事实
        claims: 诉讼请求
        phase: 当前阶段
        max_length: 最大上下文长度

    Returns:
        格式化的法律知识上下文
    """
    try:
        # 懒加载 RAG 检索器（避免 uvicorn 启动时 ChromaDB + sentence-transformers 拖慢端口绑定）
        from ..rag.retriever import retrieve_legal_knowledge as _retrieve

        # 构建检索查询
        query = f"{case_title} {facts[:500]} {claims[:300]}"

        # 检索法律知识
        legal_context = _retrieve(query, phase=phase, domain="civil")

        if not legal_context:
            logger.info(f"Phase {phase}: RAG 未检索到相关法律知识")
            return ""

        # 截断到最大长度
        if len(legal_context) > max_length:
            legal_context = legal_context[:max_length] + "\n...(内容已截断)"

        logger.info(f"Phase {phase}: RAG 检索到 {len(legal_context)} 字符的法律知识")
        return legal_context

    except Exception as e:
        logger.warning(f"Phase {phase}: RAG 检索失败: {e}")
        return ""


# ============================================================
# 状态定义
# ============================================================

class TrialState(TypedDict):
    case_input: CaseInput
    current_phase: int
    user_role: str

    # 阶段产出
    phase1_analysis: str
    phase2_complaint: str
    phase2_evidence_catalog: str
    phase3_analysis: str
    phase4_answer: str
    phase4_evidence_catalog: str
    phase5_issues: str
    phase6_cross_exam: str
    phase6_evidence_exam: str
    phase7_plaintiff_final: str
    phase7_defendant_final: str
    phase8_judgment: str
    phase8_win_rate: float

    # 用户确认
    phase1_confirmed: bool
    phase2_confirmed: bool
    phase3_confirmed: bool
    phase4_confirmed: bool
    phase5_confirmed: bool
    phase6_confirmed: bool
    phase7_confirmed: bool

    # Agent 可序列化状态
    plaintiff_state: dict
    defendant_state: dict
    judge_state: dict
    reporter_state: dict

    # Phase 6 循环控制
    cross_exam_round: int
    cross_exam_context: str
    current_evidence_index: int
    evidence_list: list[str]

    # LLM 配置
    llm_config: LLMConfig | None

    # 策略路线（单方对抗模式）
    phase1_strategy_routes: list[dict]
    phase1_selected_route: str
    phase3_strategy_routes: list[dict]
    phase3_selected_route: str

    # 策略选择等待标志
    phase1_strategy_pending: bool
    phase3_strategy_pending: bool

    # 错误
    error: str


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
    # 所有 phase 都暂停，前端分步推进，避免单次请求累积超时
    return True


def _init_state(case_input: CaseInput, user_role: str = "neutral") -> TrialState:
    return TrialState(
        case_input=case_input,
        current_phase=0,
        user_role=user_role,
        phase1_analysis="",
        phase2_complaint="",
        phase2_evidence_catalog="",
        phase3_analysis="",
        phase4_answer="",
        phase4_evidence_catalog="",
        phase5_issues="",
        phase6_cross_exam="",
        phase6_evidence_exam="",
        phase7_plaintiff_final="",
        phase7_defendant_final="",
        phase8_judgment="",
        phase8_win_rate=0.0,
        phase1_confirmed=False,
        phase2_confirmed=False,
        phase3_confirmed=False,
        phase4_confirmed=False,
        phase5_confirmed=False,
        phase6_confirmed=False,
        phase7_confirmed=False,
        plaintiff_state={},
        defendant_state={},
        judge_state={},
        reporter_state={},
        cross_exam_round=0,
        cross_exam_context="",
        current_evidence_index=0,
        evidence_list=[],
        phase1_strategy_routes=[],
        phase1_selected_route="",
        phase3_strategy_routes=[],
        phase3_selected_route="",
        phase1_strategy_pending=False,
        phase3_strategy_pending=False,
        error="",
    )


# ---- 庭审会话 dataclass（用于持久化层） ----
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

    # Phase 6 循环进度（持久化，避免 continue 时从头重来）
    cross_exam_round: int = 0
    current_evidence_index: int = 0
    evidence_list: list = field(default_factory=list)

    # Insight 缓存（避免重复 LLM 调用）— 旧字段，保留兼容
    insights_cache: dict = field(default_factory=dict)

    # 可视化数据缓存（避免重复 LLM 调用）— 旧字段，保留兼容
    viz_cache: dict = field(default_factory=dict)

    # 统一案件分析（单一事实源，替代 insights_cache + viz_cache）
    case_analysis_data: dict = field(default_factory=dict)

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
    phase5_confirmed: bool = False
    phase6_confirmed: bool = False
    phase7_confirmed: bool = False

    # Agent 可序列化状态
    plaintiff_state: dict = field(default_factory=dict)
    defendant_state: dict = field(default_factory=dict)
    judge_state: dict = field(default_factory=dict)
    reporter_state: dict = field(default_factory=dict)

    # 历史快照（用于回退）
    snapshots: list = field(default_factory=list)

    # 策略路线（单方对抗模式）
    phase1_strategy_routes: list[dict] = field(default_factory=list)
    phase1_selected_route: str = ""
    phase3_strategy_routes: list[dict] = field(default_factory=list)
    phase3_selected_route: str = ""

    # 策略选择等待标志
    phase1_strategy_pending: bool = False
    phase3_strategy_pending: bool = False

    # LLM 配置（每个 case 独立）
    llm_config: LLMConfig | None = None

    # 用户隔离（新增）
    user_id: int | None = None

    # 元数据
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrialSession":
        case_input = CaseInput(**data["case_input"])
        llm_config = LLMConfig(**data["llm_config"]) if data.get("llm_config") else None
        field_names = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in field_names and k not in ("case_input", "llm_config")}
        return cls(case_input=case_input, llm_config=llm_config, **kwargs)


# ============================================================

def _build_source_context(source_materials: str) -> str:
    """
    构建案卷原文上下文，按长度分级控制：
    - <3000 字：完整注入
    - 3000-8000 字：完整保留并提示
    - >8000 字：截断到 8000 并提示走证据系统
    """
    if not source_materials:
        return ""
    length = len(source_materials)
    if length <= 3000:
        return f"【案卷原文】\n{source_materials}\n\n请以原文为准，上述摘要仅供参考。"
    elif length <= 8000:
        return f"【案卷原文】（内容较长，已完整保留）\n{source_materials}\n\n请以原文为准，上述摘要仅供参考。"
    else:
        truncated = source_materials[:8000]
        return f"【案卷原文】（原文较长，已截断前 8000 字；建议通过证据系统上传完整材料）\n{truncated}\n\n请以原文为准，上述摘要仅供参考。"



def create_initial_state(case_input: CaseInput, user_role: str = "neutral") -> TrialState:
    return _init_state(case_input, user_role)


if __name__ == "__main__":
    session = TrialSession(
        case_input=CaseInput(case_title="test", facts="f", evidence="e", claims="c"),
        current_phase=2,
        phase1_analysis="analysis",
    )
    d = session.to_dict()
    restored = TrialSession.from_dict(d)
    assert restored == session, f"{restored} != {session}"
    print("round-trip ok")
