"""
可视化数据提取 — LLM Prompt 模板

为每种图表类型定义专用的 system prompt + 提取 prompt，
指导 LLM 从自由文本中提取结构化 JSON 数据。
"""

# ============================================================
# System Prompt（通用）
# ============================================================

VIZ_SYSTEM_PROMPT = (
    "你是一名专业的诉讼可视化数据提取助手。"
    "你的任务是从法律文书中提取结构化数据，用于生成可视化图表。"
    "严格按要求的 JSON 格式输出，不要添加额外字段，不要输出 Markdown 代码块。"
)

# ============================================================
# Phase 1: 请求权基础树形图
# ============================================================

PHASE1_CLAIM_BASIS_TREE = """请从以下请求权基础分析中提取请求权树形结构数据。

输出 JSON 格式：
{{
  "type": "claim_basis_tree",
  "data": {{
    "root": {{
      "label": "请求权名称",
      "law": "法律条文引用",
      "children": [
        {{
          "label": "构成要件名称",
          "law": "对应法条",
          "evidence": "对应证据（如有）",
          "status": "established" 或 "disputed" 或 "weak" 或 "unknown"
        }}
      ]
    }},
    "alternative_claims": [
      {{
        "label": "备选请求权",
        "law": "法条",
        "feasibility": "high" 或 "medium" 或 "low"
      }}
    ]
  }}
}}

说明：
- root 是主请求权，children 是其构成要件
- status: "established"=已证实, "disputed"=有争议, "weak"=证据不足, "unknown"=未知
- alternative_claims 是备选/竞合的请求权（如有）

原文：
{content}"""

# ============================================================
# Phase 2: 案件时间轴 + 证据链
# ============================================================

PHASE2_TIMELINE = """请从以下起诉状和证据目录中提取案件时间线数据。

输出 JSON 格式：
{{
  "type": "timeline",
  "data": {{
    "events": [
      {{
        "date": "YYYY-MM-DD 或 YYYY-MM",
        "label": "事件描述（简洁）",
        "type": "contract" 或 "breach" 或 "action" 或 "deadline" 或 "fact" 或 "evidence",
        "evidence": "对应证据编号或名称（如有）",
        "party": "原告" 或 "被告" 或 "双方" 或 ""
      }}
    ]
  }}
}}

说明：
- 按时间先后排序
- type: "contract"=签约/合同, "breach"=违约行为, "action"=诉讼行为, "deadline"=期限, "fact"=一般事实, "evidence"=证据相关
- 至少提取 3-10 个关键事件

原文：
{content}"""

PHASE2_EVIDENCE_CHAIN = """请从以下起诉状和证据目录中提取证据链数据。

输出 JSON 格式：
{{
  "type": "evidence_chain",
  "data": {{
    "items": [
      {{
        "id": "E1",
        "name": "证据名称",
        "evidence_type": "书证" 或 "物证" 或 "电子数据" 或 "证人证言" 或 "鉴定意见" 或 "其他",
        "proves": "待证事实（一句话）",
        "legal_element": "对应的法律要件",
        "strength": "strong" 或 "medium" 或 "weak",
        "side": "plaintiff" 或 "defendant"
      }}
    ],
    "chains": [
      {{
        "element": "法律要件名称",
        "evidence_ids": ["E1", "E2"],
        "sufficiency": "sufficient" 或 "insufficient" 或 "partial"
      }}
    ]
  }}
}}

说明：
- items: 每个证据项
- chains: 证据→法律要件的聚合链
- sufficiency: 该要件的证据是否充分

原文：
{content}"""

# ============================================================
# Phase 3: 答辩策略（攻防图 - 被告视角）
# ============================================================

