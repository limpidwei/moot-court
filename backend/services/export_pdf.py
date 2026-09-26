"""
PDF 报告导出服务

使用 reportlab + matplotlib 生成高质量 PDF：
- reportlab 原生支持中文 CID 字体，避免乱码
- matplotlib 渲染矢量图表，保证清晰度
- 支持富文本格式（标题、加粗、列表）
"""

import io
import json
import re
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image,
    Table, TableStyle, KeepTogether, ListFlowable, ListItem
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.fonts import addMapping

from ..orchestration.workflow import TrialSession, PHASE_LABELS
from ..orchestration.analysis import CaseAnalysis


# 注册中文字体
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
pdfmetrics.registerFont(UnicodeCIDFont('MSung-Light'))


def _get_viz_by_type(_analysis: CaseAnalysis, _viz_type: str) -> dict | None:
    """可视化数据提取（已废弃，保留函数签名兼容）。"""
    # 可视化功能已下线，PDF 导出不再嵌入图表
    return None


# ---------------------------------------------------------------------------
# 2026-09-26 viz 恢复（demo 导向）：从 session 已有庭审产出组装图表数据。
# 全部数据来自真实庭审阶段字段（facts / phase8_judgment / evidence_list / claims），
# 零 LLM 调用；无数据时对应图表优雅跳过。
# ---------------------------------------------------------------------------

_DATE_EVENT_RE = re.compile(r"(\d{4}年\d{1,2}月\d{1,2}日)[，,]?\s*([^；。\n]{4,60})")
_DIM_SCORE_RE = re.compile(r"\*{0,2}([^|\n*]{2,20})\*{0,2}\s*\|\s*\*{0,2}\s*(\d{1,3})\s*分")
_LAW_ARTICLE_RE = re.compile(r"《[^》]{2,30}》第[零一二三四五六七八九十百千\d]+条")


def _viz_from_session(session: TrialSession, analysis: CaseAnalysis, viz_type: str) -> dict | None:
    """按 viz_type 从 session 组装图表数据；数据不足时返回 None（图表跳过）。"""
    ci = getattr(session, "case_input", None)
    facts = (getattr(ci, "facts", "") or "") if ci is not None else ""
    judgment = getattr(session, "phase8_judgment", "") or ""

    if viz_type == "timeline":
        if not facts:
            return None
        events = []
        for m in _DATE_EVENT_RE.finditer(facts):
            date, label = m.group(1), m.group(2).strip()
            if any(k in label for k in ("合同", "协议", "签约")):
                etype = "contract"
            elif any(k in label for k in ("不良", "缺陷", "未达", "不符", "违约", "故障")):
                etype = "breach"
            elif any(k in label for k in ("解除", "函", "检测", "委托", "协商", "会议")):
                etype = "action"
            else:
                etype = "other"
            events.append({"date": date, "label": label, "type": etype})
        return {"events": events[:12]} if events else None

    if viz_type == "win_rate_radar":
        # 维度分优先读 analysis 结构化字段（新案件），旧案件从判决书"胜率评估"表格解析
        dims_raw = getattr(analysis, "win_rate_dimensions", None) or {}
        dims = []
        if isinstance(dims_raw, dict) and dims_raw:
            for name, score in dims_raw.items():
                try:
                    s = float(score)
                except (TypeError, ValueError):
                    continue
                if 0 < s <= 100:
                    dims.append({"name": str(name)[:10], "score": s})
        if not dims and judgment:
            idx = judgment.find("胜率评估")
            seg = judgment[idx: idx + 1500] if idx >= 0 else judgment
            for m in _DIM_SCORE_RE.finditer(seg):
                name = m.group(1).strip().strip("*").strip()
                try:
                    score = float(m.group(2))
                except ValueError:
                    continue
                if 0 < score <= 100 and name and "综合" not in name:
                    dims.append({"name": name, "score": score})
        if not dims:
            return None
        overall = float(getattr(session, "phase8_win_rate", 0.0) or 0.0)
        return {"dimensions": dims[:6], "overall": overall}

    if viz_type == "evidence_chain":
        raw = getattr(session, "evidence_list", None) or []
        items = []
        for i, e in enumerate(raw):
            if isinstance(e, dict):
                items.append({
                    "id": str(e.get("id", f"E{i + 1}")),
                    "name": str(e.get("name", ""))[:22] or f"证据{i + 1}",
                    "strength": e.get("strength", "medium"),
                })
            elif isinstance(e, str) and e.strip():
                # 旧格式："《名称》（类型）—— 描述"；名称取"（"前部分
                text = e.strip()
                name = re.split(r"[（(]", text)[0].strip()[:22] or text[:22]
                # 强度启发式：鉴定/检测类证据证明力标注为 strong，仅影响配色，不做事实判断
                strength = "strong" if any(k in text for k in ("检测报告", "鉴定", "判决")) else "medium"
                items.append({"id": f"E{i + 1}", "name": name, "strength": strength})
        return {"items": items, "chains": []} if items else None

    if viz_type == "claim_basis_tree":
        claims_text = (getattr(ci, "claims", "") or "") if ci is not None else ""
        claim_list = [re.sub(r"^\d+[\.、]\s*", "", c.strip()) for c in re.split(r"[\n;；]", claims_text) if c.strip()]
        if not claim_list:
            return None
        laws = _LAW_ARTICLE_RE.findall(judgment)
        main_law = next((law for law in laws if "民法典" in law), (laws[0] if laws else ""))
        # 判决主文（"判决如下"之后）出现的请求视为被支持（established）
        holding_seg = ""
        hidx = judgment.find("判决如下")
        if hidx >= 0:
            holding_seg = judgment[hidx: hidx + 900]
        children = []
        for c in claim_list[:4]:
            label = c.strip("，。；、")[:20]
            if not label:
                continue
            status = "unknown"
            if holding_seg:
                key = label[:6]
                status = "established" if key in holding_seg else "disputed"
            children.append({"label": label, "law": "", "status": status})
        if not children:
            return None
        return {"root": {"label": "请求权基础", "law": main_law, "status": "established", "children": children}}

    return None

