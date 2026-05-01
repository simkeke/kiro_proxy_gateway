"""通道与通道组抽象基类"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

from app.channels.meta import ChannelMeta, ChannelGroupMeta
from app.schemas.internal import InternalRequest, InternalStreamChunk


class ChannelStatus(Enum):
    """通道组可用性状态"""
    AVAILABLE = "available"      # 有可用通道，可以直接发
    THROTTLED = "throttled"      # 有健康通道但都在忙，可排队等
    UNAVAILABLE = "unavailable"  # 无健康通道，换组


@dataclass
class ChannelStats:
    """通道统计信息"""
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0


@dataclass
class GroupStats:
    """通道组汇总统计"""
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    channel_stats: dict[str, ChannelStats] = field(default_factory=dict)


class Channel(metaclass=ChannelMeta):
    """通道抽象基类（单账号级别）"""

    @property
    @abstractmethod
    def name(self) -> str:
        """通道名称"""

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级（数值越小优先级越高）"""

    @property
    @abstractmethod
    def models(self) -> list[str]:
        """支持的模型列表"""

    @abstractmethod
    async def send(self, request: InternalRequest) -> AsyncGenerator[InternalStreamChunk, None]:
        """发送请求，输出内部格式 chunk 流"""

    @abstractmethod
    def is_healthy(self) -> bool:
        """渠道状态是否正常（token 有效 + 额度未尽）"""

    @abstractmethod
    def is_throttled(self) -> bool:
        """是否被限流（并发满了）"""

    @abstractmethod
    async def get_stats(self) -> ChannelStats:
        """获取统计信息"""

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict) -> Channel:
        """从配置字典创建通道实例，子类自行解析所需字段"""

    async def initialize(self) -> None:
        """初始化通道（拉取模型列表、额度等），子类按需覆写"""


class ChannelGroup(metaclass=ChannelGroupMeta):
    """通道组抽象基类（同类型通道集合）"""

    @property
    @abstractmethod
    def name(self) -> str:
        """通道组名称"""

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级（数值越小优先级越高）"""

    @property
    @abstractmethod
    def strategy(self) -> str:
        """通道选择策略（ordered / random / round_robin）"""

    @property
    @abstractmethod
    def models(self) -> list[str]:
        """支持的模型列表（从内部通道汇总，排除异常通道）"""

    @abstractmethod
    async def send(self, request: InternalRequest) -> AsyncGenerator[InternalStreamChunk, None]:
        """选一个可用通道发送请求，输出内部格式 chunk 流"""

    @abstractmethod
    async def is_available(self, model: str) -> ChannelStatus:
        """
        查询指定模型在组内的可用性

        返回:
            AVAILABLE   — 有支持该模型的健康通道且未限流
            THROTTLED   — 有支持该模型的健康通道但都在忙
            UNAVAILABLE — 无支持该模型的健康通道
        """

    @abstractmethod
    async def get_stats(self) -> GroupStats:
        """汇总组内所有通道的统计"""

    @abstractmethod
    def get_channels(self) -> list[Channel]:
        """获取组内通道列表"""

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict, channels: list[Channel]) -> ChannelGroup:
        """从配置字典 + 已初始化的通道列表创建通道组实例"""
