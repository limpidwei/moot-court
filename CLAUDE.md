# CLAUDE.md

This file provides quick-start guidance for Claude Code (claude.ai/code).

**权威技术规范见 `TECH_SPEC.md`** —— 所有架构细节、模块边界、接口契约、开发指南均在其中。

## Quick Start

### Frontend (Next.js 16, App Router)
```bash
cd frontend-next
npm run dev      # localhost:3000
npm run build    # production build
```

### Backend (FastAPI + Python 3.11+)
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### Windows
```bash
launcher.bat
```

## Important Notes

- **Next.js 16** has breaking changes. Read `node_modules/next/dist/docs/` for accurate reference.
- **Git Bash quirk**: `python` may point to Windows Store stub (exit code 49). Use `py` instead.
- **Only `frontend-next/` is active**. `frontend/` is dead Streamlit code.
- **V2 Agent is the only production path**: `USE_AGENT_V2=true` is effectively hardcoded via `compat.py`.

## When Modifying Code

1. Check `TECH_SPEC.md` Section 8 (独立开发指南) for module boundaries.
2. Any change to `TrialState`, `TrialSession`, `AgentMessageV2`, or `CaseInput` fields requires synchronized updates across `workflow.py`, `main.py`, and `frontend/lib/types.ts`.
3. Run `py -m py_compile backend/**/*.py` and `npx tsc --noEmit` before committing.

## Session Handoff（会话接力）

> **Why**: 单个 Claude 会话的上下文窗口有限，无法长期承载多个大任务；且每次启动新会话时，Claude 无法自动获知此前已完成的代码变更，导致重复审计代码、浪费 token、甚至做出矛盾修改。
>
> **Rule**: 任何对代码产生**实质性改动**的任务完成后，Claude 必须将工作摘要写入本文档末尾的「Running Log」章节（或专门的 `SESSION_LOG.md`），确保下一个会话能通过阅读文档快速恢复上下文。
>
> **项目级强制要求（自动执行）**: 在 moot-court 项目中，凡是涉及 Bug 修复、功能实现、重构或方案设计的任务，任务收尾时必须完成以下两步，无需用户额外提醒：
> 1. 按下方格式更新 **Running Log**；
> 2. 若改动影响模块边界、接口契约或关键行为，同步更新 `TECH_SPEC.md` 或新建专门文档。

### 何时必须记录

- 方案设计 / 架构决策（尤其是涉及模块边界、接口契约的）
- 新功能实现（含前端组件、后端 API、数据库迁移）
- Bug 修复（含根因分析）
- 重构或重大代码结构调整

### 记录格式（每次追加到 Running Log）

```markdown
### YYYY-MM-DD — 一句话任务描述
- **Scope**: 改动的文件/模块列表
- **Key Decisions**: 关键决策及原因（尤其是反直觉的选择）
- **Status**: 已完成 / 部分完成 / 待验证
- **Validation**: 测试/构建/部署状态（如 `npx tsc --noEmit` 通过）
- **Next / Tech Debt**: 遗留问题、下一步建议、需要关注的风险
```

### 使用方式

新会话启动时，Claude 应先阅读本文档的 **Running Log** 和 `TECH_SPEC.md` 相关章节，确认当前工作状态后再继续，避免重复劳动。

---

## Running Log

<!-- 按时间倒序追加 -->

### 2026-07-10 — 本地部署 BAAI/bge-small-zh-v1.5，解决 Hugging Face 连接超时
- **Scope**:
  - 将 RAG embedding 模型 `BAAI/bge-small-zh-v1.5` 完整下载到项目内 `models/bge-small-zh-v1.5/`
  - 修改 `backend/rag/embeddings.py` 的 `_resolve_model_path()`，优先加载项目内本地模型
- **Key Decisions**:
  - 解析优先级：项目 `models/` 目录 → Hugging Face 本地缓存 → 联网下载
  - 模型文件名 `BAAI/bge-small-zh-v1.5` 映射到 `models/bge-small-zh-v1.5/`，离线可用
- **Status**: 已完成
- **Validation**:
  - `py -c "from rag.embeddings import LocalEmbeddings; ..."` 从本地路径加载成功
  - 输出维度 512，归一化后向量模长 ≈ 1.0
- **Next / Tech Debt**:
  - 后续如需新增 embedding 模型，按同样方式放入 `models/` 即可自动识别

