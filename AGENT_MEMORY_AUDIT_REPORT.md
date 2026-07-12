# moot-court Agent 记忆与消息传递机制审计报告

> **审计日期**: 2026-06-08
> **审计范围**: `backend/agents/v2/` 全目录 + `backend/orchestration/workflow_v2.py`
> **审计目标**: 验证原告/被告律师是否为独立 Agent（非一套 Prompt），记忆与消息传递机制是否真实运转，策略分析与法律文书的信息隔离是否有效。

---

## 一、总体结论（Executive Summary）

| 维度 | 设计层面 | 实现层面 | 评级 |
|------|---------|---------|------|
| 原被告 Agent 独立性 | ✅ 独立类、独立 system_prompt、独立 MemoryBank 实例 | ⚠️ Phase 1-5 为单 Agent 顺序执行，无并发交互 | **B** |
| 记忆基础设施 | ✅ MemoryBank（三层）、CommChannel（ACL+visibility）、序列化/反序列化 | ✅ 完整实现 | **A** |
| 消息传递机制 | ✅ 协议完备（public/peer/private_to_judge） | ❌ inbox 几乎未被消费；Phase 6 消息通过参数旁路传递 | **C** |
| 策略-文书信息隔离 | ✅ 策略存 private，文书走 public/shared | ⚠️ Skill 层 LLM 调用不注入 memory context，策略对 Skill 不可见 | **C** |
| 动态策略调整 | ✅ `adapt_strategy()` 接口存在 | ❌ 全工作流中从未被调用 | **F** |

**一句话判断**：你的怀疑**部分成立**。项目确实不是"一套 Prompt 工程"——它有独立的 Agent 类、独立的 MemoryBank 实例、以及完备的通信协议框架。但工作流层对这些基础设施的**利用率极低**：`inbox` 形同虚设、Skill 层与记忆层断裂、Phase 7 的顺序交互存在实现漏洞、策略动态调整完全未接线。架构是"真多 Agent"，但运转方式在大量环节退化为"单 Agent 顺序调用"。

---

## 二、原被告律师是否为独立 Agent？

### 2.1 结论：是独立实例，但 Phase 1-5 无并发交互

**证据 1：独立的类与 System Prompt**

