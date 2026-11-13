# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""services - 业务编排层

用 PEP 562 惰性导出: `from services import ServiceLocator` 之前,
本包不会 import core/* 任何模块。service_locator 内部刻意把 core 的导入
放在函数里做延迟加载, 这里再顶层导出会把整条 core 导入链提前拉起来,
既拖慢启动, 也破坏那层延迟设计。
"""
from __future__ import annotations
from typing import Any

__all__ = [
    "ServiceLocator",
    "ConnectionService",
    "TransferService",
    "LogService",
    "ClipboardService",
    "SearchService",
    "CacheService",
    "PermissionService",
]

# 导出名 -> (模块, 类名)
_LAZY_EXPORTS = {
    "ServiceLocator": (".service_locator", "ServiceLocator"),
    "ConnectionService": (".connection_service", "ConnectionService"),
    "TransferService": (".transfer_service", "TransferService"),
    "LogService": (".log_service", "LogService"),
    "ClipboardService": (".clipboard_service", "ClipboardService"),
    "SearchService": (".search_service", "SearchService"),
    "CacheService": (".cache_service", "CacheService"),
    "PermissionService": (".permission_service", "PermissionService"),
}


def __getattr__(name: str) -> Any:
    """PEP 562: 首次访问某个导出名时才真正 import 对应模块"""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from importlib import import_module
    module_name, attr = target
    value = getattr(import_module(module_name, __name__), attr)
    # 缓存到模块全局, 后续访问不再走 __getattr__
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals().keys()) | set(__all__))
