"""
全局限流器

职责：
- 模型校验：不支持的 model 直接拒绝
- 等待数控制：总等待数 + 单 model 等待数双重限制
- 等待通道可用：协程循环检查 is_available()，让出控制权等待通道空闲

数据流位置：
网关层(内部格式) → 【限流层】 → 路由层 → 通道组 → 通道 → 上游 API

流程：
请求进来 → 模型不支持报错 → 等待数超限报错 → 等待通道可用 → 放行到路由层
"""

import asyncio
import time

from loguru import logger

from app.channels.base import ChannelStatus
from app.channels.registry import get_registry
from app.config import settings
from app.core.exceptions import (
    ModelNotSupportedError,
    NoAvailableChannelError,
    ThrottleTimeoutError,
    TooManyRequestsError,
)


class Throttle:
    """全局限流器"""

    def __init__(
        self,
        max_total_waiting: int,
        max_model_waiting: int,
        timeout: float,
    ) -> None:
        self._max_total_waiting = max_total_waiting
        self._max_model_waiting = max_model_waiting
        self._timeout = timeout
        self._total_waiting: int = 0
        self._model_waiting: dict[str, int] = {}

    async def acquire(self, model: str) -> None:
        """
        限流入口：模型校验 → 等待数检查 → 等待通道可用

        通过后即可调用 router.route(request) 发送请求。
        """
        # 1. 模型校验
        if not self._is_model_supported(model):
            raise ModelNotSupportedError(model)

        # 2. 等待数检查
        if self._total_waiting >= self._max_total_waiting:
            raise TooManyRequestsError("Total waiting requests exceeded")
        if self._model_waiting.get(model, 0) >= self._max_model_waiting:
            raise TooManyRequestsError(f"Waiting requests for model {model} exceeded")

        # 3. 计数 +1，进入等待
        self._total_waiting += 1
        self._model_waiting[model] = self._model_waiting.get(model, 0) + 1
        try:
            await self._wait_for_available(model)
        finally:
            # 无论成功还是异常，计数 -1
            self._total_waiting -= 1
            self._model_waiting[model] = self._model_waiting.get(model, 0) - 1

    async def _wait_for_available(self, model: str) -> None:
        """循环检查通道可用性，让出控制权等待"""
        deadline = time.monotonic() + self._timeout

        while True:
            # 检查通道组状态
            status = await self._check_available(model)

            if status == ChannelStatus.AVAILABLE:
                return

            if status == ChannelStatus.UNAVAILABLE:
                raise NoAvailableChannelError(model)

            # THROTTLED → 检查超时，让出控制权
            if time.monotonic() >= deadline:
                logger.warning(f"限流等待超时: model={model}")
                raise ThrottleTimeoutError()

            await asyncio.sleep(0)

    @staticmethod
    def _is_model_supported(model: str) -> bool:
        """检查是否有通道组支持该模型"""
        for group in get_registry().groups:
            if model in group.models:
                return True
        return False

    @staticmethod
    async def _check_available(model: str) -> ChannelStatus:
        """
        遍历所有通道组，返回最优状态

        优先级: AVAILABLE > THROTTLED > UNAVAILABLE
        """
        best = ChannelStatus.UNAVAILABLE
        for group in get_registry().groups:
            status = await group.is_available(model)
            if status == ChannelStatus.AVAILABLE:
                return ChannelStatus.AVAILABLE
            if status == ChannelStatus.THROTTLED:
                best = ChannelStatus.THROTTLED
        return best


# ==================== 模块级接口 ====================

_throttle: Throttle | None = None


def init_throttle() -> None:
    """启动时调用，初始化全局限流器"""
    global _throttle
    _throttle = Throttle(
        max_total_waiting=settings.max_total_waiting,
        max_model_waiting=settings.max_model_waiting,
        timeout=settings.throttle_timeout,
    )
    logger.info(
        f"Throttle 初始化完成: "
        f"max_total={settings.max_total_waiting}, "
        f"max_model={settings.max_model_waiting}, "
        f"timeout={settings.throttle_timeout}s"
    )


def get_throttle() -> Throttle:
    """获取全局限流器实例"""
    if _throttle is None:
        raise RuntimeError("Throttle 未初始化，请先调用 init_throttle()")
    return _throttle
