"""
Case Ontology 提取器

从 CaseInput / TrialSession 中提取结构化 Ontology 对象。
首期以规则提取为主，保证稳定可用；后续可用 LLM 增强复杂案由。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from ..models.case import CaseInput
from ..orchestration.workflow import TrialSession, PHASE_LABELS
from .models import (
    CaseObject,
    Party,
    Claim,
    Fact,
    Evidence,
    LegalNorm,
    Issue,
    Decision,
    ActionItem,
    CaseOntology,
)


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _extract_parties_from_text(text: str) -> list[tuple[str, str]]:
    """从文本中尝试抽取原告/被告名称（简单规则）"""
    parties: list[tuple[str, str]] = []
    # 匹配「原告：XXX」或「原告：XXX公司」
    plaintiff_match = re.search(r"原告[：:]\s*([^，,。；;\n]{2,30})", text)
    if plaintiff_match:
        parties.append(("plaintiff", plaintiff_match.group(1).strip()))
    defendant_match = re.search(r"被告[：:]\s*([^，,。；;\n]{2,30})", text)
    if defendant_match:
        parties.append(("defendant", defendant_match.group(1).strip()))
    return parties


def _infer_case_type(title: str) -> str:
    """根据标题推断案由"""
    keywords = {
        "借款": "民间借贷纠纷",
        "借贷": "民间借贷纠纷",
        "劳动": "劳动争议",
        "合同": "合同纠纷",
        "买卖": "买卖合同纠纷",
        "租赁": "房屋租赁合同纠纷",
        "侵权": "侵权责任纠纷",
        "离婚": "离婚纠纷",
        "继承": "继承纠纷",
        "交通": "机动车交通事故责任纠纷",
    }
    for kw, ctype in keywords.items():
        if kw in title:
            return ctype
    return "民事纠纷"


def _split_lines(text: str) -> list[str]:
    """按行拆分并清理空行"""
    return [line.strip() for line in text.replace("\r", "\n").split("\n") if line.strip()]


def _extract_legal_norms(text: str, case_id: str) -> list[LegalNorm]:
    """从文本中提取法条引用（《法规》第X条）"""
    norms: list[LegalNorm] = []
    # 匹配《XXX》第XX条、第XX条之一、第XX款、第XX项
    pattern = re.compile(r"《([^《》]{2,30})》\s*第\s*([一二三四五六七八九十百零〇0-9]+)\s*条(?:\s*之\s*一)?(?:\s*第\s*([一二三四五六七八九十0-9]+)\s*款)?(?:\s*第\s*([一二三四五六七八九十0-9]+)\s*项)?")
    seen = set()
    for m in pattern.finditer(text):
        source = m.group(1).strip()
        article = f"第{m.group(2)}条"
        if m.group(3):
            article += f"第{m.group(3)}款"
        if m.group(4):
            article += f"第{m.group(4)}项"
        key = f"{source}|{article}"
        if key in seen:
            continue
        seen.add(key)
        norms.append(LegalNorm(
            id=_uid("ln_"),
            case_id=case_id,
            source=source,
            article=article,
            text="",
            role="principal",
            confidence=0.7,
        ))
    return norms


def _extract_issues(text: str, case_id: str) -> list[Issue]:
    """从 phase5_issues 中提取争议焦点"""
    issues: list[Issue] = []
    lines = _split_lines(text)
    # 去掉常见标题行
    for line in lines:
        if any(skip in line for skip in ["争议焦点", "本案", "归纳", "如下"]):
            continue
        # 去掉序号前缀
        clean = re.sub(r"^\d+[.、)）]\s*", "", line)
        clean = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", clean)
        if len(clean) < 5:
            continue
        issues.append(Issue(
            id=_uid("iss_"),
            case_id=case_id,
            title=clean[:80],
            description=clean,
            issue_type="mixed",
            priority=max(1, min(5, 6 - len(issues))),
        ))
    return issues


def extract_from_case_input(case: CaseInput) -> CaseOntology:
    """从 CaseInput 提取基础 Ontology"""
    case_id = _uid("case_")
    case_obj = CaseObject(
        id=case_id,
        title=case.case_title,
        case_type=_infer_case_type(case.case_title),
        mode=case.mode,  # type: ignore[arg-type]
        user_side=case.user_side,  # type: ignore[arg-type]
        status="draft",
        raw_materials=case.source_materials,
    )

    # 当事人
    parties: list[Party] = []
    # 1. 尝试从 case_title 抽取
    party_candidates = _extract_parties_from_text(case.case_title)
    # 2. 回退：从 facts/claims 抽取
    if len(party_candidates) < 2:
        party_candidates = _extract_parties_from_text(case.facts + "\n" + case.claims)
    # 去重
    seen_names = set()
    for role, name in party_candidates:
        if name in seen_names:
            continue
        seen_names.add(name)
        parties.append(Party(
            id=_uid("pty_"),
            case_id=case_id,
            role=role,  # type: ignore[arg-type]
            name=name,
        ))
    # 若未抽到，按模式兜底
    if not parties and case.mode == "asymmetric":
        if case.user_side == "plaintiff":
            parties.append(Party(id=_uid("pty_"), case_id=case_id, role="plaintiff", name="我方（原告）"))
            parties.append(Party(id=_uid("pty_"), case_id=case_id, role="defendant", name="对方（被告）"))
        elif case.user_side == "defendant":
            parties.append(Party(id=_uid("pty_"), case_id=case_id, role="plaintiff", name="对方（原告）"))
            parties.append(Party(id=_uid("pty_"), case_id=case_id, role="defendant", name="我方（被告）"))

    # 事实：按句子拆分
    facts: list[Fact] = []
    sentences = re.split(r"(?<=[。；;!！?？])\s+", case.facts)
    for s in sentences:
        s = s.strip()
        if len(s) < 8:
            continue
        facts.append(Fact(
            id=_uid("fact_"),
            case_id=case_id,
            description=s,
        ))

    # 诉讼请求 / 主张
    claims: list[Claim] = []
    for line in _split_lines(case.claims):
        # 识别被告抗辩
        claim_type: str = "principal"
        if any(k in line for k in ["被告", "答辩", "抗辩", "不认可", "不存在"]):
            claim_type = "defense"
        claims.append(Claim(
            id=_uid("claim_"),
            case_id=case_id,
            party_id=parties[0].id if parties and claim_type != "defense" else (parties[1].id if len(parties) > 1 else ""),
            claim_text=line,
            claim_type=claim_type,  # type: ignore[arg-type]
        ))

    # 证据
    evidence: list[Evidence] = []
    for i, line in enumerate(_split_lines(case.evidence), 1):
        # 简单解析「1. 证据名称（类型）—— 描述」
        m = re.match(r"\d+[.、)）]?\s*(.+?)(?:[（(]([^)）]+)[)）])?\s*(?:——|-|--|：)?\s*(.*)", line)
        name = m.group(1).strip() if m else f"证据{i}"
        ev_type = m.group(2).strip() if m and m.group(2) else "unknown"
        desc = m.group(3).strip() if m and m.group(3) else ""
        evidence.append(Evidence(
            id=_uid("ev_"),
            case_id=case_id,
            name=name,
            source_type="manual",
            content=line,
            summary=desc,
            evidence_type="document" if "书证" in ev_type or "合同" in name else "unknown",  # type: ignore[arg-type]
        ))

    # 法条：从 claims + facts 提取
    legal_norms = _extract_legal_norms(case.facts + "\n" + case.claims, case_id)

    return CaseOntology(
        case=case_obj,
        parties=parties,
        claims=claims,
        facts=facts,
        evidence=evidence,
        legal_norms=legal_norms,
    )


def enrich_from_trial_session(ontology: CaseOntology, session: TrialSession) -> CaseOntology:
    """基于 TrialSession 各阶段输出补充/更新 Ontology"""
    case_id = ontology.case.id

    # 更新案件状态与胜率
    ontology.case.status = "completed" if session.current_phase >= 8 else "running"

    # Phase 5：争议焦点
    if session.phase5_issues:
        ontology.issues = _extract_issues(session.phase5_issues, case_id)

    # Phase 1/3：法条
    for text in (session.phase1_analysis, session.phase3_analysis):
        if text:
            existing = {(n.source, n.article) for n in ontology.legal_norms}
            for norm in _extract_legal_norms(text, case_id):
                if (norm.source, norm.article) not in existing:
                    ontology.legal_norms.append(norm)
                    existing.add((norm.source, norm.article))

    # Phase 8：决策与行动项
    if session.phase8_judgment:
        ontology.decisions.append(Decision(
            id=_uid("dec_"),
            case_id=case_id,
            decision_type="strategy",
            title="判决方向预测",
            rationale=session.phase8_judgment[:500],
            made_by="ai",
            source_ref_ids=[i.id for i in ontology.issues],
        ))

        # 生成 ActionItem：基于缺失证据与未决问题
        for issue in ontology.issues:
            if issue.status == "open":
                ontology.action_items.append(ActionItem(
                    id=_uid("act_"),
                    case_id=case_id,
                    title=f"就「{issue.title[:30]}」补充证据或法律依据",
                    action_type="supplement_evidence",
                    priority="high" if issue.priority >= 4 else "medium",
                ))
        # 证据薄弱项
        for ev in ontology.evidence:
            if ev.authenticity < 0.5 or ev.legality < 0.5 or ev.relevance < 0.5:
                ontology.action_items.append(ActionItem(
                    id=_uid("act_"),
                    case_id=case_id,
                    title=f"补强证据「{ev.name[:30]}」的三性说明",
                    action_type="supplement_evidence",
                    priority="medium",
                ))

    return ontology


def build_ontology(session: TrialSession) -> CaseOntology:
    """从 TrialSession 构建完整 Ontology"""
    ontology = extract_from_case_input(session.case_input)
    return enrich_from_trial_session(ontology, session)


def build_ontology_from_case_input(case: CaseInput) -> CaseOntology:
    """仅基于 CaseInput 构建基础 Ontology"""
    return extract_from_case_input(case)
