# 跨阶段记忆传递修复报告

> 修复时间：2026-06-08  
> 相关文档：[`CROSS_PHASE_MESSAGE_FIX_PLAN.md`](../CROSS_PHASE_MESSAGE_FIX_PLAN.md)、[`AGENT_MEMORY_AUDIT_REPORT.md`](../AGENT_MEMORY_AUDIT_REPORT.md)  
> 影响范围：P6 → P7 的记忆传递、最后陈述质量、举证质证 inbox 机制

---

## 一、背景与问题发现

在 2026-06-08 的 Agent Memory 审计中，我们发现 moot-court V2 Agent 的跨阶段消息传递存在严重断裂：庭审最激烈的 Phase 6（交叉询问、举证质证）产生的交锋记录，**无法被 Phase 7（最后陈述）感知到**。

这导致双方最后陈述变成了"基于起诉状和答辩状的静态总结"，而不是"回应当庭暴露的新矛盾、证据弱点和对方言辞漏洞"，直接削弱了庭审真实感和判决说服力。

### 1.1 消息流转全景

```
P1 原告策略分析 ──publish──→ shared ✅
                            │
P2 原告起诉状+证据目录 ──publish──→ shared ✅
                            │
P3 被告抗辩策略 ──publish──→ shared ✅
                            │
P4 被告答辩状+证据目录 ──publish──→ shared ✅
                            │
P5 法官争议焦点 ──publish──→ shared ✅
                            │
P6 交叉询问 ──peer──→ inbox ──consume──→ 丢失 ❌
   举证质证 ──peer──→ inbox ──consume──→ 丢失 ❌
   法官引导/ruling ──public──→ shared ✅
                            │
P7 双方最后陈述 ──public──→ shared ✅
                            │
P8 法官判决 ←──shared── 正常 ✅
```

### 1.2 阶段判定

| 传递路径 | 状态 | 根因 |
|---------|------|------|
| P2 原告文书 → P3 被告策略 | ✅ 通 | `publish` 进 shared，被告 `analyze_defense` 读 `shared.get_by_phase(2)` |
| P3 被告策略 → P4 被告答辩状 | ✅ 通 | 被告 `draft_answer` 读 `shared.get_by_phase(3)` |
| P4 被告答辩状 → P5/P6 原告 | ⚠️ 半通 | `build_context()` 能看到，但 workflow 层仍直接传参 |
| **P6 交叉询问/质证 → P7 最后陈述** | ❌ **断裂** | peer 消息被 `consume_inbox()` 后只进 `private.consumed_messages`，`build_context()` **不读取**该字段；P7 node **未调用** `_sync_state_to_memory`，Phase 6 整体记录未进入 P7 Agent shared memory |
| P6 法官引导 → P7 双方 | ⚠️ 半通 | public 进 shared，`build_context()` 能看到，但 `final_statement` 未主动引用 |
| P7 双方陈述 → P8 法官 | ✅ 通 | public 进 shared，`_sync_state_to_memory` 同步 |
| **策略隔离（法官不读策略）** | ✅ 正确 | 所有 strategy 产物均在 `private` 层，未 publish |

---

## 二、根因分析

### 2.1 核心设计缺陷：consume 后成为"记忆黑洞"

`MemoryBank.consume_inbox()` 在消费消息后的行为：

```python
for m in matched:
    self.inbox.remove(m)
    self.private.consumed_messages.append(m)  # 仅归档到 consumed_messages
```

问题：`build_context()` 读取了 `private.strategy_notes`、`private.fact_timeline`、`shared.documents`、`inbox`，但**从来不读 `private.consumed_messages`**。

这导致所有 `consume_inbox()` 处理过的 peer 消息（P6 的问题、回答、质证意见）对 LLM 不可见。

### 2.2 P7 node 缺少 `_sync_state_to_memory`

其他 phase 切换节点（P3、P4、P5、P8）都会调用 `_sync_state_to_memory(agent, state)` 将 `TrialState` 中的字符串字段同步回 Agent 的 `shared memory`，但 `phase7_node_v2()` **漏掉了这一步**。

结果：即使 `build_context()` 能读 `shared.get_by_phase(6)`，P7 开始时 shared 里也没有 Phase 6 的整体记录（`phase6_cross_exam`、`phase6_evidence_exam`）。

### 2.3 `final_statement()` 内容空洞

原实现只传入案由和诉讼请求：

