# 跨阶段消息传递审计与修复方案

## 一、审计结论

### 消息流转全景图

```
P1 原告策略分析 ──publish──→ shared ✅
                            │
P2 原告起诉状+证据目录 ──publish──→ shared ✅
                            │
P3 被告抗辩策略 ──publish──→ shared ✅（被告内部流转正常）
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

### 逐阶段判定

| 传递路径 | 状态 | 根因 |
|---------|------|------|
| P2 原告文书 → P3 被告策略 | ✅ 通 | `publish` 进 shared，被告 `analyze_defense` 读 `shared.get_by_phase(2)` |
| P3 被告策略 → P4 被告答辩状 | ✅ 通 | 被告 `draft_answer` 读 `shared.get_by_phase(3)` |
| P4 被告答辩状 → P5/P6 原告 | ⚠️ 半通 | `build_context()` 能看到，但 `cross_exam_question` 的 `context` 由 workflow 直接拼接 `_phase_context(state)` 传入，Agent 未主动从 memory 读取 |
| P6 交叉询问/质证 → P7 最后陈述 | ❌ **断裂** | peer 消息被 `consume_inbox()` 后移入 `private.consumed_messages`，`build_context()` **不读取** consumed_messages；P7 node **未调用** `_sync_state_to_memory`，Phase 6 整体记录未进入 P7 Agent 的 shared |
| P6 法官引导 → P7 双方 | ⚠️ 半通 | guidance/ruling 是 public 进 shared，`build_context()` 能看到，但 `final_statement` 未主动引用 |
| P7 双方陈述 → P8 法官 | ✅ 通 | public 进 shared，`_sync_state_to_memory` 同步，法官 `render_judgment` 读 shared |
| **策略隔离** | ✅ 正确 | 所有 `strategy_notes`、`formulate_strategy` 产出均在 `private` 层，未 publish，对方与法官均不可见 |

### 最严重问题：P6 → P7 的"记忆黑洞"

Phase 6 交叉询问和举证质证是庭审最激烈的对抗环节。但：
- 原告设计的刁钻问题、被告的回答策略 → **consume 后只躺在 `consumed_messages` 里**
- 被告对原告证据的质证意见、原告的举证说明 → **consume 后同样丢失**
- `_sync_state_to_memory` 在 P7 node **未被调用**，`phase6_cross_exam` / `phase6_evidence_exam` 这两个整体记录 **没有同步到 P7 Agent 的 shared memory**

导致 Phase 7 `final_statement` 生成时，LLM 的上下文中**完全看不到 Phase 6 的任何内容**。最后陈述变成了"基于起诉状和答辩状的静态总结"，而不是"回应庭审中暴露的新矛盾、新证据弱点"。

---

## 二、修复方案

### 原则
1. **公开言词/文书进 shared**，通过 `build_context()` 自然流入后续阶段
2. **peer 消息 consume 后必须归档到可检索的 private 字段**（而非只放 `consumed_messages`）
3. **Agent 方法主动从 memory 读取材料**，减少 workflow 层直接传参
4. **P7 最后陈述必须能看到 P6 完整庭审记录**

---

### 修复点 1：peer 消息消费后归档到 `fact_timeline`（P6 → P7 可见）

**文件**: `backend/agents/v2/memory.py`

修改 `consume_inbox()`，在消费消息后，自动将消息内容追加到 `private.fact_timeline`：

```python
def consume_inbox(self, tag: str = "") -> list[AgentMessageV2]:
    ...
    for m in matched:
        self.inbox.remove(m)
        self.private.consumed_messages.append(m)
        # 新增：关键庭审互动自动归档到事实时间线
        if m.phase == 6 and m.content_type in ("question", "answer", "evidence_opinion"):
            self.private.fact_timeline += f"\n\n[{m.sender}] {m.content_type}:\n{m.content[:500]}"
    return matched
```

**作用**：`build_context()` 本来就会读取 `fact_timeline`，这样 P7 的 `_call_llm` 注入上下文时，LLM 能看到双方在 P6 的交锋要点。

---

### 修复点 2：P7 最后陈述主动读取全部历史材料

**文件**: `backend/agents/v2/plaintiff.py`、`backend/agents/v2/defendant.py`

当前 `final_statement(case_title, claims)` 只接收标题和请求，内容空洞。

**原告 `final_statement` 应组装**：
- 自己的起诉状（`shared.get_by_phase(2)`）
- 被告答辩状（`shared.get_by_phase(4)`）
- 争议焦点（`shared.get_by_phase(5)`）
- 庭审交锋记录（`private.fact_timeline` 已包含 P6 内容）
- 自己的策略笔记（`private.strategy_notes`）

**被告 `final_statement` 应组装**：
- 原告起诉状（`shared.get_by_phase(2)`）
- 自己的答辩状（`shared.get_by_phase(4)`）
- 争议焦点（`shared.get_by_phase(5)`）
- 庭审交锋记录（`private.fact_timeline`）
- 自己的策略笔记（`private.strategy_notes`）

```python
async def final_statement(self, case_title: str, claims: str) -> str:
    complaint = "\n".join(d.content for d in self.memory.shared.get_by_phase(2))
    answer = "\n".join(d.content for d in self.memory.shared.get_by_phase(4))
    issues = "\n".join(d.content for d in self.memory.shared.get_by_phase(5))
    cross_exam_log = self.memory.private.fact_timeline

    materials = f"""案由：{case_title}
原告诉讼请求：{claims}

【原告起诉状】
{complaint[:1500]}

【被告答辩状】
{answer[:1500]}

【争议焦点】
{issues[:1000]}

【庭审交锋记录】
{cross_exam_log[:2000]}
"""
    return await self.think_with_skill("drafting", {
        "doc_type": "statement",
        "materials": materials,
    })
