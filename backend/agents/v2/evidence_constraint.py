"""
证据编造约束模块 —— 为 AI 被告编造对抗性证据提供三层约束框架

架构：
  FactExtractor      → 从案件材料提取不可变事实清单（事实锁）
  EvidenceConstraintBuilder → 构建带约束的证据生成 prompt
  ConsistencyChecker  → 验证生成证据与事实锁的一致性（P2）

使用位置：DefendantAgentV2.draft_evidence_catalog()
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ...llm import llm_call


# ── 数据模型 ──────────────────────────────────────────────

@dataclass
class FactLock:
    """事实锁：案件中的不可变事实清单

    所有字段均为"高置信度"客观事实，被告编造证据时不得与之直接矛盾。
    """

    time_facts: list[str] = field(default_factory=list)
    entity_facts: list[str] = field(default_factory=list)
    action_facts: list[str] = field(default_factory=list)
    document_facts: list[str] = field(default_factory=list)
    user_claims: list[str] = field(default_factory=list)
    prohibited_facts: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        """将事实锁格式化为 prompt 文本，直接注入 LLM 上下文。"""
        lines: list[str] = []
        lines.append("## 事实锁（不可违背）")

        def _section(title: str, items: list[str]):
            lines.append(f"\n### {title}")
            if items:
                for f in items:
                    lines.append(f"- {f}")
            else:
                lines.append("- （无）")

        _section("时间事实", self.time_facts)
        _section("主体事实", self.entity_facts)
        _section("行为事实", self.action_facts)
        _section("已确认证据", self.document_facts)
        _section("原告主张", self.user_claims)
        if self.prohibited_facts:
            _section("明确禁止编造", self.prohibited_facts)
        return "\n".join(lines)


# ── 第一层：事实边界约束 ──────────────────────────────────

class FactExtractor:
    """从案件材料中提取事实锁（轻量级规则提取，无需额外 LLM 调用）"""

    # 中文常见日期格式（宽匹配）
    _TIME_RE = re.compile(
        r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}年\d{1,2}月|\d{4}[-/]\d{1,2}[-/]\d{1,2})"
    )
    # 金额
    _AMOUNT_RE = re.compile(
        r"(?:人民币|￥)?\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:元|万元|亿元)"
    )
    # 行为动词（用于提取关键句）
    _ACTION_KWS = {"借", "转", "还", "付", "签", "约", "催", "辩", "认", "同", "告", "诉", "偿"}

    def extract(self, case_input) -> FactLock:
        """从 CaseInput 提取事实锁。"""
        text = self._build_materials(case_input)

        return FactLock(
            time_facts=self._extract_time_facts(text),
            entity_facts=self._extract_entity_facts(text),
            action_facts=self._extract_action_facts(text),
            document_facts=self._extract_document_facts(case_input),
            user_claims=self._extract_user_claims(case_input),
            prohibited_facts=self._build_prohibited_facts(text),
        )

    def _build_materials(self, case_input) -> str:
        parts: list[str] = []
        if hasattr(case_input, "case_title") and case_input.case_title:
            parts.append(f"案由：{case_input.case_title}")
        if hasattr(case_input, "facts") and case_input.facts:
            parts.append(f"事实：{case_input.facts}")
        if hasattr(case_input, "evidence") and case_input.evidence:
            parts.append(f"证据：{case_input.evidence}")
        if hasattr(case_input, "claims") and case_input.claims:
            parts.append(f"诉讼请求：{case_input.claims}")
        return "\n".join(parts)

    def _extract_time_facts(self, text: str) -> list[str]:
        """提取含时间的关键事实句。"""
        facts: list[str] = []
        for sent in re.split(r"[。；\n]", text):
            sent = sent.strip()
            if not sent:
                continue
            if self._TIME_RE.search(sent):
                # 清理过长句子，保留核心信息
                clean = sent[:120] if len(sent) > 120 else sent
                if clean not in facts:
                    facts.append(clean)
        return facts

    def _extract_entity_facts(self, text: str) -> list[str]:
        """提取当事人主体信息。"""
        facts: list[str] = []
        # 显式标注的主体（如"原告：张三"）
        for m in re.finditer(r"(原告|被告|证人|第三人|出借人|借款人)[是为：:]\s*([^，。；\n\s]{2,8})", text):
            name = m.group(2).strip()
            # 过滤掉过短或包含动词的误匹配
            if len(name) >= 2 and not any(kw in name for kw in ("通过", "辩称", "主张", "起诉", "归还")):
                facts.append(f"{m.group(1)}：{name}")
        return list(dict.fromkeys(facts))

    def _extract_action_facts(self, text: str) -> list[str]:
        """提取包含行为动词的关键句。"""
        facts: list[str] = []
        for sent in re.split(r"[。；\n]", text):
            sent = sent.strip()
            if len(sent) >= 8 and any(kw in sent for kw in self._ACTION_KWS):
                facts.append(sent)
        return list(dict.fromkeys(facts))

    def _extract_document_facts(self, case_input) -> list[str]:
        """提取用户已提供的证据清单。"""
        ev = getattr(case_input, "evidence", None)
        if not ev:
            return []
        items = re.split(r"\n\s*\d+[.、.]\s*|\n\s*-\s*", ev)
        return [i.strip() for i in items if i.strip()]

    def _extract_user_claims(self, case_input) -> list[str]:
        """提取原告诉讼请求。"""
        cl = getattr(case_input, "claims", None)
        if not cl:
            return []
        items = re.split(r"\n\s*\d+[.、.]\s*|\n\s*-\s*|；", cl)
        return [i.strip() for i in items if i.strip()]

    def _build_prohibited_facts(self, text: str) -> list[str]:
        """根据案件材料推断明确禁止编造的事实。"""
        prohibited: list[str] = []

        # 还款/支付相关
        if "未还" in text or "逾期未还" in text or "未归还" in text:
            prohibited.append("不得编造被告已还款的银行转账凭证、收据、收条等")
        if "未支付" in text or "拖欠" in text:
            prohibited.append("不得编造被告已支付款项的凭证")

        # 违约相关
        if "违约" in text and "未违约" not in text:
            prohibited.append("不得编造证明被告未违约的证据（除非有合理抗辩理由）")

        # 时间约束：禁止编造最早时间之前的关键协议
        times: list[str] = []
        for m in self._TIME_RE.finditer(text):
            times.append(m.group(1))
        if times:
            prohibited.append(
                f"不得编造发生在 {times[0]} 之前的'书面协议''合同''借条'等关键文件（除非材料明确支持）"
            )

        return prohibited


# ── 第二层：证据类型约束 ──────────────────────────────────

EVIDENCE_TYPE_WHITELIST: dict[str, dict] = {
    "借款合同纠纷": {
        "allowed": [
            "被告主张款项为投资/合作的聊天记录（需有原始载体说明）",
            "被告方证人证言（证人须与当事人有合理关系，能出庭）",
            "项目计划、费用支出等投资相关资料",
            "被告与原告之间的其他沟通记录",
            "被告对款项性质的书面说明或单方记录",
        ],
        "forbidden": [
            "伪造的银行还款凭证（转账截图、流水记录）",
            "不存在的书面借条/借款合同",
            "无合理关联的第三人代还款记录",
            "伪造的微信/支付宝转账截图",
            "国家机关出具的虚假证明文件",
        ],
        "chain_requirements": (
            "如主张'10万元是投资款'，必须同时提供三组证据："
            "①投资合意证据（如双方讨论投资的聊天记录）；"
            "②投资项目证据（如项目计划、费用支出）；"
            "③风险分担证据（如双方约定'共担风险'的记录）。"
            "禁止仅编造单一孤证。"
        ),
    },
    "买卖合同纠纷": {
        "allowed": [
            "质量异议函、验收记录",
            "交货单、物流单据",
            "被告方质检报告",
            "双方关于质量/交货的沟通记录",
            "行业标准或合同约定的质量规范",
        ],
        "forbidden": [
            "伪造的付款凭证",
            "不存在的合同补充协议",
            "伪造的第三方检测报告",
        ],
        "chain_requirements": (
            "如主张'货物质量合格'，必须同时提供：验收记录+质检标准+双方确认记录。"
            "禁止仅编造单一孤证。"
        ),
    },
    "劳动争议": {
        "allowed": [
            "考勤记录、工资发放记录",
            "解除劳动合同通知",
            "被告方证人（同事）证言",
            "公司规章制度",
            "绩效考核记录",
        ],
        "forbidden": [
            "伪造的工伤鉴定报告",
            "不存在的劳动合同（如原告主张未签）",
            "伪造的社保缴纳记录",
        ],
        "chain_requirements": (
            "如主张'合法解除'，必须同时提供：解除依据+程序合规证据+送达记录。"
            "禁止仅编造单一孤证。"
        ),
    },
}


def _normalize_case_type(case_type: str) -> str:
    if not case_type:
        return ""
    ct = case_type.lower()
    if "借款" in ct or "借贷" in ct:
        return "借款合同纠纷"
    if "买卖" in ct:
        return "买卖合同纠纷"
    if "劳动" in ct or "工伤" in ct or "解雇" in ct:
        return "劳动争议"
    if "合同" in ct:
        return "买卖合同纠纷"  # 兜底
    return case_type


class EvidenceConstraintBuilder:
    """构建带约束的证据生成 prompt（第二层约束：证据类型 + 证据链）"""

    def __init__(self, case_type: str = "", intensity: int = 3):
        self.case_type = _normalize_case_type(case_type)
        self.intensity = max(1, min(5, intensity))

    def _get_whitelist(self) -> dict:
        """根据对抗强度动态调整证据类型白名单/黑名单。"""
        base = EVIDENCE_TYPE_WHITELIST.get(self.case_type, {})
        if not base:
            return base

        allowed = list(base.get("allowed", []))
        forbidden = list(base.get("forbidden", []))

        if self.intensity <= 2:
            # 保守：仅允许单方说明和对现有记录的不同解读
            allowed = [
                "被告对款项/事实性质的书面说明或单方记录",
                "对现有聊天记录、证据的合理解释和不同解读",
            ]
            forbidden.extend([
                "新编造的证人证言",
                "新编造的项目资料、投资计划",
                "任何新编造的聊天记录（除对现有记录的不同解读外）",
            ])
        elif self.intensity == 3:
            pass  # 默认行为，不做额外调整
        elif self.intensity == 4:
            allowed.extend([
                "会议纪要复印件（需说明来源）",
                "往来函件、通知复印件（需说明是否原件核对）",
            ])
            if "伪造的国家机关出具的证明文件" not in forbidden:
                forbidden.append("伪造的国家机关出具的证明文件")
        elif self.intensity >= 5:
            allowed.extend([
                "会议纪要复印件（需说明来源）",
                "往来函件、通知复印件（需说明是否原件核对）",
                "被告声称已发送但被原告否认的通知、函件、催款记录",
            ])
            if "伪造的国家机关出具的证明文件" not in forbidden:
                forbidden.append("伪造的国家机关出具的证明文件")

        return {
            "allowed": allowed,
            "forbidden": forbidden,
            "chain_requirements": base.get("chain_requirements", ""),
        }

    def _intensity_notes(self) -> str:
        """根据对抗强度生成提示语。"""
        labels = {1: "保守", 2: "保守", 3: "平衡", 4: "激进", 5: "激进"}
        label = labels.get(self.intensity, "平衡")
        notes = f"\n## 对抗强度设置：{self.intensity}（{label}）\n"
        if self.intensity <= 2:
            notes += (
                "- 被告证据编造受到严格限制，主要依赖对现有事实的合理解释和抗辩\n"
                "- 禁止编造新的聊天记录、证人证言、项目资料\n"
                "- 时间红线严格：任何早于最早日期的电子数据（含聊天记录）亦不得编造\n"
            )
        elif self.intensity == 3:
            notes += (
                "- 被告允许编造聊天记录、证人证言、项目资料等对抗性证据\n"
                "- 禁止编造银行还款凭证、书面借条/合同等关键书证\n"
            )
        elif self.intensity >= 4:
            notes += (
                "- 被告可编造更多类型的对抗性证据（含会议纪要、往来函件复印件等）\n"
                "- 时间红线适度放宽：聊天记录可接受略早于最早日期（须合理说明）\n"
                "- 禁止编造银行还款凭证、国家机关书证等硬约束始终生效\n"
            )
        return notes

    def build_prompt(self, fact_lock: FactLock) -> str:
        """构建完整的约束 prompt，将直接附加到证据目录生成任务中。"""
        lines: list[str] = []

        # 1. 事实锁
        lines.append(fact_lock.to_prompt())

        # 2. 禁止事项（硬约束）
        lines.append("\n## 禁止事项（ HARD CONSTRAINTS —— 绝对不可违背 ）")
        lines.append("1. **不得编造与上述'事实锁'直接矛盾的证据**。如果事实锁中未提及某事实，不得编造证明该事实存在的证据。")
        lines.append("2. **不得编造涉及案件以外第三方的关键证据**（除非有合理关联）。")
        lines.append("3. **不得编造声称'已还款''已履行'等直接否定原告诉请的虚假凭证**。")
        lines.append("4. **不得编造无法当庭出示原始载体的电子数据**。")
        lines.append("5. **时间红线**：如果事实锁中最早的明确日期为 X，则**任何发生在 X 之前的书证、电子数据、协议、合同、计划书均不得编造**。唯一的例外是：材料中已明确提及该日期前存在某文件。")
        lines.append("6. **每项证据必须有具体的'证据来源'说明**，禁止模糊表述如'相关记录''有关文件'。")

        # 3. 对抗强度说明
        lines.append(self._intensity_notes())

        # 4. 证据类型白名单（动态调整）
        whitelist = self._get_whitelist()
        if whitelist:
            lines.append(f"\n## 证据类型约束（案件类型：{self.case_type}）")
            lines.append("### 允许编造的对抗性证据类型")
            for t in whitelist["allowed"]:
                lines.append(f"- {t}")
            lines.append("\n### 禁止编造的证据类型")
            for t in whitelist["forbidden"]:
                lines.append(f"- {t}")
            lines.append(f"\n### 证据链完整性要求")
            lines.append(whitelist["chain_requirements"])
        else:
            lines.append("\n## 证据类型约束")
            lines.append("允许编造：与案件相关的聊天记录、证人证言、书面说明等")
            lines.append("禁止编造：银行转账凭证、国家机关出具的书证、涉及第三方的关键证据")

        # 5. 证据来源要求
        lines.append("\n## 证据来源要求（每项必须说明）")
        lines.append("- 电子数据：必须声称有原始载体（手机/电脑），可当庭展示")
        lines.append("- 书证复印件：必须说明是否有原件核对")
        lines.append("- 证人证言：证人必须能出庭作证，需说明证人身份、与当事人关系")
        lines.append("- 单方记录：需说明制作时间、地点、保存方式")

        # 6. 允许编造的范围（明确给 LLM 自由度）
        lines.append("\n## 允许编造的范围（在此范围内发挥对抗性）")
        lines.append("- 被告对款项/事实性质的不同解读（如借款→投资款、合作款）")
        lines.append("- 被告与原告之间的其他沟通记录（需符合双方角色设定，时间在案件时间框架内）")
        lines.append("- 被告方的证人证言（需符合证人资格要求，能出庭）")
        lines.append("- 被告对事实的合理解释和补充说明（不得与事实锁矛盾）")

        return "\n".join(lines)


# ── 第三层：一致性验证（P2）────────────────────────────────

class ConsistencyChecker:
    """一致性验证模块 —— 验证生成证据与事实锁的矛盾（需要额外 LLM 调用）

    建议在生成后调用，发现矛盾时触发修正。
    """

    def __init__(self, intensity: int = 3):
        self.intensity = max(1, min(5, intensity))

    _CHECK_PROMPT = """你是一名严谨的事实核查员，专门检测证据与已知事实之间的矛盾。

