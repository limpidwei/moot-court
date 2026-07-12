"""
可视化数据提取服务

从各阶段的文本产出中，利用 LLM 提取结构化 JSON 数据，
供前端渲染为可视化图表。

复用 insights.py 的 JSON 解析逻辑，并扩展为多图表提取。
"""

import json
import logging
import re
from typing import Any

from ..llm import llm_call, LLMConfig
from .viz_prompts import (
    VIZ_SYSTEM_PROMPT,
    PHASE_VIZ_PROMPTS,
    GLOBAL_VIZ_PROMPTS,
)

logger = logging.getLogger(__name__)


async def extract_phase_viz(
    phase: int,
    content: str,
    llm_config: LLMConfig | None = None,
    extra_context: dict | None = None,
) -> list[dict]:
    """
    提取指定阶段的所有可视化数据。

    Args:
        phase: 阶段编号 (1-8)
        content: 阶段文本内容
        llm_config: 可选的 LLM 配置
        extra_context: 额外上下文（如 Phase 7 需要双方陈述）

    Returns:
        可视化数据列表，每项包含 type 和 data 字段。
        如提取失败返回空列表。
    """
    prompts = PHASE_VIZ_PROMPTS.get(phase)
    if not prompts:
        return []

    # 截断内容避免超出上下文
    truncated = content[:5000] + ("\n...[内容已截断]" if len(content) > 5000 else "")

    results = []
    for viz_type, prompt_template in prompts:
        try:
            # 构建 prompt
            format_kwargs: dict[str, Any] = {"content": truncated}

            # Phase 7 需要双方内容
            if extra_context:
                format_kwargs.update(extra_context)

            # Phase 8 雷达图可注入已知胜率
            if phase == 8 and viz_type == "win_rate_radar" and extra_context:
                win_rate = extra_context.get("win_rate")
                if win_rate is not None:
                    format_kwargs["win_rate_hint"] = (
                        f"\n注意：已知胜率为 {win_rate}%，overall 字段必须使用此数值。"
                    )
                else:
                    format_kwargs["win_rate_hint"] = ""
            elif "win_rate_hint" not in format_kwargs:
                format_kwargs["win_rate_hint"] = ""

            prompt = prompt_template.format(**format_kwargs)

            result = await llm_call(
                VIZ_SYSTEM_PROMPT, prompt,
                max_tokens=2048,
                max_retries=2,
                config=llm_config,
            )

            parsed = _try_parse_json(result)
            if parsed and "type" in parsed:
                results.append(parsed)
            else:
                logger.warning(f"Phase {phase} viz_type={viz_type} JSON 解析失败")

        except Exception as e:
            logger.error(f"Phase {phase} viz_type={viz_type} 提取失败: {e}")

    return results


async def extract_global_viz(
    case_content: str,
    llm_config: LLMConfig | None = None,
) -> list[dict]:
    """
    提取全局可视化数据（当事人关系图等）。

    Args:
        case_content: 案件综合信息（事实 + 证据 + 诉讼请求）
        llm_config: 可选的 LLM 配置

    Returns:
        可视化数据列表
    """
    truncated = case_content[:4000] + ("\n...[内容已截断]" if len(case_content) > 4000 else "")

    results = []
    for viz_type, prompt_template in GLOBAL_VIZ_PROMPTS:
        try:
            prompt = prompt_template.format(content=truncated)
            result = await llm_call(
                VIZ_SYSTEM_PROMPT, prompt,
                max_tokens=2048,
                max_retries=2,
                config=llm_config,
            )
            parsed = _try_parse_json(result)
            if parsed and "type" in parsed:
                results.append(parsed)
            else:
                logger.warning(f"Global viz_type={viz_type} JSON 解析失败")
        except Exception as e:
            logger.error(f"Global viz_type={viz_type} 提取失败: {e}")

    return results


def _try_parse_json(text: str) -> dict | None:
    """尝试多种方式解析 JSON（复用 insights.py 的逻辑）"""
    text = text.strip()

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 从 Markdown 代码块中提取
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 尝试提取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start: end + 1])
        except json.JSONDecodeError:
            pass

    return None