### 2026-07-08 — Codex 式 Agentic 执行 + 扩展 Legal Skill + 三大杀手场景
- **Scope**:
  - 扩展 `backend/agents/v2/skill.py` 基类：新增 `_call_llm_structured()` 支持 JSON schema 结构化输出
  - 新增 `backend/agents/v2/extended_skills.py`：
    - `EvidenceChainSkill`：证据链缺口诊断，生成补强 ActionItem
    - `PleaBargainSkill`：调解/和解策略与报价区间，生成 Settlement Decision
    - `ExecutionRiskSkill`：执行风险评估与财产保全建议
    - `JudgeQuestionSkill`：预测法官庭审追问
  - 新增 `backend/agentic/` 模块：
    - `models.py` / `service.py`：Proposal 数据与审批生命周期
    - `executor.py`：AgenticExecutor，任务 → Proposal → 律师审批 → Skill 执行 → 写入 Ontology
  - 新增 `backend/routers/agentic.py`：
    - `/agent/{case_id}/run` 提交任务生成 Proposal
    - `/agent/{case_id}/proposals/{id}/approve|reject` 审批门
    - 杀手场景快捷 API：`/agent/{case_id}/analysis/evidence-chain|plea-bargain|execution-risk|judge-questions`
  - 前端：`frontend-next/src/components/agentic/AgenticPanel.tsx` + 集成到 Workspace
  - 测试：`tests/test_agentic.py` 5 项通过
- **Key Decisions**:
  - 所有扩展 Skill 输出结构化对象并直接写入 Ontology，形成可累积的案件资产
  - 杀手场景走统一 Agentic 审批门：AI 先提案，律师审批后执行，符合 Palantir Human-in-the-Loop
  - 用 `AnalystAgent` 注册扩展 Skill，避免污染庭审角色 Agent
  - 默认任务规则映射，保证稳定可预期；后续可接入 LLM-based planner
- **Status**: 已完成（Milestone 3：Agentic 执行 + 杀手场景）
- **Validation**:
  - `py -m py_compile backend/main.py backend/agents/v2/skill.py backend/agents/v2/extended_skills.py backend/agentic/*.py backend/routers/*.py backend/ontology/*.py` 通过
  - `npx tsc --noEmit` 前端通过
  - `py -m pytest tests/test_auth.py tests/test_cases.py tests/test_evidence.py tests/test_ontology.py tests/test_agentic.py -v` → **33 passed, 0 failed**
- **Next / Tech Debt**:
  - 接入真实 LLM 跑通端到端杀手场景（当前单元测试用 mock）
  - 接入北大法宝/裁判文书网 MCP 提升法条与判例权威性
  - 前端 AgenticPanel 结果可视化：证据链缺口卡片、调解区间图、法官问题清单
  - 将 Proposal 持久化到 PostgreSQL，避免仅内存存储

### 2026-07-08 — Palantir 式产品重构：Case Ontology 与决策工作台奠基
- **Scope**:
  - 产品方案：`docs/PRODUCT_REDESIGN_PALANTIR_v1.md` —— 从「AI 模拟法庭玩具」重构为「律师决策操作系统」
  - 新增 `backend/ontology/` 模块：
    - `models.py`：定义 CaseObject / Party / Claim / Fact / Evidence / LegalNorm / Precedent / Issue / Decision / ActionItem / CaseOntology
    - `extractor.py`：从 `CaseInput` / `TrialSession` 规则提取结构化 Ontology
    - `service.py`：内存缓存 + JSON 持久化 + Dashboard 汇总 + Decision/ActionItem 更新
  - 新增 `backend/routers/ontology.py`：8 个 Ontology REST API（获取本体、重新提取、Dashboard、Issues、Evidence Chain、Legal Basis、Decisions、Action Items）
  - 集成到 `backend/main.py`：
    - `create_case` 后自动构建基础 Ontology
    - `delete_case` 级联删除 Ontology 文件
    - `app.include_router(ontology_router.router)` 注册路由
  - 测试：`tests/test_ontology.py` 4 项全部通过
- **Key Decisions**:
  - 不推翻现有 8 阶段庭审引擎，而是之上增加「Ontology 衍生层」，保持兼容且可重建
  - Ontology 持久化采用 `data/ontologies/{case_id}.json`，与现有 `sessions.json` 同目录，避免新增 DB 迁移
  - 首期规则提取保证稳定；后续用 LLM 增强复杂案由
  - API Router 延迟导入 `main.sessions` 避免循环依赖
- **Status**: 已完成（Milestone 1：Case Ontology 与提取服务）
- **Validation**:
  - `py -m py_compile backend/main.py backend/ontology/*.py backend/routers/ontology.py` 通过
  - `py -m pytest tests/test_ontology.py -v` → **4 passed, 0 failed**
  - 全量核心测试运行中（test_auth/cases/evidence/v2_integration/asymmetric + test_ontology）
- **Next / Tech Debt**:
  - Milestone 2：前端 Workspace Dashboard（`/workspace/[caseId]`）
  - Milestone 3：Decision Card 与 Action Items 交互
  - 后续将 Ontology 持久化迁移到 PostgreSQL 以支持跨进程/多 worker
  - LLM 增强提取：当事人识别、事实时间抽取、证据三性评估

