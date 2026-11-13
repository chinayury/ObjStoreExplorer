# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/widgets/search_entry - 搜索框 (含图标 + 防抖)

用法:
    se = SearchEntry(parent, placeholder="搜索消息...", on_change=self._filter)
    se.pack()
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional, Callable

from ..styles import Neutral, UIFont, Space
from ...utils.icons import get as get_icon


class SearchEntry(tk.Frame):
    """带放大镜图标 + 占位符 + 防抖的搜索输入"""

    def __init__(
        self,
        parent: tk.Misc,
        placeholder: str = "搜索...",
        on_change: Optional[Callable[[str], None]] = None,
        width: int = 30,
        debounce_ms: int = 200,
        **kw,
    ):
        super().__init__(
            parent, bg=Neutral.BG_PANEL,
            highlightbackground=Neutral.BORDER,
            highlightthickness=1, bd=0, **kw,
        )
        self._on_change = on_change
        self._placeholder = placeholder
        self._debounce_ms = debounce_ms
        self._after_token: Optional[str] = None
        # 程序化改值时抑制 trace: clear()/显示占位符都会触发 write trace,
        # 结果是"点一下搜索框"或"点 × 清空"就重跑一遍 on_change 过滤
        self._suppress = False

        # 放大镜图标
        img = get_icon("search", 16)
        if img is not None:
            lbl = tk.Label(self, image=img, bg=Neutral.BG_PANEL)
            lbl.image = img
            lbl.pack(side=tk.LEFT, padx=(Space.SM, Space.XS), pady=Space.XS)
        else:
            tk.Label(
                self, text="○", font=("Segoe UI Symbol", 10),
                bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
            ).pack(side=tk.LEFT, padx=(Space.SM, Space.XS), pady=Space.XS)

        # Entry
        self.var = tk.StringVar()
        self.entry = tk.Entry(
            self, textvariable=self.var,
            font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
            relief="flat", bd=0, width=width,
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True,
                        padx=(0, Space.SM), pady=Space.XS)

        # placeholder
        self._show_placeholder()
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.var.trace_add("write", self._on_var_change)

    def _show_placeholder(self) -> None:
        self._suppress = True
        try:
            self.entry.delete(0, tk.END)
            self.entry.insert(0, self._placeholder)
            self.entry.configure(fg=Neutral.TEXT_3)
        finally:
            self._suppress = False

    def _on_focus_in(self, _e=None):
        if self.entry.get() == self._placeholder:
            self._suppress = True
            try:
                self.entry.delete(0, tk.END)
                self.entry.configure(fg=Neutral.TEXT_1)
            finally:
                self._suppress = False

    def _on_focus_out(self, _e=None):
        if not self.entry.get():
            self._show_placeholder()

    def _on_var_change(self, *args):
        if self._suppress:
            return
        text = self.var.get()
        if text == self._placeholder:
            return
        if self._after_token:
            try:
                self.after_cancel(self._after_token)
            except Exception:
                pass
            self._after_token = None
        if self._on_change:
            self._after_token = self.after(
                self._debounce_ms, lambda: self._fire(text),
            )

    def _fire(self, text: str) -> None:
        try:
            if self._on_change:
                self._on_change(text)
        except Exception:
            pass

    def get_value(self) -> str:
        v = self.entry.get()
        return "" if v == self._placeholder else v

    def clear(self) -> None:
        # 程序化清空: 抑制 trace, 不重跑 on_change("")
        self._suppress = True
        try:
            self.entry.delete(0, tk.END)
        finally:
            self._suppress = False
        self._show_placeholder()
