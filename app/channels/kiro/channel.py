"""
Kiro 通道实现

单账号级别的最小请求处理单元，组装 auth / converter / client 三个模块，
对外暴露 Channel 抽象接口（send / is_available / get_stats）。

数据流:
InternalRequest → converter → client(HTTP + event stream) → converter → InternalStreamChunk 流
"""

import time
from collections.abc import AsyncGenerator

from loguru import logger

from app.channels.base import Channel, ChannelStats
from app.channels.kiro.auth import KiroAuth
from app.channels.kiro.client import KiroClient
from app.channels.kiro.converter import KiroConverter
from app.schemas.internal import InternalRequest, InternalStreamChunk, InternalChoice, InternalDelta


class KiroChannel(Channel):
    """Kiro 单通道（单账号）"""

    channel_type = "kiro"

    def __init__(
        self,
        channel_name: str,
        priority: int,
        refresh_token: str,
        region: str = "us-east-1",
        supported_models: list[str] | None = None,
        max_concurrency: int = 1,
    ) -> None:
        self._name = channel_name
        self._priority = priority
        self._configured_models = supported_models
        self._models: list[str] = supported_models or []
        self._max_concurrency = max_concurrency

        # 内部模块
        self._auth = KiroAuth(refresh_token=refresh_token, region=region)
        self._converter = KiroConverter()
        self._client = KiroClient(self._auth, self._converter)

        # 运行时状态
        self._active_requests = 0
        self._stats = ChannelStats()
        self._initialized = False

        # 额度管理
        self._usage_limit: float = 0
        self._current_usage: float = 0
        self._next_reset: float = 0
        self._requests_since_sync: int = 0
        self._sync_interval: int = 20

    # ==================== 属性 ====================

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def models(self) -> list[str]:
        return self._models

    # ==================== 工厂方法 ====================

    @classmethod
    def from_config(cls, config: dict) -> "KiroChannel":
        """从配置字典创建 Kiro 通道实例"""
        return cls(
            channel_name=config["name"],
            priority=config.get("priority", 99),
            refresh_token=config["refresh_token"],
            region=config.get("region", "us-east-1"),
            supported_models=config.get("models"),
            max_concurrency=config.get("max_concurrency", 1),
        )

    # ==================== 初始化 ====================

    async def initialize(self) -> None:
        """初始化通道：拉取模型列表 + 额度信息（启动时调用一次）"""
        if self._initialized:
            return

        # 模型列表
        api_models = await self._client.fetch_models()
        if self._configured_models:
            api_set = set(api_models)
            self._models = [m for m in self._configured_models if m in api_set]
            logger.info(f"Channel {self._name} models (intersection): {self._models}")
        else:
            self._models = api_models
            logger.info(f"Channel {self._name} models (from API): {self._models}")

        # 额度
        await self._sync_usage()
        self._initialized = True

    # ==================== 核心接口 ====================

    async def send(self, request: InternalRequest) -> AsyncGenerator[InternalStreamChunk, None]:
        """发送请求，输出内部格式 chunk 流"""
        profile_arn = self._auth.profile_arn or ""
        kiro_payload = self._converter.to_kiro_request(request, profile_arn=profile_arn)

        self._stats.total_requests += 1
        self._active_requests += 1
        try:
            # 流式输出
            last_credit: float = 0
            last_usage = None
            async for chunk in self._client.stream_chat(kiro_payload):
                if chunk.credit_usage > 0:
                    last_credit = chunk.credit_usage
                if chunk.usage:
                    last_usage = chunk.usage
                yield chunk

            # 流结束：输出 tool_calls 或 finish chunk
            tool_calls = self._converter.get_pending_tool_calls()
            finish_reason = "tool_calls" if tool_calls else "stop"
            delta = InternalDelta(tool_calls=tool_calls) if tool_calls else InternalDelta()

            yield InternalStreamChunk(
                id=self._converter.completion_id,
                object="chat.completion.chunk",
                created=self._converter.created,
                model=request.model,
                choices=[InternalChoice(index=0, delta=delta, finish_reason=finish_reason)],
            )

            # 更新统计
            self._stats.success_count += 1
            if last_usage:
                self._stats.total_prompt_tokens += last_usage.prompt_tokens
                self._stats.total_completion_tokens += last_usage.completion_tokens

            # 额度扣减
            if last_credit > 0:
                self._current_usage += last_credit
                logger.debug(f"Channel {self._name} credit -{last_credit:.4f}, now {self._current_usage:.2f}/{self._usage_limit}")

            # 定期校准
            self._requests_since_sync += 1
            if self._requests_since_sync >= self._sync_interval:
                await self._sync_usage()

        except Exception:
            self._stats.failure_count += 1
            raise
        finally:
            self._active_requests -= 1

    def is_healthy(self) -> bool:
        """
        渠道状态是否正常（token 有效 + 额度未尽）

        不检查并发，仅判断渠道本身能不能用。
        """
        if not self._auth.has_valid_token():
            return False
        if 0 < self._usage_limit <= self._current_usage:
            if 0 < self._next_reset <= time.time():
                self._current_usage = 0
                logger.info(f"Channel {self._name} usage reset")
            else:
                return False
        return True

    def is_throttled(self) -> bool:
        """是否被限流（并发满了）"""
        return self._active_requests >= self._max_concurrency

    async def get_stats(self) -> ChannelStats:
        return self._stats

    # ==================== 内部方法 ====================

    async def _sync_usage(self) -> None:
        """从 API 校准额度"""
        info = await self._client.fetch_usage_limits()
        if info:
            self._usage_limit = info.get("usage_limit", 0)
            self._current_usage = info.get("current_usage", 0)
            self._next_reset = info.get("next_reset", 0)
            self._requests_since_sync = 0
            logger.info(f"Channel {self._name} usage synced: {self._current_usage}/{self._usage_limit} Credits")