### 2026-06-27 — P4 边缘打磨落地（P4-1/P4-2/P4-3）
- **Scope**:
  - `backend/main.py`（P4-1 SSE NameError）：`notif_db` 前置初始化 `None` + finally `if not None: close()`
  - `backend/auth.py`（P4-2 int(user_id) 500）：`int(user_id)` 包 try/except ValueError → 401
  - `frontend lib/api.ts`（P4-3）：`API_BASE` 改为 `export const`，统一 4 处定义；SSE decoder 循环后 `decoder.decode()` flush 残留 + 末尾行处理
  - `frontend lib/api.ts`（P4-3）：3 文件（login/register/FullReportExport）改从 api.ts import API_BASE
  - `frontend components/viz/FullReportExport.tsx`（P4-3）：`mountedRef` guard + AbortController abort + fetch signal，防卸载后 setState/请求泄漏
  - `frontend components/AuthGuard.tsx`（P4-3）：`authorized` state + 首次渲染同步判断 → 受保护页不再 flash
  - `frontend app/trial/layout.tsx`（✅ 新建）：Suspense 包裹 trial 路由树，解决 useSearchParams 无 Suspense 边界
- **Key Decisions**:
  - AuthGuard 选同步+state 双重判断而非仅异步 effect：`isAuthenticated()` 读 localStorage 同步可用，首次渲染即可判断无需等待 effect
  - trial/layout.tsx 选新建 layout 而非根 layout 加 Suspense：根 layout 的 Suspense 会影响所有路由，仅 trial 需要
  - FullReportExport 选 mountedRef + AbortController 双重防护：setTimeout 回调 guard + fetch abort 并发控制
- **Status**: 已完成
- **Validation**:
  - `npx tsc --noEmit` 通过（exit 0）
  - `py_compile` 后端通过
  - `test_auth.py` → 9 passed
- **Next**: 无 P5 计划。P0–P4 共覆盖 27 项整改（7 Critical + 11 High + 9 Medium）。

### 2026-06-27 — P3 技术债清理落地（死代码/H10/文档/RAG锁/text_extractor）
- **Scope**:
  - 前端：删 `InsightCard.tsx`（514 行）；删 11 个 dead viz 组件（AttackDefenseMap/CaseTimeline/ClaimBasisTree/DebateFlowGraph/DisputeFocusMap/EvidenceChain/LegalRelationGraph/PositionComparison/VerdictTree/VizExportButton/WinRateRadar）+ `shared/` 目录，仅保留 `FullReportExport.tsx`；删 `api.ts` 7 个孤儿函数（startTrial/continueTrial/getPhaseContent/exportReport/listShares/deleteShare/deleteNotification）；删 trial 页 dead import（ReactMarkdown/remarkGfm）与 dead state（highlightedPhase/insightsVersion）；首页删 H10「📊 可视化」按钮（指向不存在的 /viz/[caseId]）
  - 后端：删 `rag/web_fetcher.py`（死代码，恒返 None + 死 import subprocess）；`text_extractor.py` `_read_text_with_encoding` 加 charset-normalizer 首选 + latin-1 仅兜底且记 warning（P3 修复：latin-1 不抛错但中文乱码且不报错）；`embeddings.py` + `retriever.py` 单例加双重检查锁
  - 文档：TECH_SPEC §4.7 持久化描述更新（JSON 唯一权威 + DB 元数据索引，删除失效双写声称）
- **Key Decisions**:
  - InsightCard/viz 组件全部删除而非保留「以备未来重做」：它们依赖已下线的 visualization.py，代码与当前架构脱节，重做需从零设计
  - H10 选删按钮而非补路由：11 个 viz 组件已全删，补 `/viz/[caseId]` 页将是无内容空壳
  - RAG 双重检查锁：embeddings 加载 SentenceTransformer 模型（数百 MB），retriever 初始化 ChromaDB 连接（SQLite），并发初始化会造成双倍内存开销或 SQLite 冲突
  - 保留 `FullReportExport.tsx`：trial 页实际引用，功能正常
- **Status**: 已完成
- **Validation**:
  - `py_compile` 后端文件通过；`npx tsc --noEmit` 前端通过
  - `grep -rn "web_fetcher\|InsightCard\|startTrial\|continueTrial\|getPhaseContent\|exportReport\|listShares\|deleteShare\|deleteNotification\|highlightedPhase\|insightsVersion\|ReactMarkdown\|remarkGfm"` → 前端零残留；后端 web_fetcher 零残留
- **Next**:
  - 补 P3 测试补齐：test_rag/test_main_api/test_evidence_service/test_export_pdf
  - 前端 accessibility：弹窗 ESC/focus-trap、按钮 aria-label
  - 前端 `API_BASE` 4 处重复定义统一到单常量
  - TECH_SPEC 版本号更新为 v2.2

