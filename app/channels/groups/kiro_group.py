"""
Kiro 通道组实现

管理多个 Kiro 账号（通道），对外暴露 ChannelGroup 抽象接口。
负责：模型汇总、可用性判断（三态）、按策略选通道、统计汇总。

调用链:
路由层 → group.is_available(model) → group.send(request) → channel.send(request) → chunk 流
"""

import random
from collections.abc import AsyncGenerator

from app.channels.base import Channel, ChannelGroup, ChannelStatus, GroupStats
from app.channels.kiro.channel import KiroChannel
from app.schemas.internal import InternalRequest, InternalStreamChunk


class KiroChannelGroup(ChannelGroup):
    """Kiro 通道组（管理多个 Kiro 账号）"""

    group_type = "kiro"

    def __init__(
        self,
        group_name: str,
        priority: int,
        channels: list[KiroChannel],
        strategy: str = "ordered",
    ) -> None:
        self._name = group_name
        self._priority = priority
        self._channels = channels
        self._strategy = strategy
        self._rr_index = 0  # round_robin 轮询计数器

    # ==================== 工厂方法 ====================

    @classmethod
    def from_config(cls, config: dict, channels: list[Channel]) -> "KiroChannelGroup":
        """从配置字典 + 已初始化的通道列表创建 Kiro 通道组实例"""
        return cls(
            group_name=config["name"],
            priority=config.get("priority", 99),
            channels=channels,
            strategy=config.get("strategy", "ordered"),
        )

    # ==================== 属性 ====================

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def strategy(self) -> str:
        return self._strategy

    @property
    def models(self) -> list[str]:
        """从健康通道汇总支持的模型列表（去重，排除异常通道）"""
        all_models: set[str] = set()
        for ch in self._channels:
            if ch.is_healthy():
                all_models.update(ch.models)
        return list(all_models)

    # ==================== 核心接口 ====================

    async def send(self, request: InternalRequest) -> AsyncGenerator[InternalStreamChunk, None]:
        """选一个可用通道发送请求（按模型匹配 + 策略选择）"""
        channel = await self._select_channel(request.model)
        async for chunk in channel.send(request):
            yield chunk

    async def is_available(self, model: str) -> ChannelStatus:
        """
        查询指定模型在组内的可用性

        判断逻辑:
        1. 找"支持该模型 + healthy"的通道
        2. 一个都没有 → UNAVAILABLE
        3. 有，但全部 throttled → THROTTLED
        4. 有且至少一个没被限流 → AVAILABLE
        """
        has_healthy = False
        for ch in self._channels:
            if model not in ch.models or not ch.is_healthy():
                continue
            has_healthy = True
            if not ch.is_throttled():
                return ChannelStatus.AVAILABLE
        return ChannelStatus.THROTTLED if has_healthy else ChannelStatus.UNAVAILABLE

    # ==================== 统计 ====================

    async def get_stats(self) -> GroupStats:
        """汇总组内所有通道的统计"""
        stats = GroupStats()
        for ch in self._channels:
            ch_stats = await ch.get_stats()
            stats.channel_stats[ch.name] = ch_stats
            stats.total_requests += ch_stats.total_requests
            stats.success_count += ch_stats.success_count
            stats.failure_count += ch_stats.failure_count
            stats.total_prompt_tokens += ch_stats.total_prompt_tokens
            stats.total_completion_tokens += ch_stats.total_completion_tokens
        return stats

    def get_channels(self) -> list[Channel]:
        return list(self._channels)

    # ==================== 内部方法 ====================

    async def _select_channel(self, model: str) -> KiroChannel:
        """
        根据策略选择一个支持指定模型的可用通道

        策略:
        - ordered: 按优先级取第一个
        - random: 随机选
        - round_robin: 轮询
        """
        # 筛选候选通道：支持该模型 + 健康 + 未限流
        candidates = [
            ch for ch in self._channels
            if model in ch.models and ch.is_healthy() and not ch.is_throttled()
        ]
        if not candidates:
            raise RuntimeError(f"通道组 {self._name} 无可用通道（model={model}）")

        if self._strategy == "random":
            return random.choice(candidates)

        if self._strategy == "round_robin":
            idx = self._rr_index % len(candidates)
            self._rr_index += 1
            return candidates[idx]

        # ordered（默认）: 按优先级取第一个
        candidates.sort(key=lambda c: c.priority)
        return candidates[0]
