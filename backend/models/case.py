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
