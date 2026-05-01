"""内部统一格式定义（= OpenAI Chat Completions 格式）"""

from pydantic import BaseModel, Field


# ==================== 请求侧 ====================


class InternalFunctionDef(BaseModel):
    """工具函数定义"""
    name: str
    description: str | None = None
    parameters: dict | None = None


class InternalTool(BaseModel):
    """工具定义（OpenAI 格式：type + function）"""
    type: str = "function"
    function: InternalFunctionDef


class InternalFunctionCall(BaseModel):
    """工具调用的函数信息"""
    name: str
    arguments: str


class InternalToolCall(BaseModel):
    """工具调用"""
    id: str
    type: str = "function"
    function: InternalFunctionCall


class InternalMessage(BaseModel):
    """消息（覆盖 system / user / assistant / tool 四种角色）"""
    role: str
    content: str | None = None
    tool_calls: list[InternalToolCall] | None = None
    tool_call_id: str | None = None


class InternalRequest(BaseModel):
    """内部统一请求格式"""
    model: str
    messages: list[InternalMessage]
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | str | None = None
    tools: list[InternalTool] | None = None
    tool_choice: str | None = None


# ==================== 响应侧（流式 chunk） ====================


class InternalDelta(BaseModel):
    """增量内容（chunk 中新增的内容片段）"""
    role: str | None = None
    content: str | None = None
    tool_calls: list[InternalToolCall] | None = None


class InternalChoice(BaseModel):
    """选项（chunk 中的一个回复选项）"""
    index: int = 0
    delta: InternalDelta = Field(default_factory=InternalDelta)
    finish_reason: str | None = None


class InternalUsage(BaseModel):
    """用量统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class InternalStreamChunk(BaseModel):
    """流式片段（内部统一的 chunk 格式）"""
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list[InternalChoice] = Field(default_factory=list)
    usage: InternalUsage | None = None
    credit_usage: float = Field(default=0.0, exclude=True)  # Kiro 专用：本次请求消耗的 credit 数，不序列化到响应
