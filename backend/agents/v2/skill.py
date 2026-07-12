"""
Skill 系统 —— 可插拔的法律专业能力模块

每个 Skill 封装一类真实法律工作流中的专业能力。
Agent 通过 register_skill() 获得能力，而非在 system prompt 里写死。
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Optional

from ...llm import llm_call, llm_call_stream, LLMConfig
from ...streaming import stream_queue_ctx, put_event


class Skill(ABC):
    """Skill 基类"""

    name: str = ""
    description: str = ""
    # Skill 自带的 tools（Agent 注册后获得使用权）
    tools: list[str] = []
    # Skill 的专属 prompt 模板（注册后追加到 system prompt）
    prompt_template: str = ""

    @abstractmethod
    def can_handle(self, task_type: str) -> bool:
        """该 Skill 是否可处理某类任务"""

    @abstractmethod
    async def execute(self, agent: "BaseAgentV2", context: dict) -> str:
        """执行 Skill，返回产出文本"""

    async def _call_llm(
        self, agent: "BaseAgentV2", task: str, *, temperature: float = 0.3, max_tokens: int = 4096
    ) -> str:
        """统一 LLM 调用入口：若上下文存在流式队列，则走流式输出并推送 token 事件。"""
        memory_ctx = agent.memory.build_context(include_private=True)
        full_task = f"【你的记忆与当前状态】\n{memory_ctx}\n\n【当前任务】\n{task}" if memory_ctx else task

        queue = stream_queue_ctx.get(None)
        if queue:
            full: list[str] = []
            async for token in llm_call_stream(
                agent.system_prompt,
                messages=[{"role": "user", "content": full_task}],
                config=agent.llm_config,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                put_event({"type": "token", "agent": agent.name, "content": token})
                full.append(token)
            return "".join(full)
        return await llm_call(
            agent.system_prompt,
            messages=[{"role": "user", "content": full_task}],
            config=agent.llm_config,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _call_llm_structured(
        self,
        agent: "BaseAgentV2",
        task: str,
        output_schema: dict,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """要求 LLM 按 JSON schema 输出，并解析验证。

        用于 Codex 式 Agentic 执行：Skill 产出结构化对象，直接写入 Ontology。
        """
        schema_prompt = (
            "请严格按以下 JSON schema 输出，只返回 JSON 对象，不要 markdown 代码块，"
            "不要解释性文字：\n"
            f"{json.dumps(output_schema, ensure_ascii=False, indent=2)}"
        )
        raw = await self._call_llm(agent, f"{task}\n\n{schema_prompt}", temperature=temperature, max_tokens=max_tokens)
        return _extract_json(raw)


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象"""
    text = text.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取 markdown 代码块
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 尝试提取第一个 { ... } 对象
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法从 LLM 输出中提取 JSON: {text[:200]}")


# ── 律师 Skill ────────────────────────────────────────────

class LegalResearchSkill(Skill):
    """法律研究 Skill —— 对应真实律师的"法条检索与类案检索"工作流"""

    name = "legal_research"
    description = "检索请求权基础法条、抗辩法条、司法解释及类案（请求权基础驱动型）"
    tools = ["search_legal_db", "search_case_law"]
    prompt_template = """
## 法律研究能力——请求权基础分析法

你是一名精通德国法学方法的资深律师，进行法律研究时必须遵循请求权基础分析框架。

### 核心问题
处理每个案件时，首先明确："谁得向谁，依据何项法律规定，主张何种权利？"

### 第一步：请求权检索与排序
按以下顺序检索可能的请求权基础（不可跳过）：
1. 合同请求权（《民法典》合同编）——最优先，因通常最有利于权利人
2. 类似合同请求权（缔约过失、无权代理等）
3. 无因管理请求权（《民法典》第979条）
4. 物权请求权（《民法典》物权编：返还原物、排除妨害等）
5. 不当得利返还请求权（《民法典》第985条）
6. 侵权损害赔偿请求权（《民法典》侵权责任编）——最后检视，因适用范围最广但通常举证责任较重

### 第二步：三层四步检视（针对最可能的请求权基础）
对每项请求权基础，按以下框架完整检视：

**三层结构**：
- 第一层：请求权是否成立？（积极要件由原告举证）
- 第二层：成立后是否消灭？（清偿、提存、抵销、免除、混同）
- 第三层：是否存在行使障碍？（诉讼时效、同时履行抗辩权、先诉抗辩权等）

**四步内容**：
1. 请求权成立要件（积极要件）
2. 权利未发生的抗辩（防御规范）
3. 权利已消灭的抗辩
4. 权利阻碍（排除）的抗辩

### 第三步：规范分类（罗森贝克规范说）
将检索到的法条按功能分类：
- **主要规范（请求权基础规范）**：支持原告诉请的核心法条
- **辅助规范**：补充、说明主要规范要件的法条（如司法解释、实施细则）
- **防御规范**：支持被告抗辩的法条（但书、例外条款）

### 第四步：举证责任分配
依据《民诉法解释》第91条和罗森贝克规范说：
- 主张法律关系存在的当事人→对产生该法律关系的基本事实承担举证责任
- 主张法律关系变更、消灭或权利受妨害的当事人→对该基本事实承担举证责任

### 第五步：类案检索（要素抽取法）
1. 从待决案件中抽取关键要素（时间、主体、行为、标的、结果）
2. 检索3-5个相似判例，标注案号、法院层级
3. 比对关键要素相似性
4. 根据代理立场（原告/被告）选择强化或打破要素匹配

### 输出要求
- 必须按请求权排序逐一分析，不可跳跃
- 每项请求权必须标注：主要规范+辅助规范+防御规范
- 明确每项积极要件的举证责任归属
- 类案必须有案号和法院层级，不可编造
- 最后给出明确诉讼策略建议：主攻哪条请求权基础，备位选择是什么，对方可能的抗辩及应对
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("legal_research", "claim_analysis", "defense_analysis")

    async def execute(self, agent, context: dict) -> str:
        query = context.get("query", "")
        case_title = context.get("case_title", "")
        role = context.get("role", "plaintiff")
        background = context.get("context", "")
        facts = context.get("facts", background)  # 兼容旧字段

        task = f"""请作为{"原告方" if role == "plaintiff" else "被告方"}代理律师，对本案进行系统的请求权基础分析。

