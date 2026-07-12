# moot-court 产品重构方案 v1.0

> **目标**：参考 Palantir 决策-centric 与 Ontology 设计哲学，结合中国律师真实执业痛点，将 moot-court 从「AI 模拟法庭玩具」重构为「律师可实际用于决策辅助的庭审准备操作系统」。
> 
> **状态**：草案（2026-07-08）
> **下一步**：按里程碑分批落地，首批聚焦 Case Ontology + 决策工作台。

---

## 一、诊断：当前产品离「律师可用」的差距

### 1.1 现状（技术优势已具备）

| 维度 | 当前状态 |
|------|---------|
| 庭审模拟 | 8 阶段完整流程，Agent V2 + CommChannel 多 Agent 协作 |
| 知识检索 | RAG 注入 16 部民事法规，552 文本块 |
| 证据处理 | 多模态上传 / OCR / AI 摘要 / 冲突检测 |
| 安全质量 | P0–P4 整改完成，路径穿越、JWT、Insight 空白、PDF 崩溃、乱码等已修复 |
| 工程 | Next.js 16 + FastAPI + LangGraph，测试覆盖核心路径 |

### 1.2 产品级差距（从 PM 视角）

| 差距 | 当前表现 | 律师真实痛点 |
|------|---------|-------------|
| **① 数据是平铺文本，不是可操作对象** | `facts`/`evidence`/`claims` 是大段字符串，Phase 输出也是长文本 | 律师需要「当事人—主张—事实—证据—法条」的网状结构，才能判断证据链是否闭环 |
| **② 输出是「观看」，不是「决策」** | 用户看 AI 生成起诉状/答辩状/判决书 | 律师需要知道：主攻哪条请求权、对方弱点在哪、还差什么证据、下一步做什么 |
| **③ 人机协作停留在「确认/编辑」** | 只能等大段文本生成后整体修改 | 律师需要在关键节点（争议焦点、证据采信、策略路线）做结构化决策 |
| **④ 缺少行动闭环** | 庭审结束只导出 Markdown/PDF | 律师庭后需要任务清单：补证据、约证人、检索判例、计算金额 |
| **⑤ 可信与可审计性不足** | LLM 结论来源不明，无法验证基于哪份证据/哪条法条 | 律师对结论负责，必须能追溯 lineage |
| **⑥ 没有「案件总览」工作台** | 首页是列表，庭审页是长文本流 | 律师习惯看「争议焦点图 + 时间轴 + 证据链 + 待办」 |

### 1.3 核心判断

> 技术层已经跑通「AI 模拟庭审」，但产品层还没有把庭审过程转化为律师可执行的「决策资产」。
> 
> 重构不是推翻 8 阶段引擎，而是在其之上增加一层 **Case Ontology + Decision Workspace + Action Loop**。

---

## 二、重构愿景：从「模拟法庭」到「律师决策操作系统」

### 2.1 一句话定位

**moot-court v3.0 = 基于案件本体的庭审准备与决策辅助系统**

- 输入：案件材料、证据、诉讼请求
- 处理：自动构建案件本体 → 模拟庭审推演 → 提取争议焦点/证据缺口/法条依据
- 输出：结构化决策看板 + 可执行任务 + 专业报告

### 2.2 Palantir 设计哲学映射

| Palantir 原则 | 在 moot-court 中的落地 |
|--------------|----------------------|
| **Ontology（本体）** | 将案件建模为 `Case → Party → Claim → Fact → Evidence → LegalNorm → Issue → Decision` 的对象关系图 |
| **Decision-Centric（决策中心）** | UI 围绕「争议焦点、证据采信、策略选择、行动项」等决策对象组织，而非 8 阶段文本流 |
| **Data + Logic + Action + Security** | 案件数据 + LLM/规则推理 + 律师执行门（审批/编辑）+ 权限与审计 |
| **Human-in-the-Loop** | LLM 生成建议 → 律师结构化确认/修改/驳回 → 系统记录决策 lineage |
| **Forward Deployed / Empathy** | 不新增花哨 viz，先解决「证据链是否闭环、还差什么证据、法官可能问什么」等高频痛点 |
| **Auditability** | 每个结论必须展示「基于哪些证据、哪条法条、哪个判例」；决策日志可导出 |

---

## 三、Case Ontology 设计

### 3.1 对象类型（Object Types）