- [`plaintiff.py:22`](backend/agents/v2/plaintiff.py#L22) `PLAINTIFF_SYSTEM_V2`："你是一名资深中国民事诉讼原告方律师"
- [`defendant.py:22`](backend/agents/v2/defendant.py#L22) `DEFENDANT_SYSTEM_V2`："你是一名资深中国民事诉讼被告方律师"
- 两者在 [`workflow_v2.py:70-72`](backend/orchestration/workflow_v2.py#L70-L72) 中被分别实例化：
  ```python
  plaintiff = PlaintiffAgentV2(llm_config=llm_cfg)
  defendant = DefendantAgentV2(llm_config=llm_cfg)
  judge = JudgeAgentV2(llm_config=llm_cfg)
  ```

**证据 2：独立的 MemoryBank**

每个 Agent 拥有独立的 `MemoryBank` 实例（[`base.py:54`](backend/agents/v2/base.py#L54)）：
```python
self.memory = MemoryBank()  # 每个 Agent 独立
```

状态持久化也是独立的四个字段（[`workflow.py:111-114`](backend/orchestration/workflow.py#L111-L114)）：
```python
plaintiff_state: dict
defendant_state: dict
judge_state: dict
reporter_state: dict
```

**问题：Phase 1-5 本质上是单 Agent 顺序执行**

TECH_SPEC 自身也承认（[TECH_SPEC.md:133](TECH_SPEC.md#L133)）：
> "Phase 1-5 和 8 本质上是高级 Prompt Engineering（单 Agent 接收材料后一次性输出）。"

在 workflow 中：
- Phase 1-2：仅 `plaintiff` Agent 运行
- Phase 3-4：仅 `defendant` Agent 运行
- Phase 5：仅 `judge` Agent 运行

这些阶段虽然各自有独立的 Agent 实例和记忆，但**并非同时运行、相互交互**。被告在 Phase 3 读取原告起诉状，但不是通过实时的消息传递，而是从 `shared memory`（或 `_sync_state_to_memory` 兼容性回填）中读取。

---

## 三、记忆与消息传递机制审计

### 3.1 基础设施：设计优秀，实现完整

| 组件 | 文件 | 状态 |
|------|------|------|
| `MemoryBank`（private/shared/inbox 三层） | [`memory.py:105`](backend/agents/v2/memory.py#L105) | ✅ 完整 |
| `CommChannel`（ACL + visibility 路由） | [`channel.py:19`](backend/agents/v2/channel.py#L19) | ✅ 完整 |
| `AgentMessageV2`（消息协议） | [`schema.py:20`](backend/agents/v2/schema.py#L20) | ✅ 完整 |
| `CourtReporterV2`（公共账本 + 去重） | [`channel.py:121`](backend/agents/v2/channel.py#L121) | ✅ 完整 |
| 状态序列化/反序列化 | [`base.py:316-331`](backend/agents/v2/base.py#L316-L331) | ✅ 完整 |
| `_save_agents_v2` / `_restore_agents_v2` | [`workflow_v2.py:66-134`](backend/orchestration/workflow_v2.py#L66-L134) | ✅ 完整 |

### 3.2 致命缺陷：inbox 机制形同虚设

**`consume_inbox()` 在全代码库中仅被调用 1 次**，且是兼容性回退代码：

[`defendant.py:67`](backend/agents/v2/defendant.py#L67)
```python
plaintiff_docs = self.memory.shared.get_by_phase(2)
if not plaintiff_docs:
    # 兼容：从 inbox 读取收到的消息
    plaintiff_docs = self.memory.consume_inbox("document")
```

**Phase 6 交叉询问的消息传递是"假传递"**：

虽然 workflow 层确实通过 `CommChannel.dispatch()` 发送了 `peer` 消息（[`workflow_v2.py:614`](backend/orchestration/workflow_v2.py#L614)）：
```python
msg_q = AgentMessageV2(
    sender="plaintiff", recipient="defendant",
    msg_type="question", ..., visibility="peer", ...
)
channel.dispatch(msg_q)
```

但 `defendant.cross_exam_answer()` **并非从 inbox 读取问题**，而是直接从 workflow 接收参数：

[`workflow_v2.py:629`](backend/orchestration/workflow_v2.py#L629)
```python
a_text = await _retry_async(defendant.cross_exam_answer, 2, q_text)
```

[`defendant.py:132`](backend/agents/v2/defendant.py#L132)
```python
async def cross_exam_answer(self, question: str) -> str:
    return await self.think_with_skill("cross_exam", {
        "mode": "answer", "target": question,
    })
```

**消息被路由到了 inbox，但 Agent 从未消费 inbox**。 workflow 直接绕过 inbox，把内容作为函数参数硬塞给 Agent。这导致：
1. `CommChannel` 的 ACL 校验虽然执行了，但对接收方无实际意义（因为它不读 inbox）。
2. `private.consumed_messages` 归档功能几乎为空。
3. 如果未来想要让 Agent 自主决定何时回复、如何回复，inbox 机制无法支撑。

### 3.3 Phase 7 "顺序交互"存在实现漏洞

TECH_SPEC 声称（[TECH_SPEC.md:133](TECH_SPEC.md#L133)）：
> "Phase 7 为顺序交互：原告先生成最后陈述并通过 `CommChannel` 广播到所有 Agent 的 shared 层，被告读取后再生成自己的陈述，可针对性回应原告论点。"

**实际代码**：

[`workflow_v2.py:913-960`](backend/orchestration/workflow_v2.py#L913-L960)
```python
# Step 1: 原告最后陈述
pf = await plaintiff.final_statement(case.case_title, case.claims)
msg_pf = AgentMessageV2(..., visibility="public", ...)
channel.dispatch(msg_pf)  # 确实广播到 shared

# Step 2: 被告最后陈述
df = await defendant.final_statement(case.case_title, case.claims)
# 注意：只传了 case_title 和 claims，没有传原告陈述
```

[`defendant.py:154`](backend/agents/v2/defendant.py#L154)
```python
async def final_statement(self, case_title: str, claims: str) -> str:
    return await self.think_with_skill("drafting", {
        "doc_type": "statement",
        "materials": f"案由：{case_title}\n原告诉讼请求：{claims}",
    })
```

**被告的 `final_statement` 方法**：
1. **没有从 `memory.shared` 读取原告陈述**（虽然原告陈述已被广播到 shared 层）。
2. 传给 Skill 的 `materials` 中只有案由和诉讼请求，**不含原告最后陈述内容**。
3. 更底层的问题是（见第 4 节）：`think_with_skill` → `_call_llm` **不注入 memory context**，所以即使 shared 层有原告陈述，LLM 也看不到。

**结论**：Phase 7 的"被告可针对性回应"是**纸面设计**，实际代码中被告完全盲打，无法感知原告陈述。

---

## 四、策略分析与法律文书的信息隔离

### 4.1 信息隔离的设计是正确的

- **策略**存储在 `memory.private.strategy`（[`base.py:225`](backend/agents/v2/base.py#L225)）和 `memory.private.strategy_notes`。
- **法律文书**通过 `publish()` 发布为 `public` → 进入所有 Agent 的 `shared` 层（[`base.py:177`](backend/agents/v2/base.py#L177)）。
- `PrivateMemory` 有完整的 `to_dict()` / `from_dict()`，策略在序列化时被保存，不会泄露到其他 Agent 的状态字段中。

### 4.2 致命断裂：Skill 层 LLM 调用不注入 memory context

这是整个系统**最严重**的实现缺陷。

**`think()` 方法**（[`base.py:86`](backend/agents/v2/base.py#L86)）正确地注入了记忆：
```python
async def think(self, task, context=None):
    messages = self._build_messages(task, context)
    # _build_messages 会调用 memory.build_context(include_private=True)
```

**`think_with_skill()` 方法**（[`base.py:126`](backend/agents/v2/base.py#L126)）调用 Skill 的 `execute()`，最终进入 `_call_llm()`：

[`skill.py:36-59`](backend/agents/v2/skill.py#L36-L59)
```python
async def _call_llm(self, agent, task, *, temperature=0.3, max_tokens=4096):
    queue = stream_queue_ctx.get(None)
    if queue:
        async for token in llm_call_stream(
            agent.system_prompt,
            messages=[{"role": "user", "content": task}],  # <-- 仅一条 user 消息！
            ...
        ): ...
```

**`_call_llm` 使用的 messages 只有 `[{"role": "user", "content": task}]`，完全不包含**：
- `memory.private.strategy_notes`（策略笔记）
- `memory.private.fact_timeline`（案件大事记）
- `memory.private.legal_notes`（法条检索笔记）
- `memory.shared.documents`（已公开文书）
- `memory.inbox`（未读消息）

这意味着：**所有通过 `think_with_skill` 生成的法律文书（起诉状、答辩状、证据目录、最后陈述、交叉询问问题/回答）都看不到策略、看不到对方文书、看不到 inbox 消息**。

而业务代码中，**几乎所有方法都使用 `think_with_skill`**：

| 方法 | 所在文件 | 调用方式 |
|------|---------|---------|
| `analyze_claims` | plaintiff.py | `think_with_skill("legal_research", ...)` |
| `draft_complaint` | plaintiff.py | `think_with_skill("drafting", ...)` |
| `draft_evidence_catalog` | plaintiff.py | `think_with_skill("drafting", ...)` |
| `cross_exam_question` | plaintiff/defendant.py | `think_with_skill("cross_exam", ...)` |
| `cross_exam_answer` | plaintiff/defendant.py | `think_with_skill("cross_exam", ...)` |
| `analyze_defense` | defendant.py | `think_with_skill("legal_research", ...)` |
| `draft_answer` | defendant.py | `think_with_skill("drafting", ...)` |
| `final_statement` | plaintiff/defendant.py | `think_with_skill("drafting", ...)` |
| `summarize_issues` | judge.py | `think_with_skill("moderation", ...)` |
| `render_judgment` | judge.py | `think_with_skill("adjudication", ...)` |

唯一使用 `think()` 的是：
- `generate_strategy_routes()`（生成策略路线）
- `comment_on_evidence()`（原告举证说明）
- `cross_examine_evidence()`（被告质证意见）
- `summarize_evidence_focus()`（法官归纳焦点）
- `moderate_cross_exam()`（法官主持）
- `should_continue_cross_exam()`（法官评估是否继续）
- `ruling_on_evidence()`（法官裁定）

**结果**：起诉状、答辩状、最后陈述、交叉询问等核心法律文书，生成时**对 Agent 自己的策略和对方文书不可见**。

### 4.3 为什么被告的 `analyze_defense` 看起来能读到起诉状？

[`defendant.py:58-85`](backend/agents/v2/defendant.py#L58-L85)
```python
async def analyze_defense(self, case_input):
    plaintiff_docs = self.memory.shared.get_by_phase(2)
    complaint = "...".join(d.content for d in plaintiff_docs)
    context = f"你收到了原告的起诉材料：\n\n{complaint}\n\n请基于以上材料，制定答辩策略。"
    return await self.think_with_skill("legal_research", {
        ..., "context": context,
    })
```

这里确实从 `shared` 读取了起诉状，并传入了 `context` 参数。但注意：
1. `think_with_skill` → `LegalResearchSkill.execute()` 接收 `context` 参数。
2. `LegalResearchSkill.execute()` 中：`task = f"...【角色】..."`，**完全没有使用 `context` 参数**！

[`skill.py:82-98`](backend/agents/v2/skill.py#L82-L98)
```python
async def execute(self, agent, context: dict):
    query = context.get("query", "")
    case_title = context.get("case_title", "")
    role = context.get("role", "plaintiff")
    task = f"请进行法律研究。\n【案由】{case_title}\n【研究主题】{query}\n【角色】..."
```

`context` 中的 `context` 键（包含起诉状）被完全忽略了！所以即使被告方法读取了起诉状，**也没有真正传入 LLM**。

### 4.4 `DraftingSkill` 同样忽略传入的上下文

[`skill.py:121-142`](backend/agents/v2/skill.py#L121-L142)
```python
async def execute(self, agent, context: dict):
    doc_type = context.get("doc_type", "complaint")
    materials = context.get("materials", "")
    task = f"请{templates[doc_type]}\n\n【参考材料】\n{materials}\n\n要求：..."
```

`DraftingSkill` 确实使用了 `materials`，所以被告 `draft_answer` 中传入的 `materials`（含起诉状和答辩策略）**确实进入了 LLM**。这是少数工作正常的路径。

但原告 `draft_complaint` 传入的 `materials` 只有 `phase1_analysis + claims + evidence`，没有问题。

核心问题是：**strategy 没有被注入**。起诉状/答辩状生成时，Agent 的 `memory.private.strategy` 虽然存在，但 `_call_llm` 不注入 `memory.build_context()`，所以 LLM 看不到策略。

---

## 五、策略动态调整：完全未接线

[`base.py:228`](backend/agents/v2/base.py#L228)
```python
async def adapt_strategy(self, new_event: AgentMessageV2, judge_guidance=None) -> LitigationStrategy:
    updated = await self.strategy_engine.adapt(current, new_event, judge_guidance, self.system_prompt)
    self.memory.private.strategy = updated
    return updated
```

**全项目搜索**：没有任何代码调用 `adapt_strategy()`。

[`strategy.py:73-111`](backend/agents/v2/strategy.py#L73-L111) `adapt()` 方法虽然实现了，但从未被触发。

**后果**：策略一旦在 Phase 1/3 制定完成，就是**静态的**。后续庭审中对方的新主张、法官的指引、交叉询问中暴露的弱点，都**不会触发策略更新**。

---

## 六、其他发现

### 6.1 `send_peer` 和 `send_private_to_judge` 从未被业务代码调用

[`base.py:197`](backend/agents/v2/base.py#L197) `send_peer()` 和 [`base.py:203`](backend/agents/v2/base.py#L203) `send_private_to_judge()` 只存在于基类中。所有 workflow 中的消息发送都是直接构造 `AgentMessageV2` + `channel.dispatch()`，没有使用 Agent 自身的封装方法。

这本身不是 bug，但说明 Agent 的"主动通信能力"（封装方法）没有被利用，通信完全由 workflow  orchestrator 控制。

### 6.2 `history` 记录不完整

[`base.py:119-122`](backend/agents/v2/base.py#L119-L122)
```python
# 记录到私有记忆
self.memory.private.history.append({"role": "user", "content": task})
self.memory.private.history.append({"role": "assistant", "content": response})
```

这段代码只在 `think()` 中执行。`think_with_skill()` 的调用结果**不记录到 history**。由于几乎所有核心文书都通过 `think_with_skill` 生成，history 实际上是一个**残缺不全的日志**，无法用于 LLM 上下文回溯。

### 6.3 `_sync_state_to_memory` 是兼容性补丁而非架构设计

[`workflow_v2.py:144-253`](backend/orchestration/workflow_v2.py#L144-L253) `_sync_state_to_memory` 将 `TrialState` 中的字符串字段回填到 Agent 的 `shared memory`。注释明确写了"兼容旧数据"。

这意味着：在理想的多 Agent 架构中，Agent 应该通过自己的 `publish()` 将文书放入 shared，而不需要外部 orchestrator 事后同步。当前设计是为了兼容 V1 的扁平 state 结构，但这也暴露了**Agent 不是自驱动的**，需要 orchestrator 不断帮它"补记忆"。

---

## 七、修复建议（按优先级排序）

### 🔴 P0：修复 Skill 层 memory context 注入

**问题**：`_call_llm` 不注入 memory，导致所有 Skill 执行盲打。

**方案**：修改 `_call_llm`，在调用 LLM 前注入 `agent.memory.build_context()`：

```python
async def _call_llm(self, agent, task, *, temperature=0.3, max_tokens=4096):
    memory_ctx = agent.memory.build_context(include_private=True)
    messages = [{"role": "system", "content": f"【你的记忆与材料】\n{memory_ctx}"}]
    messages.append({"role": "user", "content": task})
    # ... 调用 llm_call / llm_call_stream
```

**影响面**：所有 Skill 的生成质量会显著提升，策略、对方文书、历史记录将真正生效。

### 🔴 P0：修复 Phase 7 被告最后陈述的上下文

**方案**：修改 `defendant.final_statement()`，从 `memory.shared` 读取原告陈述并传入 materials：

```python
async def final_statement(self, case_title: str, claims: str) -> str:
    pf_docs = self.memory.shared.get_by_phase(7)
    pf_statement = "\n".join(d.content for d in pf_docs if d.sender == "plaintiff")
    materials = f"案由：{case_title}\n原告诉讼请求：{claims}\n\n原告最后陈述：\n{pf_statement}"
    return await self.think_with_skill("drafting", {
        "doc_type": "statement", "materials": materials,
    })
```

### 🟡 P1：修复 `LegalResearchSkill.execute` 忽略 `context` 参数

[`skill.py:82-98`](backend/agents/v2/skill.py#L82-L98) 应将 `context.get("context", "")` 注入 task。

### 🟡 P1：让 Phase 6 Agent 真正消费 inbox

**方案**：修改 `cross_exam_answer()`，使其从 `memory.consume_inbox("question")` 读取问题，而非接收参数。workflow 层不再传参，只负责触发 Agent 思考：

```python
async def cross_exam_answer(self) -> str:
    questions = self.memory.consume_inbox("question")
    if not questions:
        return "（无问题需要回答）"
    question = questions[-1].content
    return await self.think_with_skill("cross_exam", {
        "mode": "answer", "target": question,
    })
```

### 🟡 P1：接入策略动态调整

在 Phase 6 每轮结束后、Phase 7 开始前，调用 `agent.adapt_strategy()`，传入对方的最新主张或法官指引。

### 🟢 P2：统一 `think_with_skill` 的 history 记录

在 `think_with_skill` 返回后，将 task + result 追加到 `memory.private.history`，保证历史完整性。

### 🟢 P2：`_call_llm` 应复用 `agent.think()` 而非独立调用 LLM

更根本的修复是：让 Skill 的 execute 调用 `agent.think(task)` 而非直接调用 `llm_call`。这样自动获得流式、history 记录、memory context 注入等全部能力。

---

## 八、附录：代码引用速查

| 引用点 | 文件 | 行号 | 说明 |
|--------|------|------|------|
| 独立 Agent 实例化 | workflow_v2.py | 70-72 | plaintiff/defendant/judge 分别 new |
| 独立 MemoryBank | base.py | 54 | self.memory = MemoryBank() |
| inbox 唯一消费点 | defendant.py | 67 | `consume_inbox("document")` 回退 |
| Phase 6 消息 dispatch | workflow_v2.py | 614 | channel.dispatch(msg_q) |
| Phase 6 参数旁路 | workflow_v2.py | 629 | `defendant.cross_exam_answer(q_text)` |
| Phase 7 被告盲打 | workflow_v2.py | 943 | `defendant.final_statement(case.case_title, case.claims)` 无原告陈述 |
| Skill 不注入 memory | skill.py | 45 | `messages=[{"role":"user","content":task}]` |
| think() 注入 memory | base.py | 335-346 | `_build_messages` 调用 `memory.build_context()` |
| adapt_strategy 未调用 | — | — | 全项目无调用点 |
| history 只记录 think() | base.py | 119-122 | think_with_skill 不记录 |

---

*报告结束。如需对某项发现进行更深入的代码走读或提供修复 PR，请指示。*
