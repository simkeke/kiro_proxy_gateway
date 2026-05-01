"""
通道注册中心

职责：
- 读取 channels.yaml 配置
- 通过元类注册表查找 Channel / ChannelGroup 类
- 调用 from_config() 实例化，调用 initialize() 初始化
- 持有通道组列表，暴露给路由层使用

使用方式：
- 启动时: await init_registry("channels.yaml")
- 获取:   get_registry().groups
- 关闭时: await shutdown_registry()
"""

import asyncio
from pathlib import Path

import yaml
from loguru import logger

from app.channels.base import ChannelGroup
from app.channels.meta import ChannelMeta, ChannelGroupMeta

# 确保所有通道模块被导入（触发元类注册）
import app.channels  # noqa: F401


class ChannelRegistry:
    """通道注册中心"""

    def __init__(self) -> None:
        self._groups: list[ChannelGroup] = []

    @property
    def groups(self) -> list[ChannelGroup]:
        return self._groups

    async def initialize(self, config_path: str) -> None:
        """读取配置，实例化并初始化所有通道组"""
        raw = self._load_yaml(config_path)

        for group_cfg in raw.get("channel_groups", []):
            try:
                group = await self._build_group(group_cfg)
                if group:
                    self._groups.append(group)
            except Exception as e:
                logger.error(f"通道组 {group_cfg.get('name', '?')} 构建失败: {e}")

        logger.info(f"ChannelRegistry 初始化完成，共 {len(self._groups)} 个通道组")

    async def shutdown(self) -> None:
        """释放资源"""
        self._groups.clear()
        logger.info("ChannelRegistry 已关闭")

    # ---- 内部方法 ----

    @staticmethod
    def _load_yaml(path: str) -> dict:
        """读取 yaml 配置文件，相对路径基于项目根目录解析"""
        config_path = Path(path)
        if not config_path.is_absolute():
            # 项目根目录 = app/ 的上一级
            project_root = Path(__file__).resolve().parent.parent.parent
            config_path = project_root / config_path
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            raise FileNotFoundError(
                f"通道配置文件不存在: {config_path}，请复制 channels.yaml.example 为 channels.yaml 并填入实际配置"
            )

    @staticmethod
    async def _build_group(group_cfg: dict) -> ChannelGroup | None:
        """根据配置构建一个通道组（完全通用，不涉及具体参数）"""
        group_type = group_cfg.get("type")
        group_name = group_cfg.get("name", "unknown")

        # 从元类注册表拿到对应的类
        channel_cls = ChannelMeta.get(group_type)
        group_cls = ChannelGroupMeta.get(group_type)

        # 实例化通道（通过 from_config，不关心具体参数）
        channels = []
        for ch_cfg in group_cfg.get("channels", []):
            try:
                ch = channel_cls.from_config(ch_cfg)
                channels.append(ch)
            except Exception as e:
                logger.error(f"通道 {ch_cfg.get('name', '?')} 创建失败: {e}")

        if not channels:
            logger.warning(f"通道组 {group_name} 无通道，跳过")
            return None

        # 并发初始化所有通道（拉模型列表、额度等）
        results = await asyncio.gather(
            *[ch.initialize() for ch in channels],
            return_exceptions=True,
        )

        # 过滤初始化失败的通道
        healthy = []
        for ch, result in zip(channels, results):
            if isinstance(result, Exception):
                logger.error(f"通道 {ch.name} 初始化失败: {result}")
            else:
                healthy.append(ch)

        if not healthy:
            logger.warning(f"通道组 {group_name} 所有通道初始化失败，跳过")
            return None

        # 实例化通道组（通过 from_config，不关心具体参数）
        return group_cls.from_config(group_cfg, healthy)


# ==================== 模块级接口 ====================

_registry: ChannelRegistry | None = None


async def init_registry(config_path: str) -> None:
    """启动时调用，初始化全局 registry"""
    global _registry
    _registry = ChannelRegistry()
    await _registry.initialize(config_path)


def get_registry() -> ChannelRegistry:
    """获取全局 registry 实例"""
    if _registry is None:
        raise RuntimeError("ChannelRegistry 未初始化，请先调用 init_registry()")
    return _registry


async def shutdown_registry() -> None:
    """关闭时调用，释放资源"""
    global _registry
    if _registry:
        await _registry.shutdown()
        _registry = None