```python
class CaseObject:
    id: str              # case_id
    title: str
    case_type: str       # 案由分类
    mode: str            # neutral / asymmetric
    user_side: str
    status: str          # draft / running / completed / archived
    created_at: str

class Party:
    id: str
    case_id: str
    role: str            # plaintiff / defendant / third_party
    name: str
    type: str            # natural_person / enterprise / org
    position_summary: str

class Claim:
    id: str
    case_id: str
    party_id: str        # 提出方
    claim_text: str      # 原文
    claim_type: str      # principal / alternative / procedural
    legal_basis: list[str]   # 关联 LegalNorm.id
    facts: list[str]         # 关联 Fact.id
    evidence_ids: list[str]
    win_rate_contribution: float  # 对整体胜率的贡献评估

class Fact:
    id: str
    case_id: str
    description: str
    date: str | None
    parties_involved: list[str]
    evidence_ids: list[str]
    is_disputed: bool
    dispute_summary: str | None

class Evidence:
    id: str
    case_id: str
    party_id: str
    name: str
    source_type: str     # txt / docx / pdf / image / audio
    content: str         # OCR/提取文本
    summary: str
    evidence_type: str   # 书证 / 物证 / 电子数据 / 证人证言 / 鉴定意见 / 勘验笔录
    date: str | None
    proves: list[str]    # 关联 Fact.id / Claim.id
    admissibility: dict  # 三性评估：真实性/合法性/关联性
    weaknesses: list[str]

class LegalNorm:
    id: str
    case_id: str
    source: str          # 法规名
    article: str         # 条/款/项
    text: str
    role: str            # principal / auxiliary / defensive
    confidence: float
    rag_source: str | None

class Precedent:
    id: str
    case_id: str
    title: str
    court: str
    case_number: str
    similarity_score: float
    key_takeaway: str
    source: str

class Issue:
    id: str
    case_id: str
    title: str
    description: str
    issue_type: str      # fact / law / evidence / procedure
    party_positions: dict  # {plaintiff: ..., defendant: ...}
    evidence_ids: list[str]
    legal_norm_ids: list[str]
    priority: int        # 1-5
    status: str          # open / resolved / disputed

class Decision:
    id: str
    case_id: str
    decision_type: str   # strategy / evidence / issue / action
    title: str
    options: list[dict]  # [{id, label, pros, cons, recommended}]
    selected_option: str | None
    rationale: str
    made_by: str         # ai / user / ai+suggested
    created_at: str
    source_refs: list[str]  # 关联 Evidence/LegalNorm/Issue.id

class ActionItem:
    id: str
    case_id: str
    title: str
    action_type: str     # supplement_evidence / legal_research / client_comm / witness / filing
    priority: str        # high / medium / low
    due_hint: str
    status: str          # open / done / dismissed
    source_decision: str | None
```

### 3.2 链接类型（Link Types）

| 源对象 | 关系 | 目标对象 | 语义 |
|--------|------|---------|------|
| Claim | is_supported_by | Evidence | 主张由证据支持 |
| Evidence | proves | Fact | 证据证明事实 |
| Fact | relates_to | Issue | 事实构成争议焦点 |
| LegalNorm | supports | Claim / Issue | 法条支持主张或焦点 |
| Issue | blocks | Claim | 焦点决定主张成立与否 |
| Decision | resolves | Issue | 决策解决焦点 |
| ActionItem | follows | Decision | 行动来自决策 |

### 3.3 与现有数据的映射

| 现有数据 | 映射到 Ontology |
|---------|----------------|
| `CaseInput.case_title` | `CaseObject.title` + 推断 `CaseObject.case_type` |
| `CaseInput.facts` | 提取多个 `Fact` |
| `CaseInput.claims` | 提取多个 `Claim` |
| `CaseInput.evidence` | 提取多个 `Evidence`（若已上传证据则 richer） |
| `CaseInput.source_materials` | 保留为 `CaseObject.raw_materials` |
| Phase 1 `phase1_analysis` | 提取 `Claim` + `LegalNorm` + `Issue`（请求权基础） |
| Phase 2 `phase2_complaint` | 与 `Claim`、`Evidence` 对齐 |
| Phase 5 `phase5_issues` | 提取 `Issue` |
| Phase 6 `phase6_evidence_exam` | 更新 `Evidence.admissibility`、生成 `Issue` |
| Phase 8 `phase8_judgment` | 提取 `Decision`（判决方向）+ `ActionItem` |

---

## 四、决策中心 UI（Decision-Centric Workspace）

### 4.1 页面结构

新增 `/workspace/[caseId]` 作为默认进入页（保留 `/trial/[caseId]` 供完整庭审流使用）。

```
/workspace/[caseId]
├── 顶部：案件标题 + 模式标签 + 胜率 + 导出按钮
├── 左侧导航
│   ├── 案件总览（Dashboard）
│   ├── 争议焦点（Issues）
│   ├── 证据链（Evidence Chain）
│   ├── 法条与判例（Legal Basis）
│   ├── 策略决策（Decisions）
│   ├── 行动清单（Action Items）
│   └── 庭审推演（→ 跳转 /trial/[caseId]）
└── 主内容区（按导航切换）
```

### 4.2 各页面核心信息

#### 案件总览 Dashboard

