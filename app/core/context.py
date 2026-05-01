from contextvars import ContextVar


class RequestContext:
    """请求上下文变量"""

    # 当前请求 ID
    request_id: ContextVar[str] = ContextVar("request_id", default="system")

    # 请求来源格式：openai / anthropic
    source_format: ContextVar[str] = ContextVar("source_format", default="openai")
