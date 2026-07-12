# 模拟法庭版本迭代日志

> 按日期倒序记录每次对话/迭代后的功能改进、架构决策与关键修复。
> 来源：Claude 会话记忆 + CLAUDE.md Running Log + 代码提交记录。

---

## 2026-06-09 — 对抗强度滑块前后端落地 + 回归测试扩展（62 项测试）

### 1. 对抗强度滑块（P1）
**需求**：用户在创建案件时可选择 AI 被告的"对抗强度"（1-5 级），控制其编造证据的激进程度。

**后端改动**：
- `backend/models/case.py`：`CaseInput` 新增 `adversarial_intensity: int = 3`
- `backend/main.py`：`CreateCaseRequest` 新增 `adversarial_intensity`，创建时自动 clamp 到 1-5
- `backend/agents/v2/evidence_constraint.py`：
  - `EvidenceConstraintBuilder` 接收 `intensity` 参数，动态调整白名单/黑名单
  - `ConsistencyChecker` 接收 `intensity` 参数，调整时间红线严格度（保守强度下聊天记录也纳入红线）
- `backend/agents/v2/defendant.py`：`draft_evidence_catalog` 接收 `intensity` 并传递给约束构建器
- `backend/orchestration/workflow_v2.py`：Phase 4 调用时从 `case_input.adversarial_intensity` 读取并传入

**前端改动**：
- `frontend-next/src/lib/api.ts`：`createCase` 参数新增 `adversarial_intensity`
- `frontend-next/src/app/case/new/page.tsx`：单方对抗模式下显示强度滑块（1-5）和动态说明文字

**白名单动态规则（借款合同纠纷示例）**：
| 强度 | 允许编造 | 禁止编造 |
|-----|---------|---------|
| 1-2 | 单方书面说明、对现有记录的不同解读 | 证人证言、项目资料、新聊天记录 |
| 3 | 聊天记录、证人证言、项目资料 | 银行还款凭证、书面借条/合同 |
| 4-5 | 上述全部 + 会议纪要/往来函件复印件 | 银行还款凭证 |

**回归测试扩展**：
- 取消 2 个 skip 的强度白名单测试
- 新增 2 个 ConsistencyChecker 强度边界测试（低强度聊天记录拦截 / 高强度聊天记录放行）
- 全量回归：**62 passed, 1 skipped**（原 58 passed, 3 skipped）

---

## 2026-06-09 — 全局回归测试套件建立（58 项测试）

### 1. 回归测试架构
**背景**：之前做可视化和 Insight 卡片时，后续改动导致功能损坏且难以复现，需要一个自动化的"保险锁"。

**实现**：
- 新建 `tests/regression/` 目录，含 3 个测试文件 + 共享 fixtures
  - `test_evidence_constraint.py`：23 项测试，覆盖规则提取、白名单、时间红线、LLM 检查、后置过滤、端到端生成
  - `test_insights.py`：20 项测试，覆盖 JSON 解析、各 Phase 字段结构、win_rate 注入、错误容错
  - `test_trial_flow.py`：18 项测试，覆盖状态创建、Agent 保存/恢复、Phase 1-8 节点、全图运行、单方对抗模式
- `tests/regression/conftest.py`：提供标准案件 fixtures（借款合同/买卖合同/劳动争议）和 mock LLM fixtures

**运行方式**：
```bash
py -m pytest tests/regression/ -v
```

### 2. 版本迭代日志 CHANGELOG
- 新建 `docs/CHANGELOG.md`，按日期倒序记录从 RAG 系统到证据约束框架的完整迭代路径。

---

## 2026-06-08 — 被告证据编造三层约束框架 + Agent 记忆传递修复

### 1. 被告证据编造三层约束框架（P0+P1+P2）
**背景**：AI 被告在单方对抗模式下需要编造对抗性证据以帮助用户（原告律师）做诉讼准备，但之前存在编造证据与已知事实直接矛盾的问题（如编造"已还款"凭证、早于最早日期的合同等）。

**实现**：
- 新建 `backend/agents/v2/evidence_constraint.py`
  - `FactLock` 数据模型：时间事实、主体事实、行为事实、已确认证据、原告主张、明确禁止编造项
  - `FactExtractor`：轻量级规则提取器，无需额外 LLM 调用
  - `EvidenceConstraintBuilder`：按案由类型构建证据白名单/黑名单/证据链完整性要求
  - `ConsistencyChecker`：后置一致性验证，含"时间红线"快速检查（书证早于最早日期直接判矛盾）
