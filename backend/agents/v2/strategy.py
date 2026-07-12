"""
诉讼策略引擎

基于真实律师诉讼策略制定工作流设计：
- 案件审查 → 事实梳理 → 法律关系构建 → 请求设计 → 证据编排 → 庭审预案 → 动态调整
"""

from __future__ import annotations

import logging
from typing import Optional

from .schema import (
    LitigationStrategy,
    EvidenceTiming,
    AgentMessageV2,
)
from ...llm import llm_call, LLMConfig

logger = logging.getLogger(__name__)


class LitigationStrategyEngine:
    """
    诉讼策略引擎

    驱动 Agent 在每个阶段做出自主选择：
    - 制定初始策略
    - 根据庭审进展动态调整
    - 决定证据提交时序
    """

    def __init__(self, llm_config: Optional[LLMConfig] = None):
        self.llm_config = llm_config

    async def formulate(self, case_input, role: str, system_prompt: str) -> LitigationStrategy:
        """
        制定初始诉讼策略。
        LLM 基于案件材料生成完整策略，存入 private 层。
        """
        task = f"""请为{"原告方" if role == "plaintiff" else "被告方"}制定完整诉讼策略。

【案由】{case_input.case_title}
【案情事实】
{case_input.facts}
【证据清单】
{case_input.evidence}
【诉讼请求】
{case_input.claims}

请输出结构化的诉讼策略：
1. core_theory: 核心{"请求权基础" if role == "plaintiff" else "抗辩理论"}
2. fallback_theories: 备选路径（至少2条）
3. evidence_timing_strategy: 选择一种证据提交策略（full_disclosure / staged_release）并说明理由
4. procedural_moves: 是否需要程序性动作（管辖权异议/延期举证/申请回避/保全等）
5. cross_exam_focus: 预判交叉询问的3个重点攻击方向
6. weakness_map: 分析对方潜在的3个弱点及利用方式
7. risk_assessment: 当前风险评估（高/中/低）及主要风险点"""

        response = await llm_call(
            system_prompt,
            messages=[{"role": "user", "content": task}],
            config=self.llm_config,
            temperature=0.4,
            max_tokens=4096,
        )

        # 解析 LLM 输出为结构化策略（简化版：用文本 + 启发式解析）
        strategy = self._parse_strategy_response(response, role)
        strategy.risk_assessment = self._extract_section(response, "risk_assessment", "风险评估")
        return strategy

    async def adapt(
        self,
        current_strategy: LitigationStrategy,
        new_event: AgentMessageV2,
        judge_guidance: Optional[str],
        system_prompt: str,
    ) -> LitigationStrategy:
        """
        根据庭审进展动态调整策略。
        """
        context = f"""当前策略摘要：
- 核心理论：{current_strategy.core_theory}
- 证据策略：{current_strategy.evidence_timing.strategy_type}
- 交叉询问重点：{current_strategy.cross_exam_focus}

新事件：
- 来自：{new_event.sender}
- 类型：{new_event.content_type}
- 内容：{new_event.content[:800]}

法官指导：{judge_guidance or "无"}

请判断是否需要调整策略，并输出调整建议。"""

        response = await llm_call(
            system_prompt,
            messages=[{"role": "user", "content": context}],
            config=self.llm_config,
            temperature=0.3,
            max_tokens=2048,
        )

        # 将调整建议追加到 adapt_notes
        current_strategy.adapt_notes.append(response[:500])

        # 启发式调整：若对方暴露了明显弱点，加入 weakness_map
        # 实际可由 LLM 在 response 中显式输出 JSON 调整指令
        return current_strategy

    async def decide_evidence_timing(
        self,
        strategy: LitigationStrategy,
        current_phase: int,
        remaining_evidence: list[str],
        system_prompt: str,
    ) -> tuple[list[str], list[str]]:
        """
        决定当前阶段提交哪些证据。

        返回：(submit_now, reserve)
        """
        timing = strategy.evidence_timing

        if timing.strategy_type == "full_disclosure":
            return remaining_evidence, []

        if timing.strategy_type == "staged_release":
            # 试探型：提交核心证据，保留边缘证据
            if len(remaining_evidence) <= 2:
                return remaining_evidence, []
            core = remaining_evidence[:2]
            reserve = remaining_evidence[2:]
            return core, reserve

        return remaining_evidence, []

    # ── 内部解析工具 ──

    def _parse_strategy_response(self, response: str, role: str) -> LitigationStrategy:
        """从 LLM 文本响应中启发式提取结构化策略"""
        strategy = LitigationStrategy()
        strategy.core_theory = self._extract_section(response, "core_theory", "核心")

        # 提取 fallback_theories
        fb_text = self._extract_section(response, "fallback_theories", "备选")
        if fb_text:
            strategy.fallback_theories = [l.strip("- ") for l in fb_text.split("\n") if l.strip().startswith("-")]

        # 提取 evidence_timing
        et_text = self._extract_section(response, "evidence_timing", "证据提交策略")
        if "staged" in et_text.lower() or "分阶段" in et_text:
            strategy.evidence_timing.strategy_type = "staged_release"
        else:
            strategy.evidence_timing.strategy_type = "full_disclosure"

        # 提取 procedural_moves
        pm_text = self._extract_section(response, "procedural_moves", "程序性")
        if "管辖权异议" in pm_text:
            from .schema import ProceduralMove
            strategy.procedural_moves.append(ProceduralMove(move_type="jurisdiction_objection", reason="管辖权异议"))

        # 提取 cross_exam_focus
        ce_text = self._extract_section(response, "cross_exam_focus", "交叉询问")
        if ce_text:
            strategy.cross_exam_focus = [l.strip("- ") for l in ce_text.split("\n") if l.strip().startswith("-")]

        # 提取 weakness_map
        wm_text = self._extract_section(response, "weakness_map", "弱点")
        if wm_text:
            for line in wm_text.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    strategy.weakness_map[k.strip("- ")] = v.strip()

        return strategy

    @staticmethod
    def _extract_section(text: str, key: str, fallback_label: str) -> str:
        """启发式提取段落"""
        import re
        patterns = [
            rf"{key}[：:]\s*(.+?)(?=\n\d+\.|\n[A-Z]|$)",
            rf"{fallback_label}[：:]\s*(.+?)(?=\n\d+\.|\n[A-Z]|$)",
        ]
        for p in patterns:
            m = re.search(p, text, re.DOTALL | re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""
