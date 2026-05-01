import json
import time
from fnmatch import fnmatch
from typing import Any, Dict

import shortuuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.core.context import RequestContext
from app.core.logger import log

# 跳过自定义处理的路径
_SKIP_PATHS = {"/openapi.json", "/docs", "/redoc"}


def _is_whitelisted(path: str) -> bool:
    """判断路径是否在白名单中，使用 fnmatch 通配符匹配"""
    for pattern in settings.auth_whitelist:
        if fnmatch(path, pattern):
            return True
    return False


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求生成唯一 ID 并写入响应头"""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = shortuuid.ShortUUID().random(length=18)
        request.state.uuid = request_id
        RequestContext.request_id.set(request_id)

        # 根据请求路径设置来源格式
        if request.url.path.startswith("/v1/messages"):
            RequestContext.source_format.set("anthropic")
        else:
            RequestContext.source_format.set("openai")

        with log.contextualize(request_id=request_id):
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """API Key 鉴权：非白名单路径必须携带有效的 API Key"""

    async def dispatch(self, request: Request, call_next) -> Response:
        if _is_whitelisted(request.url.path) or request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # 从 Authorization header 或 x-api-key 获取 key
        api_key = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
        if not api_key:
            api_key = request.headers.get("x-api-key")

        # 未配置 proxy_api_key 时跳过鉴权
        if not settings.proxy_api_key:
            return await call_next(request)

        if not api_key or api_key != settings.proxy_api_key:
            # BaseHTTPMiddleware 中无法抛 HTTPException 被全局处理器捕获
            # 这是 Starlette 的已知限制，只能手动构造响应
            from app.core.exceptions import build_error_response
            return Response(
                content=json.dumps(build_error_response(request, 401, "Invalid API key")),
                status_code=401,
                media_type="application/json",
            )

        return await call_next(request)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """记录请求和响应信息"""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        start_time = time.time()

        log_data: Dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else None,
        }
        log.info(f"Request: {log_data}")

        response = await call_next(request)

        process_time = round(time.time() - start_time, 4)
        log.info(f"Response: status={response.status_code} time={process_time}s")

        return response


def register_middleware(app) -> None:
    """注册所有中间件（注意：注册顺序与执行顺序相反）"""
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(ApiKeyAuthMiddleware)
    app.add_middleware(RequestIDMiddleware)
