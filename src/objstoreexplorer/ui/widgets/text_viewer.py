# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/widgets/text_viewer — 可滚动的只读文本查看窗

用 messagebox 展示长文本有两个问题:
  1. 内容超屏就看不见, 而且没法滚动;
  2. 不能选中复制 —— 用户想拿一段 key 或 ETag 去别处比对时只能截图。

对象属性 (含自定义元数据/标签)、桶策略 JSON、生命周期规则、自检结果
这几处都会出现几十行的内容, 所以统一用这个组件。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from ..styles import Brand, Neutral, Space, UIFont
from ..widgets.buttons import create_primary_button


def show_text_viewer(
    parent: Optional[tk.Misc],
    title: str,
    text: str,
    width: int = 720,
    height: int = 480,
    monospace: bool = True,
) -> tk.Toplevel:
    """弹出一个可滚动、可复制的只读文本窗

    Args:
        parent: 父窗口 (决定模态归属)
        title: 窗口标题
        text: 要展示的内容
        monospace: 是否用等宽字体 —— JSON / ARN / 路径这类内容必须等宽,
                   否则缩进和列对不齐, 没法看结构

    Returns:
        创建出来的 Toplevel (调用方若要额外挂控件可用)
    """
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry(f"{width}x{height}")
    win.minsize(420, 260)
    # 不抢焦点: 这类窗多数是"看一眼就关", 抢焦点会打断用户手上的操作
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass
    # 绑到父窗口上, 父窗口销毁时跟着走
    try:
        if parent is not None:
            win.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass

    wrap = ttk.Frame(win, style="Modern.TFrame")
    wrap.pack(fill="both", expand=True, padx=Space.LG, pady=Space.LG)

    text_box = tk.Text(
        wrap,
        wrap="word",                     # 长 ARN 行也要能换行, 否则右侧看不到
        font=UIFont.mono(10) if monospace else UIFont.body(),
        bg=Neutral.BG_SUBTLE,
        fg=Neutral.TEXT_1,
        insertbackground=Neutral.TEXT_1,
        relief="flat",
        borderwidth=0,
        padx=Space.MD,
        pady=Space.SM,
        highlightthickness=0,
    )
    text_box.pack(side="left", fill="both", expand=True)

    scroll = ttk.Scrollbar(wrap, orient="vertical", command=text_box.yview)
    scroll.pack(side="right", fill="y")
    text_box.configure(yscrollcommand=scroll.set)

    # 选中即复制: 双击选词 / Ctrl+A 全选 / Ctrl+C 复制
    def _copy(event=None) -> None:
        try:
            sel = text_box.tag_ranges("sel")
            content = text_box.get(sel[0], sel[-1]) if sel else text_box.get("1.0", "end-1c")
            if content:
                if parent:
                    parent.clipboard_clear()
                (parent or win).clipboard_append(content)
                (parent or win).clipboard_update()
        except tk.TclError:
            pass
        return "break"

    text_box.tag_configure("sel", background=Brand.PRIMARY_100, foreground=Neutral.TEXT_1)
    text_box.bind("<Control-c>", _copy)
    text_box.bind("<Control-a>", lambda e: (text_box.tag_add("sel", "1.0", "end-1c"), "break")[1])
    text_box.bind("<Double-Button-1>", lambda e: text_box.tag_add("sel", "around", "insert"))

    text_box.insert("1.0", text)
    text_box.configure(state="disabled")

    footer = ttk.Frame(win, style="Modern.TFrame")
    footer.pack(fill="x", padx=Space.LG, pady=(0, Space.LG))

    hint = ttk.Label(
        footer,
        text="双击选词 · Ctrl+A 全选 · Ctrl+C 复制",
        style="Modern.TLabel",
    )
    hint.pack(side="left")

    def _close() -> None:
        try:
            win.destroy()
        except tk.TclError:
            pass

    btn = create_primary_button(footer, "关闭", command=_close)
    btn.pack(side="right")

    # Esc 关闭
    win.bind("<Escape>", lambda e: _close())
    # 关闭时把插入光标复位, 避免下次打开还带着旧光标位置
    win.protocol("WM_DELETE_WINDOW", _close)

    return win
