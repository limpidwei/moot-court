"""
法条检索服务

通过网络搜索获取法条原文，注入 LLM 提示词以提升准确性。

注意：web_search 工具由 DeepSeek TUI 环境提供，
本模块在独立运行时降级为空操作。
"""

import re


# 法条引用模式
LAW_CITATION_PATTERN = re.compile(
    r"(《[^》]+》)\s*第\s*(\d+)\s*条"
)


def extract_citations(text: str) -> list[tuple[str, str]]:
    """从文本中提取法条引用，返回 [(法规名, 条号), ...]"""
    return LAW_CITATION_PATTERN.findall(text)


def search_law(law_name: str, article: str) -> str:
    """
    搜索法条原文。
    在 DeepSeek TUI 环境中可用 web_search 工具；
    独立运行时可扩展为真实搜索 API。
    """
    query = f"{law_name} 第{article}条 原文"
    # 预留：实际调用可通过 requests 对接搜索 API
    # 当前版本依赖 LLM 自身的法律知识
    return f"[法条检索] {law_name} 第{article}条 —— 请以权威来源为准"


def build_law_context(text: str) -> str:
    """
    从文本中提取所有法条引用，构造上下文注入片段。

    用法：在调用 LLM 之前，将返回的字符串追加到 system prompt 末尾。
    """
    citations = extract_citations(text)
    if not citations:
        return ""

    lines = ["\n## 相关法条参考（请优先引用以下法条）\n"]
    seen = set()
    for law_name, article in citations:
        key = f"{law_name}-{article}"
        if key not in seen:
            seen.add(key)
            lines.append(f"- {law_name} 第{article}条")

    return "\n".join(lines)