# 颜色定义
PRIMARY_COLOR = HexColor('#2563eb')
# matplotlib 不接受 reportlab HexColor 对象，渲染函数用原生 hex 字符串
VIZ_PRIMARY = '#2563eb'
SUCCESS_COLOR = HexColor('#10b981')
WARNING_COLOR = HexColor('#f59e0b')
DANGER_COLOR = HexColor('#ef4444')
GRAY_COLOR = HexColor('#6b7280')


def _setup_matplotlib_chinese():
    """配置 matplotlib 中文字体"""
    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False


def _render_timeline_chart(events: list[dict]) -> Optional[io.BytesIO]:
    """渲染时间轴图表"""
    if not events:
        return None

    _setup_matplotlib_chinese()
    fig, ax = plt.subplots(figsize=(16, 6))

    # 交错显示标签
    for i, event in enumerate(events):
        y_pos = 1 if i % 2 == 0 else -1

        # 绘制节点
        color = '#3b82f6' if event.get('type') == 'contract' else \
                '#ef4444' if event.get('type') == 'breach' else \
                '#10b981' if event.get('type') == 'action' else '#6b7280'

        ax.scatter(i, 0, s=200, c=color, zorder=5, edgecolors='white', linewidth=2)

        # 绘制连接线
        ax.plot([i, i], [0, y_pos * 0.3], color=color, linewidth=2, zorder=4)

        # 绘制标签（交错上下）
        date_text = event.get('date', '')
        label_text = event.get('label', '')
        evidence_text = event.get('evidence', '')

        full_text = f"{date_text}\n{label_text}"
        if evidence_text:
            full_text += f"\n{evidence_text}"

        ax.text(i, y_pos * 0.5, full_text, ha='center', va='center' if y_pos > 0 else 'top',
                fontsize=9, wrap=True,
                bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor=color, linewidth=2))

    # 设置坐标轴
    ax.axhline(y=0, color='gray', linewidth=1, linestyle='--', zorder=1)
    ax.set_xlim(-0.5, len(events) - 0.5)
    ax.set_ylim(-1.5, 1.5)
    ax.axis('off')

    plt.tight_layout()

    # 保存到内存（P2 修复：plt.savefig 失败时确保 plt.close，避免 figure 泄漏）
    buf = io.BytesIO()
    try:
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
        buf.seek(0)
    finally:
        plt.close(fig)

    return buf


