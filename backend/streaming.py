"""
庭审 SSE 流式事件支持

通过 contextvars 在 multi-agent 调用链中传递事件队列，
使 BaseAgent.think() 无需显式接收 queue 即可推送流式事件。
"""

import asyncio
import contextvars

stream_queue_ctx: contextvars.ContextVar[asyncio.Queue | None] = contextvars.ContextVar(
    "stream_queue", default=None
)


def put_event(event: dict):
    """向当前上下文中的流式队列推送事件（如无队列则静默忽略）"""
    queue = stream_queue_ctx.get()
    if queue:
        try:
            queue.put_nowait(event)
        except Exception:
            pass
