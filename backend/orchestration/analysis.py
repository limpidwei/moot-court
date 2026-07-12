"""
统一案件分析数据模型 - 单一事实源 (Single Source of Truth)

所有从 LLM 提取的结构化数据都存储在这里，确保：
- InsightCard、庭审文本显示一致
- 避免多次独立 LLM 调用导致的数据分歧
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseAnalysis:
    """统一案件分析缓存 - 所有结构化数据的唯一事实源"""

    # Phase 1: 请求权基础分析
    legal_relationship: str = ""  # 法律关系定性
    claim_basis: str = ""  # 最优请求权基础
    claim_basis_article: str = ""  # 法条编号

    # Phase 2: 起诉状与证据
    core_claims: list[str] = field(default_factory=list)  # 核心诉讼请求
    evidence_list: list[dict] = field(default_factory=list)  # 证据清单

    # Phase 3-4: 答辩
    defense_strategy: str = ""  # 被告主要抗辩策略

    # Phase 5: 争议焦点
    dispute_issues: list[dict] = field(default_factory=list)  # 争议焦点列表

    # Phase 6: 法庭辩论
    debate_highlights: list[str] = field(default_factory=list)  # 辩论要点

    # Phase 8: 判决（关键字段，强制一致）
    win_rate: float = 0.0  # 综合胜率（来自 calculate_win_rate 工具）
    win_rate_dimensions: dict[str, Any] = field(default_factory=dict)  # 四维度评分
    verdict_result: str = ""  # 判决结果
    verdict_reasons: list[str] = field(default_factory=list)  # 判决理由

    # 洞察卡片缓存（从统一提取中生成）
    insight_cards: dict[int, dict[str, Any]] = field(default_factory=dict)  # phase -> insight_data

    def update_from_phase(self, phase: int, extracted: dict[str, Any]):
        """从阶段提取结果更新分析数据"""
        if phase == 1:
            self.legal_relationship = extracted.get("legal_relationship", self.legal_relationship)
            self.claim_basis = extracted.get("claim_basis", self.claim_basis)
            self.claim_basis_article = extracted.get("claim_basis_article", self.claim_basis_article)
        elif phase == 2:
            if "core_claims" in extracted:
                self.core_claims = extracted["core_claims"]
            if "evidence_list" in extracted:
                self.evidence_list = extracted["evidence_list"]
        elif phase in (3, 4):
            self.defense_strategy = extracted.get("defense_strategy", self.defense_strategy)
        elif phase == 5:
            if "dispute_issues" in extracted:
                self.dispute_issues = extracted["dispute_issues"]
        elif phase == 6:
            if "debate_highlights" in extracted:
                self.debate_highlights = extracted["debate_highlights"]
        elif phase == 8:
            # 胜率来自工具调用，不接受 LLM 提取的胜率
            if "verdict_result" in extracted:
                self.verdict_result = extracted["verdict_result"]
            if "verdict_reasons" in extracted:
                self.verdict_reasons = extracted["verdict_reasons"]

        # 缓存 insight 数据
        if "insight_data" in extracted:
            self.insight_cards[phase] = extracted["insight_data"]

    def set_win_rate(self, rate: float, dimensions: dict[str, Any]):
        """设置胜率（来自 calculate_win_rate 工具，权威数据）"""
        self.win_rate = rate
        self.win_rate_dimensions = dimensions
        # 同步更新 insight card
        if 8 in self.insight_cards:
            self.insight_cards[8]["win_rate"] = rate
            self.insight_cards[8]["win_rate_dimensions"] = dimensions

    def get_structured_context(self, for_phase: int) -> str:
        """为指定阶段生成结构化上下文，注入到 prompt 中确保一致性"""
        context_parts = []

        if for_phase > 1 and self.legal_relationship:
            context_parts.append(f"【已确定法律关系】{self.legal_relationship}")

        if for_phase > 1 and self.claim_basis:
            context_parts.append(f"【已确定请求权基础】{self.claim_basis}（{self.claim_basis_article}）")

        if for_phase > 2 and self.core_claims:
            claims_str = "、".join(self.core_claims[:3])  # 最多显示3个
            context_parts.append(f"【已确定诉讼请求】{claims_str}")

        if for_phase > 4 and self.defense_strategy:
            context_parts.append(f"【被告主要抗辩】{self.defense_strategy}")

        if for_phase > 5 and self.dispute_issues:
            issues_str = "、".join([issue.get("text", "") for issue in self.dispute_issues[:3]])
            context_parts.append(f"【已确定争议焦点】{issues_str}")

        if for_phase == 8 and self.win_rate > 0:
            context_parts.append(f"【综合胜率】{self.win_rate}%（已通过工具计算，请直接引用）")

        return "\n".join(context_parts) if context_parts else ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，用于持久化"""
        return {
            "legal_relationship": self.legal_relationship,
            "claim_basis": self.claim_basis,
            "claim_basis_article": self.claim_basis_article,
            "core_claims": self.core_claims,
            "evidence_list": self.evidence_list,
            "defense_strategy": self.defense_strategy,
            "dispute_issues": self.dispute_issues,
            "debate_highlights": self.debate_highlights,
            "win_rate": self.win_rate,
            "win_rate_dimensions": self.win_rate_dimensions,
            "verdict_result": self.verdict_result,
            "verdict_reasons": self.verdict_reasons,
            "insight_cards": {str(k): v for k, v in self.insight_cards.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseAnalysis":
        """从字典反序列化"""
        analysis = cls()
        analysis.legal_relationship = data.get("legal_relationship", "")
        analysis.claim_basis = data.get("claim_basis", "")
        analysis.claim_basis_article = data.get("claim_basis_article", "")
        analysis.core_claims = data.get("core_claims", [])
        analysis.evidence_list = data.get("evidence_list", [])
        analysis.defense_strategy = data.get("defense_strategy", "")
        analysis.dispute_issues = data.get("dispute_issues", [])
        analysis.debate_highlights = data.get("debate_highlights", [])
        analysis.win_rate = data.get("win_rate", 0.0)
        analysis.win_rate_dimensions = data.get("win_rate_dimensions", {})
        analysis.verdict_result = data.get("verdict_result", "")
        analysis.verdict_reasons = data.get("verdict_reasons", [])
        # 恢复 insight_cards 的整数键
        insight_cards_raw = data.get("insight_cards", {})
        analysis.insight_cards = {int(k): v for k, v in insight_cards_raw.items()}
        return analysis
