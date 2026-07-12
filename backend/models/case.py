"""
案卷与庭审记录数据模型
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class CaseInput:
    """用户提交的案卷"""
    case_title: str          # 案由
    facts: str               # 事实描述
    evidence: str            # 证据清单（每行一项）
    claims: str              # 诉讼请求
    plaintiff_position: str = ""  # 用户是哪一方（原告/被告/中立）

    # 单方对抗模式字段（Phase B）
    mode: str = "neutral"           # "neutral" | "asymmetric"
    user_side: str = ""             # "plaintiff" | "defendant" | ""
    user_strategy_hint: str = ""    # 用户策略倾向提示（可选）
    opponent_materials: str = ""    # AI 生成的对方材料（单方模式下）

    # 案卷原始材料（双轨制：结构化数据 + 原始全文）
    source_materials: str = ""      # 用户输入的原始完整文本

    # 单方对抗模式：AI 对手对抗强度（1-5，默认 3）
    adversarial_intensity: int = 3

    # 可视化预留字段（未来由证据梳理模块填充）
    timeline_events: list = field(default_factory=list)   # TimelineEvent 列表
    party_relations: list = field(default_factory=list)    # PartyRelation 列表


@dataclass
class TrialRecord:
    """完整庭审记录"""
    case_id: str
    case_input: CaseInput
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 各阶段输出
    plaintiff_opening: str = ""       # 原告律师：起诉策略+陈述
    defendant_response: str = ""      # 被告律师：答辩策略+回应
    disputed_issues: str = ""         # 法官：归纳争议焦点
    evidence_examination: str = ""    # 举证质证记录
    plaintiff_final: str = ""         # 原告最后陈述
    defendant_final: str = ""         # 被告最后陈述
    judgment: str = ""                # 法官判决
    win_rate: float = 0.0             # 综合胜率
    win_rate_breakdown: dict = field(default_factory=dict)  # 维度拆解
