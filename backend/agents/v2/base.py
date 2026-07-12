"""
Agent V2 基类 —— BaseAgentV2

核心能力：
- 独立 MemoryBank（三层记忆）
- Skill 注册与调用
- 受控通信（通过 CommChannel）
- 策略引擎集成
"""

from __future__ import annotations

import logging
from typing import Optional

from .schema import AgentMessageV2, LitigationStrategy, StrategyRoute
from .memory import MemoryBank
from .skill import Skill, ALL_SKILLS
from .strategy import LitigationStrategyEngine
from ...llm import llm_call, llm_call_stream, LLMConfig
from ...streaming import stream_queue_ctx

logger = logging.getLogger(__name__)


class BaseAgentV2:
    """
    Agent V2 基类

    - name: 唯一标识
    - system_prompt: 角色定义
    - memory: 独立 MemoryBank
    - skills: 已注册的能力模块
    - strategy_engine: 诉讼策略引擎
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: Optional[list[str]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        llm_config: Optional[LLMConfig] = None,
    ):
        self.name = name
        self.base_system_prompt = system_prompt
        self.tools = tools or []
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.llm_config = llm_config

        # 核心组件
        self.memory = MemoryBank()
        self.skills: list[Skill] = []
        self.strategy_engine = LitigationStrategyEngine(llm_config=llm_config)

        # 通信信道（由外部注入）
        self.channel: Optional["CommChannel"] = None

    # ── Skill 管理 ──

    def register_skill(self, skill: Skill) -> None:
        """注册 Skill，获得其能力"""
        self.skills.append(skill)
        self.tools.extend(skill.tools)
        logger.info(f"[{self.name}] 注册 Skill: {skill.name}")

    def get_skill(self, name: str) -> Optional[Skill]:
        for s in self.skills:
            if s.name == name:
                return s
        return None

    @property
    def system_prompt(self) -> str:
        """动态 system prompt = 角色定义 + 所有 Skill 的 prompt_template"""
        parts = [self.base_system_prompt]
        for skill in self.skills:
            if skill.prompt_template:
                parts.append(skill.prompt_template)
        return "\n\n".join(parts)

    # ── 核心思考 ──

    async def think(self, task: str, context: Optional[str] = None, max_tokens: Optional[int] = None, stream: bool = True) -> str:
        """
        Agent 思考并输出内容。
        自动组装 memory context + 支持流式输出。
        """
        # 组装消息
        messages = self._build_messages(task, context)
        mt = max_tokens or self.max_tokens
        queue = stream_queue_ctx.get()

        # 如果有 stream queue，走流式
        if queue and stream:
            queue.put_nowait({"type": "agent_start", "agent": self.name, "task_preview": task[:60]})
            chunks = []
            async for token in llm_call_stream(
                self.system_prompt,
                messages=messages,
                config=self.llm_config,
                temperature=self.temperature,
                max_tokens=mt,
            ):
                chunks.append(token)
                queue.put_nowait({"type": "token", "agent": self.name, "content": token})
            response = "".join(chunks)
        else:
            response = await llm_call(
                self.system_prompt,
                messages=messages,
                config=self.llm_config,
                temperature=self.temperature,
                max_tokens=mt,
            )

        # 记录到私有记忆
        self.memory.private.history.append({"role": "user", "content": task})
        self.memory.private.history.append({"role": "assistant", "content": response})
        self._truncate_history()

        return response

    async def think_with_skill(self, skill_name: str, context: dict) -> str:
        """调用指定 Skill 执行，自动发送 skill_start / skill_end SSE 事件"""
        import time
        skill = self.get_skill(skill_name)
        if not skill:
            logger.warning(f"[{self.name}] Skill 未找到: {skill_name}")
            return ""

        # 构建输入摘要（避免过长）
        input_preview = ""
        if context:
            previews = []
            for k, v in list(context.items())[:3]:
                text = str(v)[:80] + "..." if len(str(v)) > 80 else str(v)
                previews.append(f"{k}={text}")
            input_preview = "; ".join(previews)

        queue = stream_queue_ctx.get()
        start_ts = time.time()
        if queue:
            queue.put_nowait({
                "type": "skill_start",
                "agent": self.name,
                "skill": skill.name,
                "description": skill.description,
                "input_preview": input_preview,
            })

        try:
            result = await skill.execute(self, context)
        except Exception as e:
            logger.error(f"[{self.name}] Skill {skill_name} 执行失败: {e}")
            result = f"[Skill 执行错误: {e}]"

        duration_ms = int((time.time() - start_ts) * 1000)
        output_preview = result[:120] + "..." if len(result) > 120 else result

        if queue:
            queue.put_nowait({
                "type": "skill_end",
                "agent": self.name,
                "skill": skill.name,
                "description": skill.description,
                "output_preview": output_preview,
                "duration_ms": duration_ms,
            })

        return result

    # ── 通信 ──

    def publish(self, content: str, content_type: str, phase: int = 0) -> Optional[AgentMessageV2]:
        """将内容发布为共享记忆（public）"""
        if not self.channel:
            logger.warning(f"[{self.name}] 未注册通信信道，无法 publish")
            return None

        msg = AgentMessageV2(
            sender=self.name,
            recipient="all",
            msg_type="publish",
            content=content,
            visibility="public",
            content_type=content_type,
            phase=phase,
        )
        self.channel.dispatch(msg)
        # 同时加入自己的 shared 层
        self.memory.publish(msg)
        return msg

    def send_peer(self, recipient: str, content: str, content_type: str, phase: int = 0) -> bool:
        """发送 peer 消息（仅对方可见）"""
        if not self.channel:
            return False
        return self.channel.send_peer(self.name, recipient, content, content_type, phase)

    def send_private_to_judge(self, content: str, content_type: str = "strategy_note", phase: int = 0) -> bool:
        """发送仅法官可见的消息"""
        if not self.channel:
            return False
        msg = AgentMessageV2(
            sender=self.name,
            recipient="judge",
            msg_type="private",
            content=content,
            visibility="private_to_judge",
            content_type=content_type,
            phase=phase,
        )
        return self.channel.dispatch(msg)

    # ── 策略引擎快捷方法 ──

    async def formulate_strategy(self, case_input) -> LitigationStrategy:
        """制定初始诉讼策略"""
        strategy = await self.strategy_engine.formulate(
            case_input, self.name, self.system_prompt
        )
        self.memory.private.strategy = strategy
        return strategy

    async def adapt_strategy(self, new_event: AgentMessageV2, judge_guidance: Optional[str] = None) -> LitigationStrategy:
        """根据新事件调整策略"""
        current = self.memory.private.strategy
        if not current:
            return current
        updated = await self.strategy_engine.adapt(
            current, new_event, judge_guidance, self.system_prompt
        )
        self.memory.private.strategy = updated
        return updated

    async def generate_strategy_routes(self, case_input) -> list[StrategyRoute]:
        """生成 2-3 条策略路线供用户选择（单方对抗模式）"""
        prompt = f"""你是一名资深诉讼律师。基于以下案件材料，生成 2-3 条不同的策略路线。

