"""
Anthropic 协议适配器

输入转换: AnthropicRequest → InternalRequest（system 位置、tools 格式、stop 字段名等适配）
输出转换: InternalStreamChunk 流 → Anthropic 格式响应（流式 SSE / 非流式 JSON）
"""

import json
from collections.abc import AsyncGenerator

from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.internal import (
    InternalRequest,
    InternalMessage,
    InternalTool,
    InternalFunctionDef,
    InternalStreamChunk,
)
from app.schemas.anthropic_types import (
    AnthropicRequest,
    AnthropicTextBlock,
    AnthropicToolUseBlock,
    AnthropicToolResult,
    AnthropicUsage,
)


# ==================== 输入转换 ====================


def convert_request(req: AnthropicRequest) -> InternalRequest:
    """Anthropic 请求 → 内部格式"""
    messages: list[InternalMessage] = []

    # system 顶层字段 → 插入 messages 开头
    if req.system:
        messages.append(InternalMessage(role="system", content=req.system))

    # 转换消息
    for m in req.messages:
        converted = _convert_message(m)
        messages.extend(converted)

    # tools: Anthropic 扁平格式 → OpenAI 嵌套格式
    tools = None
    if req.tools:
        tools = [
            InternalTool(
                type="function",
                function=InternalFunctionDef(
                    name=t.name,
                    description=t.description,
                    parameters=t.input_schema.model_dump() if t.input_schema else None,
                ),
            )
            for t in req.tools
        ]

    # tool_choice: 对象 {"type": "auto"} → 字符串 "auto"
    tool_choice = None
    if req.tool_choice:
        tool_choice = req.tool_choice.type

    return InternalRequest(
        model=req.model,
        messages=messages,
        stream=req.stream,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
        stop=req.stop_sequences,
        tools=tools,
        tool_choice=tool_choice,
    )


def _convert_message(m) -> list[InternalMessage]:
    """
    转换单条 Anthropic 消息 → 内部格式消息列表

    Anthropic 的 content 可以是字符串或内容块数组。
    tool_result 在 Anthropic 里是 user 消息的 content 数组元素，
    需要拆成独立的 tool 角色消息。
    """
    # content 是字符串
    if isinstance(m.content, str):
        return [InternalMessage(role=m.role, content=m.content)]

    # content 是内容块数组
    result: list[InternalMessage] = []
    text_parts: list[str] = []

    for block in m.content:
        if isinstance(block, AnthropicTextBlock):
            text_parts.append(block.text)
        elif isinstance(block, AnthropicToolResult):
            # 先把之前攒的文本输出
            if text_parts:
                result.append(InternalMessage(role=m.role, content="".join(text_parts)))
                text_parts.clear()
            # tool_result → tool 角色消息
            result.append(InternalMessage(
                role="tool",
                tool_call_id=block.tool_use_id,
                content=block.content,
            ))
        elif isinstance(block, AnthropicToolUseBlock):
            # assistant 消息中的 tool_use（不常见于请求，但处理一下）
            if text_parts:
                result.append(InternalMessage(role=m.role, content="".join(text_parts)))
                text_parts.clear()

    # 剩余文本
    if text_parts:
        result.append(InternalMessage(role=m.role, content="".join(text_parts)))

    return result if result else [InternalMessage(role=m.role, content="")]


# ==================== 输出转换 ====================


async def build_response(
    chunks: AsyncGenerator[InternalStreamChunk, None],
    stream: bool,
) -> StreamingResponse | JSONResponse:
    """内部格式 chunk 流 → Anthropic 格式响应"""
    if stream:
        return StreamingResponse(
            _stream_sse(chunks),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await _build_non_stream(chunks)


async def _stream_sse(chunks: AsyncGenerator[InternalStreamChunk, None]):
    """流式：内部 chunk → Anthropic SSE 事件序列"""
    message_started = False
    content_block_started = False

    async for chunk in chunks:
        for choice in chunk.choices:
            delta = choice.delta

            # 第一个 chunk：发 message_start + content_block_start
            if not message_started and (delta.role or delta.content):
                message_started = True
                msg_start = {
                    "type": "message_start",
                    "message": {
                        "id": chunk.id,
                        "type": "message",
                        "role": "assistant",
                        "model": chunk.model,
                        "content": [],
                        "stop_reason": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                }
                yield _sse_event("message_start", msg_start)

            # content 开始
            if delta.content and not content_block_started:
                content_block_started = True
                block_start = {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                }
                yield _sse_event("content_block_start", block_start)

            # content 增量
            if delta.content:
                block_delta = {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": delta.content},
                }
                yield _sse_event("content_block_delta", block_delta)

            # tool_calls 处理
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    # 先关闭文本 block
                    if content_block_started:
                        yield _sse_event("content_block_stop", {"type": "content_block_stop", "index": 0})
                        content_block_started = False

                    # tool_use block
                    tc_index = 1  # tool_use 在 text 之后
                    block_start = {
                        "type": "content_block_start",
                        "index": tc_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.function.name,
                            "input": {},
                        },
                    }
                    yield _sse_event("content_block_start", block_start)

                    # input 增量
                    if tc.function.arguments:
                        input_delta = {
                            "type": "content_block_delta",
                            "index": tc_index,
                            "delta": {"type": "input_json_delta", "partial_json": tc.function.arguments},
                        }
                        yield _sse_event("content_block_delta", input_delta)

                    yield _sse_event("content_block_stop", {"type": "content_block_stop", "index": tc_index})

            # finish
            if choice.finish_reason:
                if content_block_started:
                    yield _sse_event("content_block_stop", {"type": "content_block_stop", "index": 0})

                stop_reason = _map_finish_reason(choice.finish_reason)
                usage_data = {}
                if chunk.usage:
                    usage_data = {"output_tokens": chunk.usage.completion_tokens}

                msg_delta = {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason},
                    "usage": usage_data,
                }
                yield _sse_event("message_delta", msg_delta)
                yield _sse_event("message_stop", {"type": "message_stop"})


async def _build_non_stream(
    chunks: AsyncGenerator[InternalStreamChunk, None],
) -> JSONResponse:
    """非流式：攒完所有 chunk，拼成 AnthropicResponse"""
    chunk_id = ""
    model = ""
    content_parts: list[str] = []
    tool_uses: list[dict] = []
    finish_reason: str | None = None
    usage: AnthropicUsage | None = None

    async for chunk in chunks:
        if chunk.id:
            chunk_id = chunk.id
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
                    try:
                        input_data = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        input_data = {}
                    tool_uses.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": input_data,
                    })

        if chunk.usage:
            usage = AnthropicUsage(
                input_tokens=chunk.usage.prompt_tokens,
                output_tokens=chunk.usage.completion_tokens,
            )

    # 构建 content 数组
    content: list[dict] = []
    if content_parts:
        content.append({"type": "text", "text": "".join(content_parts)})
    content.extend(tool_uses)

    stop_reason = _map_finish_reason(finish_reason) if finish_reason else "end_turn"

    response = {
        "id": chunk_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "usage": usage.model_dump() if usage else {"input_tokens": 0, "output_tokens": 0},
    }
    return JSONResponse(content=response)


# ==================== 工具方法 ====================


def _sse_event(event_type: str, data: dict) -> str:
    """构建 Anthropic SSE 事件（带 event: 字段）"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _map_finish_reason(reason: str) -> str:
    """OpenAI finish_reason → Anthropic stop_reason"""
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "end_turn",
    }
    return mapping.get(reason, "end_turn")
