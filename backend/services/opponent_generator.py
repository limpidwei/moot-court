"""
对方材料生成服务（单方对抗模式）

基于用户提供的案件材料，AI 生成对方（opponent）的合理主张和证据。
确保单方模式下，AI 控制的对方角色有充实的材料可以对抗用户。
"""

import logging
from ..models.case import CaseInput
from ..llm import llm_call, LLMConfig

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一名资深中国民事诉讼律师，擅长从对立角度分析案件并撰写诉讼材料。

你的任务是基于一方提供的案件材料，生成对方（对立面）的合理诉讼材料。
要求：
1. 生成的材料必须合理、有法律依据，不能是无理取闹
2. 必须基于案件已有事实，可以适当补充符合常理的推断，但不得编造离谱事实
3. 证据材料要具体，列出证据名称、形式和证明目的
4. 语言专业、正式，符合法律文书风格
5. 输出格式为结构化 Markdown 文本"""


async def generate_opponent_materials(case_input: CaseInput, llm_config: LLMConfig | None = None) -> str:
    """
    基于用户案件材料生成对方（AI 控制方）的诉讼材料。

    - user_side == "plaintiff" → 生成被告的答辩材料与反驳证据
    - user_side == "defendant" → 生成原告的起诉材料与支撑证据

    返回结构化文本，注入对方 Agent 的 private memory 中。
    """
    if case_input.mode != "asymmetric" or not case_input.user_side:
        return ""

    opponent_role = "被告" if case_input.user_side == "plaintiff" else "原告"
    user_role = "原告" if case_input.user_side == "plaintiff" else "被告"

    prompt = f"""请基于以下案件材料，生成{opponent_role}方的诉讼材料。

【案件信息】
案由：{case_input.case_title}
事实：{case_input.facts[:1500]}
证据：{case_input.evidence[:800]}
诉讼请求：{case_input.claims[:800]}
{"策略倾向：" + case_input.user_strategy_hint[:300] if case_input.user_strategy_hint else ""}

【说明】
当前是单方对抗模式，用户扮演{user_role}方。你需要为 AI 控制的{opponent_role}方生成合理的诉讼材料，使庭审对抗真实、有挑战性。

请输出以下内容：

## 一、{opponent_role}方核心主张
（2-3 条核心主张，每条包含法律依据）

## 二、关键事实陈述
（从{opponent_role}角度陈述的事实，可与对方陈述存在合理分歧）

## 三、证据清单
（3-5 项具体证据，每项包含：证据名称、证据形式、证明目的）

## 四、预期抗辩/攻击点
（针对对方材料的可质疑之处）

注意：
- 材料必须合理、专业，符合中国民事诉讼实务
- 不得编造与案件性质明显不符的事实
- 证据名称要具体，不能笼统写"相关合同"
- 如果用户提供了策略倾向，请适当参考但不必完全遵循
"""

    try:
        result = await llm_call(
            _SYSTEM_PROMPT,
            user_message=prompt,
            config=llm_config,
            max_tokens=4096,
            temperature=0.5,
        )
        logger.info(f"[OpponentGenerator] 生成{opponent_role}材料成功，长度={len(result)}")
        return result
    except Exception as e:
        logger.error(f"[OpponentGenerator] 生成对方材料失败: {e}")
        return ""
