# 模拟法庭中 AI 被告证据编造的合理性约束研究报告

> 日期：2026-06-08
> 背景：Agent V2 Skill Prompt 改造后，被告在证据目录环节出现"脑补证据"现象（如编造不存在的"投资协议聊天记录"）。在单方对抗模式中，适度编造证据有利于训练律师的质证能力，但需确保与案件基本事实不冲突。

---

## 一、问题定义

### 1.1 为什么需要 AI 编造证据

在**单方对抗模式**（用户扮演原告律师，AI 扮演被告+法官）中：
- 用户只能看到自己提供的证据，无法预知被告可能持有的证据
- 如果 AI 被告只能就用户提供的证据进行"被动反驳"，训练价值极低
- **真实庭审中，被告往往持有原告未知的证据**（如还款凭证、聊天记录、证人证言）
- 因此，AI 被告适度"编造"对抗性证据，实质是**模拟真实诉讼中信息不对称的常态**，具有重要训练价值

### 1.2 为什么需要约束

当前 LLM 编造证据存在以下问题：
| 问题类型 | 示例 | 危害 |
|---------|------|------|
| **与已知事实直接矛盾** | 被告编造"2023年2月28日投资协议聊天记录"，但用户明确陈述"2023年3月1日借款" | 破坏案件事实一致性，用户感到困惑 |
| **编造无法质证的证据** | 被告声称"有5个证人可证明投资关系"，但后续庭审中这些证人从未出现 | 破坏庭审可信度 |
| **证据链逻辑不自洽** | 被告主张"10万元是投资款"，但编造证据显示"利润对半分"，却无项目内容、无风险分担约定 | 训练价值降低，用户轻易识破 |
| **过度编造导致对抗失衡** | 被告编造大量有利证据，使原告处于绝对劣势 | 挫败用户，失去训练意义 |

### 1.3 核心矛盾

> **既要允许 AI 被告"脑补"合理对抗证据（模拟真实信息不对称），又要确保编造的证据不与案件基本事实冲突（保持训练场景的可信度）。**

---

## 二、现有实践与理论基础

### 2.1 法律教育中的"假设性证据"实践

#### （1）模拟法庭的预设事实争议型

美国俄亥俄州法律相关教育中心（OCLRE）的**State v. Randall** 案例是典型的对抗性训练材料：
- 控方证人 James 称被告"烂醉且先动手"
- 辩方证人 Phillip 称被告"几乎没醉，是被害人先动手"
- 双方陈述存在**事实不一致性**，但均围绕"夜店斗殴"这一核心事件展开

**教学启示**：对抗性训练不需要一方"编造"证据，而是**在共同事实框架下提供不同视角的解读**。但这种方式需要人工预先设计案例，不适合 AI 动态生成。

#### （2）律师庭前准备的"假设性辩护"

根据实务文章，律师在庭前常做以下假设性准备：
- 假设对方持有"借条原件"——准备笔迹鉴定申请
- 假设对方有"还款凭证"——准备质证意见（凭证时间、金额是否与主张一致）
- 假设对方申请某证人出庭——准备交叉询问提纲

**教学启示**：律师庭前准备的本质是**"基于已知事实，推断对方可能的证据并制定应对策略"**。这种"推断"不是凭空编造，而是有逻辑基础的推演。

#### （3）法律诊所教育的对抗性训练

南京大学"数字法庭虚拟仿真实验"、华东政法大学"模拟律所"等实践表明：
- 对抗性训练的核心是**"辩论对抗"**而非"证据造假"
- 证据的真实性由案例设计者保证，学生专注于质证和辩论技巧

### 2.2 AI 领域的"对抗性训练"与事实一致性

#### （1）Factual Consistency Evaluation

论文 *Face4RAG: Factual Consistency Evaluation for Retrieval Augmented Generation in Chinese* (arXiv:2407.01080) 提出：
- 将事实不一致分为 9 种错误类型、3 大类别
- 通过"逻辑保持分解"（logic-preserving decomposition）检测事实偏差

**技术启示**：可以通过**事实抽取→一致性比对**的管道，自动检测 LLM 生成内容与已知事实的冲突。

#### （2）Trustworthy Legal AI

论文 *Towards Trustworthy Legal AI through LLM Agents and Formal Reasoning* (arXiv:2511.21033) 提出：
- 使用"保守预测策略"（conservative prediction），优先选择有法律依据的规范
- 通过"法条反向验证"（statute reverse verification）减少错误

**技术启示**：在证据生成环节引入**法律依据约束**，确保证据类型和取证程序符合法律规定。

