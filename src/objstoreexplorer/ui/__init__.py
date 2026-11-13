# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""UI 模块 - 阶段 4 仅提供最小可运行版本

完整设计系统、复用组件、各类页面留待后续迭代。
"""
from .styles import Colors, Fonts, Spacing
from .windows.main_window import MainWindow

__all__ = ["Colors", "Fonts", "Spacing", "MainWindow"]
