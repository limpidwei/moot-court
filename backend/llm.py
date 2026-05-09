"""
DeepSeek API 调用适配层
"""
from openai import OpenAI
from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, TEMPERATURE

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
    return _client


def llm_call(
    system_prompt: str,
    user_message: str,
    *,
    model: str = DEEPSEEK_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = 4096,
) -> str:
    """调用 DeepSeek API，返回文本响应"""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def llm_call_stream(
    system_prompt: str,
    user_message: str,
    *,
    model: str = DEEPSEEK_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = 4096,
):
    """流式调用 DeepSeek API，逐 token 返回"""
    client = get_client()
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