---

## 三、解决方案：三层约束框架

基于上述研究，提出**"三层约束框架"**来规范 AI 被告的证据编造行为：

```
┌─────────────────────────────────────────┐
│  第一层：事实边界约束（硬约束）            │
│  ——禁止与案件基本事实直接矛盾              │
├─────────────────────────────────────────┤
│  第二层：证据类型约束（软约束）            │
│  ——只允许编造符合法律逻辑的证据类型        │
├─────────────────────────────────────────┤
│  第三层：对抗强度约束（调节阀）            │
│  ——根据用户水平动态调整编造证据的数量/质量  │
└─────────────────────────────────────────┘
```

### 3.1 第一层：事实边界约束（硬约束）

**目标**：确保 AI 编造证据不与用户提供的案件基本事实冲突。

**实现手段**：

#### （1）建立"事实锁"（Fact Lock）

从用户输入的案件材料中提取**不可变事实清单**（immutable facts），作为证据编造的约束条件：

```python
# 示例：事实锁数据结构
fact_lock = {
    "time_facts": ["2023年3月1日张三向李四转账10万元"],
    "entity_facts": ["原告：张三", "被告：李四", "证人：王五"],
    "action_facts": ["张三多次催讨", "李四回复'再等等'"],
    "document_facts": ["银行转账记录", "微信聊天记录", "证人王五证言"],
    "user_claims": ["借款本金10万元", "月利率1.5%"],
    "prohibited_facts": []  # 明确禁止编造的事实（如"李四已还款5万元"）
}
```

#### （2）证据生成前的事实一致性检查

在 LLM 生成证据目录之前，先将案件事实注入 prompt：

```
【事实约束】
以下事实已得到确认，你编造的证据不得与这些事实直接矛盾：
1. 2023年3月1日，张三通过银行转账向李四支付10万元
2. 双方通过微信沟通，李四回复"再等等"
3. 证人王五在场听到双方谈论借款事宜

【禁止编造】
你不得编造以下类型的证据：
- 涉及张三、李四以外第三方的转账记录（除非有合理理由）
- 发生在2023年3月1日之前的"借款协议"（与已知事实矛盾）
- 声称"李四已还款"的任何凭证（用户未提供此信息）

【允许编造】
你可以在以下框架内编造对抗性证据：
- 被告对"10万元性质"的不同解读（如主张为投资款、合作款）
- 被告与原告之间的其他沟通记录（需符合双方角色设定）
- 被告方的证人证言（需符合证人资格要求）
```

#### （3）生成后的事实一致性验证

使用轻量级 NLI（Natural Language Inference）模型或 LLM 自检，验证生成证据是否与事实锁冲突：

```python
async def check_evidence_consistency(evidence_text: str, fact_lock: dict) -> list[str]:
    """返回与事实锁冲突的文本片段"""
    conflicts = []
    for fact in fact_lock["time_facts"] + fact_lock["entity_facts"] + fact_lock["action_facts"]:
        # 使用 LLM 判断 evidence_text 是否与 fact 矛盾
        is_contradictory = await llm_nli_check(evidence_text, fact)
        if is_contradictory:
            conflicts.append(f"证据与事实冲突: {fact}")
    return conflicts
```

### 3.2 第二层：证据类型约束（软约束）

**目标**：只允许 AI 编造符合法律逻辑和案件情境的证据类型。

**实现手段**：

#### （1）证据类型白名单

根据案件类型和争议焦点，限定 AI 可以编造的证据类型：

| 案件类型 | 允许编造的对抗性证据类型 | 禁止编造的证据类型 |
|---------|----------------------|------------------|
| 借款合同纠纷 | 被告主张款项为投资/合作的聊天记录；被告方证人证言；项目相关资料 | 伪造的银行还款凭证；不存在的书面借条；第三人代还款记录 |
| 买卖合同纠纷 | 质量异议函；交货单；验收记录；被告方质检报告 | 伪造的付款凭证；不存在的合同补充协议 |
| 劳动争议 | 考勤记录；工资发放记录；解除通知；被告方证人（同事）证言 | 伪造的工伤鉴定报告；不存在的劳动合同 |

#### （2）证据链完整性要求

要求 AI 编造的证据必须能够形成**自洽的证据链**，不能是孤证：

```
【证据链要求】
如果你主张"10万元是投资款"，你必须同时编造：
1. 投资合意的证据（如双方讨论投资的聊天记录）
2. 投资项目的证据（如项目计划、费用支出）
3. 风险分担的证据（如双方约定"共担风险"的记录）

禁止仅编造单一证据（如只有"投资聊天记录"但无项目内容）。
```