【案件信息】
案由：{case_input.case_title}
事实：{case_input.facts[:800]}
证据：{case_input.evidence[:500]}
诉讼请求：{case_input.claims[:500]}
{"策略倾向：" + case_input.user_strategy_hint if getattr(case_input, "user_strategy_hint", "") else ""}

【要求】
每条路线必须包含：
1. 路线标题（简洁，如"主张合同无效"）
2. 核心主张（1-2 句）
3. 法律依据（具体法条）
4. 证据策略（需要哪些证据、如何编排）
5. 风险提示（可能的风险和应对）

格式（严格按以下 JSON 数组输出）：
[
  {{
    "route_id": "A",
    "title": "...",
    "is_recommended": true,
    "core_theory": "...",
    "legal_basis": "...",
    "evidence_strategy": "...",
    "risk_warning": "..."
  }},
  ...
]

注意：
- 路线之间要有实质性差异（不同的法律路径），而非措辞差异
- 第一条应为最常规、胜算最高的路线，标记 is_recommended=true
- 不得编造案件材料中不存在的事实
"""
        try:
            import json as _json
            response = await self.think(prompt, stream=False)
            # 提取 JSON 部分
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = _json.loads(text)
            routes = []
            for item in data:
                routes.append(StrategyRoute(
                    route_id=item.get("route_id", "A"),
                    title=item.get("title", ""),
                    is_recommended=item.get("is_recommended", False),
                    core_theory=item.get("core_theory", ""),
                    legal_basis=item.get("legal_basis", ""),
                    evidence_strategy=item.get("evidence_strategy", ""),
                    risk_warning=item.get("risk_warning", ""),
                ))
            logger.info(f"[{self.name}] 生成 {len(routes)} 条策略路线")
            return routes
        except Exception as e:
            logger.warning(f"[{self.name}] 生成策略路线失败: {e}")
            # 回退：生成一条默认路线
            return [StrategyRoute(
                route_id="A",
                title="基于现有材料的标准策略",
                is_recommended=True,
                core_theory="基于现有事实和证据提出主张",
                legal_basis="民法典相关条款",
                evidence_strategy="以现有证据为主",
                risk_warning="需补充更多证据",
            )]

    # ── 状态序列化 ──

    def to_state(self) -> dict:
        return {
            "name": self.name,
            "memory": self.memory.to_dict(),
            "skills": [s.name for s in self.skills],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    def load_state(self, state: dict) -> None:
        self.memory = MemoryBank.from_dict(state.get("memory", {}))
        # Skill 恢复：根据名称重新实例化
        skill_names = state.get("skills", [])
        for skill_cls in ALL_SKILLS:
            if skill_cls.name in skill_names:
                self.register_skill(skill_cls())

    # ── 辅助 ──

    def _build_messages(self, task: str, context: Optional[str]) -> list[dict]:
        msgs = [{"role": "system", "content": self.system_prompt}]

        # 注入 memory context
        memory_ctx = self.memory.build_context(include_private=True)
        if memory_ctx:
            msgs.append({"role": "system", "content": f"【你的记忆与材料】\n{memory_ctx}"})

        user_content = task
        if context:
            user_content = f"【背景信息】\n{context}\n\n【任务】\n{task}"
        msgs.append({"role": "user", "content": user_content})
        return msgs

    def _truncate_history(self):
        """简易截断：保留最近 20 条"""
        if len(self.memory.private.history) > 20:
            self.memory.private.history = self.memory.private.history[-20:]