def _render_claim_basis_tree(tree_data: dict) -> Optional[io.BytesIO]:
    """渲染请求权基础树形图"""
    if not tree_data or 'root' not in tree_data:
        return None

    _setup_matplotlib_chinese()
    fig, ax = plt.subplots(figsize=(16, 10))

    def draw_node(node, x, y, level=0, parent_pos=None):
        """递归绘制节点"""
        label = node.get('label', '')
        law = node.get('law', '')
        status = node.get('status', 'unknown')

        # 状态颜色
        color_map = {
            'established': '#10b981',
            'disputed': '#f59e0b',
            'weak': '#ef4444',
            'unknown': '#6b7280'
        }
        color = color_map.get(status, '#6b7280')

        # 绘制节点框
        text = f"{label}\n{law}" if law else label
        bbox = FancyBboxPatch((x - 1.2, y - 0.3), 2.4, 0.6,
                              boxstyle="round,pad=0.1",
                              facecolor='white', edgecolor=color, linewidth=2)
        ax.add_patch(bbox)
        ax.text(x, y, text, ha='center', va='center', fontsize=9, wrap=True)

        # 绘制到父节点的连线
        if parent_pos:
            arrow = FancyArrowPatch(parent_pos, (x - 1.2, y),
                                   arrowstyle='->', mutation_scale=15,
                                   color='#9ca3af', linewidth=1.5)
            ax.add_patch(arrow)

        # 递归绘制子节点
        children = node.get('children', [])
        if children:
            child_y_start = y - 0.8
            child_y_step = 0.8
            for i, child in enumerate(children):
                child_y = child_y_start - i * child_y_step
                draw_node(child, x + 3, child_y, level + 1, (x + 1.2, y))

    root = tree_data['root']
    draw_node(root, 0, 2)

    # 设置坐标轴
    ax.set_xlim(-2, 12)
    ax.set_ylim(-6, 4)
    ax.axis('off')

    plt.tight_layout()

    buf = io.BytesIO()
    try:
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
        buf.seek(0)
    finally:
        plt.close(fig)

    return buf


def _render_win_rate_radar(dimensions: list[dict], overall: float) -> Optional[io.BytesIO]:
    """渲染胜率雷达图"""
    if not dimensions:
        return None

    _setup_matplotlib_chinese()

    categories = [d.get('name', '') for d in dimensions]
    values = [d.get('score', 0) for d in dimensions]

    # 闭合雷达图
    N = len(categories)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]
    values += values[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    # 绘制雷达图
    ax.plot(angles, values, 'o-', linewidth=2, color=VIZ_PRIMARY)
    ax.fill(angles, values, alpha=0.25, color=VIZ_PRIMARY)

    # 设置标签
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=11)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(['20', '40', '60', '80', '100'], fontsize=9)

    # 添加总分
    ax.set_title(f'综合胜率: {overall:.1f}%', fontsize=16, fontweight='bold', pad=20, color=VIZ_PRIMARY)

    plt.tight_layout()

    buf = io.BytesIO()
    try:
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
        buf.seek(0)
    finally:
        plt.close(fig)

    return buf


def _render_evidence_chain(items: list[dict], chains: list[dict]) -> Optional[io.BytesIO]:
    """渲染证据链图"""
    if not items:
        return None

    _setup_matplotlib_chinese()
    fig, ax = plt.subplots(figsize=(16, max(8, len(items) * 0.8)))

    # 绘制证据节点（左侧）
    evidence_y_positions = {}
    for i, item in enumerate(items):
        y = len(items) - i - 1
        evidence_id = item.get('id', f'E{i}')
        evidence_y_positions[evidence_id] = y

        name = item.get('name', '')
        strength = item.get('strength', 'medium')
        color_map = {'strong': '#10b981', 'medium': '#f59e0b', 'weak': '#ef4444'}
        color = color_map.get(strength, '#6b7280')

        bbox = FancyBboxPatch((0, y - 0.3), 4, 0.6,
                              boxstyle="round,pad=0.1",
                              facecolor='white', edgecolor=color, linewidth=2)
        ax.add_patch(bbox)
        ax.text(2, y, name, ha='center', va='center', fontsize=9, wrap=True)

    # 绘制法律要件节点（右侧）
    element_y_positions = {}
    for i, chain in enumerate(chains):
        y = len(chains) - i - 1
        element = chain.get('element', '')
        element_y_positions[element] = y

        sufficiency = chain.get('sufficiency', 'partial')
        color_map = {'sufficient': '#10b981', 'partial': '#f59e0b', 'insufficient': '#ef4444'}
        color = color_map.get(sufficiency, '#6b7280')

        bbox = FancyBboxPatch((8, y - 0.3), 4, 0.6,
                              boxstyle="round,pad=0.1",
                              facecolor='white', edgecolor=color, linewidth=2)
        ax.add_patch(bbox)
        ax.text(10, y, element, ha='center', va='center', fontsize=9, wrap=True)

        # 绘制连线
        for evidence_id in chain.get('evidence_ids', []):
            if evidence_id in evidence_y_positions:
                ey = evidence_y_positions[evidence_id]
                arrow = FancyArrowPatch((4, ey), (8, y),
                                       arrowstyle='->', mutation_scale=15,
                                       color='#9ca3af', linewidth=1.5)
                ax.add_patch(arrow)

    # 设置坐标轴（chains 为空时仅渲染证据节点，收窄画幅避免右侧留白）
    ax.set_xlim(-0.5, 12.5 if chains else 4.5)
    ax.set_ylim(-0.5, max(len(items), len(chains)) + 0.5)
    ax.axis('off')

    plt.tight_layout()

    buf = io.BytesIO()
    try:
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
        buf.seek(0)
    finally:
        plt.close(fig)

    return buf


