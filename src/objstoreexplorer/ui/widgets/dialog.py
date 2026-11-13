# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/dialog — 对话框外壳组件 (「暮橙 Emberline」)

统一所有 Toplevel 的头/尾:
    ┌ 陶土橙图标块 + 英文 kicker + 中文标题 ──────────────┐
    ├ 1px 发丝线 ────────────────────────────────────┤
    │  (调用方往 body 里放内容)                        │
    ├ 1px 发丝线 ────────────────────────────────────┤
    │  浅底操作条: [取消] [确定]                        │
    └────────────────────────────────────────────────┘

用法:
    dlg = tk.Toplevel(parent)
    chrome = DialogChrome(dlg, "Create User", "创建 MinIO 用户", "user")
    chrome.pack(fill=tk.BOTH, expand=True)
    ... 构建到 chrome.body ...
    chrome.set_actions([("取消", dlg.destroy), ("创建", on_ok, True)])
    chrome.set_busy(True, "创建中…")
"""
from __future__ import annotations
import tkinter as tk
from typing import List, Optional, Tuple

from ..styles import Brand, Neutral, Space, UIFont
from ...utils.icons import get as get_icon


class DialogChrome(tk.Frame):
    """对话框头 / 体 / 尾 三段式外壳"""

    def __init__(
        self,
        parent: tk.Misc,
        kicker: str = "",
        title: str = "",
        icon: Optional[str] = None,
        icon_size: int = 36,
        **kw,
    ):
        super().__init__(parent, bg=Neutral.BG_PANEL, **kw)

        # ---------------- 头部 ----------------
        head = tk.Frame(self, bg=Neutral.BG_PANEL, height=64)
        head.pack(fill=tk.X)
        head.pack_propagate(False)

        if icon:
            chip = tk.Frame(head, bg=Brand.PRIMARY_50, width=icon_size, height=icon_size)
            chip.pack(side=tk.LEFT, padx=(Space.LG, Space.MD), pady=Space.MD)
            chip.pack_propagate(False)
            img = get_icon(icon, icon_size - 12, tint=Brand.PRIMARY)
            if img is not None:
                lbl = tk.Label(chip, image=img, bg=Brand.PRIMARY_50)
                lbl.image = img
                lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            else:
                tk.Label(
                    chip, text="◆", font=("Segoe UI Symbol", 12, "bold"),
                    bg=Brand.PRIMARY_50, fg=Brand.PRIMARY_400,
                ).place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        text_col = tk.Frame(head, bg=Neutral.BG_PANEL)
        text_col.pack(side=tk.LEFT, fill=tk.Y, pady=Space.MD)
        if kicker:
            tk.Label(
                text_col, text=kicker.upper(), font=UIFont.kicker(),
                bg=Neutral.BG_PANEL, fg=Brand.PRIMARY,
            ).pack(anchor=tk.W)
        tk.Label(
            text_col, text=title, font=UIFont.h2(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W,
        ).pack(anchor=tk.W)

        tk.Frame(self, bg=Neutral.BORDER, height=1).pack(fill=tk.X)

        # ---------------- 体 ----------------
        self.body = tk.Frame(self, bg=Neutral.BG_PANEL)
        self.body.pack(fill=tk.BOTH, expand=True, padx=Space.LG, pady=Space.LG)

        # ---------------- 尾 (默认隐藏, set_actions 时显示) ----------------
        self._foot_sep = tk.Frame(self, bg=Neutral.BORDER, height=1)
        self._foot = tk.Frame(self, bg=Neutral.BG_SUBTLE)
        self._inner = tk.Frame(self._foot, bg=Neutral.BG_SUBTLE)
        self._inner.pack(fill=tk.X, padx=Space.LG, pady=Space.MD)
        self._buttons: dict = {}

    # ==================== 操作条 ====================

    def set_actions(self, actions: List[Tuple]) -> None:
        """actions: [(text, command), ...] 或 [(text, command, primary), ...]"""
        from ..widgets.buttons import (
            create_primary_button, create_secondary_button,
        )
        if not self._foot.winfo_ismapped():
            self._foot_sep.pack(fill=tk.X, side=tk.BOTTOM)
            self._foot.pack(fill=tk.X, side=tk.BOTTOM)
        for text, cmd, *rest in actions:
            primary = bool(rest and rest[0])
            factory = (create_primary_button if primary
                       else create_secondary_button)
            btn = factory(self._inner, text, cmd, icon=None)
            btn.pack(side=tk.RIGHT, padx=(Space.XS, 0))
            self._buttons[text] = btn

    def set_busy(self, busy: bool, label: str = "") -> None:
        """连接/提交过程中禁用全部操作按钮

        注: 目前无调用点 (各对话框自己实现了 _set_busy)。保留供后续统一。
        """
        for btn in self._buttons.values():
            try:
                btn.config(state=tk.DISABLED if busy else tk.NORMAL)
            except Exception:
                pass
        if busy and label:
            for text, btn in self._buttons.items():
                if text in ("确定", "创建", "连接", "保存", "应用", "提交"):
                    try:
                        btn.config(text=label)
                    except Exception:
                        pass

    def reset_label(self, text: str) -> None:
        btn = self._buttons.get(text)
        if btn is not None:
            try:
                btn.config(text=text, state=tk.NORMAL)
            except Exception:
                pass
