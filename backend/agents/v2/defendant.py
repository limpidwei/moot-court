"""
被告律师 Agent V2

职责：
- Phase 3-4: 庭前准备（答辩策略、答辩状、反驳证据）
- Phase 6: 交叉询问提问/回答 / 举证质证质证意见
- Phase 7: 最后陈述

真实工作流对应：收到起诉状 → 程序抗辩评估 → 实体抗辩构建 → 答辩状撰写 → 反驳证据准备
"""

from __future__ import annotations

from .base import BaseAgentV2
from .skill import (
    LegalResearchSkill,
    DraftingSkill,
    EvidenceAnalysisSkill,
    CrossExamSkill,
)

DEFENDANT_SYSTEM_V2 = """你是一名资深中国民事诉讼被告方律师。

## 你的工作
代理被告方，在收到原告起诉状和证据后完成答辩准备、庭审辩论和最后陈述。

## 真实工作流
1. 收到材料：仔细阅读起诉状和证据目录
2. 程序抗辩评估：管辖权、主体适格、诉讼时效、一事不再理、仲裁条款
3. 事实与法律分析：检索抗辩法条、分析原告证据链弱点
4. 抗辩策略制定：核心抗辩路径 + 备选路径 + 证据策略
5. 文书产出：答辩状（侧重"驳斥"）+ 被告证据目录
6. 质证准备：对原告证据逐条生成三性质证意见
7. 庭审预案：预估原告主张，准备反驳提纲

## 约束
- 从被告立场出发，但不得编造有利事实
- 质证应紧扣证据三性（真实性、合法性、关联性）
- 策略建议务实，不过度乐观
"""


class DefendantAgentV2(BaseAgentV2):
    def __init__(self, temperature: float = 0.3, llm_config=None):
        super().__init__(
            name="defendant",
            system_prompt=DEFENDANT_SYSTEM_V2,
            tools=["extract_citations"],
            temperature=temperature,
            max_tokens=8192,
            llm_config=llm_config,
        )
        self.register_skill(LegalResearchSkill())
        self.register_skill(DraftingSkill())
        self.register_skill(EvidenceAnalysisSkill())
        self.register_skill(CrossExamSkill())

    async def analyze_defense(self, case_input) -> str:
        """Phase 3: 答辩策略分析

        从 memory 中读取原告已公开的起诉状，制定抗辩策略。
        """
        # 从 shared memory 读取原告 Phase 2 文书（起诉状）
        plaintiff_docs = self.memory.shared.get_by_phase(2)
        if not plaintiff_docs:
            # 兼容：从 inbox 读取收到的消息
            plaintiff_docs = self.memory.consume_inbox("document")
        complaint = "\n".join(d.content for d in plaintiff_docs) if plaintiff_docs else "（尚未收到原告起诉状）"

        # 构建 context：模拟"收到起诉状后"的工作场景
        context = f"""你收到了原告的起诉材料：

{complaint}

请基于以上材料，制定答辩策略。"""

        # 将"收到材料"记录到 private history
        self.memory.private.history.append({"role": "user", "content": f"收到原告起诉状：{complaint[:500]}..."})

        return await self.think_with_skill("legal_research", {
            "query": f"{case_input.case_title} 抗辩事由",
            "case_title": case_input.case_title,
            "role": "defendant",
            "context": context,
        })

    async def draft_answer(self, case_input) -> str:
        """Phase 4: 撰写答辩状

        从 memory 中读取自己的答辩策略和对方的起诉状。
        """
        # 读取自己的 Phase 3 答辩策略
        own_docs = self.memory.shared.get_by_phase(3)
        phase3_analysis = "\n".join(d.content for d in own_docs) if own_docs else ""
        # 兼容：从 private strategy 读取
        if not phase3_analysis and self.memory.private.strategy:
            phase3_analysis = self.memory.private.strategy.core_theory or ""

        # 读取原告 Phase 2 起诉状
        plaintiff_docs = self.memory.shared.get_by_phase(2)
        if not plaintiff_docs:
            plaintiff_docs = self.memory.consume_inbox("document")
        complaint = "\n".join(d.content for d in plaintiff_docs) if plaintiff_docs else ""

        materials = f"""答辩策略分析：
{phase3_analysis}

原告起诉状：
{complaint}"""

        return await self.think_with_skill("drafting", {
            "doc_type": "answer",
            "materials": materials,
        })

    async def draft_evidence_catalog(self, evidence: str, case_input=None, intensity: int = 3) -> str:
        """Phase 4: 撰写被告证据目录（带三层约束框架）

        Args:
            evidence: 原告提供的证据文本（保留兼容）
            case_input: 完整案件输入，用于提取事实锁和证据类型约束
            intensity: 对抗强度（1-5），控制被告编造证据的激进程度
        """
        from .evidence_constraint import FactExtractor, EvidenceConstraintBuilder

        # 1. 提取事实锁（第一层：事实边界约束）
        fact_lock = None
        constraint_prompt = ""
        if case_input is not None:
            extractor = FactExtractor()
            fact_lock = extractor.extract(case_input)

            # 2. 构建证据类型约束（第二层：证据类型 + 证据链）
            case_type = getattr(case_input, "case_title", "")
            builder = EvidenceConstraintBuilder(case_type, intensity=intensity)
            constraint_prompt = builder.build_prompt(fact_lock)

        materials = f"""【原告证据】
{evidence}

{constraint_prompt}"""

        return await self.think_with_skill("drafting", {
            "doc_type": "evidence_catalog",
            "materials": materials,
            "fact_lock": fact_lock,  # 传给 Skill 以便进一步处理
        })

    async def cross_exam_question(self, context: str, round_num: int) -> str:
        """Phase 6: 交叉询问提问"""
        weakness = self.memory.private.strategy.weakness_map if self.memory.private.strategy else {}
        return await self.think_with_skill("cross_exam", {
            "mode": "question",
            "target": context,
            "weakness_map": weakness,
        })

    async def cross_exam_answer(self) -> str:
        """Phase 6: 回答对方交叉询问（从 inbox 读取问题）"""
        inbox_questions = self.memory.consume_inbox("question")
        if not inbox_questions:
            return "（尚未收到对方交叉询问问题）"
        question = inbox_questions[-1].content

        # 归档到 private history
        self.memory.private.history.append({"role": "user", "content": f"对方交叉询问：{question}"})

        return await self.think_with_skill("cross_exam", {
            "mode": "answer",
            "target": question,
        })

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

要求：
1. 围绕真实性、合法性、关联性发表意见
2. 指出证据瑕疵或矛盾之处
3. 评估该证据对原告主张的证明力
4. 根据证据重要性和争议程度决定详略：核心证据（如合同原件、关键转账记录）可详细质证，充分指出瑕疵；形式证据（如身份证明、程序性文件）可简要处理"""
        return await self.think(task)

    async def final_statement(self, case_title: str, claims: str) -> str:
        """Phase 7: 最后陈述（主动读取起诉状、答辩状、争议焦点、庭审交锋记录、策略笔记）"""
        complaint = "\n".join(d.content for d in self.memory.shared.get_by_phase(2))
        answer = "\n".join(d.content for d in self.memory.shared.get_by_phase(4))
        issues = "\n".join(d.content for d in self.memory.shared.get_by_phase(5))
        cross_exam_log = self.memory.private.fact_timeline
        strategy_notes = self.memory.private.strategy_notes

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

【内部策略笔记】
{strategy_notes[:1000]}
"""
        return await self.think_with_skill("drafting", {
            "doc_type": "statement",
            "materials": materials,
        })
