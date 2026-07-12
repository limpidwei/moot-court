# 证据约束框架后续迭代方案

> 日期：2026-06-08
> 范围：P3 对抗强度滑块 + 自动化回归测试 + FactExtractor 升级

---

## 一、对抗强度滑块（P3）

### 1.1 需求概述

用户在创建案件时可选择 AI 被告的"对抗强度"（1-5 级），控制其编造证据的激进程度：
- **强度 1-2（保守）**：AI 被告较弱，几乎不编造证据，主要依赖对现有事实的合理解释和抗辩
- **强度 3（平衡）**：当前默认行为，允许编造聊天记录和证人证言，但禁止书证/合同等关键文件
- **强度 4-5（激进）**：AI 被告较强，允许更多类型的对抗性证据，但仍在约束框架内（不违反事实锁）

### 1.2 后端改动

#### 1.2.1 数据模型（2 个文件）

**`backend/models/case.py`** —— `CaseInput` 新增字段：
```python
@dataclass
class CaseInput:
    # ... 现有字段 ...
    adversarial_intensity: int = 3   # 1-5，默认 3（平衡）
```

**`backend/main.py`** —— `CreateCaseRequest` 新增字段：
```python
class CreateCaseRequest(BaseModel):
    # ... 现有字段 ...
    adversarial_intensity: int = 3
```

创建案件时校验范围：`1 <= adversarial_intensity <= 5`，超出范围自动 clamp。

#### 1.2.2 约束构建器（1 个文件）

**`backend/agents/v2/evidence_constraint.py`** —— `EvidenceConstraintBuilder` 接收 `intensity`：

```python
class EvidenceConstraintBuilder:
    def __init__(self, case_type: str = "", intensity: int = 3):
        self.case_type = _normalize_case_type(case_type)
        self.intensity = max(1, min(5, intensity))

    def build_prompt(self, fact_lock: FactLock) -> str:
        # ... 现有事实锁 + 禁止事项 ...

        # 根据 intensity 动态调整白名单
        whitelist = self._get_whitelist()
        # ...

        # 根据 intensity 调整对抗性语言要求
        intensity_notes = self._intensity_notes()
        lines.append(intensity_notes)
```

**白名单动态调整规则（以借款合同纠纷为例）**：

| 强度 | 允许编造的证据类型 | 禁止编造的证据类型 |
|-----|------------------|------------------|
| 1-2 | 单方书面说明、对现有聊天记录的不同解读 | 证人证言、项目资料、任何新聊天记录 |
| 3 | 聊天记录、证人证言、项目资料、单方记录 | 银行还款凭证、书面借条/合同 |
| 4 | 上述全部 + 会议纪要复印件、往来函件复印件 | 银行还款凭证、国家机关书证 |
| 5 | 上述全部 + 被告声称已发送但被否认的通知/函件 | 银行还款凭证 |

**`ConsistencyChecker` 严格度调整**：
- `intensity <= 2`：时间红线检查更严格（任何早于最早日期的电子数据也判矛盾）
- `intensity >= 4`：时间红线略微放宽（仅书证/协议/合同判矛盾，聊天记录可接受早于最早日期几天）

#### 1.2.3 工作流（1 个文件）

**`backend/orchestration/workflow_v2.py`** —— Phase 4 调用时传入 intensity：
```python
# 第 483 行附近
intensity = getattr(state["case_input"], "adversarial_intensity", 3)
catalog = await defendant.draft_evidence_catalog(
    state["case_input"].evidence,
    case_input=state["case_input"],
    intensity=intensity,
)
```

**`backend/agents/v2/defendant.py`** —— `draft_evidence_catalog` 接收 `intensity`：
```python
async def draft_evidence_catalog(
    self, evidence: str, case_input=None, intensity: int = 3
) -> str:
    # ...
    builder = EvidenceConstraintBuilder(case_type, intensity=intensity)
    # ...
```

### 1.3 前端改动

#### 1.3.1 API 客户端（1 个文件）

**`frontend-next/src/lib/api.ts`** —— `createCase` 参数新增：
```typescript
export async function createCase(data: {
  case_title: string;
  facts: string;
  evidence: string;
  claims: string;
  mode?: string;
  user_side?: string;
  user_strategy_hint?: string;
  source_materials?: string;
  adversarial_intensity?: number;   // 新增
  llm_config?: LLMConfig;
}) { ... }
```

#### 1.3.2 案件创建页（1 个文件）

**`frontend-next/src/app/case/new/page.tsx`** —— 在"模式选择"区域下方增加对抗强度选择器：

