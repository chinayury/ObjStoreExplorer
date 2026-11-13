# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""标签组件

⚠ 已废弃 (全项目零调用): 各页直接用 tk.Label + UIFont。
保留仅为兼容外部 import, 新代码别用。
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional

from ..styles import Brand, Neutral, Status, UIFont


def create_status_label(
    parent: tk.Misc,
    text: str,
    status: str = "normal",
) -> tk.Label:
    """创建状态标签

    Args:
        status: success / warning / danger / normal
    """
    color_map = {
        "success": (Status.SUCCESS, Status.SUCCESS_BG),
        "warning": (Status.WARNING, Status.WARNING_BG),
        "danger": (Status.DANGER, Status.DANGER_BG),
        "normal": (Neutral.TEXT_2, Neutral.BG_APP),
    }
    fg, bg = color_map.get(status, color_map["normal"])

    return tk.Label(
        parent, text=text, font=UIFont.body_sm(),
        fg=fg, bg=bg, padx=8, pady=2,
    )


def create_section_header(
    parent: tk.Misc,
    title: str,
    icon: Optional[str] = None,
    bg: str = Brand.PRIMARY,
) -> tk.Frame:
    """创建区域标题栏"""
    header = tk.Frame(parent, bg=bg, height=40)
    header.pack(fill=tk.X)
    header.pack_propagate(False)

    if icon:
        tk.Label(
            header, text=icon, font=("Arial", 14),
            bg=bg, fg=Neutral.TEXT_INV,
        ).pack(side=tk.LEFT, padx=12, pady=8)

    tk.Label(
        header, text=title, font=UIFont.h1(),
        bg=bg, fg=Neutral.TEXT_INV,
    ).pack(side=tk.LEFT, pady=8)

    return header
