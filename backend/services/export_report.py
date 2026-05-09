"""
庭审报告导出服务

生成 Markdown 格式的完整庭审报告，支持：
- 律师下载后用于其他 LLM 交互
- 存档复盘
"""

from datetime import datetime
from ..orchestration.graph import TrialSession, PHASE_LABELS


def export_markdown(session: TrialSession) -> str:
    """生成完整庭审报告的 Markdown 文本"""
    case = session.case_input
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 模拟法庭庭审报告",
        f"",
        f"**生成时间**：{now}",
        f"**案由**：{case.case_title}",
        f"**代理模式**：{session.user_role}",
        f"",
        f"---",
        f"",
        f"## 案卷信息",
        f"",
        f"### 案情事实",
        f"",
        f"{case.facts}",
        f"",
        f"### 证据清单",
        f"",
        f"{case.evidence}",
        f"",
        f"### 诉讼请求",
        f"",
        f"{case.claims}",
        f"",
        f"---",
        f"",
    ]

    # Phase 1
    if session.phase1_analysis:
        lines += [
            f"## 阶段一：{PHASE_LABELS[1]}",
            f"",
            f"{session.phase1_analysis}",
            f"",
        ]

    # Phase 2
    if session.phase2_complaint:
        lines += [
            f"## 阶段二：{PHASE_LABELS[2]}",
            f"",
            f"{session.phase2_complaint}",
            f"",
        ]

    # Phase 3
    if session.phase3_analysis:
        lines += [
            f"## 阶段三：{PHASE_LABELS[3]}",
            f"",
            f"{session.phase3_analysis}",
            f"",
        ]

    # Phase 4
    if session.phase4_answer:
        lines += [
            f"## 阶段四：{PHASE_LABELS[4]}",
            f"",
            f"{session.phase4_answer}",
            f"",
        ]

    # Phase 5
    if session.phase5_issues:
        lines += [
            f"## 阶段五：{PHASE_LABELS[5]}",
            f"",
            f"{session.phase5_issues}",
            f"",
        ]

    # Phase 6
    if session.phase6_cross_exam or session.phase6_evidence_exam:
        lines += [
            f"## 阶段六：{PHASE_LABELS[6]}",
            f"",
            f"### 交叉询问",
            f"",
        ]
        if session.phase6_cross_exam:
            # 尝试美化 JSON 为人类可读格式
            try:
                import json
                messages = json.loads(session.phase6_cross_exam)
                for msg in messages:
                    role_map = {
                        "plaintiff": "原告律师",
                        "defendant": "被告律师",
                        "judge": "法官",
                    }
                    type_map = {
                        "question": "提问",
                        "answer": "回答",
                        "guidance": "引导",
                    }
                    speaker = role_map.get(msg.get("speaker", ""), msg.get("speaker", ""))
                    qtype = type_map.get(msg.get("type", ""), msg.get("type", ""))
                    lines.append(
                        f"**{speaker}**（{qtype}）：{msg.get('content', '')}"
                    )
                    lines.append("")
            except (json.JSONDecodeError, Exception):
                lines.append(session.phase6_cross_exam)
                lines.append("")

        lines += [
            f"",
            f"### 举证质证",
            f"",
            session.phase6_evidence_exam,
            f"",
        ]

    # Phase 7
    if session.phase7_plaintiff_final or session.phase7_defendant_final:
        lines += [
            f"## 阶段七：{PHASE_LABELS[7]}",
            f"",
            f"### 原告最后陈述",
            f"",
            session.phase7_plaintiff_final,
            f"",
            f"### 被告最后陈述",
            f"",
            session.phase7_defendant_final,
            f"",
        ]

    # Phase 8
    if session.phase8_judgment:
        lines += [
            f"## 阶段八：{PHASE_LABELS[8]}",
            f"",
            session.phase8_judgment,
            f"",
            f"---",
            f"",
            f"*本报告由 AI 模拟法庭系统自动生成，仅供参考，不构成法律意见。*",
            f"",
        ]

    return "\n".join(lines)


def export_plaintext(session: TrialSession) -> str:
    """纯文本导出（去 Markdown 标记）"""
    md = export_markdown(session)
    import re
    # 去除 Markdown 标记但保留结构
    md = re.sub(r"^#+\s+", "", md, flags=re.MULTILINE)
    md = re.sub(r"\*\*([^*]+)\*\*", r"\1", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md)
    return md