PHASE3_DEFENSE_MAP = """请从以下答辩策略分析中提取攻防对照数据。

输出 JSON 格式：
{{
  "type": "attack_defense",
  "data": {{
    "plaintiff_claims": [
      {{
        "id": "C1",
        "claim": "原告主张内容（简洁）",
        "basis": "请求权基础"
      }}
    ],
    "defendant_defenses": [
      {{
        "id": "D1",
        "targets": ["C1"],
        "defense": "抗辩理由（简洁）",
        "type": "substantive" 或 "procedural" 或 "evidence",
        "strength": "strong" 或 "medium" 或 "weak"
      }}
    ],
    "procedural_defenses": [
      {{
        "description": "程序性抗辩描述",
        "feasibility": "high" 或 "medium" 或 "low"
      }}
    ]
  }}
}}

说明：
- type: "substantive"=实体抗辩, "procedural"=程序抗辩, "evidence"=证据抗辩
- targets: 该抗辩针对的原告主张 ID

原文：
{content}"""

# ============================================================
# Phase 4: 被告证据链（复用 PHASE2 模板，改 side）
# ============================================================

PHASE4_EVIDENCE_CHAIN = """请从以下答辩状和证据目录中提取被告方的证据链数据。

输出 JSON 格式：
{{
  "type": "evidence_chain",
  "data": {{
    "items": [
      {{
        "id": "DE1",
        "name": "证据名称",
        "evidence_type": "书证" 或 "物证" 或 "电子数据" 或 "证人证言" 或 "鉴定意见" 或 "其他",
        "proves": "待证事实（一句话）",
        "legal_element": "对应的抗辩要件",
        "strength": "strong" 或 "medium" 或 "weak",
        "side": "defendant"
      }}
    ],
    "chains": [
      {{
        "element": "抗辩要件名称",
        "evidence_ids": ["DE1", "DE2"],
        "sufficiency": "sufficient" 或 "insufficient" 或 "partial"
      }}
    ]
  }}
}}

原文：
{content}"""

# ============================================================
# Phase 5: 争议焦点思维导图
# ============================================================

PHASE5_DISPUTE_FOCUS = """请从以下争议焦点归纳中提取焦点思维导图数据。

输出 JSON 格式：
{{
  "type": "dispute_focus",
  "data": {{
    "root": {{
      "label": "案件争议总览",
      "children": [
        {{
          "label": "争议焦点1（简洁描述）",
          "category": "factual" 或 "legal" 或 "evidence",
          "favor": "plaintiff" 或 "defendant" 或 "neutral",
          "children": [
            {{
              "label": "子问题",
              "key_evidence": "关键证据",
              "analysis": "简要分析（一句话）"
            }}
          ]
        }}
      ]
    }},
    "likely_direction": "法官最可能采信的方向（一句话）"
  }}
}}

说明：
- category: "factual"=事实争议, "legal"=法律争议, "evidence"=证据争议
- favor: 该焦点对哪方有利

原文：
{content}"""

# ============================================================
# Phase 6: 辩论流程图 + 攻防配置
# ============================================================

PHASE6_DEBATE_FLOW = """请从以下法庭辩论记录中提取辩论流程数据。

输出 JSON 格式：
{{
  "type": "debate_flow",
  "data": {{
    "rounds": [
      {{
        "round": 1,
        "exchanges": [
          {{
            "speaker": "plaintiff" 或 "defendant" 或 "judge",
            "action": "question" 或 "answer" 或 "guidance" 或 "objection" 或 "ruling",
            "summary": "要点摘要（一句话）",
            "impact": "positive" 或 "negative" 或 "neutral",
            "topic": "涉及的主题"
          }}
        ]
      }}
    ],
    "key_moments": [
      {{
        "description": "关键转折点描述",
        "speaker": "plaintiff" 或 "defendant",
        "impact": "positive" 或 "negative"
      }}
    ]
  }}
}}

原文：
{content}"""

# ============================================================
# Phase 7: 双方立场对比
# ============================================================

PHASE7_POSITION_COMPARISON = """请从以下双方最后陈述中提取立场对比数据。

输出 JSON 格式：
{{
  "type": "position_comparison",
  "data": {{
    "issues": [
      {{
        "issue": "争议点描述",
        "plaintiff_position": "原告立场（一句话）",
        "defendant_position": "被告立场（一句话）",
        "gap": "large" 或 "medium" 或 "small",
        "evidence_favor": "plaintiff" 或 "defendant" 或 "balanced"
      }}
    ],
    "plaintiff_summary": "原告核心诉求总结（一句话）",
    "defendant_summary": "被告核心抗辩总结（一句话）"
  }}
}}

原文（原告最后陈述）：
{plaintiff_content}

原文（被告最后陈述）：
{defendant_content}"""

