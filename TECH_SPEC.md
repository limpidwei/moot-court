# moot-court 技术规范文档 (TECH SPEC)

> **版本**: v3.0.0  
> **日期**: 2026-07-08  
> **状态**: 生产可用（已引入 Case Ontology + Agentic 执行器）  
> **目标读者**: 新加入的协作者、开源贡献者、独立模块开发者  
> **阅读前提**: 具备 Python 3.11+、TypeScript/React、FastAPI、LangGraph 基础

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈](#2-技术栈)
3. [系统架构总览](#3-系统架构总览)
4. [后端架构详解](#4-后端架构详解)
5. [前端架构详解](#5-前端架构详解)
6. [API 规范](#6-api-规范)
7. [数据模型](#7-数据模型)
8. [独立开发指南（模块化契约）](#8-独立开发指南模块化契约)
9. [配置与环境变量](#9-配置与环境变量)
10. [测试策略](#10-测试策略)
11. [已知问题与技术债](#11-已知问题与技术债)
12. [附录：完整文件树](#12-附录完整文件树)

---

## 1. 项目概述

**moot-court** 是一款面向中国民事诉讼的 AI 模拟法庭系统。用户输入案件材料后，系统通过多 Agent 协作模拟完整庭审流程（8 阶段），输出法律文书、策略建议、争议焦点归纳、交叉询问、举证质证、判决书及胜率评估。

### 核心特性

- **8 阶段完整庭审**: 按中国民诉法程序编排（请求权分析 → 起诉/答辩 → 争议焦点 → 交叉询问 → 举证质证 → 最后陈述 → 判决）
- **单方对抗模式 (Asymmetric Mode)**: 用户扮演原告或被告，AI 全自动代理对方律师 + 法官
- **Agent V2 架构**: Actor-Memory-Skill 模型，三层记忆隔离，ACL 受控通信，6 个内置法律 Skill
- **RAG 法律知识库**: 16 部民事法规，本地 BAAI/bge-small-zh 嵌入 + ChromaDB 向量检索
- **多模态证据系统**: 支持 txt/docx/pdf/jpg/png 上传、OCR 提取、AI 分析、冲突检测
- **流式输出**: SSE (Server-Sent Events) 推送，Phase 1-5/7-8 整段推送+前端逐字动画，Phase 6 消息级流式
- **洞察卡片**（已下线）: 每阶段 LLM 提取结构化摘要，异步预热缓存；因 LLM JSON 格式偏差导致空白率高，前端组件已移除，后端提取服务保留供后续重做
- **用量配额**: LLM 调用 Token 级追踪，日/月配额限制
- **协作分享**: 案件只读分享链接（Token 机制，免登录访问）
- **通知系统**: 庭审完成、证据分析完成自动触发站内通知

### 已下线功能（后续可能重做）

- **可视化卡片 (VizPanel)**: 2026-06-07 下线，所有 viz API 已删除，前端组件已移除
- **证据突袭 (Evidence Ambush)**: 2026-06-07 下线，相关 schema / workflow 节点 / 前端展示已删除
- **洞察卡片 (InsightCard)**: 2026-06-08 下线，前端 `InsightCard.tsx` 引用已从庭审页移除；后端 `/trial/insights/{case_id}/{phase}`、`_warm_insights`、`unified_extraction.py` 保留，供后续稳定版复用

---

## 2. 技术栈

### 后端

| 层级 | 技术 | 版本 | 说明 |
|------|------|------|------|
| 运行时 | Python | 3.11+ | |
| Web 框架 | FastAPI | latest | REST API + SSE |
| 工作流引擎 | LangGraph | latest | StateGraph 编排 8 阶段庭审 |
| LLM 调用 | OpenAI-compatible SDK | latest | 支持 DeepSeek / Kimi / GLM / MiniMax / 自定义 |
| 向量数据库 | ChromaDB | latest | 本地持久化 `data/chroma_db/` |
| 嵌入模型 | BAAI/bge-small-zh-v1.5 | offline | 512 维，92MB，本地缓存 |
| 关系数据库 | PostgreSQL | 14+ | 用户/案件/证据/用量/通知/分享 |
| ORM | SQLAlchemy | 2.x | `backend/models/database.py` |
| 认证 | JWT + bcrypt | PyJWT + passlib | Bearer Token |
| OCR | pytesseract + Pillow | latest | 本地 OCR，需安装中文语言包 |
| PDF 解析 | PyMuPDF | latest | `fitz` |
| Word 解析 | python-docx | latest | |

### 前端

| 层级 | 技术 | 说明 |
|------|------|------|
| 框架 | Next.js 16 | App Router，Turbopack |
| 语言 | TypeScript 5.x | 严格模式 |
| 样式 | Tailwind CSS 4.x | 无 UI 组件库，纯 Tailwind |
| 状态管理 | React `useState` / `useReducer` | 无 Redux/Zustand |
| 图表 | ECharts (已下线) / React Flow (已下线) | viz 功能下线后暂时未使用 |

---

## 3. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层 (Client)                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   首页/案件   │  │   庭审页面    │  │  证据/用量/   │          │
│  │   管理页面    │  │  /trial/[id] │  │   通知页面    │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
└─────────┼─────────────────┼─────────────────┼──────────────────┘
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │ REST + SSE (HTTP/1.1)
┌───────────────────────────┼─────────────────────────────────────┐
│                      FastAPI 后端                               │
│  ┌────────────────────────┼──────────────────────────────┐     │
│  │         Auth (JWT)     │     CORS (localhost:3000)    │     │
│  └────────────────────────┼──────────────────────────────┘     │
│                           │                                      │
│  ┌────────────────────────▼──────────────────────────────┐     │
│  │              API Endpoints (main.py)                   │     │
│  │  /case/*  /trial/*  /evidence/*  /usage/*  /auth/*    │     │
│  └────────────────────────┬──────────────────────────────┘     │
│                           │                                      │
│  ┌────────────────────────▼──────────────────────────────┐     │
│  │         LangGraph StateGraph (workflow.py)             │     │
│  │  Phase 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8                │     │
│  │  条件边: needs_confirmation → 用户确认后继续           │     │
│  └────────────────────────┬──────────────────────────────┘     │
│                           │                                      │
│  ┌────────────────────────▼──────────────────────────────┐     │
│  │              Agent V2 系统 (agents/v2/)                │     │
│  │  PlaintiffAgentV2 ──┐                                  │     │
│  │  DefendantAgentV2 ──┼── CommChannel ── CourtReporterV2 │     │
│  │  JudgeAgentV2 ──────┘                                  │     │
│  └────────────────────────┬──────────────────────────────┘     │
│                           │                                      │
│  ┌────────────────────────┼──────────────────────────────┐     │
│  │  RAG │ Evidence │ LLM │ Parser │ Insights │ Export   │     │
│  └────────────────────────┴──────────────────────────────┘     │
│                                                                 │
│  持久化: data/sessions.json (JSON, 唯一权威) + PostgreSQL (元数据索引) │
└─────────────────────────────────────────────────────────────────┘
```

### 关键设计决策

1. **JSON 唯一权威 + DB 元数据索引**: `TrialSession` 完整数据以 `data/sessions.json` 为唯一权威来源。PostgreSQL `cases` 表仅存储案件元数据（id/title/phase/role/mode/created_at）用于列表查询与用户隔离，**不存储阶段内容**（C4 整改后废弃了失效的 CasePhase 内容双写）。启动时 `_migrate_legacy_sessions()` 确保旧数据有 user_id。
2. **V1 / V2 Agent 并存**: V2 位于 `backend/agents/v2/` 独立目录，V1 代码不动。通过 `USE_AGENT_V2=true` 环境变量切换。当前所有生产流程已统一走 V2（`compat.py` 直接路由到 `workflow_v2.py`）。
3. **Phase 6 与 Phase 7 是真正多 Agent 交互阶段**: Phase 1-5 和 8 本质上是高级 Prompt Engineering（单 Agent 接收材料后一次性输出）。Phase 6 的交叉询问和举证质证中，Agent 之间通过 `CommChannel` 发送消息、读取 inbox，是真实的多 Agent 协作。Phase 7 为顺序交互：原告先生成最后陈述并通过 `CommChannel` 广播到所有 Agent 的 shared 层，被告读取后再生成自己的陈述，可针对性回应原告论点。
4. **SSE 流式粒度分层**: Phase 1-5/7-8 为整段推送+前端逐字动画（整段生成后一次性 `token` 事件推送完整内容，前端做字符级动画）；Phase 6 为 step 级流式（每轮对话一个 `agent_step` 事件），因为前端渲染离散气泡而非连续文本。
5. **Insight 预热缓存**（前端已下线）: 每阶段完成后，后台 `asyncio.create_task(_warm_insights(session))` 异步提取洞察并缓存。前端 `InsightCard` 已移除，后端服务保留供后续复用。

---

## 4. 后端架构详解

### 4.1 目录结构

```
backend/
├── main.py                  # FastAPI 入口，所有 REST + SSE 端点
├── config.py                # API 配置（DEEPSEEK_*、MAX_DEBATE_ROUNDS、TEMPERATURE）
├── llm.py                   # OpenAI-compatible LLM 封装（llm_call / llm_call_stream）
├── streaming.py             # SSE 流式队列（contextvars: stream_queue_ctx）
├── auth.py                  # JWT 签发/验证 + bcrypt 密码哈希
├── models/
│   ├── case.py              # CaseInput / TrialRecord dataclass
│   └── database.py          # SQLAlchemy ORM 模型 + 数据库连接
├── agents/
│   ├── base.py              # V1 BaseAgent（历史遗留）
│   ├── tools.py             # V1 工具（calculate_win_rate、extract_citations）
│   └── v2/                  # Agent V2 系统（核心，见 4.3）
├── orchestration/
│   ├── workflow.py          # V1 StateGraph + TrialState/TrialSession 定义
│   ├── workflow_v2.py       # V2 StateGraph（生产使用）
│   ├── prompts.py           # LLM Prompt 模板
│   └── analysis.py          # 案情分析辅助（CaseAnalysis、set_win_rate）
├── rag/                     # RAG 系统（见 4.4）
│   ├── config.py
│   ├── embeddings.py        # 本地 BAAI/bge-small-zh 加载
│   ├── indexer.py           # 文档切分 + 索引
│   ├── retriever.py         # 向量检索
│   ├── prompts.py           # RAG Prompt 模板
│   ├── integration.py       # 工作流集成
│   └── web_fetcher.py       # 网络法条抓取（预留）
├── evidence/                # 多模态证据系统（见 4.5）
│   ├── schemas.py
│   ├── persistence.py
│   ├── registry.py
│   ├── intake.py
│   ├── ai_enrichment.py
│   └── extractors/
│       ├── text_extractor.py
│       ├── image_extractor.py
│       ├── audio_extractor.py      # 预留
│       ├── contract_extractor.py   # 预留
│       └── batch_extractor.py      # 预留
└── services/
    ├── insights.py            # 洞察卡片提取 + 缓存（前端组件已下线，服务保留）
    ├── unified_extraction.py  # 统一提取（insight + structured，供后续复用）
    ├── visualization.py       # 可视化 Prompt（已下线，文件保留但不调用）
    ├── export_pdf.py          # PDF 导出
    ├── export_report.py       # Markdown 报告导出
    ├── parser.py              # 案件材料智能解析
    ├── opponent_generator.py  # 单方对抗模式 AI 生成对方材料
    └── web_search.py          # 网络搜索（预留）
```

### 4.2 庭审工作流（LangGraph StateGraph）

#### 状态定义 (`TrialState` TypedDict)

```python
class TrialState(TypedDict):
    case_input: CaseInput              # 案卷材料
    current_phase: int                 # 当前阶段 0-8
    user_role: str                     # "plaintiff" | "defendant" | "neutral"

    # 阶段产出（字符串或 JSON 字符串）
    phase1_analysis: str
    phase2_complaint: str
    phase2_evidence_catalog: str
    phase3_analysis: str
    phase4_answer: str
    phase4_evidence_catalog: str
    phase5_issues: str
    phase6_cross_exam: str          # JSON 数组
    phase6_evidence_exam: str       # JSON 数组
    phase7_plaintiff_final: str
    phase7_defendant_final: str
    phase8_judgment: str
    phase8_win_rate: float

    # 用户确认标志
    phase1_confirmed: bool
    ...  # phase2~phase7_confirmed

    # Agent V2 可序列化状态
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

    # 策略路线（单方对抗模式 Phase 1/3）
    phase1_strategy_routes: list[dict]
    phase1_selected_route: str
    phase3_strategy_routes: list[dict]
    phase3_selected_route: str
    phase1_strategy_pending: bool
    phase3_strategy_pending: bool

    error: str
```

#### 持久化层 (`TrialSession` dataclass)

与 `TrialState` 字段一一对应，额外包含：
- `case_id: str`
- `created_at: str`
- `user_id: int | None` — 用户隔离
- `insights_cache: dict` — 洞察缓存 `{phase: insights_dict}`（前端组件已下线，保留兼容）
- `mode: str` — `"neutral" | "asymmetric"`
- `user_side: str` — `"plaintiff" | "defendant" | ""`

**重要**: 新增/删除 `TrialSession` 字段时，必须同步修改：
1. `workflow.py` 中的 `TrialSession` dataclass 定义
2. `main.py` 中的 `_state_to_session()` 和 `_session_to_state()` 字段映射

#### Graph 拓扑

```
START
  │
  ▼
phase1_node ──→ should_pause_after_phase1 ──→ (用户确认) ──► phase2_node
  │                                               │
  ▼                                               ▼
(策略选择 pending) ◄──────────────────────────────┘
  │
  ▼
phase2_node ──→ should_pause_after_phase2 ──→ phase3_node
  │                                               │
  ▼                                               ▼
(策略选择 pending) ◄──────────────────────────────┘
  │
  ▼
phase3_node ──→ ... ──► phase4_node ──► phase5_node
                                              │
                                              ▼
phase6_node ──► cross_exam_router ──► cross_exam_round_node ──► cross_exam_router (loop, max 8 rounds, judge-evaluated early stop)
                                              │
                                              ▼ (rounds complete)
                                    evidence_exam_router ──► evidence_exam_batch_node ──► evidence_exam_router (loop, batch size 3)
                                              │
                                              ▼ (evidence complete)
                                    phase6_complete
                                              │
                                              ▼
                                    phase7_node ──► phase8_node ──► END
```

#### Phase 6 详细子流程

**交叉询问 (Cross Examination)**:
- 安全上限 8 轮，每轮 4 次 LLM 调用：原告提问 → 法官主持 → 被告回答 → 法官主持
- `cross_exam_router` 控制循环，三层终止机制：
  1. **法官全局评估**（每 2 轮一次）：法官审视最近问答记录，判断是否存在新的值得追问的要点，若无则建议结束
  2. **内容重复/空洞检测**：连续 2 轮问题重复或长度 < 20 字，提前结束
  3. **安全上限**：达到 8 轮强制结束
- 输出格式：`format_cross_exam_json()` 返回 JSON 数组，前端用 `ChatBubble` 渲染

**举证质证 (Evidence Examination)**:
- 证据列表去重后按批次处理（每批 3 项）
- 每项 4 次 LLM 调用：法官归纳焦点 → 原告举证说明 → 被告质证意见 → 法官裁定
- 被告质证深度由 Agent 自主决定（Prompt 引导：核心证据详细质证，形式证据简要处理），不再硬截断为 4 个问题
- 输出格式：`format_evidence_exam_json()` 返回 JSON 数组

**进度事件**: 两个阶段均 emit `phase_progress` SSE 事件，payload 示例：
```json
{"type": "phase_progress", "phase": 6, "step": "cross_exam", "current": 2, "total": 4, "message": "交叉询问 第2轮"}
```

### 4.3 Agent V2 架构（核心）

Agent V2 采用 **Actor-Memory-Skill** 模型，模拟真实法律团队的工作方式。

#### 4.3.1 `BaseAgentV2`

所有角色 Agent 的基类，位于 `backend/agents/v2/base.py`。

```python
class BaseAgentV2:
    def __init__(self, name, system_prompt, tools=[], temperature=0.3, max_tokens=4096, llm_config=None):
        self.name = name
        self.base_system_prompt = system_prompt
        self.memory = MemoryBank()                    # 三层记忆
        self.skills: list[Skill] = []                 # 已注册 Skill
        self.strategy_engine = LitigationStrategyEngine(llm_config)
        self.channel: CommChannel | None = None       # 外部注入
```

**核心方法**:

| 方法 | 说明 |
|------|------|
| `register_skill(skill)` | 注册 Skill，自动将其 `prompt_template` 追加到 `system_prompt`，将其 `tools` 加入 Agent 工具列表 |
| `think(task, context)` | 核心思考方法。自动组装 `memory.build_context()` + task，调用 LLM。若存在 SSE queue，走 `llm_call_stream()` 逐 token 推送 |
| `think_with_skill(skill_name, context)` | 调用指定 Skill 的 `execute()`。自动发送 `skill_start` / `skill_end` SSE 事件，含耗时统计 |
| `publish(content, content_type, phase)` | 将内容发布为 `public` 共享记忆，经 `CommChannel` 广播给所有 Agent + CourtReporter |
| `send_peer(recipient, content, content_type, phase)` | 发送 `peer` 可见消息（仅收发双方） |
| `send_private_to_judge(content, content_type, phase)` | 发送仅法官可见的消息 |
| `formulate_strategy(case_input)` | 调用 `LitigationStrategyEngine` 制定初始策略，存入 `memory.private.strategy` |
| `generate_strategy_routes(case_input)` | 生成 2-3 条策略路线供用户选择（单方对抗模式） |

**动态 System Prompt**: `BaseAgentV2.system_prompt` 是动态属性：
```python
@property
def system_prompt(self) -> str:
    parts = [self.base_system_prompt]
    for skill in self.skills:
        parts.append(skill.prompt_template)
    return "\n\n".join(parts)
```

#### 4.3.2 MemoryBank（三层记忆）

```python
@dataclass
class MemoryBank:
    private: PrivateMemory    # 仅本 Agent 可见
    shared: SharedMemory      # publish() 后对所有 Agent 可见
    inbox: list[AgentMessageV2]  # 接收外部定向消息
```

**PrivateMemory 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `history` | `list[dict]` | LLM 完整对话历史（保留最近 20 条，自动截断） |
| `strategy` | `LitigationStrategy \| None` | 当前诉讼策略 |
| `strategy_notes` | `str` | 策略笔记、内部推理链 |
| `legal_notes` | `str` | 法条检索笔记 |
| `fact_timeline` | `str` | 按时间脉络整理的事实大事记 |
| `key_arguments` | `list[str]` | 核心论点列表 |
| `evidence_opinions` | `dict[str, str]` | `{evidence_id: 质证意见}` |
| `weakness_analysis` | `str` | 对对方弱点的分析 |
| `sent_messages` | `list[AgentMessageV2]` | 已发送消息归档 |
| `consumed_messages` | `list[AgentMessageV2]` | 已消费消息归档 |

**SharedMemory**: 存储已发布的 `AgentMessageV2` 文档列表。提供查询方法：
- `get_by_phase(phase)` — 按阶段过滤
- `get_by_type(content_type)` — 按内容类型过滤
- `get_latest_by_phase(phase)` — 取该阶段最新一份

**核心操作**:
- `publish(msg)`: 将消息 `visibility` 设为 `public`，加入 `shared.documents` 和 `private.sent_messages`
- `receive(msg)`: 外部消息放入 `inbox`
- `consume_inbox(tag)`: 按 `content_type` 或 `msg_type` 过滤消费，移入 `private.consumed_messages`
- `build_context()`: 组装 LLM 上下文，优先级：`strategy_notes` → `fact_timeline` → `legal_notes` → `shared.documents[-5:]` → `inbox`

#### 4.3.3 Skill 系统

Skill 是可插拔的法律专业能力模块。所有 Skill 定义在 `backend/agents/v2/skill.py`。

**Skill 基类**:

```python
class Skill(ABC):
    name: str = ""
    description: str = ""
    tools: list[str] = []
    prompt_template: str = ""        # 注册后追加到 Agent system prompt

    @abstractmethod
    def can_handle(self, task_type: str) -> bool: ...

    @abstractmethod
    async def execute(self, agent: BaseAgentV2, context: dict) -> str: ...
```

**6 个内置 Skill**:

| Skill | 名称 | 对应真实工作流 | 注册角色 | `can_handle` 任务类型 |
|-------|------|---------------|---------|---------------------|
| `LegalResearchSkill` | 法律研究 | 法条检索与类案检索 | 原告/被告 | `legal_research`, `claim_analysis`, `defense_analysis` |
| `DraftingSkill` | 文书起草 | 起诉状/答辩状/证据目录/代理词 | 原告/被告 | `draft_complaint`, `draft_answer`, `draft_evidence_catalog`, `draft_statement` |
| `EvidenceAnalysisSkill` | 证据分析 | 证据三性分析与证明力评估 | 原告/被告 | `evidence_analysis`, `chain_review`, `cross_exam_prep` |
| `CrossExamSkill` | 交叉询问 | 封闭式提问设计与证人弹劾 | 原告/被告 | `generate_question`, `generate_answer`, `impeach_witness` |
| `ModerationSkill` | 庭审主持 | 争议焦点归纳与庭审主持 | 法官 | `summarize_issues`, `moderate_exam`, `ruling_on_evidence` |
| `AdjudicationSkill` | 裁判 | 判决撰写与胜率评估 | 法官 | `render_judgment`, `calculate_win_rate` |

**Skill 注册表**: `ALL_SKILLS: list[type[Skill]]` 包含上述 6 个类，用于状态恢复时根据名称重新实例化 Skill。

**Skill 执行时的 LLM 调用**: `Skill._call_llm()` 统一入口：
- 若 `stream_queue_ctx` 存在，走 `llm_call_stream()` 逐 token 推送 `{"type": "token", "agent": ..., "content": ...}`
- 否则走普通 `llm_call()`

#### 4.3.4 CommChannel（受控通信）

Agent 不直接互相调用，所有消息经 `CommChannel` 路由。位于 `backend/agents/v2/channel.py`。

**ACL 规则（硬编码）**:

```python
ACL_RULES = {
    "plaintiff": {
        "defendant": ["document", "evidence_opinion", "question"],
        "judge":     ["document", "evidence_opinion", "procedural_move"],
        "all":       ["document", "evidence_opinion"],
    },
    "defendant": { ... },  # 对称
    "judge": {
        "plaintiff": ["guidance", "ruling", "question"],
        "defendant": ["guidance", "ruling", "question"],
        "all":       ["guidance", "ruling"],
    },
}
```

**Visibility 层级**:

| 级别 | 路由行为 | 典型场景 |
|------|---------|---------|
| `public` | 进入**所有 Agent**的 `shared` 层 + `CourtReporter` 记录 | 起诉状、答辩状发布 |
| `peer` | 仅**接收方** `inbox` + 发送方 `private.sent_messages` | 交叉询问中的提问/回答 |
| `private_to_judge` | 仅**法官** `inbox` | 程序性动作申请 |

**消息协议 (`AgentMessageV2`)**:

```python
@dataclass
class AgentMessageV2:
    sender: str
    recipient: str              # "all" / "judge" / "plaintiff" / "defendant"
    msg_type: str
    content: str
    visibility: Literal["public", "peer", "private_to_judge"] = "public"
    content_type: Literal[
        "document", "evidence_opinion", "question", "answer",
        "guidance", "ruling", "strategy_note", "procedural_move"
    ] = "document"
    phase: int = 0
    evidence_ref: str = ""      # 举证质证时关联证据 ID
    round_num: int = 0
    timestamp: str
```

**CourtReporterV2**: 只记录 `public` 消息，内部用 `(sender, recipient, msg_type, content, phase, evidence_ref)` 指纹去重。提供 `get_by_phase()`, `get_cross_exam_log()` 查询。

#### 4.3.5 LitigationStrategyEngine

位于 `backend/agents/v2/strategy.py`。

```python
class LitigationStrategyEngine:
    async def formulate(case_input, role, system_prompt) -> LitigationStrategy
    async def adapt(current_strategy, new_event, judge_guidance, system_prompt) -> LitigationStrategy
    def decide_evidence_timing(strategy, current_phase, remaining_evidence, system_prompt) -> tuple[list[str], list[str]]
```

**证据时序策略**:
- `full_disclosure`: 举证期限内一次性提交全部证据（稳健型）
- `staged_release`: 分阶段提交，先交核心，再视反应补交（试探型）

**注意**: 旧版本曾有 `ambush` 策略，已于 2026-06-07 下线。`EvidenceTiming.from_dict()` 对旧数据中的 `ambush` 值做兼容降级为 `staged_release`。

**策略数据结构 (`LitigationStrategy`)**:

```python
@dataclass
class LitigationStrategy:
    procedural_moves: list[ProceduralMove]   # 管辖权异议、延期举证等
    core_theory: str                         # 核心诉讼/抗辩理论
    fallback_theories: list[str]             # 备选路径
    evidence_timing: EvidenceTiming          # 证据提交时序
    cross_exam_focus: list[str]              # 预判交叉询问重点
    weakness_map: dict[str, str]             # 对方弱点映射
    risk_assessment: str
    adapt_notes: list[str]                   # 动态调整历史
```

#### 4.3.6 角色 Agent

| Agent | 文件 | 注册 Skill | 核心方法 |
|-------|------|-----------|---------|
| `PlaintiffAgentV2` | `plaintiff.py` | LegalResearch, Drafting, EvidenceAnalysis, CrossExam | `analyze_claims`, `draft_complaint`, `draft_evidence_catalog`, `cross_exam_question`, `cross_exam_answer`, `comment_on_evidence`, `final_statement` |
| `DefendantAgentV2` | `defendant.py` | LegalResearch, Drafting, EvidenceAnalysis, CrossExam | `analyze_defense`（读取原告 shared Phase 2 文书）, `draft_answer`, `cross_examine_evidence`, `final_statement` |
| `JudgeAgentV2` | `judge.py` | Moderation, Adjudication | `summarize_issues`（读取双方文书）, `ruling_on_evidence`, `summarize_evidence_focus`, `moderate_cross_exam`, `render_judgment`（读取全部庭审材料） |

**信息依赖关系**: 被告 `analyze_defense()` 必须从 `memory.shared.get_by_phase(2)` 读取原告起诉状；法官 `summarize_issues()` 必须读取原告 Phase 2 + 被告 Phase 4 文书；法官 `render_judgment()` 读取 Phase 2/4/5/6/7 全部 `shared` 文档。

### 4.4 RAG 系统

位于 `backend/rag/`。

- **嵌入模型**: `BAAI/bge-small-zh-v1.5`（512 维，92MB）
- **加载方式**: `snapshot_download(..., local_files_only=True)` 绕过 HuggingFace 国内网络超时
- **模型缓存**: `~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5`
- **向量数据库**: ChromaDB，持久化 `data/chroma_db/`
- **知识库**: `data/legal_knowledge/civil/`，16 部民事法规（民法典 + 15 部司法解释）
- **已索引**: 552 个文本块

**工作流集成**: `workflow.py` 中 `_build_rag_context(case_title, facts, claims, phase)` 在 Phase 1/3/5/8 自动调用，将检索结果注入 Agent Prompt。Agent 的 `analyze_claims()`, `analyze_defense()`, `summarize_issues()`, `render_judgment()` 均接受 `legal_context: str = ""` 参数。

### 4.5 证据系统

位于 `backend/evidence/`。

**支持格式**: txt（自动编码检测）、docx、pdf（含扫描件检测）、jpg、png
**Phase 3 预留**: 音频（faster-whisper）、合同结构化解析、批量/ZIP 上传

**处理流程**:
1. **上传**: `POST /evidence/upload` (multipart)，文件存 `data/uploads/{case_id}/`
2. **提取**: `extractors/text_extractor.py` / `image_extractor.py`（Pillow 预处理 + pytesseract OCR）
3. **AI 增强**: `ai_enrichment.py` 调用 LLM 生成摘要、分类、提取日期/当事人/争议焦点/关联性
4. **冲突检测**: LLM 结构化提取各方主张后对比，5 种类型：`temporal`, `factual`, `quantitative`, `party`, `stance`。系统**不做真假判断**，仅呈现矛盾供律师审查
5. **持久化**: 元数据存入 PostgreSQL `evidence_items` 和 `conflict_reports` 表
6. **庭审集成**: `POST /evidence/{case_id}/import-to-trial` 将证据注册表转换为 `case_input.evidence` 格式并更新 `TrialSession`

**Windows 准备**: 需安装 Tesseract OCR + 中文语言包 (`chi_sim`)。

### 4.6 认证与授权

- **认证**: JWT + bcrypt，`backend/auth.py`。`get_current_user` 依赖强制要求 `Authorization: Bearer <token>`
- **授权**: `_require_session_access(case_id, current_user)` 验证 `session.user_id == current_user.id`。**安全设计**: 无权访问返回 **404**（而非 403），避免信息泄露
- **用户隔离**: 所有案件查询按 `user_id` 过滤
- **旧数据迁移**: `_migrate_legacy_sessions()` 启动时自动执行，将无 `user_id` 的案件关联到 admin (id=1)
- **CORS**: 只允许 `localhost:3000` 和 `127.0.0.1:3000`

### 4.7 持久化

**权威来源**: `data/sessions.json`（JSON 文件）— 案件全部阶段内容唯一权威。

**辅助存储**: PostgreSQL（`cases` 表仅存案件元数据索引，`evidence_items`, `conflict_reports`, `llm_usage_records`, `notifications`, `case_shares` 等表）

**分层策略**（2026-06-27 C4 整改后）:
- JSON (`sessions.json`) 存储案件完整状态（`TrialSession` 全量字段），是阶段内容、庭审文本、insight 数据的唯一权威源
- PostgreSQL `cases` 表仅同步案件元数据（id / title / phase / role / mode / created_at），用于 `/cases` 列表查询（支持搜索、过滤、分页）、用户隔离
- `case_session_to_db()` 在 `_save_sessions()` 时同步元数据到 PG `cases` 表；**不再写入 CasePhase 内容**（历史双写因字段映射错位永久失效，已删除）
- 证据文件独立存储在 `data/uploads/<case_id>/`，由 `evidence/persistence.py` 管理

**数据生命周期**:
- 创建/更新案件：`_save_sessions()` 写 JSON + 同步 Case 元数据行到 PG
- 删除案件：`delete_case()` 级联删 JSON session + PG Case（FK CASCADE 删 Phase/Analysis/Evidence/Share）+ 磁盘证据文件 + LLMUsageRecord
- 冷会话清理：仅 `phase>=8` 且创建超 30 天的已完结案件（上限 200 触发），进行中案件永远保留
- 查询列表：`/cases` 从 PG `cases` 表查询（分页/排序/搜索）
- 查询详情：从 `sessions` 全局 dict（启动时从 JSON 加载到内存）读取 `TrialSession`

### 4.8 LLM 层

位于 `backend/llm.py`。

- **默认模型**: DeepSeek（通过 `.env` 配置 `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`）
- **多厂商支持**: 每个案件可携带自己的 `llm_config`（`provider`, `base_url`, `api_key`, `model`, `temperature`）
- **接口**: `llm_call(system_prompt, messages, config, temperature, max_tokens)` 和 `llm_call_stream(...)`（AsyncGenerator，yield token）
- **用量追踪**: 每次调用通过 `contextvars` (`llm_meta_ctx`) 隐式传递 `user_id` / `case_id`，写入 `LLMUsageRecord` 表。流式调用使用字符数估算 token（中文 ±20% 误差）
- **配额检查**: 日限额默认 1M tokens，月限额默认 10M tokens，超配额抛出 `QuotaExceededError`

### 4.9 SSE 流式

位于 `backend/streaming.py`。

- **机制**: `contextvars.ContextVar("stream_queue")` 在 async call chain 中隐式传递队列
- **事件类型**:
  - `phase_start`: 阶段开始（含 `phase` 字段）
  - `agent_start`: Agent 开始工作（**不含** `phase` 字段，前端不得覆盖 `streamingPhase`）
  - `token`: 整段推送输出（Phase 1-5/7-8，内容为该阶段完整生成文本，前端做逐字动画）
  - `agent_step`: 消息级流式输出（Phase 6，含 `speaker`, `msg_type`, `content`, `round` 等）
  - `phase_progress`: 阶段内部进度（Phase 6 专用）
  - `skill_start` / `skill_end`: Skill 执行起止（含耗时 `duration_ms`）
  - `awaiting_strategy_selection`: 单方对抗模式暂停等待用户选择策略路线
  - `done`: 流式结束

### 4.10 Case Ontology（案件本体）

位于 `backend/ontology/`（2026-07-08 新增）。

**设计目标**：将案件从平铺文本抽象为 Palantir 式的「对象-关系」图，支撑决策中心工作台。

**核心对象**：
- `CaseObject`: 案件根对象
- `Party`: 当事人
- `Claim`: 诉讼请求/主张
- `Fact`: 事实节点
- `Evidence`: 证据（含三性评分）
- `LegalNorm`: 法条/司法解释
- `Precedent`: 判例
- `Issue`: 争议焦点
- `Decision`: 关键决策（需律师确认）
- `ActionItem`: 行动项/待办任务

**构建流程**：
1. `create_case` 时调用 `ontology_service.build_and_save_from_case_input()` 生成基础 Ontology
2. 庭审推进后调用 `/ontology/{case_id}/extract` 从 `TrialSession` 重新提取/更新
3. Agentic Skill 执行过程中可直接读写 Ontology

**持久化**：`data/ontologies/{case_id}.json`（内存缓存 + 原子写入），后续计划迁移 PostgreSQL。

### 4.11 Agentic 执行器

位于 `backend/agentic/`（2026-07-08 新增）。

**设计目标**：引入 Codex 式 Agentic 执行，同时通过 Proposal + 审批门实现 Human-in-the-Loop。

**核心组件**：
- `AgenticExecutor`: 接收自然语言任务，生成 Proposal 列表，调用 Skill 执行
- `Proposal`: 待审批的动作提案
- `AnalystAgent`: 通用分析 Agent，注册所有扩展 Skill

**扩展 Skill**（位于 `backend/agents/v2/extended_skills.py`）：
- `EvidenceChainSkill`：证据链缺口诊断
- `PleaBargainSkill`：调解/和解策略与报价区间
- `ExecutionRiskSkill`：执行风险评估与财产保全建议
- `JudgeQuestionSkill`：预测法官庭审追问

**执行流程**：
1. 用户通过 `/agent/{case_id}/run` 提交任务
2. `AgenticExecutor.plan()` 按规则生成 Proposal（状态 `pending`）
3. 用户通过 `/agent/{case_id}/proposals/{id}/approve` 审批
4. `AgenticExecutor.execute()` 调用对应 Skill
5. Skill 输出结构化 JSON 并写入 Ontology

---

## 5. 前端架构详解

### 5.1 目录结构

```
frontend-next/
├── src/app/                    # Next.js 16 App Router
│   ├── page.tsx               # 首页（案件列表 + 搜索 + 通知铃铛）
│   ├── case/new/page.tsx      # 新建案件（含模板选择、模式选择）
│   ├── trial/[caseId]/page.tsx # 庭审页面（核心，最复杂）
│   ├── evidence/[caseId]/page.tsx # 证据管理
│   ├── usage/page.tsx         # 用量看板
│   ├── login/page.tsx
│   ├── register/page.tsx
│   └── layout.tsx             # Root layout（全局 Providers）
├── src/components/
│   ├── InsightCard.tsx        # 阶段洞察卡片（支持 8 阶段 + fallback）
│   ├── PhaseContent.tsx       # 阶段内容展示（Markdown / 对象 / 数组）
│   ├── ChatBubble.tsx         # Phase 6 对话气泡
│   ├── StrategySelector.tsx   # 策略路线选择卡片
│   ├── EvidenceUploader.tsx   # 拖拽上传
│   ├── EvidenceList.tsx       # 证据列表
│   ├── ConflictPanel.tsx      # 冲突报告面板
│   └── NotificationBell.tsx   # 通知铃铛
├── src/lib/
│   ├── api.ts                 # API 客户端（fetch 封装）
│   ├── auth.ts                # JWT 本地存储 + 登录状态
│   └── types.ts               # TypeScript 类型定义
```

### 5.2 庭审页面 (`/trial/[caseId]`)

最复杂的前端页面，约 900+ 行。

**状态管理**（全部 `useState`，无全局状态库）:
- `phases: TrialPhase[]` — 8 个阶段的数据
- `currentPhase: number` — 当前进行到第几阶段
- `streamingPhase: number` — 正在流式输出的阶段
- `streamPhase6Msgs` / `streamEvidenceMsgs` — Phase 6 气泡消息数组
- `userRole` / `mode` / `userSide` — 用户角色和模式
- `awaitingStrategySelection` — 是否在等待策略选择
- `insightsVersion` — 洞察卡片刷新触发器（前端组件已下线，字段保留兼容）

**关键交互**:
- **启动庭审**: `POST /trial/start` → 返回 `TrialState` → 设置 `phases` → 若 `current_phase > 0` 自动调用 `connectTrialStream()`
- **继续庭审**: `POST /trial/continue` 或 `connectTrialStream(action="continue")`
- **确认阶段**: 点击"确认并继续" → `continueTrial(caseId, phase, editedContent)`
- **策略选择**: 收到 `awaiting_strategy_selection` 事件 → 展示 `StrategySelector` → 用户选择后 `selectStrategy(caseId, phase, routeId)` → 重新启动流式
- **编辑限制**: 单方对抗模式下，用户只能编辑己方内容（原告编辑 Phase 1/2，被告编辑 Phase 3/4）。生成中（`continuing || streamingPhase === p.phase`）时禁用编辑

**InsightCard（已下线）**: 原每个阶段（除 Phase 6 外）显示 `InsightCard`，组件 mount 时自动 `GET /trial/insights/{caseId}/{phase}`。2026-06-08 因 LLM 提取稳定性不足导致卡片空白率过高，已从庭审页移除；后端提取服务与 API 保留，供后续重做时复用。

### 5.3 组件规范

- **样式**: 纯 Tailwind CSS，无 shadcn/ui、无 Ant Design。颜色统一使用 Tailwind 的 `indigo-*`, `gray-*`, `green-*`, `red-*`, `orange-*`, `yellow-*`, `purple-*`, `blue-*`
- **图标**: 使用 Unicode emoji（如 📋、🔔、🔗），无图标库
- **响应式**: 核心页面已适配移动端（`sm:`, `lg:` 断点）
- **类型**: 所有 props 必须显式类型化，`any` 仅在 `renderGeneric` fallback 中允许

### 5.4 API 客户端 (`src/lib/api.ts`)

- **Base URL**: `NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000"`
- **认证头**: 所有请求通过 `getAuthHeaders()` 注入 `Authorization: Bearer <token>`
- **长超时**: `startTrial` / `continueTrial` / `analyzeEvidence` 使用 30 分钟超时（`LONG_TIMEOUT`）
- **401 处理**: `handleUnauthorized()` 遇到 401 自动调用 `logout()` 并跳转登录页
- **SSE 流式**: `connectTrialStream(data, onEvent)` 手动读取 ReadableStream，解析 `data: ` 前缀的 JSON 行

---

## 6. API 规范

### 6.1 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册（`email`, `password`） |
| POST | `/auth/login` | 登录（`email`, `password`）→ 返回 `access_token` |
| GET | `/auth/me` | 获取当前用户信息 |

### 6.2 案件管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/case/create` | 创建案件（含 `mode`, `user_side`, `user_strategy_hint`, `source_materials`） |
| POST | `/case/parse-text` | 智能解析文本 → 结构化 `CaseInput` + `raw_text` |
| POST | `/case/parse-file` | 智能解析文件（multipart） |
| GET | `/cases` | 案件列表（支持 `q`, `mode`, `phase`, `sort`, `page`, `page_size`） |
| DELETE | `/cases/{case_id}` | 删除案件 |
| PATCH | `/cases/{case_id}` | 重命名案件 |

### 6.3 庭审控制

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/trial/start` | 启动庭审（`case_id`, `user_role`） |
| POST | `/trial/continue` | 继续庭审（`case_id`, `confirmed_phase`, `edited_content`） |
| POST | `/trial/stream` | SSE 流式庭审（`case_id`, `action`, `user_role`, ...） |
| GET | `/trial/state/{case_id}` | 获取当前庭审状态 |
| GET | `/trial/content/{case_id}/{phase}` | 获取指定阶段内容 |
| POST | `/trial/select-strategy/{case_id}` | 选择策略路线（`phase`, `route_id`） |
| POST | `/trial/reset/{case_id}/{to_phase}` | 回退到指定阶段 |
| GET | `/trial/history/{case_id}` | 获取完整庭审历史 |
| GET | `/trial/export/{case_id}` | 导出 Markdown 报告 |
| POST | `/trial/judge-qa` | 向法官提问（`case_id`, `question`） |

### 6.4 洞察

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/trial/insights/{case_id}/{phase}` | 获取阶段洞察（优先读缓存，miss 时 LLM 提取） |

### 6.5 证据

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/evidence/upload` | 上传证据（multipart: `case_id`, `party`, `evidence_type`, `files[]`） |
| GET | `/evidence/{case_id}` | 获取证据注册表（items + timeline + conflicts） |
| POST | `/evidence/{case_id}/analyze` | AI 分析 + 冲突检测 |
| POST | `/evidence/{case_id}/import-to-trial` | 同步到庭审会话 |
| DELETE | `/evidence/{case_id}/{evidence_id}` | 删除证据 |

### 6.6 用量

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/usage/summary` | 日/月/累计用量汇总 |
| GET | `/usage` | 用量明细列表（支持 `page`, `page_size`） |

### 6.7 分享

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/cases/{case_id}/share` | 创建分享链接（只读） |
| GET | `/cases/{case_id}/shares` | 列出分享链接 |
| DELETE | `/cases/{case_id}/share/{share_id}` | 撤销分享 |
| GET | `/shared/{token}` | 免登录只读访问 |

### 6.8 通知

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/notifications` | 获取通知列表 + 未读数 |
| POST | `/notifications/{id}/read` | 标记已读 |
| POST | `/notifications/read-all` | 全部已读 |
| DELETE | `/notifications/{id}` | 删除通知 |

### 6.9 Ontology（案件本体）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology/{case_id}` | 获取完整案件本体 |
| POST | `/ontology/{case_id}/extract` | 从 TrialSession 重新提取/更新 Ontology |
| GET | `/ontology/{case_id}/dashboard` | 获取工作台 Dashboard 汇总 |
| GET | `/ontology/{case_id}/issues` | 争议焦点列表 |
| GET | `/ontology/{case_id}/evidence-chain` | 证据链数据 |
| GET | `/ontology/{case_id}/legal-basis` | 法条与判例 |
| GET / POST | `/ontology/{case_id}/decisions` / `/{decision_id}` | 决策列表 / 提交律师决策 |
| GET / POST | `/ontology/{case_id}/action-items` / `/{action_id}` | 行动清单 / 更新状态 |

### 6.10 Agentic 执行器

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agent/{case_id}/run` | 提交任务，生成 Proposal 列表（待审批） |
| GET | `/agent/{case_id}/proposals` | 提案列表 |
| POST | `/agent/{case_id}/proposals/{id}/approve` | 审批并执行提案 |
| POST | `/agent/{case_id}/proposals/{id}/reject` | 驳回提案 |
| POST | `/agent/{case_id}/analysis/evidence-chain` | 证据链缺口诊断 |
| POST | `/agent/{case_id}/analysis/plea-bargain` | 调解/和解策略与报价 |
| POST | `/agent/{case_id}/analysis/execution-risk` | 执行风险评估 |
| POST | `/agent/{case_id}/analysis/judge-questions` | 法官追问预测 |

---

## 7. 数据模型

### 7.1 `CaseInput`（案卷输入）

```python
@dataclass
class CaseInput:
    case_title: str
    facts: str
    evidence: str           # 每行一项
    claims: str
    plaintiff_position: str = ""
    mode: str = "neutral"   # "neutral" | "asymmetric"
    user_side: str = ""     # "plaintiff" | "defendant" | ""
    user_strategy_hint: str = ""
    opponent_materials: str = ""    # AI 生成的对方材料
    source_materials: str = ""      # 用户原始完整文本（双轨制）
    timeline_events: list = field(default_factory=list)
    party_relations: list = field(default_factory=list)
```

### 7.2 `TrialPhase`（前端阶段对象）

```typescript
interface TrialPhase {
  phase: number;
  label: string;
  content: string | object;
  needs_confirm?: boolean;
  strategy_routes?: StrategyRoute[];
  selected_route?: string;
}
```

### 7.3 `TrialState`（见 4.2）

### 7.4 `AgentMessageV2`（见 4.3.4）

### 7.5 `LitigationStrategy`（见 4.3.5）

### 7.6 数据库 ORM 模型（`backend/models/database.py`）

| 表 | 说明 |
|----|------|
| `users` | 用户（id, email, hashed_password, created_at） |
| `cases` | 案件（id, case_id, user_id, case_title, current_phase, mode, user_side, created_at） |
| `case_phases` | 案件阶段（已废弃倾向，session_data 优先） |
| `case_analysis` | 案件分析（已废弃倾向） |
| `evidence_items` | 证据元数据 |
| `conflict_reports` | 冲突报告 |
| `llm_usage_records` | LLM 用量记录 |
| `notifications` | 站内通知 |
| `case_shares` | 分享链接（token, permission, expires_at） |

---

## 8. 独立开发指南（模块化契约）

> 本节的目的是：让你只凭这份文档，就能在一个干净的环境中独立开发某个模块，然后将代码发回给我时，能无缝集成。

### 8.1 如何新增一个 Skill

**约束**:
1. Skill 必须继承 `backend.agents.v2.skill.Skill`
2. `name` 使用 snake_case，全局唯一
3. `prompt_template` 使用 `## 标题` 格式，注册后自动追加到 Agent system prompt
4. `execute()` 的 `context` 参数是 `dict`，由调用方传入。约定：`task_type` 用于 `can_handle()` 分发
5. LLM 调用必须通过 `self._call_llm(agent, task, ...)`，这样会自动处理流式/非流式

**接口契约**:
```python
# 文件: backend/agents/v2/skill.py（追加到 ALL_SKILLS）
class MyNewSkill(Skill):
    name = "my_new_skill"
    description = "..."
    tools = ["my_tool"]          # 若需新 tool，需在 backend/agents/tools.py 注册
    prompt_template = "## ..."   # 追加到 system prompt

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("my_task", ...)

    async def execute(self, agent, context: dict) -> str:
        task = f"""..."""
        return await self._call_llm(agent, task, temperature=0.3)
```

**集成步骤**:
1. 在 `skill.py` 中实现 Skill 类
2. 加入 `ALL_SKILLS` 列表
3. 在 `backend/agents/v2/__init__.py` 中导出
4. 在对应角色 Agent 的 `__init__` 中 `self.register_skill(MyNewSkill())`
5. 在 Agent 的业务方法中调用 `self.think_with_skill("my_new_skill", {...})`

### 8.2 如何新增一个 Agent 角色

**约束**:
1. 继承 `BaseAgentV2`
2. `name` 全局唯一，用于 ACL 和消息路由
3. `system_prompt` 必须包含"真实工作流"和"约束"两部分
4. 若需使用已有 Skill，在 `__init__` 中注册
5. 所有对外暴露的方法必须是 `async def`

**接口契约**:
```python
# 文件: backend/agents/v2/my_agent.py
from .base import BaseAgentV2
from .skill import LegalResearchSkill, ...

MY_AGENT_SYSTEM = """你是...\n## 你的工作\n...\n## 真实工作流\n1. ...\n## 约束\n- ..."""

class MyAgentV2(BaseAgentV2):
    def __init__(self, llm_config=None):
        super().__init__(name="my_agent", system_prompt=MY_AGENT_SYSTEM, ...)
        self.register_skill(LegalResearchSkill())

    async def my_task(self, case_input) -> str:
        return await self.think_with_skill("legal_research", {...})
```

**集成步骤**:
1. 创建 `my_agent.py`
2. 在 `__init__.py` 中导出 `MyAgentV2`
3. 在 `workflow_v2.py` 的 `_restore_agents_v2()` 中实例化并注册到 `CommChannel`
4. 在 `workflow_v2.py` 的对应 phase node 中调用该 Agent 的方法
5. 在 `TrialState` / `TrialSession` 中新增该 Agent 的状态字段（如 `my_agent_state: dict`）
6. 在 `_state_to_session()` / `_session_to_state()` 中增加映射
7. 在 `main.py` 的 `_build_phases_response()` 中决定该 Agent 的哪些内容返回给前端

### 8.3 如何新增一个庭审阶段

**约束**: 当前 8 阶段已覆盖完整民诉流程。若确有新增阶段需求（如"庭前调解"插入 Phase 0），需修改：

1. **状态定义** (`workflow.py`):
   - `TrialState` 新增 `phase0_mediation: str`, `phase0_confirmed: bool`
   - `TrialSession` 新增对应字段
   - `PHASE_LABELS` 新增 `0: "庭前调解"`

2. **Graph 拓扑** (`workflow_v2.py`):
   - 新增 `phase0_node` 函数
   - 在 `build_trial_graph_v2()` 中增加节点和边：`START → phase0_node → should_pause_after_phase0 → phase1_node`

3. **Agent 方法**: 在对应 Agent 中新增业务方法（如 `JudgeAgentV2.moderate_mediation()`）

4. **前端**:
   - `types.ts` 的 `TrialState` 和 `TrialPhase` 新增字段
   - `api.ts` 无需修改（通用 `/trial/content/{caseId}/{phase}`）
   - `trial/[caseId]/page.tsx` 的 `PHASE_LABELS`（前端本地）新增标签
   - 若 InsightCard 已重做并上线，新增对应 `renderPhase0` 渲染器（或复用 `renderGeneric`）

5. **持久化**: `main.py` 的 `_state_to_session` / `_session_to_state` / `_build_phases_response` 新增字段映射

### 8.4 如何新增一个前端页面

**约束**:
1. 使用 App Router，`page.tsx` 必须 `"use client"` 或 `"use server"` 显式声明
2. API 调用走 `src/lib/api.ts`，禁止裸 `fetch`
3. 样式使用 Tailwind，禁止内联 `style={{...}}`
4. 组件放在 `src/components/` 下，文件名使用 PascalCase

**接口契约**:
```typescript
// 若需新 API，先在 api.ts 中封装
export async function myNewApi(data: MyNewRequest) {
  const res = await fetch(`${API_BASE}/my/new/endpoint`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("...");
  return res.json();
}

// 类型定义在 types.ts
export interface MyNewRequest { ... }
```

### 8.5 模块边界与接口契约

**绝对禁止跨模块直接调用**:
- Skill 禁止直接调用 `llm_call()`，必须通过 `self._call_llm()`
- Agent 禁止直接调用其他 Agent 的方法，必须通过 `CommChannel`
- 前端禁止直接访问后端文件系统或数据库
- 后端服务层（`services/`）禁止直接操作 `sessions.json`，必须通过 `main.py` 中的 `_load_sessions()` / `_save_sessions()`

**允许的安全跨模块调用**:
- `workflow_v2.py` 可以调用 `agents.v2.*` 和 `services.*`
- `main.py` 可以调用 `orchestration.workflow_v2` 和 `services.*`
- `services/` 可以互相调用（如 `insights.py` 调用 `llm.py`）
- `rag/` 内部自由调用，外部通过 `retriever.retrieve_legal_knowledge()` 调用

**数据契约**:
- `CaseInput` 的字段变更是**全局变更**，需同步修改：`models/case.py` → `workflow.py` → `main.py` (CreateCaseRequest) → `frontend/lib/types.ts` → `frontend/app/case/new/page.tsx`
- `TrialState` 的字段变更需同步修改：`workflow.py` → `main.py` (_state_to_session / _session_to_state) → `workflow_v2.py` (若使用)
- `AgentMessageV2` 的字段变更是**破坏性变更**，需同步修改：`schema.py` → `channel.py` → `memory.py` → 所有 Agent 的 publish/send 调用 → `CourtReporterV2`

---

## 9. 配置与环境变量

### 后端 `.env`

```bash
# LLM（默认 DeepSeek）
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# 数据库
DATABASE_URL=postgresql://user:pass@localhost:5432/mootcourt

# Agent 切换（已固定为 true，保留兼容）
USE_AGENT_V2=true

# 可选: 其它厂商密钥（用于前端传入 llm_config 切换）
# KIMI_API_KEY=...
# GLM_API_KEY=...
```

### 前端环境变量

```bash
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000
```

### Windows 开发准备

1. 安装 Python 3.11+，使用 `py` 启动器（Git Bash 中 `python` 可能指向 Windows Store stub）
2. 安装 Tesseract OCR + `chi_sim` 中文语言包，确保 `tesseract` 在 PATH
3. `pip install -r backend/requirements.txt`
4. `cd frontend-next && npm install`
5. 首次启动前运行 `tools/test_rag.py` 验证 RAG 环境

---

## 10. 测试策略

| 测试文件 | 覆盖 | 状态 |
|----------|------|------|
| `tests/test_cases.py` | 案件 CRUD + 搜索 + 分页 | 8/8 通过 |
| `tests/test_auth.py` | 注册/登录/认证隔离 | 9/9 通过 |
| `tests/test_evidence.py` | 上传/分析/删除 | 7/7 通过 |
| `tests/test_v2_integration.py` | V2 Agent 集成（mock LLM） | 11/11 通过 |
| `tests/test_asymmetric.py` | 单方对抗模式端到端 | 10/10 通过 |
| `tests/test_ontology.py` | Case Ontology 提取与持久化 | 4/4 通过 |
| `tests/test_agentic.py` | Agentic Executor + 审批门 | 5/5 通过 |

**缺失测试**（技术债）:
- `test_trial.py`: 完整庭审流程端到端
- `test_rag.py`: RAG 检索质量回归
- `test_insights.py`: 洞察提取准确性
- `test_agentic_e2e.py`: Agentic 杀手场景真实 LLM 端到端

**运行测试**:
```bash
py -m pytest tests/ -v
```

---

## 11. 已知问题与技术债

> **最近修复（2026-06-08）**
> - Agent V2 状态持久化链路已补全：`TrialSession` 新增 `plaintiff_state` / `defendant_state` / `judge_state` / `reporter_state`，`_session_to_state` 与 `_state_to_session` 已完成双向映射。这根治了 Phase 6 消息重复输出和举证质证重复问题。
> - 导出报告 401 已修复（`FullReportExport.tsx` 已使用 `getAuthHeaders()`）。
> - `_save_sessions()` 已加 `threading.Lock()` + 原子写入（临时文件 + `os.replace()`）。
> - Phase 1 启动体验优化：移除全屏"正在生成..."等待页，点击开始后直接进入庭审控制台并预置 Phase 1 空文本框，`token` 事件流式填充内容，与其他阶段体验一致。
> - Phase 6 流式可视化优化：交叉询问与举证质证区域在生成开始时即渲染 `ChatBubble` 容器与动态提示（"进行中…"），`agent_step` 消息到达后逐条追加，避免仅有底部进度条的空洞等待感。
> - Phase 7 改造为真正多 Agent 顺序交互：原告 `final_statement` 先生成并通过 `CommChannel.dispatch(public)` 广播到所有 Agent 的 shared 层，被告读取原告陈述后再调用 `final_statement`，可针对性回应。替代了原 `asyncio.gather` 并行调用（伪多 Agent）。
> - Insight 卡片已下线：从 `trial/[caseId]/page.tsx` 移除 `InsightCard` 组件引用，消除 LLM JSON 格式偏差导致的空白卡片问题。后端 `/trial/insights/{case_id}/{phase}` 端点、`_warm_insights`、统一提取服务保留，供后续重做时复用。
> - Phase 6 动态终止与深度自适应（2026-06-08）：交叉询问从固定 4 轮改为议题覆盖驱动（上限 8 轮 + 法官全局评估每 2 轮判断一次是否还有新议题）；举证质证去掉被告质证意见硬截断（`_limit_evidence_questions` 移除），改为 Agent 自主决定详略（Prompt 引导核心证据详细质证、形式证据简要处理）。

### 🔴 高影响

（当前无高影响阻塞项）

### 🟡 中影响

| # | 问题 | 位置 | 状态 |
|---|------|------|------|
| 2 | **email 格式未校验** — `UserRegister.email: str` 应为 `EmailStr` | `main.py` | 一行修复 |
| 3 | **无操作审计日志** — 案件删除、分享创建无记录 | — | 需新增 `AuditLog` 表 |
| 4 | **庭审进度感知不足** — Phase 6 已增加 ChatBubble 容器优先渲染 + "进行中"动态提示，但 LLM 调用前仍缺乏步骤指示器，长期建议 Skill 层支持 `execute_stream()` 实现真正 token 级流式 | `trial/[caseId]/page.tsx` | 2026-06-08 已优化容器与消息追加体验 |

### 🟢 低影响

| # | 问题 | 说明 |
|---|------|------|
| 6 | Token 估算精度 | 流式调用字符估算，中文 ±20% 误差 |
| 7 | 搜索性能 | `/cases` `q` 搜索在 Python 层遍历，量大时需迁移到 DB 全文索引 |
| 8 | 测试覆盖 | 缺少 `test_trial.py`, `test_rag.py`, `test_insights.py` |
| 9 | 国际化 | 全站中文硬编码，无多语言框架 |
| 10 | 底层 token 级流式 | Phase 1-5/7-8 为整段推送+前端逐字动画，非底层 token 级 SSE。招聘演示场景可接受，长期建议改造 Skill 层支持 `execute_stream()` |

---

### 11.x 2026-06-26 全量代码审计（含整改方案）

> 本次审计覆盖后端全量（main.py / agents/v2 / orchestration / evidence / rag / services / auth / llm）与前端全量（trial 控制台 / api.ts / auth.ts / 组件库 / 可视化）。方法：逐文件精读 + grep 交叉验证调用关系 + 持久化往返核对。下表按严重度排序，括号为责任模块。完整证据见各文件行号。

#### 🔴 Critical（7 项 — 安全 / 数据丢失 / 核心质量阻断）

| ID | 类型 | 位置 | 一句话描述 | 验收 |
|---|---|---|---|---|
| C1 | 安全·路径穿越 | `evidence/persistence.py:52,65-81,268` | `save_uploaded_file`/`delete_file`/`read_file`/`delete_case_evidence_files` 均未对 `filename`/`storage_path`/`case_id` 做 `basename`+`realpath` 边界校验，`../` 或绝对路径可任意读写删服务器文件 | 上传 `../x`、`case_id=../x` 均被拒；realpath 必须在 UPLOAD_ROOT 内 |
| C2 | 安全·鉴权 | `auth.py:18` | `JWT_SECRET_KEY` 默认值 `"your-secret-key-change-in-production"`，部署未设环境变量时任何人可用默认密钥伪造任意 user_id 的合法 JWT（本地 .env 已设，但代码默认值不安全） | 启动时若未设 JWT_SECRET_KEY 则拒启动；密钥长度校验 |
| C3 | 数据丢失 | `main.py:147-159` | `_save_sessions` 当 `len(sessions)>100` 时自动删除最早会话；若全部未完结则删最早的（无差别），用户进行中的案件被静默永久删除 | 取消自动删除，或改为归档到冷存储 + 仅删已完结且超 N 天 |
| C4 | 架构·持久化失效 | `main.py:769-879` ↔ `orchestration/workflow.py` TrialSession | `case_db_to_session`/`case_session_to_db` 用 `phase{N}_content`/`phase{N}_insight`/`case{N}_viz`/`case_analysis` 字段，而 TrialSession 实际字段是 `phase{N}_analysis`/`case_analysis_data`/`insights_cache`。`getattr(session,"phase1_content")` 恒 None → **DB CasePhase 表永远写不进庭审内容**，双写完全失效。叠加 `sessions` 是进程内全局 dict（`main.py:197`），多 worker / 重启后非当前 worker 的 case 直接 404（DB 有元数据也取不回庭审内容） | 要么修字段映射并接入双写验证，要么明确废弃 DB 内容存储并从文档删除"双写"声称 |
| C5 | 质量·Insight 空白 | `services/unified_extraction.py:228`（模板 L30/L52 等 7 处） | `prompt_template.format(**format_kwargs)` 把模板内**字面 JSON 示例的花括号**（如 `{level:"high"...}`）当成 `.format` 占位符，找不到 `level` 键抛 `KeyError`，被 `main.py` 调用方静默吞掉 → 7 个 phase 的 insight 永远为空。**即 MEMORY「庭审质量问题·Insight 空白」的根因** | 模板字面花括号转义为 `{{`/`}}`，或改 `.replace("{content}",...)`；加 try 记录失败 |
| C6 | 质量·PDF 崩溃 | `services/export_pdf.py:791,910,913` | `_insight_para`/交叉询问 fallback 把 LLM 输出**未 HTML escape** 直接拼进 reportlab `Paragraph`，LLM 文本含 `<`/`>`/`&`（如「<合同>」「A&B」「《民法典》<577条>」）时 XML parse error → `doc.build` 崩溃 → 整个 PDF 导出失败 | 对 label/display_text/交叉询问 content 统一 `html.escape` 后入 Paragraph，或全走 `_markdown_to_flowables` |
| C7 | 安全·Zip Slip | `main.py:1757`、`evidence/extractors/batch_extractor.py:88` | `zf.extractall(temp_dir)` 不防御恶意 entry 名，恶意 zip 含 `../../../etc/x` 条目可越界写 | 解压前遍历 namelist 拒绝 `..`/绝对路径，或逐 entry realpath 校验 |

#### 🟠 High（11 项）

| ID | 类型 | 位置 | 一句话描述 |
|---|---|---|---|
| H1 | 安全 | `main.py:97` | CORS `allow_origins=["*"]` + 全 methods/headers，生产应白名单 |
| H2 | 安全 | `main.py:104`（`UserRegister.email:str`）| 已导入 `EmailStr` 却未用；邮箱不校验；注册无密码强度、无限流（`test_register_invalid_email` 因此失败）|
| H3 | 质量·乱码 | `services/parser.py:55` | `content.decode("utf-8",errors="replace")` 硬编码 UTF-8，国内 GBK/GB18030 txt → 大量 `�` 喂 LLM → 输出乱码。**即 MEMORY「乱码」根因** |
| H4 | 质量·检索污染 | `rag/embeddings.py:57-84`（链及 retriever:75/indexer:172）| `embed_text` 失败时 `except Exception` 静默返回**零向量** `[0.0]*dim`：indexer 把零向量入库污染整个 ChromaDB；retriever 用零向量查询返回错误法律条文 → 法条幻觉 |
| H5 | 架构·缓存失效 | `utils/cache.py` 整模块 | `@cache_result`/`cache_viz_data`/`invalidate_case_cache` 全项目零引用，缓存层完全没接入；每次请求重跑 LLM（成本/延迟翻倍），且与 C5 叠加重复触发失败路径 |
| H6 | 逻辑·重复注入 | `orchestration/workflow_v2.py:92-107` | `_restore_agents_v2` 每次都 `append` 对方材料到 `defendant.memory.private.history`，但 `load_state` 已恢复含上次注入的 history（对比 L114 source_materials 有 `already` 去重，对方材料无）→ 经 8 阶段注入 8+ 次，prompt 膨胀 |
| H7 | 并发·竞态 | `orchestration/workflow_v2.py:888`（+787/819）| 举证质证 `asyncio.gather(*[process_one...])` 并行多证据项，共享同一组 agent + CommChannel + state；协程交错 await 期间相互改写共享 memory/state，`process_one` 内 `_save_agents_v2` 并发写 → 逻辑错乱/状态错位 |
| H8 | 前端·静默失败 | `frontend lib/api.ts:128` 等 | `createCase`/`deleteCase`/`renameCase`/`getTrialState`/`askJudge`/证据系列等**多数函数不校验 `res.ok`**，错误响应被当成功；`createCase` 失败时 `res.case_id` 为 undefined → 跳 `/trial/undefined` |
| H9 | 前端·SSE 泄漏 | `frontend lib/api.ts:337` + `trial/[caseId]/page.tsx:167,338` | `connectTrialStream` 无 AbortController，卸载/中断不取消流；卸载后仍 setState；重试按钮无 disabled → 并发多路 SSE 相互覆盖 + 后端持续烧 token |
| H10 | 前端·404 | `frontend app/page.tsx:438` | 「可视化」按钮指向 `/viz/${case_id}`，该路由无 `page.tsx` → 404（已开始案件均可点）|
| H11 | 前端·正文污染 | `frontend trial/[caseId]/page.tsx:221,392` | token 事件 `prev + event.content`，content 缺失时拼入字面量 `"undefined"` 并写入 `phases[].content` 预览 |

#### 🟡 Medium（摘要，共约 20 项）

- 后端：`llm.py:319-330` 流式 finally 无条件记 `success=True` 且无重试（非流式有 3 次）；`main.py:447` `_warm_insights` `create_task` 未持有引用（可能被 GC 取消）；`main.py:1396` `delete_case` 不删 DB Case 行/证据文件/CaseShare；`main.py:1591-1601` SSE 内 `notif_db` 若 SessionLocal() 抛错则 finally `NameError`；`main.py:491` `_build_phases_response` phase2 不返回 evidence_catalog；`main.py:1515` judge-qa 用旧 V1 `JudgeAgent`；`evidence/extractors` fitz/PIL `open` 无 `with`/finally；`evidence/registry.py:33` 全局缓存无锁且不淘汰；`audio_extractor.py:108` 每次重载 WhisperModel；`rag/indexer.py:175` `collection.add` 同 id 抛异常（非幂等）；`export_pdf.py` 4 处 matplotlib `plt.close` 无 finally；`parser.py:30,47,34` 多处未 try/围栏剥离丢内容/上传文本无截断；`visualization.py:58` `update(extra_context)` 可覆盖已截断 content；`auth.py:141` `int(user_id)` 篡改非数字时 500 而非 401。
- 前端：`trial page:221` `setPhases` 嵌套进 `setStreamingContent` updater（副作用入 reducer，StrictMode 双调用）；`ModelConfigPanel:150` 「API Key 不上传服务器」文案不实（随 createCase 上行 + 明文存 localStorage）；`api.ts:356` SSE 末尾残留不处理/decoder 不 flush/`data:` 无空格变体丢弃；多数核心 API 不调 `handleUnauthorized`（401 不跳登录）；`trial page:68` `useSearchParams` 未包 Suspense；`trial page:335` `streamingPhase` 进 callback 依赖致闭包过期；`FullReportExport` setTimeout 卸载后 setState + fetch 无 abort；`AuthGuard:24` 重定向前已渲染 children + 登录页显示全局 header。

#### 🟢 Low（摘要，共约 12 项）

- 后端：`text_extractor.py:130` latin-1 兜底返乱码不报错；`rag/web_fetcher.py` 恒返 None + `import subprocess` 死导入；RAG 单例初始化无锁；`export_pdf.py:123` draw_node 递归无环检测；`ai_enrichment.py:231` 多 batch 同秒 conflict id 重复。
- 前端：`API_BASE` 4 处重复定义；大量死代码（InsightCard 514 行、整套 viz 组件、api 7 个孤儿函数、trial 页 `ReactMarkdown`/`insightsVersion`/`highlightedPhase` 全无消费方，`highlightedPhase` 恒 false 致阶段高亮永不触发）；file input 未重置 value；react-markdown 未显式 sanitize（依赖默认不渲染 HTML）；弹窗无 ESC/focus-trap、按钮无 aria-label、用原生 confirm/alert；`useSearchParams` role 首帧错位；`/health` 探测无 abort。

#### 整改方案（分 4 批，按优先级 + 工作量）

**P0 — 立即（安全 + 数据丢失阻断，0.5–1 天）✅ 已完成 2026-06-26**
- ✅ C1 路径穿越：`evidence/persistence.py` 全部文件操作加 `os.path.basename(filename)` + `os.path.realpath(dest).startswith(realpath(UPLOAD_ROOT))` 校验；`case_id` 加 hex 白名单；`delete_file`/`read_file`/`get_file_path` 走 `_safe_abs_under_root`；新增 `PathTraversalError`。实测：恶意 filename 净化落地不越界、storage_path 穿越全部拦截、case_id 白名单生效。
- ✅ C2 JWT：`auth.py` 移除可用默认密钥，新增 `_validate_jwt_secret()` 导入期 fail-fast 校验（非空、非占位默认、≥32 字符，不满足直接 RuntimeError）。
- ✅ C3 自动删除：`main.py:_save_sessions` 去掉无差别删除，改为仅清理 `current_phase>=8 且 created_at 超 30 天` 的冷会话且记审计日志，上限 200（进行中案件一律保留）。
- ✅ C7 Zip Slip：`main.py:_process_zip_upload` 与 `batch_extractor.py` 的 `extractall` 改为逐 entry `os.path.realpath` 校验，拒绝越界条目。
- ✅ H1/H2：CORS 改 `CORS_ALLOW_ORIGINS` 环境变量白名单（默认仅 localhost:3000）+ `allow_credentials=True`；`UserRegister.email`/`UserLogin.email: EmailStr`；注册 `password` 加 `field_validator`（≥6 位）。
- 验证：`py_compile` 4 文件通过；`test_auth.py` 9 passed（含原 failing 的 `test_register_invalid_email`）；regression collection 63 项正常、纯逻辑测试通过。⚠️ regression 的 async phase 测试在本机挂在真实 LLM/RAG/PG 调用（非本次引入）。

**P1 — 本周（核心质量链路，2–4 天）✅ 已完成 2026-06-27**
- ✅ C5 Insight：`unified_extraction.py` `.format(**format_kwargs)` 改为 `.replace("{content}",...).replace("{context}",...)` 安全绕过模板内字面 JSON 花括号；验证旧路径 KeyError: 'level' crash。→ 直接消灭「Insight 空白」。
- ✅ C6 PDF：`export_pdf.py` 所有 LLM 文本入 Paragraph 前 `html.escape`（`_insight_para` label/display_text、交叉询问 speaker/msg_type/content、fallback、summary_text）。→ 消灭「PDF 导出失败」。
- ✅ H3 乱码：`parser.py:55` `extract_text_from_txt` 改为 `_decode_bytes`：charset-normalizer 检测 → UTF-8 → GB18030 → GBK → Big5 → UTF-16 → UTF-8 replace 兜底；新增 `_has_text_signal` 判解码质量。→ 消灭「中文乱码」。
- ✅ H4 RAG：`embeddings.py` 新增 `EmbeddingError`，`embed_text`/`embed_texts` 失败/零向量改抛异常；`retriever.py` 捕获后返回空检索；`indexer.py` `build_index` 循环内 try-catch 跳过单文档故障。
- ✅ H6 对方材料去重：`workflow_v2.py` 注入前加 `already` 检查（`_OPP_MARKER` "庭前准备材料"），同 source_materials 写法。
- ✅ H8/H9/H11 前端：`api.ts` 新增 `assertOk`，全部 20+ 函数加 `res.ok` 校验 + `handleUnauthorized`；`connectTrialStream` 新增 `signal?: AbortSignal` + `handleUnauthorized` + `data:` 无空格兼容；trial 页面 `useRef(AbortController)` + 卸载 cleanup + AbortError 静默 + token `?? ""` + 开始/重试按钮 `disabled={continuing}`。
- 验证：`py_compile` 全后端文件通过；`test_auth.py` 9 passed；C5/C6/H3/H4 独立脚本验证通过；`npx tsc --noEmit` 通过。⚠️ regression async 挂在本机真实 LLM/RAG/PG（与 P0 同，非本次引入）。

**P2 — 两周（架构 + 并发 + 资源，3–5 天）✅ 已完成 2026-06-27**
- ✅ C4 持久化：选方案 B —— 明确「JSON 为唯一权威源，DB 仅存案件元数据索引」。删 `case_db_to_session`；`case_session_to_db` 仅同步 Case 元数据（删 CasePhase 内容循环 + CaseAnalysis 保存）；删 `_sync_all_sessions_to_db` 及 startup 调用；删 `CasePhase`/`DBAnalysis` import。
- ✅ H5 缓存：删除 `backend/utils/cache.py` 全模块（零引用 + Redis 未配置，避免误判「已有缓存」）。
- ✅ H7 并发：`evidence_exam_batch_node_v2` 的 `asyncio.gather` 改为 `for item in batch: await process_one()` 串行逐项，单条失败不阻断批次。
- ✅ 资源泄漏：`contract_extractor.py` fitz.open 加 try-finally close；`image_extractor.py` Image.open → with；`text_extractor.py` fitz.open 加 try-finally close；`export_pdf.py` 4× plt.savefig 加 try-finally plt.close。
- ✅ `delete_case` 级联删：DB Case（FK CASCADE 自动删 CasePhase/CaseAnalysis/EvidenceItem/CaseShare）+ LLMUsageRecord 手动清理 + `delete_case_evidence_files` 磁盘清理。
- ✅ `llm.py`：`llm_call_stream` create 阶段加重试（最多 3 次指数退避）；success 由异常标记不再无条件 True；`_log_usage` 包 try；全重试失败 raise last_error。
- ✅ `_warm_insights`：task 存入模块级 `_insight_tasks` set + `add_done_callback(discard)` 防 GC。
- 验证：`py_compile` 全后端文件通过；`test_auth.py` 9 passed。⚠️ regression async 挂在本机真实 LLM/RAG/PG（与 P0/P1 同，非本次引入）。

**P3 — 迭代（产品 + 技术债，持续）**
- 死代码清理：删/接 InsightCard、整套 viz 组件、`exportReport` JSON 端点、`startTrial`/`continueTrial` 旧同步函数；要么修 H10 补 `/viz/[caseId]` 页接入 viz 组件，要么删首页按钮。
- PM 增强（见下）。
- 测试补齐：当前仅 6 个 test 文件 + 3 个 regression，缺 `test_rag`/`test_main_api`（含鉴权隔离）/`test_evidence_service`/`test_export_pdf`；接入 CI。
- 文档同步（见下）。

#### 文档与产品视角发现

**文档与实现不一致（需同步）：**
- ROADMAP 称「可视化卡片 2026-06-07 已下线」，但前端 11 个 viz 组件 + 首页「可视化」按钮 + 后端 `services/visualization.py`/`viz_prompts.py`(440行)/`export_pdf.py` 4 个 matplotlib 渲染函数全部残留 —— **下线不彻底**，文档与代码状态脱节。
- TECH_SPEC §4.7 称「JSON + PostgreSQL 双写」，但 C4 证明双写失效；§11 称「当前无高影响阻塞项」，与本审计发现的 7 个 Critical 冲突。
- ROADMAP「Insight 已下线待重做」未点明根因是 C5 format bug，导致后续重做仍可能踩同坑。
- `_PHASE_FIELDS`（main.py:597）等 dead 映射应清理或标注。

**产品经理视角改进点（在 ROADMAP 既有 P0–P3 基础上的补充建议）：**
- **质量优先于铺功能**：已交付功能存在 Insight 空白 / PDF 崩溃 / 中文乱码 / SSE 卡死等用户可感知缺陷，建议在新增功能前先用 P0–P1 收口，否则演示风险高。
- **庭审进度感知**：Phase 6 有 agent_step 实时展示，但 Phase 1–5/7/8 LLM 调用前无占位，建议加「步骤指示器」（Skill 调用阶段名 + 骨架屏），降低 30s+ 等待焦虑。
- **导出报告专业化**：当前 Markdown 逐字稿 + P2 的 `_get_viz_by_type` 永远 None 导致 PDF 无图表；建议提取各阶段关键结论（争议焦点/证据采信/判决理由）并接入可视化图表，提升报告专业度。
- **案件模板库**：新建页加「从模板创建」（借款/劳动/交通事故/租赁），降低上手门槛（2–3h）。
- **What-if 回退落地**：后端 `snapshots` 已实现，但前端 `/trial/history` 仅展示快照列表，未支持「回退到某 Phase 编辑后重推 + 多分支对比」，建议补全（ROADMAP P1#4）。
- **实时通知**：当前页面加载轮询 `/notifications`，建议先做 SSE 推送（复用庭审流式基建），再考虑 WebSocket。
- **安全基线**：面向外部演示前，CORS / JWT / API Key 上行 / 注册限流必须收口（P0），避免演示中暴露用户密钥或被伪造身份。
- **数据迁移前置评估**：ROADMAP P2#8 计划 JSON→PG 迁移，但 C4 证明现有双写映射失效，迁移前必须先修映射或重构持久化层，否则迁移会基于错误前提。

---

## 12. 附录：完整文件树

```
moot-court/
├── .env
├── CLAUDE.md                    # ← 开发者指引（薄层，指向 TECH_SPEC）
├── TECH_SPEC.md                 # ← 本文档（唯一权威技术规范）
├── ROADMAP.md                   # ← 产品路线图（定期更新）
├── launcher.bat                 # Windows 一键启动脚本
├── data/
│   ├── sessions.json            # TrialSession 权威持久化
│   ├── chroma_db/               # ChromaDB 向量数据库
│   ├── uploads/                 # 证据文件存储
│   └── legal_knowledge/civil/   # RAG 知识库（16 部法规）
├── backend/
│   ├── main.py                  # FastAPI 入口（所有端点）
│   ├── config.py
│   ├── llm.py
│   ├── streaming.py
│   ├── auth.py
│   ├── models/
│   │   ├── case.py
│   │   └── database.py
│   ├── agents/
│   │   ├── base.py              # V1 BaseAgent（历史遗留）
│   │   ├── tools.py
│   │   └── v2/                  # Agent V2 系统
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── plaintiff.py
│   │       ├── defendant.py
│   │       ├── judge.py
│   │       ├── skill.py
│   │       ├── memory.py
│   │       ├── schema.py
│   │       ├── strategy.py
│   │       ├── channel.py
│   │       ├── compat.py
│   │       └── extended_skills.py  # 扩展 Skill（证据链/调解/执行风险/法官追问）
│   ├── orchestration/
│   │   ├── workflow.py          # V1/V2 共享状态定义 + V1 Graph
│   │   ├── workflow_v2.py       # V2 StateGraph（生产使用）
│   │   ├── prompts.py
│   │   └── analysis.py
│   ├── ontology/                 # Case Ontology（Palantir 式对象图）
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── extractor.py
│   │   └── service.py
│   ├── agentic/                  # Codex 式 Agentic 执行 + 审批门
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── service.py
│   │   └── executor.py
│   ├── routers/                  # FastAPI 路由拆分
│   │   ├── ontology.py
│   │   └── agentic.py
│   ├── rag/
│   │   ├── config.py
│   │   ├── embeddings.py
│   │   ├── indexer.py
│   │   ├── retriever.py
│   │   ├── prompts.py
│   │   ├── integration.py
│   │   └── web_fetcher.py
│   ├── evidence/
│   │   ├── __init__.py
│   │   ├── schemas.py
│   │   ├── persistence.py
│   │   ├── registry.py
│   │   ├── intake.py
│   │   ├── ai_enrichment.py
│   │   └── extractors/
│   │       ├── __init__.py
│   │       ├── text_extractor.py
│   │       ├── image_extractor.py
│   │       ├── audio_extractor.py
│   │       ├── contract_extractor.py
│   │       └── batch_extractor.py
│   └── services/
│       ├── insights.py
│       ├── unified_extraction.py
│       ├── visualization.py      # 已下线，保留文件但不调用
│       ├── export_pdf.py
│       ├── export_report.py
│       ├── parser.py
│       ├── opponent_generator.py
│       └── web_search.py
├── frontend-next/               # 唯一活跃前端
│   ├── package.json
│   ├── tsconfig.json
│   ├── .env.local
│   └── src/
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── page.tsx
│       │   ├── case/new/page.tsx
│       │   ├── trial/[caseId]/page.tsx
│       │   ├── workspace/[caseId]/page.tsx  # 决策工作台 Dashboard
│       │   ├── evidence/[caseId]/page.tsx
│       │   ├── usage/page.tsx
│       │   ├── login/page.tsx
│       │   └── register/page.tsx
│       ├── components/
│       │   ├── InsightCard.tsx
│       │   ├── PhaseContent.tsx
│       │   ├── ChatBubble.tsx
│       │   ├── StrategySelector.tsx
│       │   ├── EvidenceUploader.tsx
│       │   ├── EvidenceList.tsx
│       │   ├── ConflictPanel.tsx
│       │   ├── NotificationBell.tsx
│       │   └── agentic/
│       │       └── AgenticPanel.tsx  # 杀手场景 + 审批门
│       └── lib/
│           ├── api.ts
│           ├── auth.ts
│           └── types.ts
├── frontend/                    # DEAD Streamlit 前端（历史遗留，待清理）
├── tests/
│   ├── test_cases.py
│   ├── test_auth.py
│   ├── test_evidence.py
│   ├── test_v2_integration.py
│   ├── test_asymmetric.py
│   ├── test_ontology.py         # Ontology 提取与持久化
│   └── test_agentic.py          # Agentic Executor + 审批门
└── tools/
    └── test_rag.py
```

---

*本文档应随代码变更同步更新。任何架构级修改（新增 Agent、修改消息协议、修改 TrialState 字段）必须先更新本文档，再修改代码。*
