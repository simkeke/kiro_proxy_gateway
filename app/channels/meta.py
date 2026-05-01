"""
通道元类：子类继承时自动注册到注册表

机制：
- ChannelMeta: 子类声明 channel_type = "kiro" 时自动注册
- ChannelGroupMeta: 子类声明 group_type = "kiro" 时自动注册
- registry 通过 get() 按 type 名查找对应的类，实现配置驱动实例化
"""

from abc import ABCMeta


class ChannelMeta(ABCMeta):
    """通道元类：子类定义 channel_type 时自动注册"""

    _registry: dict[str, type] = {}

    def __new__(mcs, name: str, bases: tuple, namespace: dict):
        cls = super().__new__(mcs, name, bases, namespace)
        # 跳过基类自身，只注册声明了 channel_type 的具体子类
        if bases and "channel_type" in namespace:
            type_name = namespace["channel_type"]
            mcs._registry[type_name] = cls
        return cls

    @classmethod
    def get(mcs, type_name: str) -> type:
        """按类型名查找已注册的通道类"""
        cls = mcs._registry.get(type_name)
        if not cls:
            registered = list(mcs._registry.keys())
            raise ValueError(f"未注册的通道类型: {type_name}，已注册: {registered}")
        return cls


class ChannelGroupMeta(ABCMeta):
    """通道组元类：子类定义 group_type 时自动注册"""

    _registry: dict[str, type] = {}

    def __new__(mcs, name: str, bases: tuple, namespace: dict):
        cls = super().__new__(mcs, name, bases, namespace)
        if bases and "group_type" in namespace:
            type_name = namespace["group_type"]
            mcs._registry[type_name] = cls
        return cls

    @classmethod
    def get(mcs, type_name: str) -> type:
        """按类型名查找已注册的通道组类"""
        cls = mcs._registry.get(type_name)
        if not cls:
            registered = list(mcs._registry.keys())
            raise ValueError(f"未注册的通道组类型: {type_name}，已注册: {registered}")
        return cls