- **案件基本信息**：标题、当事人、代理模式
- **争议焦点卡片**：Top 3 焦点，每个显示状态（开放/已决）
- **证据链健康度**：闭环证据数 / 总关键事实数
- **胜率仪表盘**：整体胜率 + 分维度（事实/证据/法律）
- **待办行动**：Top 5 高优先级 ActionItem
- **关键决策待确认**：需要律师审批的 Decision 列表

#### 争议焦点 Issues

- 列表视图：标题、类型、优先级、双方立场、关联证据
- 关系图（简单）：Issue ↔ Fact ↔ Evidence ↔ LegalNorm
- 每个 Issue 可「编辑立场」「补充证据」「标记解决」

#### 证据链 Evidence Chain

- 时间轴 + 证据卡片
- 每个证据显示：三性评估、证明的事实/主张、薄弱点
- 缺失证据提示（如「主张借款合意，但无聊天记录/借条」）
- 支持拖拽/点击关联到 Fact/Claim

#### 法条与判例 Legal Basis

- 主要规范 / 辅助规范 / 防御规范 分类
- 每条法条显示置信度、来源（RAG 检索 / LLM 推断）
- 相似判例卡片：案号、法院、关键要旨

#### 策略决策 Decisions

- LLM 建议的策略选项卡（与现有 StrategySelector 类似，但覆盖更多决策类型）
- 决策类型：请求权选择、证据提交时序、争议焦点优先级、是否申请鉴定/证人
- 律师可：采纳 / 修改 / 驳回 / 要求重新生成
- 每个决策显示 lineage（基于哪些 Issue/Evidence/LegalNorm）

#### 行动清单 Action Items

- 按优先级排序
- 每项可标记完成/删除/添加备注
- 支持一键生成「律师工作备忘录」导出

---

## 五、关键交互改造

### 5.1 新建案件流程

当前：粘贴/上传 → AI 解析 → 手动填表单 → 进入庭审

改造后：

1. 粘贴/上传/手动输入
2. AI 解析生成 **Ontology 预览**：当事人、事实、证据、主张、案由
3. 律师结构化确认/修正（不是改长文本，是改对象）
4. 确认后进入 Workspace，可一键「开始庭审推演」

### 5.2 庭审推演流程

保留 8 阶段引擎，但输出结构化为 Ontology 更新：

- Phase 1 → 生成/更新 `Claim`、`LegalNorm`、`Issue`
- Phase 2 → 对齐 `Claim` 与 `Evidence`
- Phase 3 → 生成被告 `Claim`、防御规范
- Phase 5 → 确认/编辑 `Issue`
- Phase 6 → 更新 `Evidence.admissibility`、生成新 `Issue`
- Phase 8 → 生成最终 `Decision` 与 `ActionItem`

每个阶段在 Workspace 中都有对应的「决策卡」，律师可以暂停、编辑、重新推演。

### 5.3 What-if / 回退

- Workspace 支持「回到 Phase N 重新推演」
- 每次回退保存一个 Snapshot
- 支持 Snapshot 对比（策略 A vs 策略 B）

---

## 六、技术实现路径

### 6.1 新增模块

```
backend/
├── ontology/
│   ├── __init__.py
│   ├── models.py          # CaseObject/Party/Claim/Fact/Evidence/LegalNorm/Precedent/Issue/Decision/ActionItem
│   ├── extractor.py       # 从 CaseInput / TrialSession 提取 Ontology 对象
│   ├── builder.py         # 构建/更新本体图
│   ├── lineage.py         # 来源追溯
│   └── service.py         # CRUD + 查询服务
│
├── extraction/
│   └── phase_extractor.py # 各 Phase 结构化提取（替代/增强 unified_extraction）
│
└── api/
    └── ontology.py        # /ontology/* 路由（可合并到 main.py 或独立 router）

frontend-next/src/
├── app/
│   └── workspace/
│       └── [caseId]/
│           ├── page.tsx           # Workspace 布局
│           ├── DashboardTab.tsx
│           ├── IssuesTab.tsx
│           ├── EvidenceChainTab.tsx
│           ├── LegalBasisTab.tsx
│           ├── DecisionsTab.tsx
│           └── ActionItemsTab.tsx
│
└── components/ontology/
    ├── OntologyGraph.tsx
    ├── EvidenceCard.tsx
    ├── IssueCard.tsx
    ├── DecisionCard.tsx
    └── ActionItemCard.tsx
```

### 6.2 关键 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology/{case_id}` | 获取完整案件本体 |
| GET | `/ontology/{case_id}/issues` | 争议焦点列表 |
| GET | `/ontology/{case_id}/evidence-chain` | 证据链 |
| GET | `/ontology/{case_id}/legal-basis` | 法条与判例 |
| GET | `/ontology/{case_id}/decisions` | 决策列表 |
| POST | `/ontology/{case_id}/decisions/{decision_id}` | 提交律师决策 |
| GET | `/ontology/{case_id}/action-items` | 行动清单 |
| POST | `/ontology/{case_id}/action-items` | 创建/更新行动项 |
| POST | `/ontology/{case_id}/extract` | 从当前 TrialSession 重新提取 Ontology |

