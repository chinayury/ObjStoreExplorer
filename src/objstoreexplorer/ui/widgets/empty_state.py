# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/widgets/empty_state — 空状态

版式: 64x64 陶土橙浅底图标块 → 主提示 → 副提示 → 快捷按钮
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional, List, Tuple, Callable

from ..styles import Brand, Neutral, Space, UIFont
from ..widgets.buttons import create_primary_button, create_secondary_button
from ...utils.icons import get as get_icon


def create_empty_state(
    parent: tk.Misc,
    message: str,
    icon: str = "",
    icon_name: Optional[str] = None,
    buttons: Optional[List[Tuple[str, Callable]]] = None,
    hint: str = "",
    bg: str = Neutral.BG_PANEL,
) -> tk.Frame:
    """创建空状态提示

    Args:
        parent:    父容器
        message:   主提示
        icon:      文字符号兜底 (仅当 icon_name 缺图时使用)
        icon_name: Lucide 图标名 (48px)
        buttons:   [(text, command), ...] 快捷按钮
        hint:      副提示 (一行小字)
    """
    state_frame = tk.Frame(parent, bg=bg)

    # 64x64 陶土橙浅底图标块
    chip = tk.Frame(state_frame, bg=Brand.PRIMARY_50, width=64, height=64)
    chip.pack(pady=(Space.XXL, Space.MD))
    chip.pack_propagate(False)

    img = get_icon(icon_name, 48, tint=Brand.PRIMARY_300) if icon_name else None
    if img is not None:
        lbl = tk.Label(chip, image=img, bg=Brand.PRIMARY_50)
        lbl.image = img
    else:
        lbl = tk.Label(
            chip, text=icon or "▢", font=("Segoe UI Symbol", 22),
            bg=Brand.PRIMARY_50, fg=Brand.PRIMARY_300,
        )
    lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    # 主提示
    tk.Label(
        state_frame, text=message, font=UIFont.h3(),
        bg=bg, fg=Neutral.TEXT_1, wraplength=440, justify=tk.CENTER,
    ).pack()

    # 副提示
    if hint:
        tk.Label(
            state_frame, text=hint, font=UIFont.body_sm(),
            bg=bg, fg=Neutral.TEXT_3, wraplength=440, justify=tk.CENTER,
        ).pack(pady=(Space.XS + 2, 0))

    # 快捷按钮
    if buttons:
        btn_frame = tk.Frame(state_frame, bg=bg)
        btn_frame.pack(pady=(Space.LG, Space.XXL))
        for i, (text, cmd) in enumerate(buttons):
            factory = create_primary_button if i == 0 else create_secondary_button
            factory(btn_frame, text, cmd, width=14).pack(
                side=tk.LEFT, padx=Space.XS,
            )

    return state_frame
