"""
模型路由器

按 model 参数遍历通道组（按优先级排序），找到可用的通道组发送请求。

数据流位置：
网关层(内部格式) → 限流层 → 【路由层】 → 通道组 → 通道 → 上游 API
"""

from collections.abc import AsyncGenerator

from loguru import logger

from app.channels.base import ChannelGroup, ChannelStatus
from app.channels.registry import get_registry
from app.core.exceptions import NoAvailableChannelError
from app.schemas.internal import InternalRequest, InternalStreamChunk


class ModelRouter:
    """模型路由器：按优先级遍历通道组，找到可用的就发"""

    def __init__(self, groups: list[ChannelGroup]) -> None:
        self._groups = sorted(groups, key=lambda g: g.priority)

    async def route(self, request: InternalRequest) -> AsyncGenerator[InternalStreamChunk, None]:
        """路由请求到可用通道组，输出内部格式 chunk 流"""
        for group in self._groups:
            status = await group.is_available(request.model)
            if status == ChannelStatus.AVAILABLE:
                logger.debug(f"路由命中通道组: {group.name} (model={request.model})")
                async for chunk in group.send(request):
                    yield chunk
                return

        raise NoAvailableChannelError(request.model)


# ==================== 模块级接口 ====================

_router: ModelRouter | None = None


def init_router() -> None:
    """registry 初始化之后调用，构建路由器"""
    global _router
    groups = get_registry().groups
    _router = ModelRouter(groups)
    logger.info(f"ModelRouter 初始化完成，共 {len(groups)} 个通道组")


def get_router() -> ModelRouter:
    """获取全局路由器实例"""
    if _router is None:
        raise RuntimeError("ModelRouter 未初始化，请先调用 init_router()")
    return _router