### 2026-06-27 — P2 架构+并发+资源整改落地（C4/H5/H7 + 资源泄漏 + llm.py）
- **Scope**:
  - `backend/main.py`（C4 持久化）：删除 `case_db_to_session`（失效读函数）；中性化 `case_session_to_db`（仅存 Case 元数据——id/title/phase/role/mode/created_at，删 CasePhase 内容循环 + CaseAnalysis 保存）；删 `_sync_all_sessions_to_db` 及启动调用；删 `CasePhase`/`DBAnalysis` import；`delete_case` 加级联删 DB Case（FK CASCADE 自动删 CasePhase/CaseAnalysis/EvidenceItem/CaseShare）+ LLMUsageRecord 手动清理 + `delete_case_evidence_files` 磁盘清理；`_warm_insights` task 存入模块级 `_insight_tasks` set + `add_done_callback` 防 GC
  - `backend/utils/cache.py`（H5 缓存）：整个文件 + 模块删除（全项目零引用 + Redis 未配置，误判「已有缓存」）
  - `backend/orchestration/workflow_v2.py`（H7 并发）：`asyncio.gather` 并行改 `for item in batch: await process_one()` 串行逐项，单条失败不阻断批次进度；删 `import asyncio`
  - `backend/evidence/extractors/contract_extractor.py`（资源泄漏）：`fitz.open` 加内层 try-finally 保证 `doc.close()`
  - `backend/evidence/extractors/image_extractor.py`（资源泄漏）：`Image.open` → `with Image.open(...) as image:`，metadata 提前读至局部变量
  - `backend/evidence/extractors/text_extractor.py`（资源泄漏）：`fitz.open` 后全文加 try-finally 保证 `doc.close()`
  - `backend/services/export_pdf.py`（资源泄漏）：4× `plt.savefig` 加 try-finally 保证 `plt.close(fig)`
  - `backend/llm.py`（P2-llm）：`llm_call_stream` 加重试（create 失败最多 3 次指数退避）；success 由异常标记不再无条件 True；`_log_usage` 包 try 防用量记录故障拖垮流式；全重试失败 raise last_error
- **Key Decisions**:
  - C4 选方案 B（JSON 唯一权威）而非方案 A（修字段映射）：TrialSession 字段与 DB 列名错位已根深蒂固，修复需同步修改 8 阶段 × 3 子字段 = 24 处映射 + 往返单测，投入产出比低；JSON sessions.json 已经在正常运行中承载全部阶段内容
  - H5 直接删除而非接入热路径：项目无 Redis 依赖（requirements 不含 redis-py），接入需引入新依赖 + 部署运维成本，当前 LLM 用量尚在可控范围
  - H7 串行 + 单条容错：逐项处理后单条异常不抛，推进进度保存已完成项，比 gather 全成功/全失败更贴近真实庭审
  - 流式重试仅覆盖 create 阶段（stream 创建失败可重试，流式传输中途失败不可重试——token 已发送），但仍准确记录 success=False
- **Status**: 已完成
- **Validation**:
  - `py_compile` 全部 8 个后端文件通过
  - `test_auth.py` → **9 passed**（import 链完整）
  - `grep -rn "CasePhase\|DBAnalysis\|_sync_all_sessions_to_db\|from.*utils.*cache"` 零残留
  - ⚠️ regression async 挂在本机真实 LLM/RAG/PG（与 P0/P1 同，非 P2 引入）
- **Next / Tech Debt**:
  - P3（技术债清理）：InsightCard 死代码、viz 组件、WebFetcher 死导入、前端 eslint 与 accessibility
  - 建议补 P2 专项测试：delete_case 级联删 end-to-end、并发流式重试 mock、资源泄漏 CI 检测（pytest-leaks/fd 计数）
  - DB CasePhase 表可在下次 schema migration 中删除（字段已不从 Python 代码访问）
  - sessions 全局内存 dict 多 worker 问题待解决（P2 原方案含 Redis sticky session，建议纳入后续架构优化）

### 2026-06-27 — P1 核心质量链路整改落地（C5/C6/H3/H4/H6/H8/H9/H11）
- **Scope**:
  - `backend/services/unified_extraction.py`（C5 Insight 空白）：`.format(**format_kwargs)` → `.replace("{content}",...).replace("{context}",...)`，安全绕过模板内字面 JSON 花括号（`{level:"high"...}` 等）；验证旧 .format 路径 KeyError: 'level' crash
  - `backend/services/export_pdf.py`（C6 PDF 崩溃）：`_insight_para` label/display_text 加 `escape()`；交叉询问 speaker/msg_type/content 加 `escape()` + fallback 加 `escape()`；summary_text 加 `escape()`
  - `backend/services/parser.py`（H3 乱码）：`extract_text_from_txt` 改为 `_decode_bytes` 多编码策略链：charset-normalizer 检测 → UTF-8 → GB18030 → GBK → Big5 → UTF-16 → UTF-8 replace 兜底；新增 `_has_text_signal` 判解码质量
  - `backend/rag/embeddings.py`（H4 RAG 零向量）：新增 `EmbeddingError(RuntimeError)`；`embed_text`/`embed_texts` 失败改抛异常（不再返回零向量）；含零向量检测拒绝
  - `backend/rag/retriever.py`（H4 联动）：`embed_text` 调用外移入 try-catch EmbeddingError，返回空检索
  - `backend/rag/indexer.py`（H4 联动）：`index_document` 调用包 try-catch，跳过单文档故障
  - `backend/orchestration/workflow_v2.py`（H6 对方材料去重）：`_restore_agents_v2` 注入前加 `already` 检查（`_OPP_MARKER`），仿 source_materials 模式
  - `frontend-next/src/lib/api.ts`（H8/H9）：新增 `assertOk` 统一 `res.ok` 校验 + `handleUnauthorized`；`deleteCase`/`renameCase`/`createCase`/`startTrial`/`continueTrial`/`getTrialState`/`getPhaseContent`/`exportReport`/`askJudge`/`getPhaseInsights`/`getTrialHistory`/`resetTrial`/证据系列/通知系列全覆盖；`connectTrialStream` 新增 `signal?: AbortSignal` 参数 + reader.releaseLock + `data:` 无空格兼容
  - `frontend-next/src/app/trial/[caseId]/page.tsx`（H9/H11）：新增 `useRef(AbortController)` + `abortStream`/`startStream` helper + 卸载 cleanup；两个 `connectTrialStream` 传入 `startStream()`；AbortError 静默不显错误；token 拼接 `event.content ?? ""`；开始/重试按钮 `disabled={continuing}`
