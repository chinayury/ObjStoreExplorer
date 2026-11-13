# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/pages - 页面组件"""
from .base_page import BasePage
from .overview_page import OverviewPage
from .buckets_page import BucketsPage
from .objects_page import ObjectsPage
from .users_page import UsersPage
from .policies_page import PoliciesPage
from .logs_page import LogsPage
from .versioning_page import VersioningPage
from .lifecycle_page import LifecyclePage
from .settings_page import SettingsPage
from .about_page import AboutPage
from .sync_page import SyncPage

__all__ = [
    "BasePage",
    "OverviewPage",
    "BucketsPage",
    "ObjectsPage",
    "UsersPage",
    "PoliciesPage",
    "LogsPage",
    "VersioningPage",
    "LifecyclePage",
    "SettingsPage",
    "AboutPage",
    "SyncPage",
]
