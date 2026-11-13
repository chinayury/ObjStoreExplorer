# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/breadcrumb - 可点击路径面包屑

用法:
    bc = Breadcrumb(parent, on_click=lambda idx: page.set_prefix_by_segment(idx))
    bc.set_segments(["桶名", "folder-a", "sub", "current"])
    # 第 0 段: 桶根; 第 -1 段: 当前层; 中间段可点
"""
from __future__ import annotations
import tkinter as tk
from typing import List, Callable, Optional

from ..styles import Brand, Neutral, Space, UIFont
from ...utils.icons import get as get_icon


class Breadcrumb(tk.Frame):
    """路径面包屑

    S3 key 最长 1024 字节, 单段目录名可以极长 —— 不截断的话面包屑会
    横向撑爆工具栏, 把桶下拉框和搜索框挤出可视区。
    """

    # 单段显示上限 (字符数), 超出则中间省略
    MAX_SEG = 24
    # 段总数上限, 超出时只保留首尾
    MAX_SEGMENTS = 10

    def __init__(
        self,
        parent: tk.Misc,
        on_click: Optional[Callable[[int], None]] = None,
        bg: Optional[str] = None,
        **kw,
    ):
        bg = bg or Neutral.BG_PANEL
        super().__init__(parent, bg=bg, **kw)
        self._on_click = on_click
        self._bg = bg
        self._segments: List[str] = []
        self._full_segments: List[str] = []

    @staticmethod
    def _ellipsize(text: str, limit: int) -> str:
        """超长段中间省略 (保留头尾, 比截尾更容易辨认)"""
        if len(text) <= limit:
            return text
        keep = max(2, (limit - 3) // 2)
        return f"{text[:keep]}...{text[-keep:]}"

    def set_segments(self, segments: List[str]) -> None:
        """更新面包屑显示"""
        self._segments = list(segments)
        self._full_segments = list(segments)
        # 清空
        for w in self.winfo_children():
            w.destroy()
        if not self._segments:
            return

        # 段数过多时中间折叠 (索引仍与 full 对应, 点击才能正确定位 prefix)
        n = len(self._segments)
        show_idx: List[int] = list(range(n))
        if n > self.MAX_SEGMENTS:
            head = self.MAX_SEGMENTS // 2
            tail = self.MAX_SEGMENTS - head - 1
            show_idx = list(range(head)) + [-1] + list(range(n - tail, n))

        for idx in show_idx:
            if idx == -1:
                self._add_ellipsis()
                continue
            is_last = (idx == n - 1)
            self._add_segment(idx, self._ellipsize(self._segments[idx], self.MAX_SEG),
                              is_last)
            if not is_last:
                self._add_separator()

    def _add_ellipsis(self) -> None:
        """被折叠掉的中间段提示 (hover 显示完整路径)"""
        hidden = self._full_segments[
            self.MAX_SEGMENTS // 2: len(self._full_segments) - (
                self.MAX_SEGMENTS - self.MAX_SEGMENTS // 2 - 1
            )
        ]
        lbl = tk.Label(
            self, text="…", font=UIFont.body(),
            bg=self._bg, fg=Neutral.TEXT_3, padx=Space.XS,
        )
        lbl.pack(side=tk.LEFT)
        self._bind_tooltip(lbl, " / ".join(hidden))

    def _bind_tooltip(self, widget: tk.Widget, text: str) -> None:
        """悬停显示完整段内容 (截断后看不到全名)"""
        tip: List[tk.Toplevel] = []

        def _show(_e=None) -> None:
            if not text or tip:
                return
            try:
                t = tk.Toplevel(widget)
                t.wm_overrideredirect(True)
                tk.Label(
                    t, text=text, font=UIFont.caption(),
                    bg=Neutral.TEXT_1, fg=Neutral.TEXT_INV,
                    padx=6, pady=3, justify=tk.LEFT,
                ).pack()
                t.update_idletasks()
                t.geometry(
                    f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 4}"
                )
                tip.append(t)
            except tk.TclError:
                pass

        def _hide(_e=None) -> None:
            for t in tip:
                try:
                    t.destroy()
                except tk.TclError:
                    pass
            tip.clear()

        widget.bind("<Enter>", _show, add="+")
        widget.bind("<Leave>", _hide, add="+")

    def _add_segment(self, idx: int, text: str, is_last: bool) -> None:
        full = self._full_segments[idx] if idx < len(self._full_segments) else text
        if is_last:
            # 当前段: 加粗,不可点
            lbl = tk.Label(
                self, text=text, font=UIFont.body(),
                bg=self._bg, fg=Neutral.TEXT_1,
                padx=Space.XS, cursor="",
            )
            lbl.pack(side=tk.LEFT)
        else:
            # 可点击段
            lbl = tk.Label(
                self, text=text, font=UIFont.body(),
                bg=self._bg, fg=Brand.PRIMARY,
                padx=Space.XS, cursor="hand2",
            )
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", lambda _e, i=idx: self._fire(i))
            lbl.bind("<Enter>", lambda _e, w=lbl: w.configure(fg=Brand.PRIMARY_700))
            lbl.bind("<Leave>", lambda _e, w=lbl: w.configure(fg=Brand.PRIMARY))
        # 截断过的段挂 tooltip, 让用户能看到完整 key 段
        if full != text:
            self._bind_tooltip(lbl, full)

    def _add_separator(self) -> None:
        img = get_icon("chevron-right", 16)
        if img is not None:
            lbl = tk.Label(self, image=img, bg=self._bg)
            lbl.image = img
            lbl.pack(side=tk.LEFT, padx=2)
        else:
            tk.Label(
                self, text="›", font=UIFont.body(),
                bg=self._bg, fg=Neutral.TEXT_3, padx=4,
            ).pack(side=tk.LEFT)

    def _fire(self, idx: int) -> None:
        if self._on_click:
            try:
                self._on_click(idx)
            except Exception:
                pass