import re
from html import escape

# 预编译正则表达式（行内 Markdown）
_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
_ITALIC_RE = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
_INLINE_CODE_RE = re.compile(r'`([^`]+)`')
_LIST_RE = re.compile(r'^(\s*)([-*+]|\d+\.)\s+(.*)$')
_HR_RE = re.compile(r'^\s*(---+|___+|\*\*\*+|\- \- \-|\* \* \*)\s*$')


def _inline_to_html(text: str) -> str:
    """将行内 Markdown 转换为 reportlab Paragraph 兼容的 HTML 子集。"""
    # 1. 把已有的 <br> 类标签统一换成换行符，后续按需恢复
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

    # 2. 暂存内联代码，防止被加粗/斜体等规则破坏
    code_map = {}
    def _save_code(m):
        key = f'\x00CODE{len(code_map)}\x00'
        code_map[key] = escape(m.group(1))
        return key
    text = _INLINE_CODE_RE.sub(_save_code, text)

    # 3. HTML 转义
    text = escape(text)

    # 4. Markdown → HTML（注意顺序：先加粗，再斜体，再链接）
    text = _BOLD_RE.sub(r'<b>\1</b>', text)
    text = _ITALIC_RE.sub(r'<i>\1</i>', text)
    text = _LINK_RE.sub(r'<a href="\2" color="#2563eb"><u>\1</u></a>', text)

    # 5. 恢复内联代码（使用等宽字体）
    for key, code in code_map.items():
        text = text.replace(
            key,
            f'<font face="Courier" size="9" color="#374151">{code}</font>',
            1
        )

    return text