- 修改 `backend/agents/v2/defendant.py`：`draft_evidence_catalog()` 集成事实锁提取与约束 prompt 注入
- 修改 `backend/agents/v2/skill.py`：`DraftingSkill` 增加证据目录专项约束 + 一致性检查修正循环 + 后置过滤安全网
- 修改 `backend/orchestration/workflow_v2.py`：Phase 4 调用证据目录时传入 `case_input`

**关键决策**：
- 采用"前置约束 prompt + 后置一致性验证 + 后置正则过滤"三重防护
- 修正策略用"只删除冲突证据，严禁新增"而非"重新生成"，防止 LLM 在修正时改变抗辩策略
- 时间红线用规则而非 LLM 判断，零误判且零额外调用成本

**验证**：
- 9 个 mock 集成测试通过
- 真实 LLM 测试验证：已还款凭证被拦截、早于最早日期的书证被拦截、证据来源说明合规、证据链完整

### 2. Agent 跨阶段记忆传递修复（P6→P7）
**背景**：Phase 6 举证质证中的交锋内容未传递到 Phase 7 最后陈述，导致最后陈述与庭审实况脱节。

**根因**：P6 peer 消息未被归档到 `fact_timeline`，且 `build_context()` 未读取 `consumed_messages`。

**实现**：
- `backend/agents/v2/memory.py`：P6 结束后将 inbox 中的交叉询问消息归档到 `fact_timeline`
- `backend/agents/v2/plaintiff.py` / `defendant.py`：`closing_statement()` 从 `fact_timeline` 读取 P6 交锋记录
- `backend/orchestration/workflow_v2.py`：Phase 7 调用前同步 `fact_timeline`
- `defendant.py`：`cross_examine_evidence()` 改为 inbox 消费模式，与 `cross_exam_answer` 保持一致

**状态**：代码已落地，待端到端庭审验证。

---

## 2026-06-06 — 庭审质量 Bug 修复（9 项）

**背景**：2026-06-02 批次功能上线后，庭审流程出现多项稳定性问题。

**主要修复**：
1. **乱码问题**：后端返回中文在 Windows 终端出现 GBK 编码错误 → 强制 UTF-8 编码输出
2. **Insight 空白**：LLM 返回的 Insight JSON 格式不标准导致解析失败 → 增加容错解析 + fallback 文本
3. **策略自动选择**：单方对抗模式下策略未按 `user_strategy_hint` 生效 → 修复策略路由逻辑
4. **材料原文丢失**：RAG 检索后未保留原始材料上下文 → 双轨制保留 `source_materials`

**文档**：`docs/trial-quality-bugs-2026-06-06.md`（根因诊断与修复方案）

---

## 2026-06-02 — 批次功能上线

**功能列表**：
1. **全局搜索**：案件列表支持按标题/事实/证据/诉讼请求全文搜索
2. **移动端适配**：庭审页面响应式布局，支持手机端查看
3. **LLM 用量配额**：用户级 LLM 调用次数统计与配额限制
4. **协作分享**：生成可分享的庭审链接，支持只读访问
5. **通知系统**：庭审阶段完成、证据分析完成等事件推送

**同时发现的问题**（列入后续修复）：
- 庭审质量问题：乱码 / Insight 空白 / 策略自动选择 / 材料原文丢失

---

## 更早阶段（已完成里程碑）

### 单方对抗模式 V2（Phase A-F）
- 10 个端到端测试通过
- 支持用户选择扮演原告律师或被告律师
- AI 生成对方材料并参与对抗
- 文件：`backend/agents/v2/` 单方对抗相关逻辑

### Agent V2 P0-P4
- 11 个集成测试通过
- Actor-Memory-Skill 模型重构
- Phase 1-5 真实多 Agent 交互
- Phase 6 CommChannel 受控通信（peer visibility）
- Phase 7-8 Agent 自主 publish

### 多模态证据处理（Phase 1+2）
- 支持文本、图片、音频证据的上传与解析
- 证据结构化存储与冲突检测
- Timeline 与 PartyRelation 可视化数据生成

### API 保护
- JWT 认证中间件
- 请求频率限制
- 敏感操作权限校验

### RAG 系统
- 法律知识库向量检索
- 案件材料上下文增强
- 法条引用准确性提升
