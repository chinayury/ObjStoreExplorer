# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""utils - 通用工具层

icon_manager 依赖 tkinter (GUI 层专用)。采用 PEP 562 惰性导入,
让 `import utils.helpers` / `import utils.thread_pool` 这类纯逻辑子模块
不会被 tkinter 依赖拖累 (`import utils.<x>` 会先执行本 __init__, 若急切
导入 icon_manager 则在无 tkinter 环境会直接崩)。
GUI 层 `from utils.icon_manager import set_root_icon` 直连子模块, 不受影响。
"""
from .helpers import (
    format_bytes,
    format_timestamp,
    truncate_path,
)
from .thread_pool import get_thread_pool, shutdown_pool

_LAZY_ICON_ATTRS = {
    "set_root_icon": "set_root_icon",
    "get_window_icon": "get_window_icon",
    # 私有符号: 保留惰性属性 (兼容历史 `utils._cleanup_temp_icons` 调用),
    # 但不写进 __all__ —— from utils import * 不该把内部实现细节导出去。
    "_temp_icon_files": "_temp_icon_files",
    "_cleanup_temp_icons": "_cleanup_temp_icons",
}


def __getattr__(name):
    """惰性导入 tkinter 绑定的 icon_manager 属性"""
    if name in _LAZY_ICON_ATTRS:
        from . import icon_manager
        value = getattr(icon_manager, _LAZY_ICON_ATTRS[name])
        globals()[name] = value
        return value
    raise AttributeError(f"module 'utils' has no attribute {name!r}")


__all__ = [
    # helpers
    "format_bytes",
    "format_timestamp",
    "truncate_path",
    # icon (惰性)
    "set_root_icon",
    "get_window_icon",
    # thread pool
    "get_thread_pool",
    "shutdown_pool",
]