【案由】{case_title}
【案件事实】{facts[:1500]}
【研究主题】{query}
【代理立场】{"原告方：需寻找最有利的请求权基础，并预判被告可能的抗辩" if role == "plaintiff" else "被告方：需寻找所有可对抗原告诉请的防御规范，并攻击原告请求权的薄弱要件"}

请严格按照以下步骤输出：

## 一、请求权基础检索（按排序逐一检视）
对合同请求权、缔约过失请求权、物权请求权、无因管理请求权、不当得利请求权、侵权请求权逐一分析：
- 该请求权是否可能适用？为什么？
- 若适用，其积极成立要件是什么？（列出具体法条及条文内容）
- 本案事实是否满足这些要件？（要件事实分析）
- 存在哪些防御规范可能否定该请求权？（被告视角）

## 二、三层四步检视（针对最可能的1-2个请求权基础）
按"成立→未消灭→可行使"三层，"积极要件→未发生抗辩→已消灭抗辩→阻止抗辩"四步进行完整检视。
每项检视必须标注举证责任归属（依据罗森贝克规范说）。

## 三、规范体系图
用层级结构展示：
- 主要规范（请求权基础）
  - 辅助规范
  - 防御规范

## 四、类案检索
检索3-5个相似判例，每项必须包含：
- 案号、审理法院、裁判日期
- 关键事实要素（与本案比对）
- 裁判要旨（对本案的参考价值）

## 五、诉讼策略建议
- 主攻请求权基础及理由
- 备位请求权基础（如有）
- 对方最可能提出的3项抗辩及具体应对
- 举证责任分配对我方的影响及应对

注意：
- 法条引用必须准确到条、款、项
- 不得编造不存在的法条或判例
- 原告方侧重"请求权成立"，被告方侧重"防御规范适用"
"""

        return await self._call_llm(agent, task, temperature=0.2, max_tokens=4096)


class DraftingSkill(Skill):
    """文书起草 Skill —— 对应真实律师的"起诉状/答辩状/证据目录撰写"工作流"""

    name = "drafting"
    description = "撰写起诉状、答辩状、证据目录、代理词等法律文书（差异化策略与要素式规范）"
    tools = ["format_document"]
    prompt_template = """
## 文书起草能力——差异化策略与要素式规范

你撰写法律文书时，必须根据不同文书类型采用差异化策略，并符合最高人民法院2025年全面推行的要素式/表格式示范文本要求。

### 起诉状策略（"藏"）
核心原则：起诉状不是代理词，不要和盘托出。

1. **"说多错多"**：避免在起诉状中出现对己方不利的事实性描述，防止被对方利用作为反驳依据
2. **"切勿过度论证"**：只陈述基本事实，详细论证留到庭审。过早暴露全部观点和证据，会让对方有针对性地准备
3. **"隐藏火力点"**：不在起诉状中暴露全部法律观点和证据策略，庭审才是详细论证的环节
4. **诉讼请求明确可执行**：必须可量化、可执行（如"判令被告支付货款人民币XX元及逾期利息"）
5. **适应要素式文本**：按"当事人信息→诉讼请求→事实要素→证据要素"的结构填写

### 答辩状策略（"攻"）
核心原则：答辩状必须针对起诉状逐项回应。

1. **针锋相对**：逐项回应原告起诉状的"事实与理由"，不可遗漏
2. **焦点突出**：去芜存菁，帮助法官快速了解案件症结
3. **标注证据**：每项反驳意见标注对应证据编号（如"详见被告证据1"），形成逻辑闭环
4. **多理性分析，少情绪化表达**：提交对象是法官，不是原告
5. **主张须有证据支撑**：反驳原告事实主张时，准备有效的反驳证据

### 证据目录策略
1. 按证明主题分组（如"证明合同关系""证明履约事实""证明违约损失"）
2. 每项标注：编号、名称、类型、证明目的、三性自评
3. 核心证据放在前面，辅助证据放在后面
4. 引用法条准确到条、款、项

### 最后陈述/代理词策略
1. 总结庭审中已确认的核心事实和法律观点
2. 回应对方最后陈述中的关键主张
3. 简明有力，不引入新观点和新证据
4. 经典格式："综上所述，本代理人认为……以上代理意见，请合议庭予以充分考虑并采纳。"