def _markdown_to_flowables(text: str, styles) -> list:
    """
    将 Markdown 文本转换为 reportlab Flowable 对象（增强版）。

    支持的元素：
    - 标题 # / ## / ###
    - 有序 / 无序列表（支持嵌套）
    - 代码块 ```…```
    - 引用块 > …
    - 表格 | … |
    - 分隔线 --- / *** / ___
    - 行内：加粗 **…**、斜体 *…*、链接 […](…)、代码 `…`
    """
    lines = text.split('\n')
    flowables = []
    i = 0
    n = len(lines)

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        # 空行
        if not stripped:
            flowables.append(Spacer(1, 0.15 * cm))
            i += 1
            continue

        # ---------- 代码块 ----------
        if stripped.startswith('```'):
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏

            code_text = escape('\n'.join(code_lines))
            code_html = code_text.replace('\n', '<br/>')
            para = Paragraph(
                f'<font face="Courier" size="9" color="#374151">{code_html}</font>',
                ParagraphStyle(
                    'CodeBlockPara', fontName='Courier', fontSize=9, leading=14,
                    textColor=HexColor('#374151')
                )
            )
            t = Table([[para]], colWidths=[16 * cm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f3f4f6')),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            flowables.append(Spacer(1, 0.2 * cm))
            flowables.append(t)
            flowables.append(Spacer(1, 0.3 * cm))
            continue

        # ---------- 引用块 ----------
        if stripped.startswith('> '):
            quote_lines = []
            while i < n and lines[i].strip().startswith('> '):
                quote_lines.append(lines[i].strip()[2:])
                i += 1
            quote_html = _inline_to_html(' '.join(quote_lines))
            para = Paragraph(
                quote_html,
                ParagraphStyle(
                    'QuotePara', fontName='STSong-Light', fontSize=10,
                    leading=16, textColor=HexColor('#4b5563'),
                    alignment=TA_JUSTIFY
                )
            )
            t = Table([[para]], colWidths=[15.5 * cm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f9fafb')),
                ('LINEBEFORE', (0, 0), (0, -1), 3, PRIMARY_COLOR),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            flowables.append(Spacer(1, 0.2 * cm))
            flowables.append(t)
            flowables.append(Spacer(1, 0.3 * cm))
            continue

        # ---------- 表格 ----------
        if stripped.startswith('|') and '|' in stripped[1:]:
            table_raw = []
            while i < n and '|' in lines[i]:
                table_raw.append(lines[i])
                i += 1

            if len(table_raw) >= 2:
                header = [c.strip() for c in table_raw[0].split('|')[1:-1]]
                # 判断第二行是否为分隔符
                is_sep = bool(re.match(r'^\s*\|?[\s\-:|]+\|?\s*$', table_raw[1]))
                data_raw = table_raw[2:] if is_sep else table_raw[1:]

                parsed = []
                header_style = ParagraphStyle(
                    'TblHeader', fontName='STSong-Light', fontSize=10,
                    leading=14, textColor=white, alignment=TA_CENTER
                )
                cell_style = ParagraphStyle(
                    'TblCell', fontName='STSong-Light', fontSize=9,
                    leading=14, textColor=black, alignment=TA_LEFT
                )
                parsed.append([Paragraph(_inline_to_html(h), header_style) for h in header])

                for row in data_raw:
                    cells = [c.strip() for c in row.split('|')[1:-1]]
                    while len(cells) < len(header):
                        cells.append('')
                    parsed.append([
                        Paragraph(_inline_to_html(c), cell_style)
                        for c in cells[:len(header)]
                    ])

                if parsed:
                    col_w = 16 * cm / len(header)
                    t = Table(parsed, colWidths=[col_w] * len(header))
                    t.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY_COLOR),
                        ('TEXTCOLOR', (0, 0), (-1, 0), white),
                        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'STSong-Light'),
                        ('FONTSIZE', (0, 0), (-1, 0), 10),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                        ('TOPPADDING', (0, 0), (-1, 0), 8),
                        ('BACKGROUND', (0, 1), (-1, -1), white),
                        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e5e7eb')),
                        ('LEFTPADDING', (0, 0), (-1, -1), 8),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                        ('TOPPADDING', (0, 1), (-1, -1), 6),
                        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ]))
                    flowables.append(Spacer(1, 0.2 * cm))
                    flowables.append(t)
                    flowables.append(Spacer(1, 0.3 * cm))
            continue

        # ---------- 分隔线 ----------
        if _HR_RE.match(stripped):
            flowables.append(Spacer(1, 0.3 * cm))
            hr = Table([['']], colWidths=[16 * cm], rowHeights=[1])
            hr.setStyle(TableStyle([
                ('LINEBELOW', (0, 0), (-1, 0), 1, HexColor('#e5e7eb')),
            ]))
            flowables.append(hr)
            flowables.append(Spacer(1, 0.3 * cm))
            i += 1
            continue

        # ---------- 标题 ----------
        if stripped.startswith('### '):
            flowables.append(Paragraph(_inline_to_html(stripped[4:]), styles['ChineseHeading3']))
            flowables.append(Spacer(1, 0.15 * cm))
            i += 1
            continue
        if stripped.startswith('## '):
            flowables.append(Paragraph(_inline_to_html(stripped[3:]), styles['ChineseHeading2']))
            flowables.append(Spacer(1, 0.2 * cm))
            i += 1
            continue
        if stripped.startswith('# '):
            flowables.append(Paragraph(_inline_to_html(stripped[2:]), styles['ChineseHeading1']))
            flowables.append(Spacer(1, 0.3 * cm))
            i += 1
            continue

        # ---------- 列表（有序 / 无序 / 嵌套） ----------
        list_m = _LIST_RE.match(raw)
        if list_m:
            indent_str, marker, first_line = list_m.groups()
            indent_level = len(indent_str) // 2

            item_lines = [first_line]
            i += 1
            while i < n:
                next_raw = lines[i]
                next_stripped = next_raw.strip()
                if not next_stripped:
                    # 空行：检查下一行是否属于当前项的续行
                    if i + 1 < n and lines[i + 1].strip():
                        nxt = lines[i + 1]
                        nxt_indent = len(nxt) - len(nxt.lstrip())
                        # 续行缩进必须大于列表标记本身的缩进
                        if nxt_indent > len(indent_str) and not _LIST_RE.match(nxt):
                            i += 1
                            continue
                    break
                next_indent = len(next_raw) - len(next_raw.lstrip())
                # 下一行缩进更大且不是新列表项 → 续行
                if next_indent > len(indent_str) and not _LIST_RE.match(next_raw):
                    item_lines.append(next_raw.lstrip())
                    i += 1
                else:
                    break

            is_ordered = bool(re.match(r'^\d+\.$', marker))
            bullet = f'{marker} ' if is_ordered else '• '
            base_style = styles['ChineseOrderedList'] if is_ordered else styles['ChineseList']
            item_style = ParagraphStyle(
                f'ListItemL{indent_level}', parent=base_style,
                leftIndent=20 + indent_level * 16,
                firstLineIndent=-12 if not is_ordered else -18,
                spaceAfter=3, leading=15
            )
            item_html = _inline_to_html(' '.join(item_lines))
            flowables.append(Paragraph(f'{bullet}{item_html}', item_style))
            continue

        # ---------- 普通段落（合并连续行） ----------
        para_lines = [stripped]
        i += 1
        while i < n:
            nxt_stripped = lines[i].strip()
            if not nxt_stripped:
                i += 1
                break
            # 遇到任何特殊块即结束当前段落
            if (nxt_stripped.startswith('#') or
                nxt_stripped.startswith('```') or
                nxt_stripped.startswith('>') or
                nxt_stripped.startswith('|') or
                _HR_RE.match(nxt_stripped) or
                _LIST_RE.match(lines[i])):
                break
            para_lines.append(nxt_stripped)
            i += 1

        para_html = _inline_to_html(' '.join(para_lines))
        flowables.append(Paragraph(para_html, styles['ChineseBody']))
        flowables.append(Spacer(1, 0.1 * cm))

    return flowables