#### （3）法律依据约束

要求 AI 编造的证据必须符合取证程序的法律规定：

```
【取证程序约束】
- 电子数据：必须声称有原始载体（手机/电脑），可当庭展示
- 书证复印件：必须说明是否有原件核对
- 证人证言：证人必须出庭作证，需说明证人身份、与当事人关系
- 鉴定意见：必须说明鉴定机构资质、检材来源
```

### 3.3 第三层：对抗强度约束（调节阀）

**目标**：根据用户水平和案件复杂度，动态调整 AI 编造证据的"难度"。

**实现手段**：

#### （1）用户等级系统

```python
class UserLevel(Enum):
    BEGINNER = "beginner"      # 新手：AI 编造证据有明显破绽，便于识别
    INTERMEDIATE = "intermediate"  # 中级：证据较为合理，需要认真质证
    ADVANCED = "advanced"      # 高级：证据链完整，需要综合运用法律知识和质证技巧

# 根据用户等级调整 prompt
def get_evidence_fabrication_prompt(level: UserLevel) -> str:
    if level == UserLevel.BEGINNER:
        return "编造的证据应有明显瑕疵（如时间矛盾、主体错误），便于原告律师识别"
    elif level == UserLevel.INTERMEDIATE:
        return "编造的证据应较为合理，但有可质证的空间（如取证程序瑕疵、证明力不足）"
    else:
        return "编造的证据链应完整自洽，需要原告律师运用高级质证技巧（如3C弹劾、证据链断裂分析）才能击破"
```

#### （2）对抗强度滑块

在前端设置"对抗强度"选项（1-5级）：

| 级别 | AI 编造证据数量 | 证据质量 | 适用场景 |
|-----|--------------|---------|---------|
| 1 | 0 | — | 纯程序演练，不编造证据 |
| 2 | 1-2 | 有明显破绽 | 新手训练，学习基本质证 |
| 3 | 2-3 | 有瑕疵但需分析 | 中级训练，标准对抗 |
| 4 | 3-5 | 证据链完整 | 高级训练，复杂案件 |
| 5 | 5+ | 专业级对抗 | 专家训练，极限压力测试 |

#### （3）动态调整机制

根据用户在庭审中的表现动态调整：
- 如果用户连续 3 轮质证都命中证据要害 → 提升对抗强度
- 如果用户质证流于表面（如只说"对真实性有异议"但无具体理由）→ 降低对抗强度或给出提示

---

## 四、技术实现方案

### 4.1 架构设计

```
用户输入案件材料
    │
    ▼
┌─────────────────┐
│  事实抽取模块    │  ← 使用 LLM 从案件材料提取事实锁
│  (FactExtractor) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  证据生成模块    │  ← 调用 DraftingSkill，注入事实锁约束
│  (EvidenceGenerator)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  一致性验证模块  │  ← 使用 LLM 或轻量模型验证
│  (ConsistencyChecker)│
└────────┬────────┘
         │
         ▼
    冲突？────是────→ 要求 LLM 修改证据
      │
      否
      ▼
    输出被告证据目录
```

### 4.2 关键代码实现

#### （1）事实抽取（FactExtractor）

```python
# backend/agents/v2/evidence_constraint.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class FactLock:
    """事实锁：案件中的不可变事实"""
    time_facts: list[str]       # 时间相关事实
    entity_facts: list[str]     # 主体相关事实
    action_facts: list[str]     # 行为相关事实
    document_facts: list[str]   # 已确认的证据
    user_claims: list[str]      # 用户主张
    prohibited_facts: list[str] # 明确禁止编造的事实


class FactExtractor:
    """从案件材料中提取事实锁"""

    EXTRACTION_PROMPT = """
请从以下案件材料中提取所有**客观事实**，并分类整理。

【案件材料】
{materials}

【输出格式】
1. 时间事实：（所有明确的时间点、时间段）
2. 主体事实：（所有涉及的人物、机构及其关系）
3. 行为事实：（所有已发生的行为、事件）
4. 证据事实：（用户已提供的证据清单）
5. 用户主张：（用户的诉讼请求及理由）

注意：
- 只提取材料中**明确陈述**的事实，不要推断
- 标注每项事实的**置信度**（高/中/低）
- 对于"被告辩称"类内容，单独标注为"被告主张"而非"事实"
"""

    async def extract(self, materials: str) -> FactLock:
        result = await llm_call(self.EXTRACTION_PROMPT.format(materials=materials[:3000]))
        # 解析 LLM 输出，构建 FactLock
        return self._parse_result(result)
```