# ============================================================
# Phase 8: 胜率雷达图 + 判决决策树
# ============================================================

PHASE8_WIN_RATE_RADAR = """请从以下判决和胜率评估中提取胜率雷达图数据。

输出 JSON 格式：
{{
  "type": "win_rate_radar",
  "data": {{
    "dimensions": [
      {{
        "name": "事实清晰度",
        "score": 85,
        "weight": 0.3,
        "reason": "一句话评估理由"
      }},
      {{
        "name": "法律依据强度",
        "score": 72,
        "weight": 0.25,
        "reason": "一句话评估理由"
      }},
      {{
        "name": "举证责任完成度",
        "score": 68,
        "weight": 0.25,
        "reason": "一句话评估理由"
      }},
      {{
        "name": "程序合规性",
        "score": 90,
        "weight": 0.2,
        "reason": "一句话评估理由"
      }}
    ],
    "overall": 77.5
  }}
}}

说明：
- score: 0-100 的评分
- weight: 权重（四个维度分别为 0.3, 0.25, 0.25, 0.2）
- overall: 加权总分{win_rate_hint}

原文：
{content}"""

PHASE8_VERDICT_TREE = """请从以下判决中提取判决决策树数据。

输出 JSON 格式：
{{
  "type": "verdict_tree",
  "data": {{
    "root": {{
      "label": "判决结论",
      "result": "support" 或 "partial" 或 "dismiss",
      "children": [
        {{
          "label": "判决理由1",
          "basis": "法律依据",
          "evidence": "关键证据",
          "weight": "decisive" 或 "major" 或 "minor",
          "children": []
        }}
      ]
    }},
    "appeal": {{
      "viable": true 或 false,
      "grounds": "上诉理由（如有）",
      "likelihood": "high" 或 "medium" 或 "low"
    }}
  }}
}}

原文：
{content}"""

# ============================================================
# 全局: 当事人法律关系图
# ============================================================

GLOBAL_RELATIONSHIP_GRAPH = """请从以下案件信息中提取当事人法律关系图数据。

输出 JSON 格式：
{{
  "type": "relationship_graph",
  "data": {{
    "nodes": [
      {{
        "id": "p1",
        "label": "当事人名称",
        "role": "plaintiff" 或 "defendant" 或 "third_party" 或 "other",
        "description": "角色描述（如：买方、卖方）"
      }}
    ],
    "edges": [
      {{
        "from": "p1",
        "to": "d1",
        "label": "关系描述",
        "type": "contract" 或 "tort" 或 "claim" 或 "defense" 或 "employment" 或 "other"
      }}
    ]
  }}
}}

原文：
{content}"""


# ============================================================
# Prompt 映射表
# ============================================================

# phase -> list of (viz_type, prompt_template)
PHASE_VIZ_PROMPTS: dict[int, list[tuple[str, str]]] = {
    1: [("claim_basis_tree", PHASE1_CLAIM_BASIS_TREE)],
    2: [
        ("timeline", PHASE2_TIMELINE),
        ("evidence_chain", PHASE2_EVIDENCE_CHAIN),
    ],
    3: [("attack_defense", PHASE3_DEFENSE_MAP)],
    4: [("evidence_chain", PHASE4_EVIDENCE_CHAIN)],
    5: [("dispute_focus", PHASE5_DISPUTE_FOCUS)],
    6: [("debate_flow", PHASE6_DEBATE_FLOW)],
    7: [("position_comparison", PHASE7_POSITION_COMPARISON)],
    8: [
        ("win_rate_radar", PHASE8_WIN_RATE_RADAR),
        ("verdict_tree", PHASE8_VERDICT_TREE),
    ],
}

# 全局可视化（不依赖特定阶段）
GLOBAL_VIZ_PROMPTS: list[tuple[str, str]] = [
    ("relationship_graph", GLOBAL_RELATIONSHIP_GRAPH),
]