```tsx
// 新增 state
const [adversarialIntensity, setAdversarialIntensity] = useState(3);

// UI 组件（在单方对抗模式下显示）
{mode === "asymmetric" && userSide && (
  <div className="mt-4">
    <label className="block text-sm font-semibold text-gray-700 mb-2">
      AI 对手对抗强度
    </label>
    <div className="flex items-center gap-4">
      <span className="text-xs text-gray-500">保守</span>
      <input
        type="range"
        min={1}
        max={5}
        step={1}
        value={adversarialIntensity}
        onChange={(e) => setAdversarialIntensity(Number(e.target.value))}
        className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
      />
      <span className="text-xs text-gray-500">激进</span>
    </div>
    <div className="flex justify-between text-xs text-gray-400 mt-1 px-1">
      <span>1</span><span>2</span><span>3</span><span>4</span><span>5</span>
    </div>
    <p className="text-xs text-gray-500 mt-2">
      {adversarialIntensity <= 2 && "AI 对手较弱，主要依赖事实解释，几乎不编造新证据"}
      {adversarialIntensity === 3 && "AI 对手适中，允许编造聊天记录和证人证言"}
      {adversarialIntensity >= 4 && "AI 对手较强，允许更多类型的对抗性证据"}
    </p>
  </div>
)}
```

提交时把 `adversarial_intensity` 加入 payload（仅单方对抗模式有效，中立模式固定为 3）。

### 1.4 验收标准
- [ ] 前端滑块在单方对抗模式下可见，中立模式下隐藏
- [ ] 后端接收并持久化 `adversarial_intensity`
- [ ] 强度 1-2 时，被告证据目录中不出现证人证言和项目资料
- [ ] 强度 4-5 时，被告证据目录中可出现会议纪要复印件等扩展类型
- [ ] 所有强度下，事实锁硬约束仍然生效（已还款凭证、早于最早日期的书证仍被拦截）

---

## 二、自动化回归测试

### 2.1 目标
用 mock LLM 验证约束模块在各种边界情况下的行为，确保后续代码变更不会破坏约束效果。

### 2.2 测试文件

**`tests/test_evidence_constraint.py`**（新建）

### 2.3 测试场景

```
test_01_fact_extractor_basic          # 规则提取能正确提取时间、主体、行为事实
test_02_prohibited_repayment          # 输入"被告未还款"，输出不含还款凭证
test_03_pre_date_document_blocked     # 输入最早日期 2023-03-01，验证不含 2023-02-20 的合同
test_04_chain_integrity               # 投资款抗辩必须有三组证据（合意+项目+风险）
test_05_source_description_required   # 验证每项证据有具体来源，无"相关记录"等模糊表述
test_06_entity_consistency            # 编造证据中的当事人名称与案件一致
test_07_post_filter_safety_net        # 验证 _post_filter_evidence 能删除残留的禁止类型
test_08_correction_delete_only        # 验证修正不会引入新证据或改变策略
test_09_low_intensity_restricted      # intensity=1 时，证据类型严格受限
test_10_high_intensity_extended       # intensity=5 时，允许更多对抗性证据
test_11_time_redline_chat_exempt      # 微信聊天记录早于最早日期，在强度 3 下不被拦截
test_12_time_redline_chat_blocked     # 微信聊天记录早于最早日期，在强度 1 下被拦截
```

### 2.4 Mock 策略

使用 `unittest.mock.patch` mock `llm_call`：

```python
@pytest.fixture
def mock_llm():
    with patch("backend.agents.v2.evidence_constraint.llm_call") as m:
        yield m

@pytest.fixture
def mock_skill_llm():
    with patch("backend.agents.v2.skill.llm_call") as m:
        yield m
```

**预设 LLM 返回**：
- `test_02`：模拟 LLM 返回含"2023-10-15 还款 2 万元银行转账记录"的目录，验证 `_post_filter_evidence` 将其删除
- `test_03`：模拟 LLM 返回含"2023-02-20 投资计划书"的目录，验证 `ConsistencyChecker` 判矛盾
- `test_08`：模拟修正轮次，验证修正后输出不含新证据

### 2.5 运行方式
```bash
py -m pytest tests/test_evidence_constraint.py -v
```

---

## 三、FactExtractor 升级（混合模式）

### 3.1 当前问题

规则提取（正则）存在以下局限：
1. **隐式主体**：材料中未显式标注"原告：张三"，只在叙述中提到"张三起诉李四"，正则可能漏提
2. **复合时间句**："2023 年 3 月 1 日签订合同，4 月 15 日交货"，正则提取为一条事实，但包含两个时间点
3. **间接行为**："经双方协商一致"隐含"协商"行为，但正则的关键词匹配可能遗漏

### 3.2 方案：混合模式（推荐）

保留规则提取的速度优势，用轻量级 LLM 调用做审查和补全。

#### 3.2.1 新增类

**`backend/agents/v2/evidence_constraint.py`** —— 新增 `FactExtractorHybrid`：

