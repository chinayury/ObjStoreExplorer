# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/card — 卡片容器 (1px 描边 + 3px 主色 accent 条)

暮橙 Emberline 的强调手段 (替代旧版纯描边):
    - 1px BORDER 描边 = 卡片轮廓 (CARD_RADIUS 10)
    - 左侧 3px PRIMARY accent 条 = 层级强调
    - 卡片内 12px 留白 + 标题区下方 1px DIVIDER 分隔

用法:
    card = Card(parent, title="分桶容量明细", icon="server")
    card.pack(fill=tk.BOTH, expand=True, padx=Space.HERO_PAD_X)
    # 业务内容放进 card.body, 与原 tk.Frame 用法一致
    tk.Label(card.body, text="hello").pack()
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional, List, Tuple, Callable

from ..styles import Brand, Neutral, Space, Surface, UIFont
from ..widgets.buttons import create_secondary_button
from ...utils.icons import get as get_icon


class Card(tk.Frame):
    """曜蓝卡片 (1px 描边 + 左侧 3px 主色 accent 条)"""

    def __init__(
        self,
        parent: tk.Misc,
        title: Optional[str] = None,
        icon: Optional[str] = None,
        padding: int = Space.CARD_PAD,
        actions: Optional[List[Tuple[str, Callable]]] = None,
        action_icons: Optional[List[Optional[str]]] = None,
        **kw,
    ):
        super().__init__(
            parent,
            bg=Neutral.BG_PANEL,
            highlightbackground=Neutral.BORDER,
            highlightthickness=1,
            bd=0,
            **kw,
        )
        self._padding = padding

        # 左侧 3px 主色 accent 条 (曜蓝强调手段, 替代旧版纯描边)
        self._accent = tk.Frame(self, bg=Brand.PRIMARY, width=Surface.ACCENT_W)
        self._accent.pack(side=tk.LEFT, fill=tk.Y)
        self._accent.pack_propagate(False)

        self._inner = tk.Frame(self, bg=Neutral.BG_PANEL)
        self._inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ---------------- header (可选) ----------------
        if title:
            header = tk.Frame(self._inner, bg=Neutral.BG_PANEL)
            header.pack(fill=tk.X, padx=padding, pady=(padding, Space.SM))

            # ⚠ Tk pack 顺序分配 cavity: 右侧按钮组先 pack,
            #   否则左侧 expand 的标题会把它们挤成 0 宽。
            btn_frame = None
            if actions:
                btn_frame = tk.Frame(header, bg=Neutral.BG_PANEL)
                btn_frame.pack(side=tk.RIGHT)
                for i, (text, cmd) in enumerate(actions):
                    ic = action_icons[i] if action_icons and i < len(action_icons) else None
                    # ⚠ 走 buttons.py 工厂: 旧版直接裸 tk.Button, 没有 hover
                    #   过渡, 配色 (padx=10/pady=4) 也是魔法数, 与全站按钮不一致。
                    create_secondary_button(btn_frame, text, cmd, icon=ic).pack(
                        side=tk.LEFT, padx=(Space.XS, 0),
                    )

            if icon:
                img = get_icon(icon, 24, tint=Brand.PRIMARY)
                if img is not None:
                    lbl_icon = tk.Label(header, image=img, bg=Neutral.BG_PANEL)
                    lbl_icon.image = img
                    lbl_icon.pack(side=tk.LEFT, padx=(0, Space.SM))

            tk.Label(
                header, text=title, font=UIFont.h2(),
                bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
                anchor=tk.W,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            tk.Frame(self._inner, bg=Neutral.DIVIDER, height=1).pack(fill=tk.X)

        # ---------------- body ----------------
        self.body = tk.Frame(self._inner, bg=Neutral.BG_PANEL)
        self.body.pack(fill=tk.BOTH, expand=True,
                       padx=padding, pady=(Space.SM if title else padding, padding))
