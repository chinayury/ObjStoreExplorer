# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/widgets - 复用 UI 组件 (「暮橙 Emberline」)"""
from .buttons import (
    create_primary_button, create_secondary_button, create_danger_button,
    create_success_button, create_ghost_button, create_danger_ghost_button,
)
from .entries import create_entry
from .labels import create_status_label, create_section_header
from .empty_state import create_empty_state
# v2 components
from .card import Card
from .badge import Badge
from .skeleton import SkeletonRow
from .toast import Toast
from .notifications import notify
from .sidebar import SidebarItem
from .breadcrumb import Breadcrumb
from .search_entry import SearchEntry
# 暮橙 Emberline
from .page_header import PageHeader, make_note
from .stat_card import StatCard
# 长文本查看窗 (对象属性 / 桶策略 / 生命周期规则 / 自检结果共用)
from .text_viewer import show_text_viewer

__all__ = [
    "create_primary_button",
    "create_secondary_button",
    "create_danger_button",
    "create_success_button",
    "create_ghost_button",
    "create_danger_ghost_button",
    "create_entry",
    "create_status_label",
    "create_section_header",
    "create_empty_state",
    # v2
    "Card", "Badge", "SkeletonRow", "Toast", "notify",
    "SidebarItem", "Breadcrumb", "SearchEntry",
    # 暮橙 Emberline
    "PageHeader", "make_note", "StatCard",
    "show_text_viewer",
]
