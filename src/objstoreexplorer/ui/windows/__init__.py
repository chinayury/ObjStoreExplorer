# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

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
