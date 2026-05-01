import traceback

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.core.logger import log


class GatewayError(Exception):
    """网关基础异常"""

    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NoAvailableChannelError(GatewayError):
    """无可用通道（所有通道组均不可用）"""

    def __init__(self, model: str) -> None:
        super().__init__(
            message=f"No available channel for model: {model}",
            status_code=503,
        )


class ModelNotSupportedError(GatewayError):
    """模型不支持（没有通道组支持该模型）"""

    def __init__(self, model: str) -> None:
        super().__init__(
            message=f"Model not supported: {model}",
            status_code=400,
        )


class TooManyRequestsError(GatewayError):
    """等待请求数超限"""

    def __init__(self, message: str = "Too many requests, please try again later") -> None:
        super().__init__(message=message, status_code=429)


class ThrottleTimeoutError(GatewayError):
    """限流等待超时"""

    def __init__(self) -> None:
        super().__init__(
            message="Request timed out waiting for available channel",
            status_code=408,
        )


def _get_uuid(request: Request) -> str | None:
    return getattr(request.state, "uuid", None)


def _is_anthropic_request(request: Request) -> bool:
    """根据请求路径判断是否为 Anthropic 风格请求"""
    return request.url.path.startswith("/v1/messages")


def _build_openai_error(message: str, error_type: str, code: str | None = None) -> dict:
    """构建 OpenAI 格式错误响应"""
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": None,
            "code": code,
        }
    }


def _build_anthropic_error(error_type: str, message: str) -> dict:
    """构建 Anthropic 格式错误响应"""
    return {
        "type": "error",
        "error": {
            "type": error_type,
            "message": message,
        }
    }


# HTTP 状态码 → 错误类型映射
_ERROR_TYPE_MAP = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "authentication_error",
    404: "invalid_request_error",
    408: "timeout_error",
    422: "invalid_request_error",
    429: "rate_limit_error",
    500: "server_error",
    503: "overloaded_error",
}

_FRIENDLY_MESSAGES = {
    400: "Invalid request",
    401: "Invalid API key",
    403: "Permission denied",
    404: "Resource not found",
    422: "Validation failed",
    429: "Rate limit exceeded",
    500: "Internal server error",
    503: "Service overloaded",
}


def build_error_response(request: Request, status_code: int, message: str) -> dict:
    """根据请求路径构建对应格式的错误响应（公开接口，供中间件等模块调用）"""
    error_type = _ERROR_TYPE_MAP.get(status_code, "server_error")
    if _is_anthropic_request(request):
        return _build_anthropic_error(error_type, message)
    return _build_openai_error(message, error_type)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    uuid = _get_uuid(request)
    log.error(f"HTTPException -- uuid: {uuid} | status: {exc.status_code} | msg: {exc.detail}")
    message = _FRIENDLY_MESSAGES.get(exc.status_code, str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(request, exc.status_code, message),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    uuid = _get_uuid(request)
    log.error(f"ValidationError -- uuid: {uuid} | errors: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content=build_error_response(request, 422, "Validation failed"),
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    uuid = _get_uuid(request)
    log.error(f"Unhandled Exception -- uuid: {uuid} | msg: {exc}\n{traceback.format_exc()}")
    msg = str(exc) if settings.env == "dev" else "Internal server error"
    return JSONResponse(
        status_code=500,
        content=build_error_response(request, 500, msg),
    )


async def gateway_exception_handler(request: Request, exc: GatewayError) -> JSONResponse:
    """网关业务异常处理（NoAvailableChannelError 等）"""
    uuid = _get_uuid(request)
    log.warning(f"GatewayError -- uuid: {uuid} | status: {exc.status_code} | msg: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(request, exc.status_code, exc.message),
    )


def register_exception_handlers(app) -> None:
    """将异常处理器挂载到 FastAPI 应用"""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(GatewayError, gateway_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