```

**注意**：被告方法里的 `complaint` 和 `answer` 与原告方法互换视角，但结构相同。

---

### 修复点 3：P7 node 调用 `_sync_state_to_memory` 补齐 P6 记录

**文件**: `backend/orchestration/workflow_v2.py` — `phase7_node_v2`

在 P7 开始前，像 P3/P4/P5/P8 一样调用 `_sync_state_to_memory`，确保 Phase 6 的整体庭审记录进入双方 Agent 的 shared：

```python
async def phase7_node_v2(state: TrialState) -> TrialState:
    ...
    try:
        # 新增：同步 P6 记录到双方 memory
        _sync_state_to_memory(plaintiff, state)
        _sync_state_to_memory(defendant, state)

        pf = await plaintiff.final_statement(case.case_title, case.claims)
        ...
```

这样 `shared.get_by_phase(6)` 能取到 `phase6_cross_exam` 和 `phase6_evidence_exam` 的整体记录，作为 `final_statement` 的补充材料。

---

### 修复点 4：举证质证环节 defendant 从 inbox 读取原告 comment

**文件**: `backend/agents/v2/defendant.py`、`backend/orchestration/workflow_v2.py`

当前 `defendant.cross_examine_evidence(evidence, plaintiff_comment, context)` 的 `plaintiff_comment` 是 workflow 直接传参。

改为 inbox 消费：
```python
async def cross_examine_evidence(self, evidence: str, context: str) -> str:
    # 从 inbox 读取原告对该证据的举证说明
    inbox_comments = self.memory.consume_inbox("evidence_opinion")
    plaintiff_comment = ""
    for m in inbox_comments:
        if m.evidence_ref == evidence or evidence in m.content:
            plaintiff_comment = m.content
            break
    if not plaintiff_comment:
        plaintiff_comment = "（未收到原告举证说明）"

    task = f"""请对以下证据发表质证意见...
【证据内容】{evidence}
【原告举证说明】{plaintiff_comment[:500]}
..."""
    return await self.think(task)
```

**workflow 层** 对应调用处去掉 `p_text` 参数：
```python
# 原：d_text = await _retry_async(defendant.cross_examine_evidence, 2, evidence_item, p_text, context)
# 改为：
d_text = await _retry_async(defendant.cross_examine_evidence, 2, evidence_item, context)
```

（注：原告 `comment_on_evidence` 是主动举证方，无需改 inbox 消费。）

---

### 修复点 5：`build_context()` 增加 `consumed_messages` 读取（兜底）

**文件**: `backend/agents/v2/memory.py`

即使 `fact_timeline` 已归档，为防遗漏，在 `build_context()` 末尾增加近期 consumed messages 的摘要：

```python
def build_context(self, include_private: bool = True) -> str:
    ...
    # 新增：最近消费的关键消息（兜底）
    recent_consumed = [
        m for m in self.private.consumed_messages[-5:]
        if m.phase == 6 and m.content_type in ("question", "answer", "evidence_opinion")
    ]
    if recent_consumed:
        msgs = "\n\n".join(f"[{m.sender}] {m.content_type}: {m.content[:300]}" for m in recent_consumed)
        parts.append(f"【近期交锋记录】\n{msgs}")

    return "\n\n---\n\n".join(parts)
```

---

## 三、法官视角的隔离性确认

用户特别要求：**法官只能看到公开言词和文书，不能看到双方策略分析**。

当前实现已满足：
- 原告/被告的策略通过 `formulate_strategy()` 写入 `memory.private.strategy`，**从未 publish**
- 原告的 Phase 1 分析虽然 `publish` 了（`plaintiff.publish(result, "document", phase=1)`），但这是请求权基础分析的**公开产出**，不是策略细节
- 被告的 Phase 3 分析同理
- 法官 `render_judgment()` 读取 `shared.get_by_phase(2/4/5/6/7)`，全是 public 消息
- 法官的 `build_context()` 如果启用（目前法官方法多走 `think()` 而非 `think_with_skill()`，但 `_call_llm` 修复后也走 `think_with_skill`），其 private 层只有法官自己的笔记，不包含双方策略

**结论**：策略隔离是正确的，无需修改。

---

## 四、实施顺序

建议按以下顺序实施，每个修复点可独立验证：

1. **修复点 1**（`memory.py` consume 归档）+ **修复点 5**（`build_context` 兜底）
   - 影响最小，立刻让 P6 peer 消息在 P7 可见
2. **修复点 3**（P7 node 同步 `_sync_state_to_memory`）
   - 补齐 P6 整体记录
3. **修复点 2**（`final_statement` 主动读材料）
   - 最后陈述质量提升最直观
4. **修复点 4**（举证质证 inbox 消费）
   - 与之前的交叉询问 inbox 改造保持一致

---

## 五、验证方式

每个修复点实施后，可通过检查 `build_context()` 的输出来验证：

```python
# 在 P7 调用 final_statement 前，打印上下文
ctx = plaintiff.memory.build_context()
print(ctx)
# 应包含：
# - 策略笔记（private）
# - 已公开文书（shared phase 2/4/5/6/7）
# - 庭审交锋记录（fact_timeline / consumed_messages）
```
