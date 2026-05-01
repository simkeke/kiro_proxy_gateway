"""
OpenAI 协议适配器

输入转换: OpenAIRequest → InternalRequest（几乎透传）
输出转换: InternalStreamChunk 流 → OpenAI 格式响应（流式 SSE / 非流式 JSON）
"""

from collections.abc import AsyncGenerator

from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.internal import (
    InternalRequest,
    InternalMessage,
    InternalTool,
    InternalFunctionDef,
    InternalStreamChunk,
)
from app.schemas.openai_types import (
    OpenAIRequest,
    OpenAIResponse,
    OpenAIResponseChoice,
    OpenAIResponseMessage,
    OpenAIToolCall,
    OpenAIFunctionCall,
    OpenAIUsage,
)


# ==================== 输入转换 ====================


def convert_request(req: OpenAIRequest) -> InternalRequest:
    """OpenAI 请求 → 内部格式（字段几乎一致，直接映射）"""
    messages = [
        InternalMessage(
            role=m.role,
            content=m.content,
            tool_calls=[
                _convert_tool_call_to_internal(tc) for tc in m.tool_calls
            ] if m.tool_calls else None,
            tool_call_id=m.tool_call_id,
        )
        for m in req.messages
    ]

    tools = None
    if req.tools:
        tools = [
            InternalTool(
                type=t.type,
                function=InternalFunctionDef(
                    name=t.function.name,
                    description=t.function.description,
                    parameters=t.function.parameters,
                ),
            )
            for t in req.tools
        ]

    return InternalRequest(
        model=req.model,
        messages=messages,
        stream=req.stream,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
        stop=req.stop,
        tools=tools,
        tool_choice=req.tool_choice,
    )


def _convert_tool_call_to_internal(tc):
    """OpenAI ToolCall → Internal ToolCall"""
    from app.schemas.internal import InternalToolCall, InternalFunctionCall
    return InternalToolCall(
        id=tc.id,
        type=tc.type,
        function=InternalFunctionCall(
            name=tc.function.name,
            arguments=tc.function.arguments,
        ),
    )


# ==================== 输出转换 ====================


async def build_response(
    chunks: AsyncGenerator[InternalStreamChunk, None],
    stream: bool,
) -> StreamingResponse | JSONResponse:
    """内部格式 chunk 流 → OpenAI 格式响应"""
    if stream:
        return StreamingResponse(
            _stream_sse(chunks),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await _build_non_stream(chunks)


async def _stream_sse(chunks: AsyncGenerator[InternalStreamChunk, None]):
    """流式：逐个 chunk 输出 SSE"""
    async for chunk in chunks:
        data = chunk.model_dump_json(exclude_none=True)
        yield f"data: {data}\n\n"
    yield "data: [DONE]\n\n"


async def _build_non_stream(
    chunks: AsyncGenerator[InternalStreamChunk, None],
) -> JSONResponse:
    """非流式：攒完所有 chunk，拼成完整 OpenAIResponse"""
    chunk_id = ""
    created = 0
    model = ""
    content_parts: list[str] = []
    tool_calls: list[OpenAIToolCall] = []
    finish_reason: str | None = None
    usage: OpenAIUsage | None = None

    async for chunk in chunks:
        if chunk.id:
            chunk_id = chunk.id
        if chunk.created:
            created = chunk.created
        if chunk.model:
            model = chunk.model

        for choice in chunk.choices:
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = choice.delta
            if delta.content:
                content_parts.append(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    tool_calls.append(
                        OpenAIToolCall(
                            id=tc.id,
                            type=tc.type,
                            function=OpenAIFunctionCall(
                                name=tc.function.name,
                                arguments=tc.function.arguments,
                            ),
                        )
                    )

        if chunk.usage:
            usage = OpenAIUsage(
                prompt_tokens=chunk.usage.prompt_tokens,
                completion_tokens=chunk.usage.completion_tokens,
                total_tokens=chunk.usage.total_tokens,
            )

    content = "".join(content_parts) or None
    response = OpenAIResponse(
        id=chunk_id,
        object="chat.completion",
        created=created,
        model=model,
        choices=[
            OpenAIResponseChoice(
                index=0,
                message=OpenAIResponseMessage(
                    role="assistant",
                    content=content,
                    tool_calls=tool_calls or None,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )
    return JSONResponse(content=response.model_dump(exclude_none=True))