### 6.3 与现有引擎的兼容

- 不修改 `TrialState` / `TrialSession` 核心字段
- Ontology 是「衍生层」，从 session 提取，可重建
- 保留 `/trial/*` 完整流式庭审路径
- Workspace 通过 `/ontology/{case_id}/extract` 主动触发重建

---

## 七、首批落地里程碑（MVP）

### Milestone 1：Case Ontology 与提取服务（1 周）

- [ ] 定义 Ontology 数据模型（Pydantic/SQLAlchemy）
- [ ] 实现从 `CaseInput` 提取 Party/Claim/Fact/Evidence
- [ ] 实现从 `TrialSession` 提取 Issue/LegalNorm/Decision/ActionItem
- [ ] 新增 `/ontology/{case_id}` API + 测试
- [ ] 将 Ontology 数据持久化到 PostgreSQL（可选，首期可内存+JSON缓存）

### Milestone 2：Workspace Dashboard（1 周）

- [ ] 新增 `/workspace/[caseId]` 页面与左侧导航
- [ ] 实现 Dashboard 总览（争议焦点、证据链健康度、胜率、待办）
- [ ] 实现 Issues 列表页（可编辑立场/状态）
- [ ] 实现 Evidence Chain 页（时间轴 + 三性评估）
- [ ] 接入现有 `/trial/[caseId]` 跳转

### Milestone 3：决策卡与行动清单（1 周）

- [ ] 设计 Decision 数据模型与 API
- [ ] 在 Phase 1/3/5/8 生成结构化 Decision 建议
- [ ] Workspace 中 Decision 确认/修改/驳回交互
- [ ] 基于最终判决生成 ActionItem 清单
- [ ] 导出「律师工作备忘录」Markdown/PDF

### Milestone 4：闭环验证（1 周）

- [ ] 端到端测试：创建案件 → 庭审推演 → Workspace 决策 → 导出报告
- [ ] 邀请目标用户（法学生/实习律师/执业律师）试用并收集反馈
- [ ] 根据反馈调整 Ontology 字段与 UI 优先级

---

## 八、成功指标

| 指标 | 当前 | 目标（3 个月后） |
|------|------|----------------|
| 用户完成首次庭审推演后返回使用 | 未知 | ≥60% 次日留存 |
| 庭审报告被导出/分享 | 低 | 每案平均 ≥1 次导出 |
| 律师在 Workspace 中做结构化决策 | 0 | 每案 ≥3 个 Decision 被确认/修改 |
| ActionItem 完成率 | 0 | ≥30% 被标记完成 |
| 用户主动反馈「提升效率」 | 无 | NPS ≥30 |

---

## 九、风险与应对

| 风险 | 应对 |
|------|------|
| Ontology 提取准确率不足 | 先从高频案由（借款/劳动/买卖）做规则+LLM混合提取，逐步扩展 |
| LLM 法条/判例幻觉 | 所有 LegalNorm 必须关联 RAG source，Precedent 只显示检索到的真实判例 |
| 前端工作量大 | 先做 Workspace Dashboard，庭审页不改造；复用现有组件 |
| 用户不习惯结构化工作流 | 保留「完整庭审流」入口，Workspace 作为增强视图 |
| 性能问题 | Ontology 提取异步执行，不阻塞庭审流式输出 |

---

## 十、下一步行动

1. **确认本 PRD**：与利益相关者（用户/开发者）确认方向与 Milestone 范围。
2. **开始 Milestone 1**：实现 `backend/ontology/` 模块与提取服务。
3. **同步更新 TECH_SPEC**：将 Ontology 模块、API 契约、数据模型写入 `TECH_SPEC.md` §4.x。
4. **更新 CLAUDE.md Running Log**：记录本次产品重构决策。

---

*参考来源：*
- [Palantir Ontology: a arquitetura decision-centric – RDD10+](https://www.robertodiasduarte.com.br/en/palantir-ontology-a-arquitetura-decision-centric/)
- [Palantir Foundry Design Patterns – Spencer Fuller](https://spencerfuller.dev/projects/foundry-patterns/)
- [The Architecture That Turns AI Agents Into Decision-Making Systems – Glitchwire](https://glitchwire.com/news/palantir-ontology-the-architecture-that-turns-ai-agents-into-decision-making-sys/)
- [How to Build AIP-Powered Workshop Apps in Palantir Foundry – LinkedIn](https://www.linkedin.com/posts/deepak-suryawanshi-a79665126_palantirfoundry-aip-workshop-activity-7389504483149393920-QQKb)