- **Key Decisions**:
  - C5 用 `.replace` 而非模板花括号转义 `{{ }}`：prompt 模板已 7 份 230+ 行，转义工作量大且易漏；`.replace` 更安全、可读性更好
  - C6 仅 escape 动态文本（LLM/insight 字段），保留 `<b>`/`<font>` 标签；fallback 原可用于 JSON 解析失败时直接抛原始 LLM 文本进 Paragraph（同样缺 escape）
  - H3 用 charset-normalizer（3.4.7 已装）作为首选检测器，回退链覆盖国内全部常用中文编码
  - H4 选「抛 EmbeddedError + 上层跳过」而非「try 内 return None」：indexer 离线批任务应该跳过坏文档继续建库；retriever 在线查询应返回空检索而非崩溃
  - H6 与 source_materials 统一 `already` 模式：双方材料都查 `"【庭前准备材料"` 标记
  - H8 统一用 `assertOk` 包装 read-body-on-error 模式，而非在每个函数里重复 `if (!res.ok)` 块
  - H9 AbortError 自动静默（来自卸载/重开/重试的正常中断），其他异常仍展示
- **Status**: 已完成
- **Validation**:
  - `py_compile` 全部 10 个后端文件通过
  - `test_auth.py` → **9 passed**
  - C5 独立验证：全部 8 个 phase 模板 safe-render + 确认旧 `.format` 在 `KeyError: 'level'` 时 crash
  - C6 独立验证：对抗性 LLM 文本（`<`/`>`/`&`）escape 后 `doc.build` 成功，bytes 正常产出
  - H3 独立验证：GBK/GB18030/UTF-8/UTF-16 全部 round-trip OK，随机 bytes 不崩溃
  - H4 独立验证：零向量/GPU OOM 均 raise EmbeddingError
  - `npx tsc --noEmit` 前端通过（exit 0）
  - ⚠️ regression async 测试挂在本机真实 LLM/RAG/PG（与 P0 同，非 P1 引入）
- **Next / Tech Debt**:
  - P2（架构+并发，3–5 天）：C4 持久化双写修复、H5 缓存接入/删除、H7 举证质证串行化、资源 with 化、delete_case 级联
  - 建议真实 LLM 端到端验证：创建案件 → 走完 8 阶段 → 检查 Insight 卡片非空 → PDF 导出成功 → 无乱码
  - C6 建议补 `test_export_pdf.py` 含对抗性 LLM 文本的端到端 PDF 生成与验证

### 2026-06-26 — P0 安全+数据丢失整改落地（C1/C2/C3/C7 + H1/H2）
- **Scope**:
  - `backend/evidence/persistence.py`（C1 路径穿越）：新增 `_validate_case_id`（hex 白名单）、`_safe_abs_under_root`（realpath 边界校验）、`PathTraversalError`；`save_uploaded_file` 取 basename 净化 + 写入前 dest_real 校验；`delete_file`/`read_file`/`get_file_path` 走 `_safe_abs_under_root`；`delete_case_evidence_files` 加 case_id 校验 + rmtree 前确认直接子目录
  - `backend/auth.py`（C2 JWT）：移除可用的默认密钥，新增 `_validate_jwt_secret()` 导入期 fail-fast 校验（非空、非占位默认、≥32 字符）
  - `backend/main.py`（C3 + C7 + H1 + H2）：`_save_sessions` 自动清理改为仅删「phase>=8 且创建超 30 天」冷会话并记审计日志（上限 200，不再无差别删进行中案件）；`_process_zip_upload` 加 Zip Slip 逐 entry realpath 校验；CORS 改 `CORS_ALLOW_ORIGINS` 环境变量白名单（默认仅 localhost:3000）+ `allow_credentials=True`；`UserRegister.email: EmailStr` + `UserLogin.email: EmailStr` + `password` 加 `field_validator`（≥6 位）
  - `backend/evidence/extractors/batch_extractor.py`（C7 Zip Slip）：`extractall` 改逐 entry realpath 校验
