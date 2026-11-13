# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/badge — 胶囊徽章 (状态 / 标签 / 计数)

浅底 + 同色系描边 + 略小字重。用于状态标记 (启用/停用/角色等)。
dot=True 时左侧加 8px 实心圆点 (Canvas 画, Tk 没有 border-radius)。
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional

from ..styles import Status, Neutral, Brand, UIFont, Space
from ...utils.icons import get as get_icon


_KIND_COLORS = {
    "success": (Status.SUCCESS_FG, Status.SUCCESS_BG, Status.SUCCESS),
    "warning": (Status.WARNING_FG, Status.WARNING_BG, Status.WARNING),
    "danger":  (Status.DANGER_FG,  Status.DANGER_BG,  Status.DANGER),
    "info":    (Status.INFO_FG,    Status.INFO_BG,    Status.INFO),
    "primary": (Brand.PRIMARY_800, Brand.PRIMARY_50,  Brand.PRIMARY),
    "neutral": (Neutral.TEXT_2,    Neutral.BG_SUBTLE, Neutral.BORDER_HI),
}


class Badge(tk.Frame):
    """前景 + 浅底色的小胶囊徽章

    用法:
        Badge(parent, "已连接", kind="success", dot=True).pack()
    """

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        kind: str = "info",
        dot: bool = False,
        bg: Optional[str] = None,
        icon: Optional[str] = None,
        **kw,
    ):
        fg, bg_color, line = _KIND_COLORS.get(kind, _KIND_COLORS["info"])
        outer_bg = bg or bg_color
        super().__init__(
            parent, bg=outer_bg,
            highlightbackground=line,
            highlightthickness=1, bd=0,
            **kw,
        )

        inner = tk.Frame(self, bg=outer_bg)
        inner.pack(padx=Space.SM, pady=1)

        if dot:
            canvas = tk.Canvas(
                inner, width=8, height=8, bg=outer_bg,
                highlightthickness=0, bd=0,
            )
            canvas.create_oval(0, 0, 7, 7, fill=line, outline=line)
            canvas.pack(side=tk.LEFT, padx=(0, 6))

        img = get_icon(icon, 16, tint=fg) if icon else None
        if img is not None:
            lbl_icon = tk.Label(inner, image=img, bg=outer_bg)
            lbl_icon.image = img
            lbl_icon.pack(side=tk.LEFT, padx=(0, 5))

        self._label = tk.Label(
            inner, text=text, font=UIFont.caption(),
            bg=outer_bg, fg=fg,
        )
        self._label.pack(side=tk.LEFT)

    def set_text(self, text: str) -> None:
        """更新徽章文字 (Badge 的 kind 不可变, 需要换色请重建)"""
        try:
            self._label.configure(text=text)
        except Exception:
            pass