```python
async def final_statement(self, case_title: str, claims: str) -> str:
    return await self.think_with_skill("drafting", {
        "doc_type": "statement",
        "materials": f"案由：{case_title}\n诉讼请求：{claims}",
    })
```

虽然 `_call_llm()` 会注入 memory context，但 `materials` 里没有明确要求回应当庭交锋，LLM 也没有主动读取庭审记录的意识，导致最后陈述干瘪。

### 2.4 举证质证仍使用函数参数传参

被告 `cross_examine_evidence(evidence, plaintiff_comment, context)` 的 `plaintiff_comment` 由 workflow 直接传入，没有走 inbox。

这与交叉询问 `cross_exam_answer()` 的 inbox 化改造不一致，也使得被告 Agent 无法从 memory 层面感知"收到的举证说明"。

---

## 三、修复方案与实现

共 5 个修复点，实施顺序按依赖关系排列：

### 修复点 1：peer 消息消费后归档到 `fact_timeline`

**文件**：`backend/agents/v2/memory.py`

在 `consume_inbox()` 中，消费 P6 的 `question`/`answer`/`evidence_opinion` 消息后，追加到 `private.fact_timeline`：

```python
for m in matched:
    self.inbox.remove(m)
    self.private.consumed_messages.append(m)
    # 关键庭审互动自动归档到事实时间线，确保 P6 交锋记录能被 P7 最后陈述看到
    if m.phase == 6 and m.content_type in ("question", "answer", "evidence_opinion"):
        self.private.fact_timeline += f"\n\n[{m.sender}] {m.content_type}:\n{m.content[:500]}"
```

**作用**：`build_context()` 本来就会读取 `fact_timeline`，P6 交锋记录因此自然流入 P7 上下文。

---

### 修复点 2：`build_context()` 增加 `consumed_messages` 兜底

**文件**：`backend/agents/v2/memory.py`

在 `build_context()` 末尾增加近期已消费关键消息的摘要：

```python
# 兜底：近期已消费的关键 peer 消息（防止 P6 交锋记录遗漏）
recent_consumed = [
    m for m in self.private.consumed_messages[-5:]
    if m.phase == 6 and m.content_type in ("question", "answer", "evidence_opinion")
]
if recent_consumed:
    msgs = "\n\n".join(
        f"[{m.sender}] {m.content_type}: {m.content[:300]}"
        for m in recent_consumed
    )
    parts.append(f"【近期交锋记录】\n{msgs}")
```

**作用**：双重保险。即使 `fact_timeline` 归档逻辑遗漏某类消息，`consumed_messages` 也能兜底。

---

### 修复点 3：P7 node 调用 `_sync_state_to_memory`

**文件**：`backend/orchestration/workflow_v2.py` — `phase7_node_v2`

在生成最后陈述前补全 P6 记录同步：

```python
try:
    # 同步 Phase 6 庭审记录到双方 memory，确保最后陈述能看到完整庭审上下文
    _sync_state_to_memory(plaintiff, state)
    _sync_state_to_memory(defendant, state)

    # Step 1: 原告最后陈述
    pf = await plaintiff.final_statement(case.case_title, case.claims)
    ...
```

**作用**：`shared.get_by_phase(6)` 现在包含 `phase6_cross_exam` 和 `phase6_evidence_exam` 的整体记录。

---

### 修复点 4：`final_statement()` 主动读取全部历史材料

**文件**：`backend/agents/v2/plaintiff.py`、`backend/agents/v2/defendant.py`

重写 `final_statement()`，从 memory 组装完整上下文：

```python
async def final_statement(self, case_title: str, claims: str) -> str:
    complaint = "\n".join(d.content for d in self.memory.shared.get_by_phase(2))
    answer = "\n".join(d.content for d in self.memory.shared.get_by_phase(4))
    issues = "\n".join(d.content for d in self.memory.shared.get_by_phase(5))
    cross_exam_log = self.memory.private.fact_timeline
    strategy_notes = self.memory.private.strategy_notes

    materials = f"""案由：{case_title}
诉讼请求：{claims}

【原告起诉状】
{complaint[:1500]}

【被告答辩状】
{answer[:1500]}

【争议焦点】
{issues[:1000]}

【庭审交锋记录】
{cross_exam_log[:2000]}

【内部策略笔记】
{strategy_notes[:1000]}
"""
    return await self.think_with_skill("drafting", {
        "doc_type": "statement",
        "materials": materials,
    })
```

原被告使用相同结构，仅视角不同。

