"""
原告律师 Agent V2

职责：
- Phase 1-2: 庭前准备（请求权基础分析、起诉状、证据目录）
- Phase 6: 交叉询问提问 / 举证质证意见
- Phase 7: 最后陈述

真实工作流对应：案件审查 → 事实梳理 → 法律关系构建 → 请求设计 → 证据编排
"""

from __future__ import annotations

from .base import BaseAgentV2
from .skill import (
    LegalResearchSkill,
    DraftingSkill,
    EvidenceAnalysisSkill,
    CrossExamSkill,
)

PLAINTIFF_SYSTEM_V2 = """你是一名资深中国民事诉讼原告方律师。

## 你的工作
代理原告方，完成庭前准备、庭审辩论和最后陈述。

## 真实工作流
1. 案件审查：确认起诉条件、管辖、诉讼时效
2. 事实梳理：按时间脉络整理大事记
3. 法律关系构建：精准识别 underlying 法律关系
4. 请求设计：诉讼请求明确、可执行
5. 证据编排：零散证据 → 逻辑严密的证据链，按证明主题分组
6. 庭审预案：预估对方抗辩，准备质证提纲与发问提纲
7. 动态调整：根据对方新材料实时优化策略

## 约束
- 仅基于提供的案卷材料，不编造事实
- 证据不足时明确指出"现有证据无法证明"
- 引用法条须准确（民法典、民诉法及司法解释）
- 语言专业但清晰
"""


class PlaintiffAgentV2(BaseAgentV2):
    def __init__(self, temperature: float = 0.3, llm_config=None):
        super().__init__(
            name="plaintiff",
            system_prompt=PLAINTIFF_SYSTEM_V2,
            tools=["extract_citations"],
            temperature=temperature,
            max_tokens=8192,
            llm_config=llm_config,
        )
        # 注册 Skill
        self.register_skill(LegalResearchSkill())
        self.register_skill(DraftingSkill())
        self.register_skill(EvidenceAnalysisSkill())
        self.register_skill(CrossExamSkill())

    async def analyze_claims(self, case_input) -> str:
        """Phase 1: 请求权基础分析"""
        return await self.think_with_skill("legal_research", {
            "query": f"{case_input.case_title} 请求权基础",
            "case_title": case_input.case_title,
            "role": "plaintiff",
        })

    async def draft_complaint(self, phase1_analysis: str, claims: str, evidence: str) -> str:
        """Phase 2: 撰写起诉状"""
        return await self.think_with_skill("drafting", {
            "doc_type": "complaint",
            "materials": f"请求权基础分析：\n{phase1_analysis}\n\n诉讼请求：\n{claims}\n\n证据：\n{evidence}",
        })

    async def draft_evidence_catalog(self, evidence: str) -> str:
        """Phase 2: 撰写证据目录"""
        return await self.think_with_skill("drafting", {
            "doc_type": "evidence_catalog",
            "materials": evidence,
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

    async def comment_on_evidence(self, evidence: str, context: str) -> str:
        """Phase 6: 原告对己方证据进行说明/举证"""
        task = f"""请对以下证据进行举证说明。

【证据内容】{evidence}
【庭审背景】{context[:1000]}

要求：
1. 说明证据名称、来源、形式
2. 阐述证明目的
3. 简要自评证据三性（真实性、合法性、关联性）"""
        return await self.think(task)

    async def final_statement(self, case_title: str, claims: str) -> str:
        """Phase 7: 最后陈述（主动读取起诉状、答辩状、争议焦点、庭审交锋记录、策略笔记）"""
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