### 通用格式要求
1. 严格遵循最高人民法院发布的文书格式
2. 事实与理由部分逻辑严密，时间线清晰
3. 引用法条准确到条、款、项
4. 语言专业但清晰，避免晦涩难懂的法律术语
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("draft_complaint", "draft_answer", "draft_evidence_catalog", "draft_statement")

    async def execute(self, agent, context: dict) -> str:
        doc_type = context.get("doc_type", "complaint")
        materials = context.get("materials", "")
        opponent_doc = context.get("opponent_doc", "")
        ctx = context.get("context", "")

        if doc_type == "complaint":
            task = f"""请撰写起诉状。

【参考材料】
{materials}

请严格按照以下要求撰写：

## 一、当事人信息
（原告/被告基本信息，按要素式文本要求）

## 二、诉讼请求
- 明确、可执行、可量化
- 避免模糊表述（如"要求被告赔偿损失"应改为"判令被告赔偿原告经济损失人民币XX元"）
- 如有多个请求，分项列明

## 三、事实与理由
**"藏"的策略要求**：
1. 只陈述对己方有利的基本事实，时间线清晰
2. 不暴露全部法律观点和证据策略（隐藏火力点）
3. 不详细论证（留到庭审和代理词）
4. 避免对己方不利的事实描述（说多错多）
5. 引用法条点到为止，不必展开论证

## 四、证据目录（简要）
- 按证明主题分组
- 每项标注：编号、名称、证明目的

## 五、此致/落款

注意：
- 适应2025年最高法要素式/表格式示范文本要求
- 格式规范、逻辑严密
- 引用法条准确
- 语言专业但清晰
"""
        elif doc_type == "answer":
            opponent_section = f"""
【原告起诉状要点】
{opponent_doc[:1500]}

要求：针对原告起诉状逐项回应。""" if opponent_doc else ""

            task = f"""请撰写答辩状。

【参考材料】
{materials}
{opponent_section}

请严格按照以下要求撰写：

## 一、当事人信息

## 二、答辩意见
**"攻"的策略要求**：
1. 逐项回应原告的诉讼请求和事实理由（不可遗漏）
2. 对原告每项主张明确表态：承认/否认/需要补充说明
3. 每项反驳意见标注对应证据编号（如"详见被告证据1"）
4. 去芜存菁，突出争议焦点，帮助法官快速了解症结
5. 多理性分析，少情绪化表达

## 三、事实与理由
- 针锋相对地反驳原告的事实主张
- 提出我方的事实主张和证据支撑
- 逻辑严密，时间线清晰

## 四、反诉（如有）
- 若提出反诉，单独列明反诉请求和事实理由

## 五、此致/落款

注意：
- 答辩状的提交对象是法官，不是原告
- 主张须有证据支撑
- 引用法条准确到条、款、项
"""
        elif doc_type == "statement":
            task = f"""请撰写最后陈述/代理词结尾。

【参考材料】
{materials}

【庭审已确认的关键事实】
{context.get("confirmed_facts", "")[:800]}

【对方最后陈述要点】
{context.get("opponent_statement", "")[:500]}

请按以下结构撰写：

## 一、总结关键证据和观点
概述庭审中最为关键、有力的证据与事实（不超过3点）

## 二、回应对方关键主张
针对对方最后陈述中的1-2个核心主张进行简要反驳

## 三、综合论述
围绕法庭归纳的争议焦点，对全案进行有组织、有推理的阐述：
- 事实层面：基于已采信证据，我方主张的事实已被证实
- 法律层面：引用核心法条，说明我方主张的法律依据
- 逻辑层面：展示对方主张的逻辑漏洞或举证不足

## 四、明确请求
请求法庭作出有利于己方的裁决

经典格式：
"综上所述，本代理人认为……[综合论述]……以上代理意见，敬请合议庭予以采纳。"

要求：
- 不引入新观点和新证据
- 简明有力，留给法官深刻印象
- 语言朴实，避免过多形容词和感叹号
- 若已充分辩论，避免重复已陈述过的意见
"""
        elif doc_type == "evidence_catalog":
            task = f"""请撰写被告证据目录。

【参考材料】
{materials}

要求：
1. 按证明主题分组（如"证明投资关系""证明履约事实""证明款项性质"）
2. 每项标注：编号、名称、证据类型、证明目的、三性自评、证据来源
3. 核心证据放在前面，辅助证据放在后面
4. 引用法条准确到条、款、项
5. **证据来源必须具体**（如"被告手机微信聊天记录，可当庭展示原始载体"），禁止模糊表述
6. 如编造聊天记录，时间必须在已知事实时间框架内，不得早于案件最早时间点
7. 如编造证人，证人必须与当事人有合理关系，且能出庭作证
8. 严格遵循上文"禁止事项"和"证据类型约束"，不得编造禁止类型的证据
"""
        else:
            task = f"""请撰写证据目录。

【参考材料】
{materials}

要求：
1. 按证明主题分组（如"证明合同关系""证明履约事实""证明违约损失"）
2. 每项标注：编号、名称、类型、证明目的、三性自评
3. 核心证据放在前面，辅助证据放在后面
4. 引用法条准确到条、款、项
"""

        raw_catalog = await self._call_llm(agent, task, temperature=0.3, max_tokens=8192)

        # ── P2: 一致性验证（可选，发现矛盾时触发一次修正）──
        fact_lock = context.get("fact_lock")
        if fact_lock and doc_type == "evidence_catalog":
            try:
                from .evidence_constraint import ConsistencyChecker
                checker = ConsistencyChecker()
                conflicts = await checker.check_catalog(raw_catalog, fact_lock)
                if conflicts:
                    # 提取冲突证据名称，用于后置过滤
                    conflict_names = [c["item"] for c in conflicts]
                    correction = "\n\n".join(
                        f"[冲突证据] {c['item']}\n[冲突原因] {c['raw_result']}" for c in conflicts
                    )
                    fix_task = f"""以下被告证据与已知事实存在直接矛盾，你必须删除这些证据，然后输出修正后的证据目录。

{correction}

【绝对规则】
1. 只删除上述冲突证据，保留其余所有未冲突证据完全不变（包括格式、编号、内容）
2. **严禁新增任何新证据**，不得改变抗辩策略，不得编造替代证据
3. 删除冲突证据后，如果证据编号不连续，直接保留原编号（不要求重新编号）
4. 如果所有证据均被删除，只输出说明"无可采纳的被告证据"

【原始证据目录】
{raw_catalog}

请输出仅删除冲突证据后的证据目录：
"""
                    raw_catalog = await self._call_llm(agent, fix_task, temperature=0.1, max_tokens=8192)

                    # 后置过滤：扫描输出，若仍包含"已还款"类凭证则直接删除该行
                    raw_catalog = self._post_filter_evidence(raw_catalog, fact_lock)
            except Exception as e:
                # 一致性检查失败不阻断主流程
                import logging
                logging.getLogger(__name__).warning(f"证据一致性检查失败: {e}")

        return raw_catalog

    def _post_filter_evidence(self, catalog_text: str, fact_lock) -> str:
        """后置过滤：删除输出中仍残留的禁止类型证据行（安全网）。"""
        import re
        lines = catalog_text.split("\n")
        filtered: list[str] = []

        # 模式1：已还款类凭证
        repayment_patterns = [
            r"还款.*(?:转账|凭证|记录|收据|截图)",
            r"(?:转账|凭证|记录|收据).*还款",
            r"已还.*\d+.*元",
            r"(?:银行转账|微信转账|支付宝).*\d+.*元.*还款",
        ]

        # 模式2：时间红线 —— 提取最早日期，禁止早于该日期的书证/协议/合同/计划书
        earliest_date: str | None = None
        for pf in getattr(fact_lock, "prohibited_facts", []):
            m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", pf)
            if m:
                earliest_date = m.group(1)
                break

        doc_keywords = ("协议", "合同", "计划书", "书证", "意向书", "备忘录")

        for line in lines:
            stripped = line.strip()
            # 过滤1：已还款类凭证
            if any(re.search(p, stripped) for p in repayment_patterns):
                continue

            # 过滤2：时间红线 —— 早于最早日期的书证类文件
            if earliest_date and any(kw in stripped for kw in doc_keywords):
                dates_in_line = re.findall(r"\d{4}年\d{1,2}月\d{1,2}日", stripped)
                if dates_in_line:
                    # 简单字符串比较（中文日期格式一致）
                    try:
                        earliest = _parse_cn_date(earliest_date)
                        for d in dates_in_line:
                            if _parse_cn_date(d) < earliest:
                                # 发现早于最早日期的书证，跳过该行
                                break
                        else:
                            filtered.append(line)
                        continue
                    except Exception:
                        pass

            filtered.append(line)
        return "\n".join(filtered)