#### （2）证据生成约束（EvidenceGenerator）

```python
class EvidenceGenerator:
    """在事实锁约束下生成被告证据"""

    def build_constrained_prompt(
        self,
        case_type: str,
        fact_lock: FactLock,
        user_level: str = "intermediate",
        intensity: int = 3
    ) -> str:
        """构建带约束的证据生成 prompt"""

        allowed_types = self._get_allowed_evidence_types(case_type)

        return f"""
## 角色设定
你是一名资深诉讼律师，正在为被告方准备证据目录。

## 事实锁（不可违背）
以下事实已经确认，你准备的证据不得与这些事实直接矛盾：

### 时间事实
{chr(10).join(f"- {f}" for f in fact_lock.time_facts)}

### 主体事实
{chr(10).join(f"- {f}" for f in fact_lock.entity_facts)}

### 行为事实
{chr(10).join(f"- {f}" for f in fact_lock.action_facts)}

### 已确认证据
{chr(10).join(f"- {f}" for f in fact_lock.document_facts)}

### 原告主张
{chr(10).join(f"- {f}" for f in fact_lock.user_claims)}

## 证据类型约束
你只能在以下类型中选择编造对抗证据：
{chr(10).join(f"- {t}" for t in allowed_types)}

## 禁止事项
1. 不得编造与上述"事实锁"直接矛盾的证据
2. 不得编造涉及案件以外第三方的关键证据（除非有合理关联）
3. 不得编造声称"已还款""已履行"等直接否定原告诉请的虚假凭证
4. 不得编造无法当庭出示原始载体的电子数据
5. 每项证据必须有合理的"证据来源"说明

## 对抗强度设定
当前等级：{user_level}（强度 {intensity}/5）
{"证据应有明显破绽，便于原告识别" if intensity <= 2 else ""}
{"证据应较为合理，但有可质证空间" if 2 < intensity <= 4 else ""}
{"证据链应完整自洽，需要高级质证技巧" if intensity > 4 else ""}

## 输出要求
请按以下格式输出被告证据目录：

### 第一组：[证明主题]
| 编号 | 证据名称 | 证据类型 | 证明目的 | 三性自评 | 证据来源 |
|------|---------|---------|---------|---------|---------|

注意：
- "证据来源"必须具体（如"被告手机微信聊天记录，可当庭展示原始载体"）
- 如果编造聊天记录，时间必须在已知事实时间框架内
- 如果编造证人，证人必须与当事人有合理关系
"""
```

#### （3）一致性验证（ConsistencyChecker）

```python
class ConsistencyChecker:
    """验证生成证据与事实锁的一致性"""

    CHECK_PROMPT = """
请判断以下"被告证据"是否与"已知事实"存在矛盾。

【已知事实】
{facts}

【被告证据】
{evidence}

【判断标准】
- "矛盾"：证据内容与已知事实直接冲突（如时间相反、主体错误、行为矛盾）
- "不一致"：证据内容与已知事实不符，但不一定是矛盾（如添加了未知细节）
- "一致"：证据内容与已知事实不冲突

【输出格式】
判断：（矛盾/不一致/一致）
冲突点：（如有，请具体说明）
建议修改：（如果矛盾，请建议如何修改使其合理）
"""

    async def check(
        self,
        evidence_items: list[dict],
        fact_lock: FactLock
    ) -> list[dict]:
        """返回有冲突的证据项及修改建议"""
        conflicts = []
        all_facts = (fact_lock.time_facts + fact_lock.entity_facts +
                     fact_lock.action_facts + fact_lock.document_facts)

        for item in evidence_items:
            result = await llm_call(
                self.CHECK_PROMPT.format(
                    facts="\n".join(f"- {f}" for f in all_facts),
                    evidence=item["content"]
                )
            )
            if "矛盾" in result:
                conflicts.append({
                    "item": item,
                    "check_result": result
                })

        return conflicts
```

### 4.3 集成到现有流程

修改 `DefendantAgentV2.draft_evidence_catalog()` 方法：

