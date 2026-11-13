# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/stat_card — 统计卡

版式:
    ┃ (3px 陶土橙 accent 竖条, 颜色按指标语义取)
    [16px 图标] 标签
    大数字 (等宽字体, 数值跳动不抖)
    英文小标

用法:
    sc = StatCard(parent, "存储桶数量", "BUCKETS", "archive", Brand.PRIMARY)
    sc.pack(fill=tk.X)
    sc.set_value("6")
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional

from ..styles import Brand, Neutral, Space, Surface, UIFont
from ...utils.icons import get as get_icon


class StatCard(tk.Frame):
    """带左侧陶土橙 accent 竖条的统计卡"""

    def __init__(
        self,
        parent: tk.Misc,
        label: str,
        sublabel: str = "",
        icon: Optional[str] = None,
        accent: str = Brand.PRIMARY,
        bg: str = Neutral.BG_PANEL,
        **kw,
    ):
        super().__init__(
            parent, bg=bg,
            highlightbackground=Neutral.BORDER,
            highlightthickness=1, bd=0,
            **kw,
        )
        self._accent = accent

        row = tk.Frame(self, bg=bg)
        row.pack(fill=tk.BOTH, expand=True,
                 padx=Space.LG, pady=(Space.MD, Space.MD))

        # 左侧 3px 陶土橙 accent 竖条
        tk.Frame(row, bg=accent, width=Surface.ACCENT_W).pack(
            side=tk.LEFT, fill=tk.Y, padx=(0, Space.MD),
        )

        body = tk.Frame(row, bg=bg)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 标签行: 图标 + 文字
        head = tk.Frame(body, bg=bg)
        head.pack(anchor=tk.W)
        if icon:
            img = get_icon(icon, 16, tint=accent)
            if img is not None:
                lbl = tk.Label(head, image=img, bg=bg)
                lbl.image = img
                lbl.pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(
            head, text=label, font=UIFont.body_sm(),
            bg=bg, fg=Neutral.TEXT_2,
        ).pack(side=tk.LEFT)

        # 大数字
        self._value = tk.Label(
            body, text="—", font=UIFont.metric(),
            bg=bg, fg=Neutral.TEXT_1, anchor=tk.W,
        )
        self._value.pack(anchor=tk.W, pady=(Space.XS, 0))

        if sublabel:
            tk.Label(
                body, text=sublabel, font=UIFont.kicker(),
                bg=bg, fg=Neutral.TEXT_3,
            ).pack(anchor=tk.W, pady=(2, 0))

        # 供 Skeleton 占位用
        self.value_holder = tk.Frame(body, bg=bg, height=26)
        self.value_holder.pack(anchor=tk.W, fill=tk.X, pady=(Space.XS, 0))
        self.value_holder.pack_forget()

    def set_value(self, value: str) -> None:
        try:
            self._value.config(text=str(value))
        except Exception:
            pass

    def show_placeholder(self, show: bool) -> None:
        """数值位在加载中时让位给 Skeleton"""
        try:
            if show:
                self._value.pack_forget()
                self.value_holder.pack(anchor=tk.W, fill=tk.X, pady=(Space.XS, 0))
            else:
                self.value_holder.pack_forget()
                self._value.pack(anchor=tk.W, pady=(Space.XS, 0))
        except Exception:
            pass


# 说明: 旧版此处还有 _TINT / tint_for() 两个"主色 → 浅底色"的死代码
# (全项目零调用)。卡片浅底固定取 bg 参数传入的 Neutral.BG_PANEL,
# 不再按 accent 二次着色, 故已删除, 相应地从 widgets/__init__.py
# 的导出列表里一并移除。