【已知事实】
{facts}

【待核查证据】
{evidence}

【判断标准】
- "矛盾"：证据内容与已知事实直接冲突（如时间相反、主体错误、行为矛盾、金额不符）
- "不一致"：证据添加了未知细节，但不与已知事实直接冲突
- "一致"：证据内容与已知事实不冲突

【输出格式】
判断：（矛盾/不一致/一致）
冲突点：（如有，请具体说明）
建议修改：（如果矛盾，请建议如何修改使其合理）
"""

    async def check_evidence(self, evidence_text: str, fact_lock: FactLock) -> dict:
        """对单条证据进行一致性检查。

        Returns:
            {"verdict": "矛盾"|"不一致"|"一致", "raw_result": str}
        """
        import re

        # -- 前置快速检查：时间红线 --
        earliest_date = None
        for pf in fact_lock.prohibited_facts:
            m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', pf)
            if m:
                earliest_date = m.group(1)
                break
        if earliest_date:
            # 根据对抗强度调整时间红线严格度
            if self.intensity <= 2:
                # 保守：电子数据也纳入红线
                doc_keywords = ("协议", "合同", "计划书", "意向书", "备忘录", "确认函", "聊天记录", "微信", "短信")
            elif self.intensity >= 4:
                # 激进：仅核心书证纳入红线
                doc_keywords = ("协议", "合同", "计划书", "意向书", "备忘录", "确认函", "书证")
            else:
                doc_keywords = ("协议", "合同", "计划书", "意向书", "备忘录", "确认函")
            if any(kw in evidence_text for kw in doc_keywords):
                dates_in_ev = re.findall(r'\d{4}年\d{1,2}月\d{1,2}日', evidence_text)
                if dates_in_ev:
                    try:
                        earliest = self._parse_date(earliest_date)
                        for d in dates_in_ev:
                            if self._parse_date(d) < earliest:
                                return {
                                    "verdict": "矛盾",
                                    "raw_result": (
                                        f"该证据日期为 {d}，早于案件已知事实的最早日期 {earliest_date}。"
                                        f"根据约束，不得编造发生在 {earliest_date} 之前的书证/协议/合同/计划书等关键文件。"
                                    ),
                                }
                    except Exception:
                        pass

        all_facts = (
            fact_lock.time_facts
            + fact_lock.entity_facts
            + fact_lock.action_facts
            + fact_lock.document_facts
            + fact_lock.prohibited_facts
        )
        if not all_facts:
            return {"verdict": "一致", "raw_result": "无已知事实可供比对"}

        facts_text = "\n".join(f"- {f}" for f in all_facts)
        prompt = self._CHECK_PROMPT.format(facts=facts_text, evidence=evidence_text)

        result = await llm_call(
            system_prompt="你是一名严谨的事实核查员。只依据已知事实判断，不推断未知信息。",
            messages=[{"role": "user", "content": prompt}],
        )

        verdict = "一致"
        if "矛盾" in result:
            verdict = "矛盾"
        elif "不一致" in result:
            verdict = "不一致"

        return {"verdict": verdict, "raw_result": result}

    @staticmethod
    def _parse_date(date_str: str) -> tuple[int, int, int]:
        import re
        m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
        if not m:
            raise ValueError(f"无法解析日期: {date_str}")
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    async def check_catalog(self, catalog_text: str, fact_lock: FactLock) -> list[dict]:
        """对证据目录批量检查，返回所有存在矛盾的证据项。"""
        items = self._extract_items(catalog_text)

        conflicts: list[dict] = []
        for item in items:
            result = await self.check_evidence(item, fact_lock)
            if result["verdict"] == "矛盾":
                conflicts.append({"item": item, **result})
        return conflicts

    def _extract_items(self, catalog_text: str) -> list[str]:
        """从证据目录文本中提取单条证据描述（多策略）。"""
        items: list[str] = []
        lines = catalog_text.split("\n")

        # 策略1：Markdown 表格行（| 编号 | 名称 | 类型 | ...）
        for line in lines:
            line = line.strip()
            if line.startswith("|") and not line.startswith("|---"):
                cells = [c.strip() for c in line.split("|")]
                cells = [c for c in cells if c]
                if len(cells) >= 2:
                    # 取编号+名称列作为证据标识
                    items.append(f"{cells[0]}. {cells[1]}")

        # 策略2："### 证据X：..." 格式
        for line in lines:
            line = line.strip()
            m = re.search(r"###\s*证据\s*\d+[：:]\s*(.+)", line)
            if m:
                items.append(m.group(1))

        # 策略3：包含时间+证据关键词的行（去重）
        seen = set(items)
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("|") or line.startswith("-"):
                continue
            if any(kw in line for kw in ("证据", "记录", "截图", "证言", "协议", "合同", "聊天", "计划书", "说明")):
                if line not in seen and len(line) > 10:
                    items.append(line)
                    seen.add(line)

        return items