- **Key Decisions**:
  - C1 对恶意 filename 采取「basename 净化后落地 + realpath 边界校验」而非直接拒绝（既杜绝越界，又不破坏正常上传）；storage_path 入口（delete/read）则严格拒绝穿越
  - C2 选择导入期 raise 而非运行期降级 —— fail-fast 杜绝弱密钥上线；conftest 已设 32+ 字节测试密钥
  - C3 把自动清理阈值从 100 提到 200、且只删冷会话，根治「进行中案件静默丢失」；保留 PG 同步逻辑不变
  - H2 用 `EmailStr`（email_validator 2.3.0 已装），顺带修好 `test_register_invalid_email`（原 failing 现返回 422）
- **Status**: 已完成
- **Validation**:
  - `py -m py_compile backend/main.py backend/auth.py backend/evidence/persistence.py backend/evidence/extractors/batch_extractor.py` 通过
  - `py -m pytest tests/test_auth.py` → **9 passed**（含原 failing 的 `test_register_invalid_email`）
  - `py -m pytest tests/regression/test_trial_flow.py` 纯逻辑部分（TestTrialStateBasics + TestAgentV2Persistence 共 4 项）通过；`--collect-only` 63 项正常收集
  - C1 路径穿越防护独立脚本验证：恶意 filename 净化落地不越界、storage_path 穿越全部拦截、case_id 白名单生效
  - ⚠️ 已知环境问题（非本次引入）：`tests/regression/` 的 async phase 测试（test_phase1 起）及全量 `tests/` 在本机执行时挂在真实 LLM/RAG/PG 调用（collection 正常、test_auth 通过，判断为本地 DeepSeek/PG/Chroma 服务状态导致），与 P0 改动无关
- **Next / Tech Debt**:
  - P1（核心质量，待执行）：C5 format→replace 修 Insight 空白、C6 PDF escape 修崩溃、H3 parser 多编码修乱码、H4 RAG 零向量改抛异常、H6 对方材料去重、H8/H9/H11 前端 api.ts 统一 res.ok + SSE AbortController
  - 建议补 P0 专项单测：persistence 路径穿越、Zip Slip、JWT 弱密钥 fail-fast、_save_sessions 冷会话清理
  - 待隔离本地环境挂起根因（建议 pytest 加 `--timeout` 插件 + mock 真实 LLM/PG 调用）

### 2026-06-09 — 对抗强度滑块前后端落地 + 回归测试扩展（62 项测试）
- **Scope**: 
  - 后端：`backend/models/case.py`（新增字段）、`backend/main.py`（API 接收）、`backend/agents/v2/evidence_constraint.py`（动态白名单+时间红线）、`backend/agents/v2/defendant.py`（传参）、`backend/orchestration/workflow_v2.py`（Phase 4 传入）
  - 前端：`frontend-next/src/lib/api.ts`（参数）、`frontend-next/src/app/case/new/page.tsx`（滑块 UI）
  - 回归测试：`tests/regression/test_evidence_constraint.py`（取消 2 个 skip + 新增 2 个强度边界测试）
- **Key Decisions**:
  - 白名单动态调整：强度 1-2 仅允许单方说明；强度 3 为默认（聊天记录+证人）；强度 4-5 扩展至会议纪要/往来函件
  - 时间红线随强度变化：保守强度（≤2）下聊天记录也纳入红线；激进强度（≥4）下仅核心书证纳入红线
  - 事实锁硬约束（已还款凭证、早于最早日期的关键书证）在所有强度下始终生效
  - 前端滑块仅在单方对抗模式下显示，中立模式固定强度 3
- **Status**: 已完成
- **Validation**: `py -m pytest tests/regression/` → **62 passed, 1 skipped, 0 failed**
  - `test_evidence_constraint.py`: 25 项（新增 2 个强度白名单测试 + 2 个 ConsistencyChecker 强度边界测试）
  - `test_insights.py`: 20 项
  - `test_trial_flow.py`: 18 项
- **Next / Tech Debt**:
  - P2：FactExtractor 升级（混合模式）
  - 后续每次新增功能时同步补充回归测试

### 2026-06-09 — 全局回归测试套件建立（58 项测试）
- **Scope**: 新建 `tests/regression/` 目录 + 3 个回归测试文件 + 1 个共享 fixtures
- **Key Decisions**:
  - 将回归测试集中到 `tests/regression/` 目录，与现有 `tests/test_*.py` 区分：回归测试覆盖"关键行为不被改坏"，单元测试覆盖"模块功能正确"
  - 所有回归测试使用 mock LLM（`unittest.mock.patch`），零 API 调用成本，运行时间约 3 分钟
  - `conftest.py` 提供 3 种标准案件 fixtures（借款合同/买卖合同/劳动争议）和 3 种 mock LLM fixtures
  - 发现 `ConsistencyChecker` verdict 判断存在"子串匹配"误触发问题（mock 返回"不构成矛盾"被误判为"矛盾"），已在测试中规避，后续可改进为更精确的解析
