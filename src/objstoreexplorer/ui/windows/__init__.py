# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/windows - 窗口组件

注: 版本控制 / 生命周期原先各有一个独立弹窗, 现已由
`ui/pages/versioning_page.py` 与 `ui/pages/lifecycle_page.py`
在主窗口右侧就地渲染取代, 两个旧弹窗已删除。
"""
from .main_window import MainWindow
from .connect_dialog import ConnectDialog
from .create_user_dialog import OneClickSetupDialog, CreateUserDialog
from .edit_user_dialog import EditUserDialog
from .policy_dialog import PolicyDialog
from .sync_dialog import SyncDialog

__all__ = [
    "MainWindow",
    "ConnectDialog",
    "OneClickSetupDialog",
    "CreateUserDialog",
    "EditUserDialog",
    "PolicyDialog",
    "SyncDialog",
]
