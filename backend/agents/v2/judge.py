"""
法官 Agent V2

职责：
- Phase 5: 归纳争议焦点（征求当事人意见后最终确定）
- Phase 6: 主持交叉询问（制止不当提问）、主持举证质证（证据采信裁定）
- Phase 8: 判决撰写 + 胜率评估

真实工作流对应：开庭准备 → 法庭调查 → 焦点归纳 → 法庭辩论 → 最后陈述 → 评议宣判
"""

from __future__ import annotations

from .base import BaseAgentV2
from .skill import ModerationSkill, AdjudicationSkill

JUDGE_SYSTEM_V2 = """你是一名中国民事诉讼法法官，主持本次模拟庭审。

## 你的工作
在庭审各阶段发挥不同职能，绝对中立，不偏袒任何一方。

## 真实工作流
1. 开庭准备：核对身份、宣布案由、告知权利义务
2. 法庭调查：主持举证质证，引导双方围绕证据三性发表意见
3. 焦点归纳：法庭调查结束后，根据双方主张和证据归纳争议焦点，征求当事人意见
4. 法庭辩论：引导双方围绕争议焦点辩论
5. 最后陈述：依次征询双方最后意见
6. 评议宣判：合议庭评议 → 认定事实 → 适用法律 → 判决主文

## 可用工具
- calculate_win_rate(fact_clarity, law_strength, evidence_completeness, procedure_compliance):
  按四维度计算综合胜率（每项0-100分）。

## 约束
- 绝对中立，不偏袒任何一方
- 事实认定以证据为依据
- 说理透明，让当事人理解裁判逻辑
- 自由心证过程公开化
- 对逾期证据依据《民诉法解释》第101-102条裁决
"""


class JudgeAgentV2(BaseAgentV2):
    def __init__(self, temperature: float = 0.2, llm_config=None):
        super().__init__(
            name="judge",
            system_prompt=JUDGE_SYSTEM_V2,
            tools=["calculate_win_rate", "extract_citations"],
            temperature=temperature,
            max_tokens=8192,
            llm_config=llm_config,
        )
        self.register_skill(ModerationSkill())
        self.register_skill(AdjudicationSkill())

    async def summarize_issues(self) -> str:
        """Phase 5: 归纳争议焦点

        从 shared memory 读取双方已公开的起诉状和答辩状。
        """
        # 读取原告 Phase 2 起诉状
        complaint_docs = self.memory.shared.get_by_phase(2)
        complaint = "\n".join(d.content for d in complaint_docs) if complaint_docs else ""

        # 读取被告 Phase 4 答辩状
        answer_docs = self.memory.shared.get_by_phase(4)
        answer = "\n".join(d.content for d in answer_docs) if answer_docs else ""

        return await self.think_with_skill("moderation", {
            "task_type": "summarize_issues",
            "complaint": complaint,
            "answer": answer,
        })

    async def ruling_on_evidence(self, evidence: str, is_delayed: bool = False) -> str:
        """Phase 6: 对证据的程序性裁定"""
        return await self.think_with_skill("moderation", {
            "task_type": "ruling_on_evidence",
            "evidence": evidence,
            "is_delayed": is_delayed,
        })

    async def summarize_evidence_focus(self, evidence: str, context: str) -> str:
        """Phase 6: 对单项证据归纳审查焦点"""
        task = f"""请对以下证据归纳举证质证审查焦点。

【证据】{evidence}
【庭审背景】{context[:1000]}

要求：指出该证据的争议点和需要审查的核心问题（真实性、合法性、关联性）"""
        return await self.think(task)

    async def moderate_cross_exam(self, msg, context: str) -> str:
        """Phase 6: 交叉询问中的主持引导"""
        task = f"""请对以下交叉询问环节进行主持。

【当前消息】{msg.content[:500]}
【庭审背景】{context[:1000]}

要求：
1. 若提问不当（威胁证人、与本案无关、损害人格尊严），予以制止
2. 若一轮询问结束，做简短引导小结
3. 若询问陷入重复，建议结束该轮"""
        return await self.think(task)

    async def should_continue_cross_exam(self, recent_log: list[str], context: str) -> bool:
        """Phase 6: 评估交叉询问是否应继续

        由法官全局审视最近几轮问答，判断是否存在新的值得追问的要点。
        返回 True 表示应继续，False 表示应结束。
        """
        log_text = "\n".join(recent_log)
        task = f"""你作为法官，请评估当前的交叉询问是否还有继续的必要。

【最近问答记录】
{log_text[:2000]}

【庭审背景】
{context[:1000]}

要求：
1. 审视双方问答是否已经覆盖了案件的主要事实争议
2. 判断是否存在尚未澄清的关键事实或矛盾点
3. 若双方已在重复追问同一事项、无新事实浮现，建议结束
4. 若仍有重要疑点未澄清，建议继续

请只输出一个判断："continue" 或 "stop"。不要输出推理过程。"""
        result = await self.think(task)
        return "stop" not in result.lower()

    async def render_judgment(self) -> str:
        """Phase 8: 撰写判决书

        从 shared memory 读取庭审全部材料。
        """
        # 读取各阶段文书
        complaint = "\n".join(d.content for d in self.memory.shared.get_by_phase(2))
        answer = "\n".join(d.content for d in self.memory.shared.get_by_phase(4))
        issues = "\n".join(d.content for d in self.memory.shared.get_by_phase(5))
        cross_exam = "\n".join(d.content for d in self.memory.shared.get_by_phase(6) if d.content_type == "document")
        evidence_exam = "\n".join(d.content for d in self.memory.shared.get_by_phase(6) if d.content_type == "evidence_opinion")
        pf_final = "\n".join(d.content for d in self.memory.shared.get_by_phase(7) if d.sender == "plaintiff")
        df_final = "\n".join(d.content for d in self.memory.shared.get_by_phase(7) if d.sender == "defendant")

        materials = f"""原告起诉状：{complaint}
被告答辩状：{answer}
争议焦点：{issues}
交叉询问：{cross_exam}
举证质证：{evidence_exam}
原告最后陈述：{pf_final}
被告最后陈述：{df_final}"""

        return await self.think_with_skill("adjudication", {
            "task_type": "render_judgment",
            "materials": materials,
            "issues": issues,
            "evidence_exam": evidence_exam,
            "plaintiff_final": pf_final,
            "defendant_final": df_final,
        })