```python
async def draft_evidence_catalog(self, evidence: str) -> str:
    """Phase 4: 撰写被告证据目录（带约束）"""
    from .evidence_constraint import FactExtractor, EvidenceGenerator, ConsistencyChecker

    # 1. 从 memory 中读取案件材料
    case_materials = self._get_case_materials()

    # 2. 提取事实锁
    extractor = FactExtractor()
    fact_lock = await extractor.extract(case_materials)

    # 3. 生成带约束的证据目录 prompt
    generator = EvidenceGenerator()
    constrained_prompt = generator.build_constrained_prompt(
        case_type=self._detect_case_type(),
        fact_lock=fact_lock,
        user_level=self._get_user_level(),  # 从用户历史表现获取
        intensity=self._get_adversarial_intensity()
    )

    # 4. 调用 LLM 生成证据目录
    raw_catalog = await self._call_llm(constrained_prompt)

    # 5. 一致性验证
    checker = ConsistencyChecker()
    evidence_items = self._parse_evidence_catalog(raw_catalog)
    conflicts = await checker.check(evidence_items, fact_lock)

    # 6. 如有冲突，要求 LLM 修改
    if conflicts:
        correction_prompt = f"""
以下证据与已知事实存在矛盾，请修改：

{chr(10).join(f"证据：{c['item']['name']}\n冲突：{c['check_result']}" for c in conflicts)}

请重新生成被告证据目录，确保与案件事实一致。
"""
        raw_catalog = await self._call_llm(correction_prompt)

    return raw_catalog
```

---

## 五、前端交互设计

### 5.1 对抗强度设置

在案件创建或庭审设置页面增加选项：

```
┌────────────────────────────────────────┐
│  🎚️ 对抗强度设置                        │
│                                         │
│  被告证据编造难度                        │
│  ○ 关闭（被告仅使用原告提供的证据反驳）    │
│  ● 初级（证据有明显破绽）                │
│  ○ 中级（证据有瑕疵但需分析）[推荐]       │
│  ○ 高级（证据链完整自洽）                │
│                                         │
│  [?] 被告会编造与案件相关的对抗性证据，   │
│      但不会与案件基本事实冲突。           │
└────────────────────────────────────────┘
```

### 5.2 庭审中的证据提示

当被告出示编造证据时，前端可显示提示：

```
💡 提示：被告出示的证据为 AI 模拟生成，可能存在与案件事实
   不一致之处。请仔细质证！
```

### 5.3 复盘时的证据分析

庭审复盘报告中增加"证据编造分析"部分：

```markdown
## 被告证据编造分析

| 证据名称 | 是否合理 | 与事实冲突 | 你的质证质量 |
|---------|---------|-----------|------------|
| 投资协议聊天记录 | ⚠️ 部分合理 | 时间点在转账前一天，未与已知事实冲突 | ⭐⭐⭐ 指出无原件核对 |
| 还款5000元凭证 | ❌ 不合理 | 与"被告至今未还款"直接矛盾 | ⭐⭐ 仅否认真实性 |
```

---

## 六、实施优先级

| 优先级 | 模块 | 工作量 | 效果 |
|-------|------|--------|------|
| **P0** | 事实锁提取 + 禁止事项 prompt | 2小时 | 立即减少明显矛盾 |
| **P1** | 证据类型白名单 + 证据链要求 | 4小时 | 提升证据合理性 |
| **P2** | 一致性验证模块 | 6小时 | 自动检测冲突 |
| **P3** | 用户等级 + 对抗强度滑块 | 4小时 | 个性化训练体验 |
| **P4** | 复盘证据分析 | 3小时 | 强化学习效果 |

---

## 七、参考来源

1. [OCLRE Mock Trial Materials - Adversary Process](https://www.oclre.org/aws/OCLRE/asset_manager/get_file/131894)
2. [南京大学数字法庭虚拟仿真实验](https://law.nju.edu.cn/info/2021/13511.htm)
3. [华东政法大学本科教学质量报告](https://jwc.ecupl.edu.cn/_upload/article/files/c6/1f/340b1bb74a0395b555806c1b6cce/3e5b6262-9d41-47b8-95e1-2fb041189422.pdf)
4. [Face4RAG: Factual Consistency Evaluation for RAG](https://arxiv.org/html/2407.01080v2)
5. [Towards Trustworthy Legal AI through LLM Agents and Formal Reasoning](https://arxiv.org/html/2511.21033v2)
6. [广州市律师代理民事诉讼出庭指引（2022）](http://mp.weixin.qq.com/s?__biz=MzkzNDc3NTcyNg==&mid=2247488152&idx=1&sn=e353062828e57ee92198caf96e7329ee)
7. [律师庭前准备实务](http://mp.weixin.qq.com/s?__biz=Mzg4MDc1MjMzNg==&mid=2247498511&idx=1&sn=8111e32009b94f8aee8c9e9652356c25)
8. [假设性辩护策略](https://www.sohu.com/a/101084472_386767)
