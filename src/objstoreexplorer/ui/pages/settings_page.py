# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""系统设置页面 — 应用设置 (「暮橙 Emberline」)

设置项:
    - 最大单文件上传 (MB), 0 表示不限制

通过 ConfigManager 持久化到加密 SQLite (app_settings 表), 跨重启保留。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import messagebox

from ..pages.base_page import BasePage
from ..styles import Neutral, Space, UIFont, ttk_scrollbar
from ..widgets.scrollarea import bind_mousewheel
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.buttons import create_primary_button, create_secondary_button
from ..widgets.notifications import notify
from ...config.settings import MAX_UPLOAD_SIZE
from ...core.config_manager import ConfigManager


class SettingsPage(BasePage):
    """系统设置页面"""

    SETTING_KEY_MAX_UPLOAD_MB = "max_upload_size_mb"
    _DEFAULT_MB = MAX_UPLOAD_SIZE // 1024 // 1024

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="Settings",
            title="系统设置",
            subtitle="应用级参数保存到本地加密数据库，改后立即生效，跨重启保留。",
            icon="settings",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))

        wrap = tk.Frame(self.frame, bg=Neutral.BG_APP)
        wrap.pack(fill=tk.BOTH, expand=True,
                  padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))

        # 可滚动内容区
        canvas = tk.Canvas(wrap, bg=Neutral.BG_APP, highlightthickness=0, bd=0)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk_scrollbar(wrap)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scroll.set)

        body = tk.Frame(canvas, bg=Neutral.BG_APP)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")

        # 关键: create_window 先于 bind <Configure>, 否则 itemconfig 静默失败
        body.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        # ⚠ 旧版只更新 scrollregion, 不同步 body 宽度 → 窗口拉宽后内层 body
        #   保持原自然宽度, 右侧留白/控件不跟随拉伸。
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(body_window, width=e.width),
        )
        # ⚠ 旧版完全没绑滚轮: 自己搓了 Canvas 滚动却没调 bind_mousewheel,
        #   光标在设置页任何位置滚动都没反应 (本项目其他 5 处都在用)。
        bind_mousewheel(canvas, body)

        self._build_upload_card(body)

    # ==================== 卡片: 上传设置 ====================

    def _build_upload_card(self, parent: tk.Misc) -> None:
        card = Card(parent, title="上传策略", icon="upload")
        card.pack(fill=tk.X)

        inner = card.body

        tk.Label(
            inner, text="限制单次上传的最大文件大小，超出会直接拒绝上传。",
            font=UIFont.body_sm(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
        ).pack(anchor=tk.W, pady=(0, Space.MD))

        row = tk.Frame(inner, bg=Neutral.BG_PANEL)
        row.pack(fill=tk.X)

        tk.Label(
            row, text="最大单文件上传", font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
        ).grid(row=0, column=0, sticky=tk.W, padx=(0, Space.MD))

        self.max_upload_var = tk.StringVar()
        self.max_upload_var.set(str(self._load_max_upload_mb()))
        tk.Entry(
            row, textvariable=self.max_upload_var,
            font=UIFont.metric(12), width=10, justify=tk.RIGHT,
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, relief="flat", bd=0,
            highlightbackground=Neutral.BORDER_HI, highlightthickness=1,
        ).grid(row=0, column=1, padx=(0, Space.SM), ipady=4)

        tk.Label(
            row, text="MB", font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
        ).grid(row=0, column=2, padx=(0, Space.LG))

        create_primary_button(
            row, "保存", self._save_upload, icon="check",
        ).grid(row=0, column=3, padx=Space.XS)
        create_secondary_button(
            row, "重置默认", self._reset_upload, icon="refresh-cw",
        ).grid(row=0, column=4, padx=Space.XS)

        tk.Label(
            inner, text="填 0 表示不限制；默认值为应用内置上限。",
            font=UIFont.caption(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
        ).pack(anchor=tk.W, pady=(Space.SM, 0))

        row.columnconfigure(3, weight=1)

    # ==================== 操作 ====================

    def _load_max_upload_mb(self) -> int:
        return ConfigManager().get_setting_int(
            self.SETTING_KEY_MAX_UPLOAD_MB, self._DEFAULT_MB,
        )

    def _save_upload(self) -> None:
        raw = self.max_upload_var.get().strip()
        try:
            value = int(raw)
            if value < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "请输入非负整数 (0 表示不限制)")
            return
        ConfigManager().set_setting(self.SETTING_KEY_MAX_UPLOAD_MB, str(value))
        if value == 0:
            notify(self.frame, "success", "已保存: 上传不限制大小")
        else:
            notify(self.frame, "success", f"已保存: 最大上传 {value} MB")
        self.locator.logger.info("set_max_upload_mb", str(value), "用户修改上传限制")

    def _reset_upload(self) -> None:
        self.max_upload_var.set(str(self._DEFAULT_MB))
        ConfigManager().delete_setting(self.SETTING_KEY_MAX_UPLOAD_MB)
        notify(self.frame, "success", f"已重置为默认 {self._DEFAULT_MB} MB")

    def refresh(self) -> None:
        if not hasattr(self, "max_upload_var"):
            return
        # ⚠ 旧版无条件重置输入框: 用户改完没点"保存"就切页, 改动被静默丢弃,
        #   回来时值已经变了却没有任何提示。
        current = self.max_upload_var.get().strip()
        saved = str(self._load_max_upload_mb())
        if current and current != saved:
            if not messagebox.askyesno(
                "放弃未保存的修改?",
                f"当前输入: {current}\n已保存值: {saved}\n\n"
                "刷新将丢弃未保存的修改, 继续?",
                parent=self.frame,
            ):
                return
        self.max_upload_var.set(saved)
