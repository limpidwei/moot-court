"""
多模型 LLM 调用适配层（异步版本，带重试、用量追踪与配额检查）

支持通过 LLMConfig 动态切换不同厂商的 OpenAI-compatible API。
用量追踪支持显式 meta 参数或 contextvars 隐式传递。
"""
import asyncio
import contextvars
import logging
import time
import re
from dataclasses import dataclass
from openai import AsyncOpenAI, APIError, APITimeoutError
from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, TEMPERATURE

logger = logging.getLogger(__name__)

# ContextVar 用于隐式传递 user_id / case_id，避免逐层修改调用签名
llm_meta_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar("llm_meta", default=None)


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.3  # 与 config.py TEMPERATURE 保持一致，低温度保证法律文本准确性


class QuotaExceededError(Exception):
    """用户配额已耗尽"""
    pass


def _default_config() -> LLMConfig:
    return LLMConfig(
        base_url=DEEPSEEK_BASE_URL,
        api_key=DEEPSEEK_API_KEY,
        model=DEEPSEEK_MODEL,
        temperature=TEMPERATURE,
    )


def get_client(config: LLMConfig) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文按字≈1，英文按词≈1.3，其他≈0.5）"""
    if not text:
        return 0
    cn_chars = len(re.findall(r"[一-鿿]", text))
    en_words = len(re.findall(r"[a-zA-Z]+", text))
    other = len(text) - cn_chars - sum(len(w) for w in re.findall(r"[a-zA-Z]+", text))
    return max(1, int(cn_chars * 1.0 + en_words * 1.3 + other * 0.5))


def _count_message_tokens(messages: list[dict]) -> int:
    """估算 messages 的总 token 数"""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, str):
            total += _estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += _estimate_tokens(part["text"])
    return total


def _check_quota(user_id: int | None):
    """检查用户是否超出日/月 token 配额"""
    if not user_id:
        return
    db = None
    try:
        from backend.database import SessionLocal
        from backend.models.database import User, LLMUsageRecord
        from sqlalchemy import func
        from datetime import datetime

        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # 日配额检查
        if user.daily_token_limit > 0:
            today_usage = (
                db.query(func.sum(LLMUsageRecord.total_tokens))
                .filter(
                    LLMUsageRecord.user_id == user_id,
                    LLMUsageRecord.created_at >= today_start,
                )
                .scalar()
                or 0
            )
            if today_usage >= user.daily_token_limit:
                raise QuotaExceededError(
                    f"日 token 配额已用完（上限 {user.daily_token_limit:,}）"
                )

        # 月配额检查
        if user.monthly_token_limit > 0:
            month_usage = (
                db.query(func.sum(LLMUsageRecord.total_tokens))
                .filter(
                    LLMUsageRecord.user_id == user_id,
                    LLMUsageRecord.created_at >= month_start,
                )
                .scalar()
                or 0
            )
            if month_usage >= user.monthly_token_limit:
                raise QuotaExceededError(
                    f"月 token 配额已用完（上限 {user.monthly_token_limit:,}）"
                )
    except QuotaExceededError:
        raise
    except Exception as e:
        logger.warning(f"配额检查失败: {e}")
    finally:
        if db:
            db.close()


def _log_usage(
    meta: dict | None,
    model: str,
    endpoint: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    success: bool = True,
    error_message: str | None = None,
):
    """异步记录 LLM 用量到数据库"""
    if not meta:
        return
    db = None
    try:
        from backend.database import SessionLocal
        from backend.models.database import LLMUsageRecord

        db = SessionLocal()
        db.add(
            LLMUsageRecord(
                user_id=meta.get("user_id"),
                case_id=meta.get("case_id"),
                model=model,
                endpoint=endpoint,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
            )
        )
        db.commit()
    except Exception as e:
        logger.warning(f"用量记录失败: {e}")
    finally:
        if db:
            db.close()


async def llm_call(
    system_prompt: str,
    user_message: str | None = None,
    *,
    messages: list[dict] | None = None,
    config: LLMConfig | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 4096,
    max_retries: int = 3,
    meta: dict | None = None,
) -> str:
    """异步调用 LLM API，带指数退避重试、用量追踪与配额检查"""
    effective_meta = meta or llm_meta_ctx.get(None)
    cfg = config or _default_config()
    client = get_client(cfg)
    mdl = model or cfg.model
    temp = temperature if temperature is not None else cfg.temperature
    last_error = None

    # 配额预检
    if effective_meta and effective_meta.get("user_id"):
        _check_quota(effective_meta["user_id"])

    if messages is not None:
        api_messages = messages
        if not api_messages or api_messages[0].get("role") != "system":
            api_messages = [{"role": "system", "content": system_prompt}] + api_messages
    else:
        api_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    start_ts = time.time()
    prompt_tokens_est = _count_message_tokens(api_messages)

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=mdl,
                messages=api_messages,
                temperature=temp,
                max_tokens=max_tokens,
                timeout=300,
            )
            latency_ms = int((time.time() - start_ts) * 1000)

            # 精确读取 usage
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", prompt_tokens_est)
                completion_tokens = getattr(usage, "completion_tokens", 0)
            else:
                prompt_tokens = prompt_tokens_est
                completion_tokens = _estimate_tokens(
                    response.choices[0].message.content or ""
                )

            _log_usage(
                meta=effective_meta,
                model=mdl,
                endpoint="llm_call",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=True,
            )
            return response.choices[0].message.content or ""
        except (APITimeoutError, APIError) as e:
            last_error = e
            wait = 2 ** attempt
            logger.warning(f"LLM call failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait}s...")
            await asyncio.sleep(wait)
        except Exception as e:
            last_error = e
            wait = 2 ** attempt
            logger.warning(f"LLM call unexpected error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait}s...")
            await asyncio.sleep(wait)

    # 全部重试失败，记录错误用量
    latency_ms = int((time.time() - start_ts) * 1000)
    _log_usage(
        meta=effective_meta,
        model=mdl,
        endpoint="llm_call",
        prompt_tokens=prompt_tokens_est,
        completion_tokens=0,
        latency_ms=latency_ms,
        success=False,
        error_message=str(last_error)[:500],
    )
    raise last_error


async def llm_call_stream(
    system_prompt: str,
    user_message: str | None = None,
    *,
    messages: list[dict] | None = None,
    config: LLMConfig | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 4096,
    meta: dict | None = None,
):
    """流式异步调用 LLM API，逐 token 返回，带重试与用量追踪。

    P2 修复：
    - 创建流时重试（create 失败，最多 3 次指数退避），流式传输中途失败无法重试但会准确记录日志。
    - finally 内 _log_usage 包 try，用量记录失败不拖垮流式响应。
    - success 状态由异常标记，不再无条件写 True。
    """
    effective_meta = meta or llm_meta_ctx.get(None)
    cfg = config or _default_config()
    client = get_client(cfg)
    mdl = model or cfg.model
    temp = temperature if temperature is not None else cfg.temperature

    # 配额预检
    if effective_meta and effective_meta.get("user_id"):
        _check_quota(effective_meta["user_id"])
    if meta and meta.get("user_id"):
        _check_quota(meta["user_id"])

    if messages is not None:
        api_messages = messages
        if not api_messages or api_messages[0].get("role") != "system":
            api_messages = [{"role": "system", "content": system_prompt}] + api_messages
    else:
        api_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    start_ts = time.time()
    prompt_tokens_est = _count_message_tokens(api_messages)
    completion_text = ""
    stream_success = False
    last_error = None
    max_retries = 3

    try:
        for attempt in range(max_retries):
            # P2 修复：分离"创建流"与"消费流"的控制流。
            # 原代码：内层 break（跳出 async for）后继续走到 stream_success=True; break，
            # 导致中途失败被标记为 success，且 3 次重试形同虚设。
            # 新结构：create 失败（外 except）→ 重试；consume 失败（内 except）→
            # 只能结束（token 已发出），不可重试。
            try:
                stream = await client.chat.completions.create(
                    model=mdl,
                    messages=api_messages,
                    temperature=temp,
                    max_tokens=max_tokens,
                    stream=True,
                    timeout=300,
                )
            except (APITimeoutError, APIError) as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(f"Stream create failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
                continue
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(f"Stream unexpected error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
                continue

            # 流创建成功，开始消费
            try:
                async for chunk in stream:
                    if chunk.choices[0].delta.content:
                        completion_text += chunk.choices[0].delta.content
                        yield chunk.choices[0].delta.content
            except Exception as e:
                # 流式传输中途失败：无法重试（token 已发送给调用方），记录并结束
                last_error = e
                logger.warning(f"Stream interrupted after {attempt + 1} attempt(s): {e}")
                stream_success = False
                break  # 跳出重试循环（不可重试）

            # 正常消费完毕
            stream_success = True
            break  # 跳出重试循环
    finally:
        latency_ms = int((time.time() - start_ts) * 1000)
        completion_tokens = _estimate_tokens(completion_text)
        try:
            _log_usage(
                meta=effective_meta,
                model=mdl,
                endpoint="llm_call_stream",
                prompt_tokens=prompt_tokens_est,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=stream_success,
                error_message=str(last_error)[:500] if last_error else None,
            )
        except Exception as e:
            logger.warning(f"_log_usage failed in stream finally: {e}")

    # 全重试失败时抛出最后的错误
    if not stream_success and last_error is not None:
        raise last_error