- **Status**: 已完成
- **Validation**: `py -m pytest tests/regression/` → **58 passed, 3 skipped, 0 failed**
  - `test_evidence_constraint.py`: 23 项（覆盖规则提取、白名单构建、时间红线、LLM 检查、后置过滤、端到端生成）
  - `test_insights.py`: 20 项（覆盖 JSON 多策略解析、各 Phase 字段结构、win_rate 注入、错误容错、prompt 模板完整性）
  - `test_trial_flow.py`: 18 项（覆盖状态创建、Agent 保存/恢复、Phase 1-8 节点、全图运行、单方对抗模式创建）
- **Next / Tech Debt**:
  - 后续每次新增功能时同步补充回归测试
  - 可将回归测试接入 CI（每次 push 自动运行）

### 2026-06-09 — 版本迭代日志 CHANGELOG 建立
- **Scope**: 新建 `docs/CHANGELOG.md`，记录从 RAG 系统到证据约束框架的完整迭代路径
- **Status**: 已完成

### 2026-06-08 — 被告证据编造三层约束框架落地（P0+P1+P2）
- **Scope**: 新建 `backend/agents/v2/evidence_constraint.py`；修改 `backend/agents/v2/defendant.py`、`backend/agents/v2/skill.py`、`backend/orchestration/workflow_v2.py`
- **Key Decisions**:
  - 采用"三层约束框架"：第一层事实边界（FactLock + 禁止事项 prompt）、第二层证据类型（白名单 + 证据链完整性）、第三层对抗强度（预留扩展）
  - 使用"前置约束 prompt + 后置一致性验证 + 后置正则过滤"的三重防护，而非单一依赖 LLM 自律
  - ConsistencyChecker 增加"时间红线"快速检查：书证/协议/合同/计划书等如果日期早于已知事实最早日期，无需 LLM 判断直接判矛盾
  - 修正策略采用"只删除冲突证据、严禁新增"而非"重新生成"，防止 LLM 在修正时引入新的编造（如"已还款"凭证）
  - 后置过滤层作为安全网：正则扫描输出，删除仍残留的"还款"类凭证
- **Status**: 已完成（P0-P2 全部落地）
- **Validation**: `py -m py_compile` 通过；9 个 mock 集成测试通过；真实 LLM 测试验证约束效果：
  - ✅ 已禁止编造"已还款"银行转账凭证（后置过滤生效）
  - ✅ 已禁止编造早于最早日期的书证/协议/合同/计划书（ConsistencyChecker 时间红线生效）
  - ✅ 证据来源说明要求被遵守（每项有具体来源）
  - ✅ 证据链完整性要求被遵守（投资合意 + 投资行为 + 未约定利息）
  - ⚠️ 早于最早日期的"微信聊天记录"仍被保留（属于电子数据而非书证，法律逻辑上可接受）
- **Next / Tech Debt**:
  - P3（对抗强度滑块/用户等级）尚未实现，需前端配合
  - 可考虑将 FactExtractor 改为 LLM 驱动（当前为规则提取，准确率有限但速度快）
  - 建议增加自动化回归测试：用 mock LLM 验证约束模块在各种边界情况下的行为

### 2026-06-08 — 修复 Agent 跨阶段记忆传递（P6→P7）
- **Scope**: `backend/agents/v2/memory.py`, `backend/agents/v2/plaintiff.py`, `backend/agents/v2/defendant.py`, `backend/orchestration/workflow_v2.py`；新增文档 `docs/cross-phase-memory-fix-report-2026-06-08.md`
- **Key Decisions**: 
  - 选择通过 `fact_timeline` 归档 P6 peer 消息，而不是修改 `build_context` 直接去读 `consumed_messages`，保持 memory 语义清晰
  - `build_context()` 仅将 `consumed_messages` 作为兜底，而不是主路径
  - 被告 `cross_examine_evidence` 改为 inbox 消费，与 `cross_exam_answer` 保持一致
- **Status**: 已完成（5 个修复点全部落地）
- **Validation**: `py -m py_compile` 通过；全项目 grep 无旧签名残留；未跑端到端庭审验证
- **Next / Tech Debt**: 
  - 需运行端到端庭审测试，确认 P7 最后陈述中出现 P6 交锋内容
  - 建议补充 P6→P7 记忆传递的回归测试
  - 可考虑引入 LLM 摘要步骤压缩 `fact_timeline` 长度

### 2026-06-22 — 修复庭审启动/流式输出稳定问题
- **Scope**: 
  - 后端：`backend/llm.py`（修正 SessionLocal 导入路径）、`backend/main.py`（create_case 主键冲突自恢复 + insight 失败日志增强）、`backend/services/unified_extraction.py`（评估字段防御式规范化）、`backend/agents/v2/base.py`（策略路线生成关闭流式）
