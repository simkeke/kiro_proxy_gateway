"""Anthropic Messages 协议类型定义"""

from pydantic import BaseModel, Field


# ==================== 内容块（请求和响应共用） ====================


class AnthropicTextBlock(BaseModel):
    """文本内容块"""
    type: str = "text"
    text: str


class AnthropicToolUseBlock(BaseModel):
    """工具调用内容块"""
    type: str = "tool_use"
    id: str
    name: str
    input: dict


class AnthropicToolResult(BaseModel):
    """工具结果（嵌在 user message content 数组中）"""
    type: str = "tool_result"
    tool_use_id: str
    content: str


# ==================== 请求 ====================


class AnthropicToolInputSchema(BaseModel):
    """工具输入 schema"""
    type: str = "object"
    properties: dict | None = None
    required: list[str] | None = None


class AnthropicTool(BaseModel):
    """工具定义（Anthropic 扁平格式，无 function 嵌套）"""
    name: str
    description: str | None = None
    input_schema: AnthropicToolInputSchema | None = None


class AnthropicToolChoice(BaseModel):
    """工具选择"""
    type: str = "auto"


class AnthropicMessage(BaseModel):
    """消息（content 可以是字符串或内容块数组）"""
    role: str
    content: str | list[AnthropicTextBlock | AnthropicToolUseBlock | AnthropicToolResult]


class AnthropicRequest(BaseModel):
    """Anthropic Messages 请求"""
    model: str
    messages: list[AnthropicMessage]
    system: str | None = None
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int = 4096
    stop_sequences: list[str] | None = None
    tools: list[AnthropicTool] | None = None
    tool_choice: AnthropicToolChoice | None = None


# ==================== 非流式响应 ====================


class AnthropicUsage(BaseModel):
    """用量统计"""
    input_tokens: int = 0
    output_tokens: int = 0


class AnthropicResponse(BaseModel):
    """Anthropic 非流式完整响应"""
    id: str = ""
    type: str = "message"
    role: str = "assistant"
    model: str = ""
    content: list[AnthropicTextBlock | AnthropicToolUseBlock] = Field(default_factory=list)
    stop_reason: str | None = None
    usage: AnthropicUsage | None = None


# ==================== 流式响应事件 ====================


class AnthropicMessageStart(BaseModel):
    """message_start 事件"""
    type: str = "message_start"
    message: AnthropicResponse


class AnthropicContentBlockStart(BaseModel):
    """content_block_start 事件"""
    type: str = "content_block_start"
    index: int
    content_block: AnthropicTextBlock | AnthropicToolUseBlock


class AnthropicTextDelta(BaseModel):
    """文本增量"""
    type: str = "text_delta"
    text: str


class AnthropicInputJsonDelta(BaseModel):
    """工具输入增量"""
    type: str = "input_json_delta"
    partial_json: str


class AnthropicContentBlockDelta(BaseModel):
    """content_block_delta 事件"""
    type: str = "content_block_delta"
    index: int
    delta: AnthropicTextDelta | AnthropicInputJsonDelta


class AnthropicContentBlockStop(BaseModel):
    """content_block_stop 事件"""
    type: str = "content_block_stop"
    index: int


class AnthropicMessageDelta(BaseModel):
    """message_delta 事件的 delta 部分"""
    stop_reason: str | None = None


class AnthropicMessageDeltaEvent(BaseModel):
    """message_delta 事件"""
    type: str = "message_delta"
    delta: AnthropicMessageDelta
    usage: AnthropicUsage | None = None


class AnthropicMessageStop(BaseModel):
    """message_stop 事件"""
    type: str = "message_stop"


# ==================== 错误响应 ====================


class AnthropicErrorDetail(BaseModel):
    """错误详情"""
    type: str
    message: str


class AnthropicErrorResponse(BaseModel):
    """Anthropic 错误响应"""
    type: str = "error"
    error: AnthropicErrorDetail
