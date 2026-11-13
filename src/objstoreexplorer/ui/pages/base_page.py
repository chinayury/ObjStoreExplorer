# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""页面基类 - 所有页面继承此类"""
from __future__ import annotations
from abc import ABC, abstractmethod
import tkinter as tk
from typing import Optional

from ...services.service_locator import ServiceLocator
from ..styles import Neutral


class BasePage(ABC):
    """页面基类

    子类需要实现:
        - _build_ui(): 构建 UI 组件
        - refresh(): 刷新数据 (可选,默认空实现)
    """

    def __init__(self, parent: tk.Misc, locator: ServiceLocator):
        self.parent = parent
        self.locator = locator
        self.frame: Optional[tk.Frame] = None

    @abstractmethod
    def _build_ui(self) -> None:
        """构建 UI 组件 (子类必须实现)"""
        pass

    def show(self) -> None:
        """显示页面"""
        if self.frame is None:
            self.frame = tk.Frame(self.parent, bg=Neutral.BG_APP)
            self._build_ui()
        self.frame.pack(fill=tk.BOTH, expand=True)

    def hide(self) -> None:
        """隐藏页面"""
        if self.frame is not None:
            self.frame.pack_forget()

    def refresh(self) -> None:
        """刷新数据 (子类可重写)"""
        pass

    def on_upload(self) -> None:
        """上传事件 (子类可重写)"""
        pass

    def on_download(self) -> None:
        """下载事件 (子类可重写)"""
        pass
