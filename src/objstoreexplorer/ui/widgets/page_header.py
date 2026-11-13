# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/page_header — 页面标题 (Hero)

版式:
    ── OVERVIEW                      [操作区 actions]
    ▣ 存储总览
    并发统计全部存储桶的对象数…

用法:
    hdr = PageHeader(self.frame, "Overview", "存储总览",
                     "并发统计全部存储桶的对象数、文件夹数与容量占用。",
                     icon="layout-dashboard")
    hdr.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.MD))
    create_primary_button(hdr.actions, "刷新", self.refresh).pack(side=tk.LEFT)
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional

from ..styles import Brand, Neutral, Space, UIFont
from ...utils.icons import get as get_icon


class PageHeader(tk.Frame):
    """页眉: kicker + 巨型标题 + 副标题 + 右侧操作区"""

    def __init__(
        self,
        parent: tk.Misc,
        kicker: str,
        title: str,
        subtitle: str = "",
        icon: Optional[str] = None,
        bg: str = Neutral.BG_APP,
        **kw,
    ):
        super().__init__(parent, bg=bg, **kw)

        # ⚠ Tk pack 顺序分配 cavity: 右侧操作区必须先 pack,
        #   否则左侧 expand 的 main 会把它挤成 0 宽。
        self.actions = tk.Frame(self, bg=bg)
        self.actions.pack(side=tk.RIGHT, anchor=tk.S, padx=(Space.LG, 0))

        # ---- 左侧: kicker / 标题 / 副标题 ----
        main = tk.Frame(self, bg=bg)
        main.pack(side=tk.LEFT, fill=tk.X, expand=True)

        if kicker:
            kick = tk.Frame(main, bg=bg)
            kick.pack(anchor=tk.W, pady=(0, 2))
            # 16x2 陶土橙短横线 + 英文小标
            tk.Frame(kick, bg=Brand.PRIMARY_300, width=16, height=2).pack(
                side=tk.LEFT, pady=(4, 0), padx=(0, 7),
            )
            tk.Label(
                kick, text=kicker.upper(), font=UIFont.kicker(),
                bg=bg, fg=Brand.PRIMARY,
            ).pack(side=tk.LEFT)

        title_row = tk.Frame(main, bg=bg)
        title_row.pack(anchor=tk.W)

        if icon:
            # 34x34 陶土橙浅底图标块
            chip = tk.Frame(title_row, bg=Brand.PRIMARY_50, width=34, height=34)
            chip.pack(side=tk.LEFT, padx=(0, Space.MD))
            chip.pack_propagate(False)
            img = get_icon(icon, 24, tint=Brand.PRIMARY)
            if img is not None:
                lbl = tk.Label(chip, image=img, bg=Brand.PRIMARY_50)
                lbl.image = img
                lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            else:
                tk.Label(
                    chip, text="▣", font=("Segoe UI Symbol", 14),
                    bg=Brand.PRIMARY_50, fg=Brand.PRIMARY,
                ).place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        tk.Label(
            title_row, text=title, font=UIFont.display(),
            bg=bg, fg=Neutral.TEXT_1, anchor=tk.W,
        ).pack(side=tk.LEFT)

        if subtitle:
            tk.Label(
                main, text=subtitle, font=UIFont.body_sm(),
                bg=bg, fg=Neutral.TEXT_2, anchor=tk.W,
                justify=tk.LEFT, wraplength=760,
            ).pack(anchor=tk.W, pady=(5, 0))

        # ---- 底部分隔线 ----
        tk.Frame(self, bg=Neutral.BORDER, height=1).pack(
            side=tk.BOTTOM, fill=tk.X, pady=(Space.MD, 0),
        )


def make_note(parent: tk.Misc, text: str, icon: Optional[str] = None,
              bg: str = Neutral.BG_APP) -> tk.Frame:
    """虚线提示条 (用于页面顶部的补充说明)"""
    holder = tk.Frame(
        parent, bg=Neutral.BG_PANEL,
        highlightbackground=Neutral.BORDER_HI,
        highlightthickness=1, bd=0,
    )
    inner = tk.Frame(holder, bg=Neutral.BG_PANEL)
    inner.pack(padx=Space.MD, pady=Space.XS + 1)
    if icon:
        img = get_icon(icon, 16, tint=Neutral.TEXT_3)
        if img is not None:
            lbl = tk.Label(inner, image=img, bg=Neutral.BG_PANEL)
            lbl.image = img
            lbl.pack(side=tk.LEFT, padx=(0, 6))
    tk.Label(
        inner, text=text, font=UIFont.caption(),
        bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
    ).pack(side=tk.LEFT)
    return holder