def _parse_cn_date(date_str: str) -> tuple[int, int, int]:
    """将'2023年3月1日'解析为可比较的元组 (年, 月, 日)。"""
    import re
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not m:
        raise ValueError(f"无法解析日期: {date_str}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


class EvidenceAnalysisSkill(Skill):
    """证据分析 Skill —— 对应真实律师的"证据三性分析与证明力评估"工作流"""

    name = "evidence_analysis"
    description = "对证据进行三性分析、证明力评估、证据链完整性审查（四步法定向质证）"
    tools = ["extract_citations", "timeline_build"]
    prompt_template = """
## 质证能力——"定位-定性-说理-结论"四步法

你作为诉讼律师，对对方证据发表质证意见时，必须严格遵循四步法，确保每项异议都有法律依据和事实支撑。

### 第一步：定位
先明确以下信息：
- 证据名称、编号、形式（原件/复印件/电子数据/视听资料/证人证言等）
- 对方欲证明的待证事实（证明目的）
- 该证据在对方证据体系中的位置（核心证据/辅助证据/形式证据）

### 第二步：定性（围绕三性逐项审查）

**真实性审查要点**：
1. 是否原件/原物？复印件/扫描件有无原件核对？
2. 内容有无涂改、增减、剪辑？
3. 是否与其他证据矛盾？是否违背常理、交易习惯？
法律依据：《证据规定》第61条、第87条、第90条

**合法性审查要点**：
1. 取证主体/程序是否合法？（如偷拍偷录是否侵害隐私）
2. 证据形式是否符合法定要求？（如证人是否签署保证书）
3. 是否属于非法证据排除范围？
法律依据：《民诉法解释》第106条、《证据规定》第71条

**关联性审查要点**：
1. 证据指向的事实是否为本案争议焦点？
2. 是否仅为间接证据？能否直接推导结论？
3. 是否已被对方自认？是否为无争议事实？
法律依据：《证据规定》第85条、第87条

### 第三步：说理
每项异议必须结合：
- 具体法律条文（写明条文序号及内容）
- 本案具体事实矛盾点
- 证据之间的印证/矛盾关系
- 证明力大小评估（直接证据vs间接证据、原始证据vs传来证据）

### 第四步：结论
明确请求法庭：
- 不予采信（证据存在严重瑕疵）
- 部分采信（部分内容可采信，部分内容存疑）
- 采信但证明力有限（仅能证明部分待证事实）
- 采信（无异议时仍可就证明力大小发表意见）

### 特殊证据类型质证策略

**电子数据**：
- 要求展示原始载体（手机/电脑）
- 核查是否提供哈希值、时间戳、区块链存证
- 法律依据：《证据规定》第93条

**鉴定意见**：
- 审查鉴定机构/人员资质
- 审查检材移交记录
- 审查鉴定程序是否合规
- 法律依据：《证据规定》第34条

**证人证言**：
- 证人是否旁听庭审（《证据规定》第72条）
- 与当事人有无利害关系
- 感知/记忆/表达能力

**书证复印件**：
- 要求核对原件
- 无法核对原件的，不得单独作为定案依据（《证据规定》第90条）

### 输出原则
- 避免笼统说"证据无效"，必须明确指出"哪份证据、在哪一属性上存在何种问题"
- 若对三性无异议，仍应就证明力大小发表意见
- 核心证据详细质证，形式证据简要处理
- 善于利用对方证据中的矛盾点或对我方有利的内容（以子之矛攻子之盾）
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("evidence_analysis", "chain_review", "cross_exam_prep")

    async def execute(self, agent, context: dict) -> str:
        evidence = context.get("evidence", "")
        purpose = context.get("purpose", "analysis")
        evidence_type = context.get("evidence_type", "书证")
        opponent_purpose = context.get("opponent_purpose", "")
        ctx = context.get("context", "")

        task = f"""请对以下证据发表{"质证意见" if purpose == "cross_exam" else "三性分析与证明力评估"}。

【证据内容】
{evidence}

【对方证明目的】
{opponent_purpose}

【证据类型】{evidence_type}

【庭审背景】
{ctx[:800]}

请严格按照"定位-定性-说理-结论"四步法输出：

## 一、定位
- 证据名称：
- 证据形式：
- 对方欲证明的待证事实：
- 该证据在对方证据体系中的重要性：（核心证据/辅助证据/形式证据）

## 二、定性（三性质证）

### 1. 真实性
- 意见：（无异议/有异议）
- 具体理由：（结合本案事实，指出真实性瑕疵）
- 法律依据：（具体条文序号及内容）

### 2. 合法性
- 意见：（无异议/有异议）
- 具体理由：（取证程序、证据形式、非法证据排除）
- 法律依据：（具体条文序号及内容）

### 3. 关联性
- 意见：（无异议/有异议）
- 具体理由：（是否指向争议焦点、是否为间接证据）
- 法律依据：（具体条文序号及内容）

## 三、说理
- 证据之间的印证/矛盾关系分析
- 证明力大小评估（原始vs传来、直接vs间接、证据链完整性）
- 特殊证据类型的专项审查（如适用）

## 四、结论
明确请求法庭对该证据的处理意见：
- 不予采信 / 部分采信 / 采信但证明力有限 / 采信
- 理由总结（1-2句）

注意：
- 每项异议必须结合具体法律条文
- 不得笼统否定，必须指出具体问题
- 核心证据详细质证，形式证据简要处理
- 善于发现对方证据中对我方有利的内容
"""

        return await self._call_llm(agent, task, temperature=0.3, max_tokens=4096)


class CrossExamSkill(Skill):
    """交叉询问 Skill —— 对应真实律师的"交叉询问提问与回答策略"工作流

    核心原则（基于真实庭审规则）：
    - 3C弹劾法则：Commit（确认立场）→Credit（强化情境）→Confront（对质）
    - 封闭式问题为主，只能用"是/否"回答
    - 每个问题只包含一个事实，短句推进
    - 循序渐进，先固定外围事实，再逼入核心矛盾
    - "关门"技术：先固定证人当前陈述，再展示矛盾
    """

    name = "cross_exam"
    description = "交叉询问中的提问设计、回答策略、证人弹劾技术（3C弹劾驱动型）"
    tools = ["weakness_scan"]
    prompt_template = """
## 交叉询问能力——3C弹劾驱动型询问技术

你是一名精通交叉询问技术的资深诉讼律师。交叉询问的目的不是让证人"翻供"，而是：降低证人可信度、截取对我方有利的片段、获取弹药用于结案陈词。

### 核心原则
1. 只问封闭式问题（是/否/记不清），每个问题只包含一个事实
2. 永远不问你不知道答案的问题
3. 获取弹药用于结案陈词，而非当场争论结论
4. 宁可低估也不要高估预期能证明的事实

### 3C弹劾法则（发现矛盾时使用）
当你发现证人当庭陈述与先前记录矛盾时，严格按以下三步执行：

**第一步：Commit（确认立场）**
让证人明确、具体地确认其当庭陈述。不可使用模糊表述。
示例："您刚才明确向法庭陈述，2023年5月1日被告亲手将文件交给您，对吗？"

**第二步：Credit（强化情境）**
强调先前陈述是在何种正式情境下作出，增强其可信度权重。
示例："这份笔录是2023年6月15日在派出所由两名警官在场的情况下所作，您当时仔细阅读并签字确认，对吗？"

**第三步：Confront（对质）**
出示先前记录的具体内容，要求证人解释矛盾。
示例："但笔录第3页第5行记载：'文件是被告的助理交给我的'。请问，'被告亲手交给您'与'被告助理交给您'，哪一个是事实？"

### 问题链设计模板
每轮交叉询问按以下结构逐层推进：

**第一层：锚定外围事实（时空要素）**
- "2023年5月1日下午3点，您是否在公司会议室？"
- "当时会议室内除了您和被告，还有其他人吗？"

**第二层：锁定感官细节**
- "当时室内灯光是否充足？"
- "您距离被告大约几米？"
- "您是否戴眼镜？"

**第三层：固定核心陈述**
- "您是否向法官陈述过'文件是被告亲手交给您的'？"
- "您能否确认文件袋的颜色？"

**第四层：展示矛盾或限制**
- "但监控显示当天被告并未进入该楼层，您如何解释？"
- "您说记不清了，但您在庭前笔录中详细描述了该场景，是什么导致您的记忆发生变化？"

### 应对回避策略
若证人回答"记不清了""不确定""可能吧"：
1. 追问记忆基础："您说记不清了，但您在庭前笔录中详细描述了该场景，请问是什么导致您的记忆发生变化？"
2. 降低可信度：不再追问该细节，但记下该矛盾点用于结案陈词
3. 转换角度："既然您记不清具体日期，您是否记得是上午还是下午？"

### 禁止事项
- 不问开放式问题（"你当时看到了什么？"）
- 不问复合问题（"你是否购买了货物并直接交给张三？"）
- 不在问题前后添加"预估对方回答"等内部思考
- 不在交叉询问中争论结论（留到结案陈词）
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("generate_question", "generate_answer", "impeach_witness")

    async def execute(self, agent, context: dict) -> str:
        mode = context.get("mode", "question")
        target = context.get("target", "")
        weakness_map = context.get("weakness_map", "")

        if mode == "question":
            task = f"""请设计交叉询问问题链。

【询问对象/目标】{target}
【已知弱点/矛盾点】{weakness_map}
【当前轮次】第 {context.get("round_num", 1)} 轮
【已进行的交叉询问记录】{context.get("history", "")[:800]}

请严格按照以下要求设计：

## 第一阶段：内部策略分析（此阶段内容不输出，仅用于指导问题设计）
1. 本轮要锁定什么外围事实？（时空锚点）
2. 核心矛盾点是什么？（与已知弱点/矛盾点的关联）
3. 证人最可能如何回避？（预测3种回避方式并设计对应追问）
4. 本轮目标：获取什么"弹药"用于结案陈词？

## 第二阶段：问题链（仅输出此部分）
设计3-5个连续的封闭式问题，要求：
- 每个问题以前一个问题确认的事实为基础（积木式提问）
- 问题格式：直接陈述事实+要求确认
- 结尾不使用"是不是这样？""对吗？"等弱化语气的后缀
- 最后一个问题必须直接暴露矛盾或限制证人陈述范围
- 如适用3C弹劾法则，明确标注第几步

示例格式：
Q1: [封闭式问题，锚定外围事实]
Q2: [封闭式问题，锁定感官细节]
Q3: [封闭式问题，固定核心陈述]
Q4: [封闭式问题，展示矛盾——3C第三步：Confront]

## 第三阶段：预判与应对（不输出，内部参考）
- 若证人回答"是"：下一步如何递进？
- 若证人回答"否"：如何用已有记录反驳？
- 若证人回答"记不清"：如何降低其可信度并转换角度？

严禁输出：预估、推理过程、策略说明、"对方可能会说……"等内部思考。
仅输出问题链本身。"""
        else:
            task = f"""请设计对以下交叉询问问题的回答策略。

【对方问题】{target}
【我方已知材料】{context.get("materials", "")[:800]}
【当前策略】{context.get("strategy", "防守为主，不主动暴露新信息")}

请按以下框架输出：

## 一、问题分析
- 该问题的性质：（事实确认/陷阱问题/弹劾准备）
- 对方可能的目的：
- 若如实回答对我方的影响：

## 二、回答策略
1. **直接回答**（如事实有利且无法回避）：简洁确认，不扩展
2. **限制性承认**（如部分有利）："是的，但仅限于……"
3. **合理澄清**（如问题含误导）："需要澄清的是……"
4. **记忆限制**（如确不记得）："关于具体时间，我的记忆不够精确……"

## 三、风险提示
- 该问题链下一步可能的方向
- 对方可能准备的弹劾材料
- 建议的应对准备

要求：
- 基于已有材料合理回答，不编造有利事实
- 若问题含陷阱，识别并化解
- 保持专业、冷静，不情绪化
- 回答尽量简短，不给对方"讲故事"的机会"""

        return await self._call_llm(agent, task, temperature=0.3, max_tokens=4096)


# ── 法官 Skill ────────────────────────────────────────────

class ModerationSkill(Skill):
    """庭审主持 Skill —— 对应真实法官的"争议焦点归纳与庭审主持"工作流"""

    name = "moderation"
    description = "归纳争议焦点、主持举证质证、制止不当提问（请求权基础驱动型焦点归纳）"
    tools = ["summarize_issues"]
    prompt_template = """
## 庭审主持能力——请求权基础驱动型焦点归纳

你作为法官主持庭审时，必须以请求权基础为逻辑主线，通过系统化的方法归纳争议焦点，引导庭审高效推进。

### 争议焦点归纳方法

**方法一：诉辩交锋法**
1. 提取原告诉请要点
2. 提取被告抗辩要点
3. 逐项比对，找出矛盾与差异之处
4. 区分"权利否定型"抗辩（否认要件事实）与"权利阻碍型"抗辩（以时效、抗辩权等对抗）

**方法二：请求权基础分析法**
将争议拆分为要件化问题，而非笼统的疑问句。
示例：
- ❌ 笼统："被告是否应承担责任？"
- ✅ 要件化：
  1. 合同是否成立并生效？
  2. 被告是否存在违约行为？
  3. 损害后果与违约行为是否存在因果关系？
  4. 被告提出的免责事由是否成立？

**方法三：动态提炼法**
1. 第一阶段：归纳概括性焦点（如"双方是否存在合同关系"）
2. 第二阶段：随着证据交换和法庭调查，细化为具体焦点（如"印章真伪""表见代理是否成立"）
3. 第三阶段：根据新证据修正焦点

### 焦点归纳后的程序要求
依据《民诉法解释》第226条：
- 就归纳的争议焦点征求当事人意见
- 若当事人认为有遗漏或偏差，及时补充修正
- 确保辩论阶段围绕已固定的焦点展开

### 举证质证主持
- 引导双方围绕证据三性发表意见
- 对不当提问（威胁证人、与本案无关、损害人格尊严）及时制止
- 对逾期证据根据《民诉法解释》第101-102条裁决是否采纳及是否训诫

### 自由心证公开
- 证据分析阶段：写明采信结果+内心判断过程
- 事实认定阶段：写明内心确信的事实经过
- 对不能形成确信的部分说明可能情形
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("summarize_issues", "moderate_exam", "ruling_on_evidence")

    async def execute(self, agent, context: dict) -> str:
        task_type = context.get("task_type", "summarize_issues")

        if task_type == "summarize_issues":
            complaint = context.get("complaint", "")
            answer = context.get("answer", "")
            task = f"""请作为法官，归纳本案争议焦点。

【原告起诉状要点】
{complaint[:2000]}

【被告答辩状要点】
{answer[:2000]}

请严格按照以下步骤：

## 第一步：诉辩交锋比对
列出原告诉请要点（1. 2. 3.）和被告抗辩要点（1. 2. 3.），逐点比对找出矛盾差异。

## 第二步：请求权基础拆分（如适用）
若本案为给付之诉，将争议拆分为要件化问题：
- 合同/法律关系是否成立并生效？
- 是否存在违约/侵权/不履行行为？
- 损害后果与行为是否存在因果关系？
- 免责/减责事由是否成立？
- 诉讼时效/除斥期间是否届满？

## 第三步：归纳争议焦点
区分事实争议焦点和法律争议焦点，每项标注：
- 焦点名称（要件化表述）
- 原告主张
- 被告主张
- 需要查明的关键证据
- 举证责任分配（依据罗森贝克规范说）

## 第四步：焦点排序
按重要性和审理逻辑排序：
1. 最基础/最重要的焦点（如合同效力）
2. 依赖基础焦点的事实焦点（如违约行为）
3. 损害赔偿相关焦点
4. 程序性焦点（如诉讼时效）

## 第五步：征求当事人意见
以法官口吻表述："上述争议焦点，双方当事人有无补充或异议？"

注意：
- 焦点应来源于双方主张和证据（《民诉法解释》第226条）
- 避免将诉请直接变为疑问句（如"原告是否有权解除合同？"过于笼统）
- 需要查明的证据应具体明确
- 必须区分事实争议和法律争议
"""

        elif task_type == "ruling_on_evidence":
            evidence = context.get("evidence", "")
            is_delayed = context.get("is_delayed", False)
            deadline = context.get("deadline", "法定举证期限内")
            opponent_consent = context.get("opponent_consent", "未明确")
            task = f"""请对该证据作出程序性裁定。

【证据】{evidence}
【是否逾期提交】{"是" if is_delayed else "否"}
【举证期限】{deadline}
【对方是否同意质证】{opponent_consent}

请按以下结构裁定：

## 一、证据基本信息
- 证据名称、形式、提交时间

## 二、是否采纳及理由
1. **逾期证据审查**（如适用）：
   - 逾期原因（客观原因/故意或重大过失）
   - 证据与案件基本事实的关联程度
   - 是否予以训诫、罚款（《民诉法解释》第101-102条）

2. **证据能力审查**：
   - 是否属于非法证据排除范围
   - 取证程序是否合法

## 三、采信意见
- 予以采信 / 不予采信 / 部分采信
- 若采信，对其证明力大小的初步判断

## 四、法律依据
引用具体条文序号及内容
"""

        else:
            task = context.get("task", "请对当前庭审环节进行主持引导。")

        return await self._call_llm(agent, task, temperature=0.2, max_tokens=4096)


class AdjudicationSkill(Skill):
    """裁判 Skill —— 对应真实法官的"判决撰写与胜率评估"工作流"""

    name = "adjudication"
    description = "撰写判决书、评估胜率、四维度打分（五理回应式判决）"
    tools = ["calculate_win_rate", "render_judgment"]
    prompt_template = """
## 裁判能力——"五理"回应式判决

你撰写判决书时，必须以争议焦点为主线，通过"五理"说理体系进行论证，做到胜败皆明。

### 基本格式
严格按以下结构：
1. 案由及审理经过
2. 原告诉讼请求
3. 被告答辩意见
4. 法院认定事实（基于证据，写明采信/不采信理由）
5. 本院认为（法律适用及论证——以争议焦点为主线）
6. 判决主文

### "五理"说理体系

**1. 事理**
对案件主要事实的认定提供依据并说明理由。
要求：不仅写明认定结果，还要说明"为什么这样认定"——证据如何印证、矛盾如何排除。

**2. 法理**
援引法律、司法解释准确完整。
要求：写明规范性文件名称、条款项序号及条文内容。不仅罗列法条，还要阐述援引法条背后的价值判断过程。

**3. 学理**
必要时运用法学理论辅助说理。
要求：在法律规定不明确或存在争议时，引用通说或权威学者观点（如王泽鉴、梁慧星等）。

**4. 情理**
结合道德规范、生活经验、公序良俗。
要求：在法律框架内，考虑社会常理和一般人认知，增强裁判的可接受性。

**5. 文理**
逻辑严密、用语规范、文字精练。
要求：避免前后矛盾，避免使用模糊表述（如"根据有关法律规定"），杜绝语法错误。

### 自由心证公开要求

**证据分析阶段**：
- 不仅写明采信结果
- 还应阐明：为什么采信这份证据？为什么不采信那份证据？证据证明力大小如何判断？

**事实认定阶段**：
- 写明内心确信的事实经过
- 对不能形成确信的部分说明可能情形
- 对证据之间的矛盾如何排除

**判决理由阶段**：
- 阐明自由裁量的具体考量（如为何判定承担30%责任而非其他比例）
- 结合法律认知、民俗习惯、审判经验进行说明

### 回应式说理
- 对原告的每项诉讼请求逐一回应：支持/驳回/部分支持，并说明理由
- 对被告的每项抗辩意见逐一回应：采纳/不采纳，并说明理由
- 对当事人的自由裁量疑惑进行针对性回应
- 做到"胜败皆明"——胜诉方知道为什么胜，败诉方知道为什么败

### 证明标准
依据《民诉法解释》第108条：
- 本证需使待证事实存在具有"高度可能性"（高度盖然性）
- 若反证使事实陷入真伪不明，由负有举证责任的当事人承担败诉后果

### 胜率评估四维度
1. 事实清晰度 30%
2. 法律依据强度 25%
3. 举证责任完成度 25%
4. 程序合规性 20%
"""

    def can_handle(self, task_type: str) -> bool:
        return task_type in ("render_judgment", "calculate_win_rate")

    async def execute(self, agent, context: dict) -> str:
        task_type = context.get("task_type", "render_judgment")

        if task_type == "render_judgment":
            materials = context.get("materials", "")
            issues = context.get("issues", "")
            task = f"""请撰写本案判决书。

【案件材料】
{materials[:4000]}

【争议焦点】
{issues}

【举证质证情况】
{context.get("evidence_exam", "")[:1000]}

【双方最后陈述】
原告：{context.get("plaintiff_final", "")[:500]}
被告：{context.get("defendant_final", "")[:500]}

请严格按照以下结构和要求撰写：

## 一、案由及审理经过
- 案号、立案时间、开庭时间、审理程序

## 二、原告诉讼请求
逐项列明原告的诉讼请求

## 三、被告答辩意见
逐项列明被告的抗辩意见

## 四、法院认定事实
**自由心证公开要求**：
- 围绕争议焦点逐一认定事实
- 每项事实认定必须写明：依据哪些证据、为什么采信这些证据、为什么不采信对方证据
- 对证据之间的矛盾如何排除
- 对不能形成确信的事实说明可能情形
- 依据《民诉法解释》第105条，运用逻辑推理和日常生活经验判断证据

## 五、本院认为（法律适用及论证）
**必须以争议焦点为主线**，逐一分析论证。

每项焦点分析必须包含"五理"：
1. **事理**：基于已认定事实的逻辑推演
2. **法理**：援引具体法条（写明名称、条款项序号及条文内容），阐述价值判断过程
3. **学理**：必要时引用权威学者观点或主流学说
4. **情理**：结合社会常理和公序良俗
5. **文理**：逻辑严密，前后一致

**回应式说理要求**：
- 对原告的每项诉讼请求逐一回应
- 对被告的每项抗辩意见逐一回应
- 做到"胜败皆明"

## 六、判决主文
明确、可执行的判项

## 七、四维度胜率评估
- 事实清晰度（0-100分）及理由
- 法律依据强度（0-100分）及理由
- 举证责任完成度（0-100分）及理由
- 程序合规性（0-100分）及理由
- 综合胜率（加权计算：事实30%+法律25%+举证25%+程序20%）

要求：
- 说理透明，让当事人理解裁判逻辑
- 自由心证过程公开化（不要"暗箱操作"）
- 胜败皆明
- 引用法条准确到条、款、项
- 不得使用"根据有关法律规定"等模糊表述
"""

        else:
            task = context.get("task", "请评估胜率。")

        return await self._call_llm(agent, task, temperature=0.2, max_tokens=8192)


# ── Skill 注册表 ─────────────────────────────────────────

from .extended_skills import EvidenceChainSkill, PleaBargainSkill, ExecutionRiskSkill

ALL_SKILLS: list[type[Skill]] = [
    LegalResearchSkill,
    DraftingSkill,
    EvidenceAnalysisSkill,
    CrossExamSkill,
    ModerationSkill,
    AdjudicationSkill,
    EvidenceChainSkill,
    PleaBargainSkill,
    ExecutionRiskSkill,
]