```python
class FactExtractorHybrid(FactExtractor):
    """混合模式事实提取器：规则提取 + LLM 审查补全"""

    async def extract(self, case_input) -> FactLock:
        # 1. 规则提取（快速、低成本）
        base = super().extract(case_input)

        # 2. LLM 审查补全（仅当材料较长或规则提取结果较少时触发）
        raw_text = self._build_materials(case_input)
        if len(raw_text) < 100:
            return base  # 材料过短，规则提取足够

        prompt = f"""你是一名案件事实审查员。以下是从案件材料中用规则自动提取的事实清单，请审查是否有遗漏的重要客观事实，并补充。

【案件材料】
{raw_text[:2000]}

【已提取事实】
{base.to_prompt()}

【任务】
1. 审查已提取事实是否准确（是否误提取、是否遗漏）
2. 补充材料中明确提及但被遗漏的重要事实
3. 所有补充事实必须是材料中**明确存在**的，不得推断

【输出格式】严格输出 JSON，不要其他文字：
{{"time_facts": ["..."], "entity_facts": ["..."], "action_facts": ["..."], "document_facts": ["..."], "user_claims": ["..."], "prohibited_facts": ["..."]}}
"""
        result = await llm_call(
            system_prompt="你只输出 JSON，不输出任何解释文字。",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )

        # 解析 JSON（容错）
        try:
            import json, re
            json_match = re.search(r'\{{.*\}}', result, re.DOTALL)
            if json_match:
                enriched = json.loads(json_match.group(0))
                # 合并策略：规则提取 + LLM 补充，去重
                return self._merge_fact_locks(base, enriched)
        except Exception:
            pass

        return base

    def _merge_fact_locks(self, base: FactLock, enriched: dict) -> FactLock:
        def merge_list(existing: list[str], new: list[str]) -> list[str]:
            seen = set(existing)
            merged = list(existing)
            for item in new:
                if item not in seen:
                    merged.append(item)
                    seen.add(item)
            return merged

        return FactLock(
            time_facts=merge_list(base.time_facts, enriched.get("time_facts", [])),
            entity_facts=merge_list(base.entity_facts, enriched.get("entity_facts", [])),
            action_facts=merge_list(base.action_facts, enriched.get("action_facts", [])),
            document_facts=merge_list(base.document_facts, enriched.get("document_facts", [])),
            user_claims=merge_list(base.user_claims, enriched.get("user_claims", [])),
            prohibited_facts=merge_list(base.prohibited_facts, enriched.get("prohibited_facts", [])),
        )
```

#### 3.2.2 使用点切换

**`backend/agents/v2/defendant.py`**：
```python
from .evidence_constraint import FactExtractor, FactExtractorHybrid

async def draft_evidence_catalog(self, evidence: str, case_input=None, intensity: int = 3) -> str:
    fact_lock = None
    if case_input is not None:
        # 默认使用混合模式，未来可配置
        extractor = FactExtractorHybrid()
        fact_lock = await extractor.extract(case_input)
```

### 3.3 为什么不选纯 LLM 模式？

| 维度 | 规则提取 | 混合模式 | 纯 LLM 模式 |
|-----|---------|---------|-----------|
| 延迟 | 0ms | +1 LLM 调用（~500ms） | +1 LLM 调用（~500ms） |
| 成本 | 0 token | ~500 token | ~1500 token |
| 准确率 | 中（漏提隐式事实） | 高（规则保底 + LLM 补全） | 高（但可能幻觉） |
| 稳定性 | 极高（确定性输出） | 高（规则保底） | 中（LLM 可能输出不标准 JSON） |

混合模式兼顾了速度、成本和准确率，且规则提取的保底结果确保即使 LLM 失败也不会导致系统崩溃。

---

## 四、实施优先级与估算

| 优先级 | 任务 | 预估工作量 | 依赖 |
|-------|------|----------|------|
| P0 | 自动化回归测试 | 2-3 小时 | 无 |
| P1 | 对抗强度滑块 | 4-5 小时 | 无 |
| P2 | FactExtractor 升级 | 3-4 小时 | 无 |

建议按 P0 → P1 → P2 顺序实施：
1. **先写测试**：为现有约束行为建立基线，防止后续改动破坏
2. **再做滑块**：前端可见功能，用户能直接感知
3. **最后升级提取器**：提升准确率，属于体验优化

---

## 五、风险与缓解

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 对抗强度滑块导致强度 5 时约束失效 | 中 | 白名单扩展有限制，事实锁硬约束在所有强度下始终生效 |
| FactExtractor Hybrid 增加 LLM 调用延迟 | 低 | 材料 <100 字时跳过 LLM；Phase 4 本身已有多次 LLM 调用，+1 次影响可控 |
| 回归测试 mock 不完整 | 低 | 逐步补充场景，核心场景（还款凭证、时间红线）优先覆盖 |
