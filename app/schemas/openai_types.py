"""OpenAI Chat Completions 协议类型定义"""

from pydantic import BaseModel, Field


# ==================== 请求 ====================


class OpenAIFunctionDef(BaseModel):
    """工具函数定义"""
    name: str
    description: str | None = None
    parameters: dict | None = None


class OpenAITool(BaseModel):
    """工具定义"""
    type: str = "function"
    function: OpenAIFunctionDef


class OpenAIFunctionCall(BaseModel):
    """工具调用的函数信息"""
    name: str
    arguments: str


class OpenAIToolCall(BaseModel):
    """工具调用"""
    id: str
    type: str = "function"
    function: OpenAIFunctionCall


class OpenAIMessage(BaseModel):
    """消息"""
    role: str
    content: str | None = None
    tool_calls: list[OpenAIToolCall] | None = None
    tool_call_id: str | None = None


class OpenAIRequest(BaseModel):
    """OpenAI Chat Completions 请求"""
    model: str
    messages: list[OpenAIMessage]
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | str | None = None
    tools: list[OpenAITool] | None = None
    tool_choice: str | None = None


# ==================== 非流式响应 ====================


class OpenAIResponseMessage(BaseModel):
    """非流式响应中的消息"""
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[OpenAIToolCall] | None = None


class OpenAIUsage(BaseModel):
    """用量统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIResponseChoice(BaseModel):
    """非流式响应中的选项"""
    index: int = 0
    message: OpenAIResponseMessage = Field(default_factory=OpenAIResponseMessage)
    finish_reason: str | None = None


class OpenAIResponse(BaseModel):
    """OpenAI 非流式完整响应"""
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[OpenAIResponseChoice] = Field(default_factory=list)
    usage: OpenAIUsage | None = None


# ==================== 流式响应 ====================


class OpenAIDelta(BaseModel):
    """流式增量内容"""
    role: str | None = None
    content: str | None = None
    tool_calls: list[OpenAIToolCall] | None = None


class OpenAIStreamChoice(BaseModel):
    """流式响应中的选项"""
    index: int = 0
    delta: OpenAIDelta = Field(default_factory=OpenAIDelta)
    finish_reason: str | None = None


class OpenAIStreamChunk(BaseModel):
    """OpenAI 流式 chunk"""
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list[OpenAIStreamChoice] = Field(default_factory=list)
    usage: OpenAIUsage | None = None


# ==================== 错误响应 ====================


class OpenAIErrorDetail(BaseModel):
    """错误详情"""
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class OpenAIErrorResponse(BaseModel):
    """OpenAI 错误响应"""
    error: OpenAIErrorDetail