def _header_footer(canvas, doc):
    """非封面页页眉页脚绘制回调"""
    canvas.saveState()
    canvas.setFont('STSong-Light', 8)
    canvas.setFillColor(GRAY_COLOR)
    # 页脚居中：报告名 + 页码
    canvas.drawCentredString(
        A4[0] / 2, 1 * cm,
        f'模拟法庭庭审报告　第 {doc.page} 页'
    )
    # 页眉分隔线
    canvas.setStrokeColor(HexColor('#e5e7eb'))
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, A4[1] - 1.5 * cm, A4[0] - 2 * cm, A4[1] - 1.5 * cm)
    canvas.restoreState()


def generate_case_report(
    session: TrialSession,
    analysis: CaseAnalysis,
    output_path: str
) -> str:
    """
    生成完整的案件 PDF 报告

    Args:
        session: 庭审会话
        analysis: 案件分析数据
        output_path: PDF 输出路径

    Returns:
        生成的 PDF 文件路径
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    # 创建样式
    styles = getSampleStyleSheet()

    # 自定义中文字体样式
    styles.add(ParagraphStyle(
        name='ChineseTitle',
        parent=styles['Title'],
        fontName='STSong-Light',
        fontSize=24,
        textColor=PRIMARY_COLOR,
        spaceAfter=30,
        alignment=TA_CENTER
    ))

    styles.add(ParagraphStyle(
        name='ChineseHeading1',
        parent=styles['Heading1'],
        fontName='STSong-Light',
        fontSize=18,
        textColor=PRIMARY_COLOR,
        spaceAfter=12,
        spaceBefore=20
    ))

    styles.add(ParagraphStyle(
        name='ChineseHeading2',
        parent=styles['Heading2'],
        fontName='STSong-Light',
        fontSize=14,
        textColor=HexColor('#1e40af'),
        spaceAfter=10,
        spaceBefore=15
    ))

    styles.add(ParagraphStyle(
        name='ChineseHeading3',
        parent=styles['Heading3'],
        fontName='STSong-Light',
        fontSize=12,
        textColor=HexColor('#1e3a8a'),
        spaceAfter=8,
        spaceBefore=12
    ))

    styles.add(ParagraphStyle(
        name='ChineseBody',
        parent=styles['BodyText'],
        fontName='STSong-Light',
        fontSize=10,
        leading=16,
        alignment=TA_JUSTIFY,
        spaceAfter=6
    ))

    styles.add(ParagraphStyle(
        name='ChineseList',
        parent=styles['BodyText'],
        fontName='STSong-Light',
        fontSize=10,
        leading=16,
        leftIndent=20,
        spaceAfter=4
    ))

    styles.add(ParagraphStyle(
        name='ChineseOrderedList',
        parent=styles['BodyText'],
        fontName='STSong-Light',
        fontSize=10,
        leading=16,
        leftIndent=20,
        spaceAfter=4
    ))

    # 使用自定义样式名称
    heading1_style = styles['ChineseHeading1']
    heading2_style = styles['ChineseHeading2']
    heading3_style = styles['ChineseHeading3']
    body_style = styles['ChineseBody']
    list_style = styles['ChineseList']

    story = []

    # 封面
    story.append(Spacer(1, 4*cm))
    story.append(Paragraph('模拟法庭庭审报告', styles['ChineseTitle']))
    story.append(Spacer(1, 1*cm))

    # 案件信息
    case_info = [
        ['案由:', session.case_input.case_title or '未命名案件'],
        ['生成时间:', datetime.now().strftime('%Y年%m月%d日 %H:%M')],
        ['当前阶段:', PHASE_LABELS.get(session.current_phase, '未知')],
        ['代理模式:', session.user_role]
    ]

    info_table = Table(case_info, colWidths=[4*cm, 10*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'STSong-Light'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('TEXTCOLOR', (0, 0), (0, -1), GRAY_COLOR),
        ('TEXTCOLOR', (1, 0), (1, -1), black),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(PageBreak())

    # 可视化图表部分
    story.append(Paragraph('可视化分析', heading1_style))
    story.append(Spacer(1, 0.5*cm))

    # 时间轴
    timeline_data = _viz_from_session(session, analysis, 'timeline')
    if timeline_data and isinstance(timeline_data, dict) and 'events' in timeline_data:
        story.append(Paragraph('案件时间轴', heading2_style))
        chart_buf = _render_timeline_chart(timeline_data['events'])
        if chart_buf:
            img = Image(chart_buf, width=16*cm, height=6*cm)
            story.append(img)
            story.append(Spacer(1, 0.5*cm))

    # 请求权基础树
    claim_tree = _viz_from_session(session, analysis, 'claim_basis_tree')
    if claim_tree and isinstance(claim_tree, dict) and 'root' in claim_tree:
        story.append(Paragraph('请求权基础分析', heading2_style))
        chart_buf = _render_claim_basis_tree(claim_tree)
        if chart_buf:
            img = Image(chart_buf, width=16*cm, height=10*cm)
            story.append(img)
            story.append(Spacer(1, 0.5*cm))

    # 胜率雷达图
    win_rate_data = _viz_from_session(session, analysis, 'win_rate_radar')
    if win_rate_data and isinstance(win_rate_data, dict) and 'dimensions' in win_rate_data:
        story.append(Paragraph('胜率评估', heading2_style))
        chart_buf = _render_win_rate_radar(
            win_rate_data['dimensions'],
            win_rate_data.get('overall', analysis.win_rate)
        )
        if chart_buf:
            img = Image(chart_buf, width=10*cm, height=10*cm)
            story.append(img)
            story.append(Spacer(1, 0.5*cm))

    # 证据链
    evidence_chain = _viz_from_session(session, analysis, 'evidence_chain')
    if evidence_chain and 'items' in evidence_chain:
        story.append(Paragraph('证据链分析', heading2_style))
        chart_buf = _render_evidence_chain(
            evidence_chain['items'],
            evidence_chain.get('chains', [])
        )
        if chart_buf:
            img = Image(chart_buf, width=16*cm, height=min(12*cm, len(evidence_chain['items']) * 0.8*cm))
            story.append(img)
            story.append(Spacer(1, 0.5*cm))

    story.append(PageBreak())

    # 关键洞察摘要（先出摘要，再出原文）
    story.append(Paragraph('关键洞察摘要', heading1_style))
    story.append(Spacer(1, 0.3*cm))

    def _insight_para(label: str, text: str, color=GRAY_COLOR):
        style = ParagraphStyle(
            'InsightRow', parent=body_style, fontSize=10, leftIndent=10,
            textColor=black, spaceAfter=4, leading=16
        )
        display_text = text.strip() if text else '—'
        # C6 修复：label/display_text 来自 LLM/insight 卡片，可能含 < > &（如「<合同>」「A&B」「《民法典》<577条>」）。
        # reportlab Paragraph 解析类 XML 标记，未转义会导致 XML parse error → doc.build 崩溃、整个 PDF 导出失败。
        # 此处仅转义动态文本，保留我们刻意写入的 <b>/<font> 标签。
        safe_label = escape(label)
        safe_text = escape(display_text)
        return Paragraph(f'<b><font color="{color.hexval()}">{safe_label}</font></b> {safe_text}', style)

    # Phase 1 洞察
    i1 = analysis.insight_cards.get(1, {})
    if i1:
        story.append(Paragraph('策略分析', heading2_style))
        if i1.get('legal_relation'):
            story.append(_insight_para('法律关系：', i1['legal_relation']))
        if i1.get('best_claim_basis'):
            story.append(_insight_para('最优请求权：', str(i1['best_claim_basis'])))
        if i1.get('win_rate_assessment'):
            story.append(_insight_para('胜诉概率：', i1['win_rate_assessment'].get('reason', '')))
        if i1.get('next_action'):
            story.append(_insight_para('建议：', i1['next_action']))
        story.append(Spacer(1, 0.3*cm))

    # Phase 2 洞察
    i2 = analysis.insight_cards.get(2, {})
    if i2:
        story.append(Paragraph('攻防摘要', heading2_style))
        for c in i2.get('core_claims', []):
            story.append(_insight_para('核心请求：', c))
        for e in i2.get('evidence_strength', []):
            story.append(_insight_para(
                '证据强弱：',
                f"{e.get('name', '')} — {e.get('reason', '')}",
                SUCCESS_COLOR if e.get('strength') == 'strong' else WARNING_COLOR
            ))
        story.append(Spacer(1, 0.3*cm))

    # Phase 5 洞察
    i5 = analysis.insight_cards.get(5, {})
    if i5:
        story.append(Paragraph('争议焦点', heading2_style))
        for issue in i5.get('key_issues', []):
            favor = issue.get('favor', 'neutral')
            color = SUCCESS_COLOR if favor == 'plaintiff' else DANGER_COLOR if favor == 'defendant' else WARNING_COLOR
            story.append(_insight_para('焦点：', f"{issue.get('text', '')}（{favor}）", color))
        if i5.get('likely_direction'):
            story.append(_insight_para('采信方向：', i5['likely_direction']))
        story.append(Spacer(1, 0.3*cm))

    # Phase 8 洞察
    i8 = analysis.insight_cards.get(8, {})
    if i8:
        story.append(Paragraph('判决摘要', heading2_style))
        verdict = i8.get('verdict', {})
        if verdict:
            v_result = verdict.get('result', '')
            v_color = SUCCESS_COLOR if v_result == 'support' else WARNING_COLOR if v_result == 'partial' else DANGER_COLOR
            story.append(_insight_para('判决结果：', verdict.get('summary', ''), v_color))
        if isinstance(i8.get('win_rate'), (int, float)):
            story.append(_insight_para('胜率评估：', f"{i8['win_rate']}%"))
        for r in i8.get('key_reasons', []):
            story.append(_insight_para('关键理由：', r))
        if i8.get('appeal_suggestion'):
            story.append(_insight_para('上诉建议：', i8['appeal_suggestion']))
        story.append(Spacer(1, 0.3*cm))

    story.append(PageBreak())

    # 庭审记录部分（精简版：每个阶段先摘要后原文）
    story.append(Paragraph('庭审记录', heading1_style))
    story.append(Spacer(1, 0.5*cm))

    phase_contents = [
        (1, '请求权基础分析', session.phase1_analysis),
        (2, '起诉状与证据目录', session.phase2_complaint),
        (3, '答辩策略分析', session.phase3_analysis),
        (4, '答辩状与证据目录', session.phase4_answer),
        (5, '争议焦点归纳', session.phase5_issues),
        (7, '原告最后陈述', session.phase7_plaintiff_final),
        (7, '被告最后陈述', session.phase7_defendant_final),
        (8, '判决与胜率评估', session.phase8_judgment),
    ]

    for phase, title, content in phase_contents:
        if content and content.strip():
            story.append(Paragraph(f'阶段{phase}: {title}', heading2_style))
            # 优先显示 insight 摘要
            i = analysis.insight_cards.get(phase, {})
            if i:
                summary_style = ParagraphStyle(
                    'SummaryBox', parent=body_style, fontSize=9,
                    backColor=HexColor('#f3f4f6'), leftIndent=8, rightIndent=8,
                    spaceAfter=6, leading=14
                )
                summary_lines = []
                if phase == 1:
                    summary_lines = [i.get('legal_relation', ''), i.get('next_action', '')]
                elif phase == 2:
                    summary_lines = i.get('core_claims', [])
                elif phase == 5:
                    summary_lines = [issue.get('text', '') for issue in i.get('key_issues', [])]
                elif phase == 8:
                    summary_lines = [i.get('verdict', {}).get('summary', '')]
                summary_text = ' | '.join(s for s in summary_lines if s)
                if summary_text:
                    story.append(Paragraph(f'<i>摘要：{escape(summary_text)}</i>', summary_style))
            # 原文只保留前 2000 字，避免冗长
            truncated = content[:2000] + ('\n\n...[后文已省略，详见系统]' if len(content) > 2000 else '')
            flowables = _markdown_to_flowables(truncated, styles)
            story.extend(flowables)
            story.append(Spacer(1, 0.5*cm))

    # 交叉询问（特殊处理）
    if session.phase6_cross_exam:
        story.append(Paragraph('阶段6: 法庭辩论', heading2_style))
        story.append(Paragraph('交叉询问', heading3_style))

        try:
            messages = json.loads(session.phase6_cross_exam)
            for msg in messages:
                speaker_map = {'plaintiff': '原告律师', 'defendant': '被告律师', 'judge': '法官'}
                type_map = {'question': '提问', 'answer': '回答', 'guidance': '引导'}
                speaker = speaker_map.get(msg.get('speaker', ''), msg.get('speaker', ''))
                msg_type = type_map.get(msg.get('type', ''), msg.get('type', ''))
                content = msg.get('content', '')

                # C6 修复：speaker/msg_type/content 均来自 LLM/用户输入，统一 escape 后再拼 reportlab 标记。
                text = f'<b>{escape(str(speaker))}（{escape(str(msg_type))}）:</b> {escape(str(content))}'
                story.append(Paragraph(text, body_style))
        except Exception:
            # JSON 解析失败时的兜底：原文也必须 escape，避免原始串含 < > & 时崩溃。
            story.append(Paragraph(escape(session.phase6_cross_exam or ''), body_style))

        story.append(Spacer(1, 0.5*cm))

    # 页脚
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        '本报告由 AI 模拟法庭系统自动生成，仅供参考，不构成法律意见。',
        ParagraphStyle('Footer', parent=body_style, fontSize=8, textColor=GRAY_COLOR, alignment=TA_CENTER)
    ))

    # 生成 PDF（封面不加页眉页脚，后续页添加）
    doc.build(
        story,
        onFirstPage=lambda canvas, doc: None,
        onLaterPages=_header_footer
    )
    return output_path