**作用**：LLM 在最后陈述时明确看到起诉状、答辩状、争议焦点、P6 交锋、策略笔记，能针对性地总结和反驳。

---

### 修复点 5：举证质证 `cross_examine_evidence` 改为 inbox 消费

**文件**：`backend/agents/v2/defendant.py`、`backend/orchestration/workflow_v2.py`

被告 `cross_examine_evidence()` 改为从 inbox 读取原告 comment：

```python
async def cross_examine_evidence(self, evidence: str, context: str) -> str:
    """Phase 6: 被告对原告证据发表质证意见（从 inbox 读取原告举证说明）"""
    inbox_comments = self.memory.consume_inbox("evidence_opinion")
    plaintiff_comment = ""
    for m in inbox_comments:
        if m.evidence_ref == evidence or evidence in m.content:
            plaintiff_comment = m.content
            break
    if not plaintiff_comment:
        plaintiff_comment = "（未收到原告举证说明）"

    task = f"""请对以下证据发表质证意见。

【证据内容】{evidence}
【原告举证说明】{plaintiff_comment[:500]}
【庭审背景】{context[:1000]}
..."""
    return await self.think(task)
```

Workflow 层对应调用同步更新：

```python
# 修改前：
# d_text = await _retry_async(defendant.cross_examine_evidence, 2, evidence_item, p_text, context)

# 修改后：
d_text = await _retry_async(defendant.cross_examine_evidence, 2, evidence_item, context)
```

**作用**：与交叉询问 inbox 改造保持一致，被告 Agent 从 memory 层面感知原告举证说明。

---

## 四、修改文件汇总

| 文件 | 修改类型 | 修复点 |
|------|---------|--------|
| `backend/agents/v2/memory.py` | 改方法 | 1, 5 |
| `backend/orchestration/workflow_v2.py` | 改 phase 节点、改调用 | 3, 4 |
| `backend/agents/v2/plaintiff.py` | 改方法 | 2 |
| `backend/agents/v2/defendant.py` | 改方法签名与实现 | 2, 4 |

---

## 五、验证

### 5.1 语法编译

```bash
py -m py_compile backend/agents/v2/memory.py backend/agents/v2/plaintiff.py backend/agents/v2/defendant.py backend/orchestration/workflow_v2.py
# 输出: all clean
```

### 5.2 旧签名残留检查

全项目 grep `cross_examine_evidence` 仅返回：

- `defendant.py:147` — 新签名定义
- `workflow_v2.py:861` — 新签名调用

无其他旧签名调用残留。

### 5.3 运行时验证建议

在 P7 调用 `final_statement` 前打印上下文：

```python
ctx = plaintiff.memory.build_context()
print(ctx)
# 应包含：
# - 内部策略笔记
# - 案件大事记（含 P6 交锋）
# - 已公开文书
# - 近期交锋记录（consumed_messages 兜底）
```

同时检查被告最后陈述中是否出现对原告当庭言辞的回应。

---

## 六、设计原则与约束保持

### 6.1 法官策略隔离仍然有效

- 原被告策略通过 `formulate_strategy()` 写入 `memory.private.strategy`，**从未 publish**
- 法官 `render_judgment()` 读取 `shared.get_by_phase(2/4/5/6/7)`，均为 public 消息
- 本次修复**没有**将任何 private 策略字段暴露给法官

### 6.2 Memory Bank 三层结构未被破坏

- `private` 层仍仅本 Agent 可访问
- `shared` 层仍需显式 `publish()` 或 `_sync_state_to_memory()` 同步
- `inbox` 仍需显式 `consume_inbox()` 消费
- 本次修复强化了"消费后归档"的规则，而非破坏分层

---

## 七、后续可优化方向

1. **P6 交锋记录摘要化**：当前是直接拼接原始消息到 `fact_timeline`。后续可引入一个 LLM 摘要步骤，生成"庭审争议要点"，控制上下文长度。
2. **原被告 `cross_exam_question` 主动读取 memory**：当前仍由 workflow 直接传 `context`。未来可改为 Agent 主动从 memory 读取被告答辩状、争议焦点，设计更有针对性的问题。
3. **Judge memory 的 build_context 启用**：法官当前多走 `think()` 而非 `think_with_skill()`，`_call_llm()` 修复后，可考虑让法官也走 `think_with_skill()`，自动注入 shared memory 上下文。
4. **增加回归测试**：建议为 P6→P7 的记忆传递增加单元测试，断言 `build_context()` 输出中包含预期的交锋关键词。
