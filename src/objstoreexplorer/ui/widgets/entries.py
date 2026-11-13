# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""输入框组件

⚠ 已废弃 (全项目零调用): 实际输入框都用各页直接 new tk.Entry, 或用
widgets/search_entry.py。保留仅为兼容外部 import, 新代码别用。

修复 (旧版两处真 bug, 留着迟早被误用):
  1. placeholder 被 `entry.insert(0, placeholder)` 写进了 textvariable
     绑定的 Entry —— 用户不动直接读 `entry.get()` / var.get() 拿到的
     是 "请输入..." 而不是真实值, 拿去当密码提交必然失败。
     改为: 独立 overlay Label 画占位符, Entry 自身始终为空。
  2. on_focus_out 里 `show=""` 把密码框的遮罩清空 —— 失焦后明文暴露。
     改为: 失焦一律恢复原遮罩。
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional

from ..styles import Brand, Neutral, UIFont


def create_entry(
    parent: tk.Misc,
    textvariable: Optional[tk.StringVar] = None,
    placeholder: str = "",
    show: str = "",
    width: int = 30,
) -> tk.Entry:
    """现代化输入框 (支持占位符) — 已废弃, 见模块 docstring"""
    if textvariable is None:
        textvariable = tk.StringVar()

    entry = tk.Entry(
        parent, textvariable=textvariable,
        font=UIFont.body(), bg=Neutral.BG_PANEL,
        fg=Neutral.TEXT_1, insertbackground=Brand.PRIMARY,
        relief="solid", bd=1, width=width, show=show,
    )

    if not placeholder:
        return entry

    # 占位符用 overlay Label, 不进 Entry 内容
    ph = tk.Label(
        entry, text=placeholder, font=UIFont.body(),
        bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3, anchor=tk.W,
    )
    ph.place(x=2, rely=0.5, anchor=tk.W)

    def _sync_placeholder(*_a) -> None:
        try:
            if not entry.get():
                ph.place(x=2, rely=0.5, anchor=tk.W)
            else:
                ph.place_forget()
        except tk.TclError:
            pass

    textvariable.trace_add("write", _sync_placeholder)
    entry.bind("<FocusIn>", lambda _e: _sync_placeholder())
    entry.bind("<FocusOut>", lambda _e: _sync_placeholder())
    _sync_placeholder()

    return entry
