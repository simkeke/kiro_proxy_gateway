"""
Chat API 路由

对外暴露两个接口：
- POST /v1/chat/completions  (OpenAI 风格)
- POST /v1/messages          (Anthropic 风格)

调用链：
请求 → adapter.convert_request → throttle.acquire → router.route → adapter.build_response → 响应
"""

from fastapi import APIRouter

from app.gateway.adapters import openai as openai_adapter
from app.gateway.adapters import anthropic as anthropic_adapter
from app.gateway.throttle import get_throttle
from app.gateway.router import get_router
from app.schemas.openai_types import OpenAIRequest
from app.schemas.anthropic_types import AnthropicRequest

router = APIRouter()


@router.post("/v1/chat/completions")
async def openai_chat(req: OpenAIRequest):
    """OpenAI Chat Completions 接口"""
    # 输入转换
    internal_request = openai_adapter.convert_request(req)

    # 限流
    await get_throttle().acquire(internal_request.model)

    # 路由 → 通道 → chunk 流
    chunk_stream = get_router().route(internal_request)

    # 输出转换
    return await openai_adapter.build_response(chunk_stream, internal_request.stream)


@router.post("/v1/messages")
async def anthropic_chat(req: AnthropicRequest):
    """Anthropic Messages 接口"""
    # 输入转换
    internal_request = anthropic_adapter.convert_request(req)

    # 限流
    await get_throttle().acquire(internal_request.model)

    # 路由 → 通道 → chunk 流
    chunk_stream = get_router().route(internal_request)

    # 输出转换
    return await anthropic_adapter.build_response(chunk_stream, internal_request.stream)