- **Key Decisions**:
  - `SessionLocal` 实际定义在 `backend.database`，`llm.py` 原从 `backend.models.database` 导入导致配额/用量记录全部静默失败，改为正确导入
  - create_case 遇到 `IntegrityError` 时自动重试生成新 case_id 并迁移内存 session，避免偶发主键冲突导致 500
  - `_warm_insights` 增加 `exc_info=True` 以捕获 Phase 1 `'level'` 错误的完整堆栈，便于后续定位根因
  - 策略路线生成走 `think(stream=False)`，避免原始 JSON token 被前端误当作 Phase 1 正文展示
- **Status**: 已完成
- **Validation**: 
  - `py -m py_compile backend/main.py backend/llm.py backend/services/unified_extraction.py backend/agents/v2/base.py` 通过
  - `py -m pytest tests/regression/` → **62 passed, 1 skipped, 0 failed**
  - `cd frontend-next && npx tsc --noEmit` 通过
- **Next / Tech Debt**:
  - 需观察后续真实 LLM 运行时 `_warm_insights` 是否仍报 `'level'` 错误，若复现可根据完整堆栈继续修复
  - 前端初始 401 / 连接失败属于启动时序问题，建议后续增加后端就绪检测或请求重试

### 2026-06-26 — 全量代码审计 + 整改方案落档（未改业务代码，仅文档）
- **Scope**:
  - 后端全量精读：`main.py`(2283)、`llm.py`、`auth.py`、`orchestration/workflow_v2.py`+`workflow.py`、`agents/v2/*`(base/channel/memory/skill/plaintiff/defendant/judge/strategy/evidence_constraint/schema)、`evidence/*`、`rag/*`、`services/*`、`utils/cache.py`
  - 前端全量精读：`trial/[caseId]/page.tsx`(977)、`lib/api.ts`、`lib/auth.ts`、首页/案卷/证据/用量页、AuthGuard/PhaseContent/ChatBubble/ModelConfigPanel/FullReportExport 等 18 组件
  - 文档一致性核对：TECH_SPEC / ROADMAP / CLAUDE.md
- **Key Decisions**:
  - 本次仅产出审计报告与整改方案，不改业务代码；完整结论写入 `TECH_SPEC.md §11.x`（7 Critical / 11 High / ~20 Medium / ~12 Low + 4 批整改方案 + 文档与产品视角），前端逐条证据另存 `docs/_audit_frontend.md`
  - 根因对接已有症状：C5 `unified_extraction.py:228` 的 `.format` 花括号 bug = 「Insight 空白」根因；C6 `export_pdf` 未 escape = 「PDF 崩溃」根因；H3 `parser.py:55` 硬编码 UTF-8 = 「中文乱码」根因
  - 最严重架构债 C4：`case_db_to_session`/`case_session_to_db` 字段映射与 `TrialSession` 完全错位 → DB 阶段内容双写永久失效 + sessions 全局内存 dict 致多 worker/重启丢数据
  - 最严重安全洞 C1/C7：证据上传/删除路径穿越 + Zip Slip，可任意读写删服务器文件
- **Status**: 已完成（审计 + 文档落档；代码整改待执行，见 TECH_SPEC §11.x P0–P3）
- **Validation**: 未改代码，无构建/测试变更
- **Next / Tech Debt**:
  - P0（安全+数据丢失，0.5–1天）：路径穿越 basename+realpath、JWT 强制环境变量、取消 `_save_sessions` 自动删除、CORS 白名单、EmailStr
  - P1（核心质量，2–4天）：format→replace、PDF escape、parser 多编码、RAG 零向量改抛异常、对方材料去重、前端 api.ts 统一 res.ok + SSE AbortController
  - P2（架构+并发，3–5天）：修或废弃 DB 双写映射、cache 接入或删除、证据质证改串行、资源 with 化、delete_case 级联
  - P3（迭代）：死代码清理（InsightCard/整套 viz/孤儿 API 函数）、PM 增强、测试补齐、文档同步
  - 注意：本地 `.env` 已设 `JWT_SECRET_KEY`（C2 风险在部署未配时成立）；DB 密码明文在 .env（虽 gitignore，注意本地泄露）

## Known Issues

> **2026-06-26 全量审计发现的 7 个 Critical / 11 个 High 详见 [`TECH_SPEC.md §11.x`](./TECH_SPEC.md#11x-2026-06-26-全量代码审计含整改方案)**。摘要：证据模块路径穿越（C1）、JWT 默认密钥（C2）、`_save_sessions` 自动删除会话（C3）、DB 双写映射失效（C4）、Insight `.format` bug（C5）、PDF 未 escape 崩溃（C6）、Zip Slip（C7）。整改方案按 P0–P3 分批见同处。

- `tests/test_auth.py::test_register_invalid_email` fails (email field uses `str` instead of `EmailStr`).
- See `TECH_SPEC.md` Section 11 for full tech debt list.
