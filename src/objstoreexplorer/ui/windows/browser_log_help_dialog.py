# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""浏览器 F12 Console 日志收集说明

ObjStoreExplorer 本身是 tkinter 桌面应用, 不会产生浏览器 console 日志.
但很多内部系统配套有 Web 管理端 (MinIO Console / 自建 Web), 遇到问题时常需要
收集浏览器控制台日志. 这个 Dialog 教用户怎么操作.

触发位置: 反馈 Dialog 的自检区「F12 取浏览器日志说明」按钮
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk

from ..widgets.scrollarea import bind_mousewheel
from ..styles import Brand, Neutral, Status, UIFont
from ..widgets.buttons import create_primary_button
from ...utils.icon_manager import get_window_icon


STEPS = [
    ("1", "打开浏览器", "在出问题的网页上, 按键盘 F12 (或右键 → 检查 / Inspect)"),
    ("2", "切到 Console 标签", "在开发者工具面板里找 「Console」 标签, 点击打开"),
    ("3", "复现错误", "保持 Console 打开, 重新操作触发问题, 错误会实时打印在 Console"),
    ("4", "保留 Network 日志 (可选)", "切到 「Network」 标签, 同样复现, 失败请求 (红色) 截图"),
    ("5", "保存 Console 日志", "在 Console 里右键 → 「Save as...」, 保存为 .log 文件, 一并发给管理员"),
    ("6", "截图", "连同 Console 面板一起截屏, 一起作为反馈附件上传"),
]


class BrowserLogHelpDialog:
    """浏览器 F12 Console 日志收集教程 Dialog"""

    def __init__(self, parent: tk.Misc):
        self.parent = parent
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("浏览器日志收集说明")
        self.dialog.geometry("560x520")
        self.dialog.minsize(480, 440)
        self.dialog.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self.dialog.grab_set()

        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconphoto(False, icon)
        except Exception:
            pass

        self._create()

    def _create(self):
        # 顶部说明
        tk.Label(
            self.dialog, text="如何收集浏览器 F12 Console 日志",
            font=(UIFont.family(), 13, "bold"),
            bg=Brand.PRIMARY, fg=Neutral.TEXT_INV,
        ).pack(fill="x", pady=(0, 8), ipady=12)

        tk.Label(
            self.dialog, text=(
                "ObjStoreExplorer 是 Windows 桌面应用, 本身没有浏览器控制台.\n"
                "但如果你在用配套的 Web 端 (如 MinIO Console) 遇到问题,\n"
                "按下面 6 步收集浏览器控制台日志, 一并提交到反馈里."
            ),
            font=(UIFont.family(), 10), fg=Neutral.TEXT_1,
            justify="left", anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 12))

        # 步骤区 (滚动)
        wrap = tk.Frame(self.dialog)
        wrap.pack(fill="both", expand=True, padx=20)
        canvas = tk.Canvas(wrap, highlightthickness=0, bg=Neutral.BG_PANEL)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=Neutral.BG_PANEL)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        # 原来用 bind_all + add="+" 且从不解绑, 关闭本窗口后残留 handler
        # 仍引用已销毁的 canvas, 任何一次滚轮都会 TclError 崩溃。
        # 注: 递归绑定必须在**内容建完之后**调用 —— 本窗内容全是 Label,
        #     提前调用时这些控件还不存在, 滚轮落在它们身上依旧没反应。

        for num, title, desc in STEPS:
            row = tk.Frame(inner, bg=Neutral.BG_PANEL)
            row.pack(fill="x", pady=6, anchor="w")
            tk.Label(
                row, text=num, font=(UIFont.family(), 12, "bold"),
                bg=Brand.PRIMARY, fg=Neutral.TEXT_INV, width=3, height=1,
            ).pack(side="left", padx=(0, 10))
            col = tk.Frame(row, bg=Neutral.BG_PANEL)
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=title, font=(UIFont.family(), 10, "bold"), bg=Neutral.BG_PANEL, anchor="w").pack(fill="x")
            tk.Label(col, text=desc, font=(UIFont.family(), 9), fg=Neutral.TEXT_3, bg=Neutral.BG_PANEL,
                     wraplength=380, justify="left", anchor="w").pack(fill="x", pady=(2, 0))

        # 内容全部建完, 现在才能把滚轮绑到所有后代控件上
        bind_mousewheel(canvas, inner)

        # 提示卡
        tip = tk.Frame(self.dialog, bg=Status.WARNING_BG, bd=1, relief="solid", highlightthickness=0)
        tip.pack(fill="x", padx=20, pady=12)
        tk.Label(
            tip, text=(
                "进阶: 还可以截屏当前窗口 (反馈 Dialog 的「截当前窗口」按钮),\n"
                "配合 F12 面板一起看, 管理员能直接定位错误."
            ),
            font=(UIFont.family(), 9), bg=Status.WARNING_BG, fg=Neutral.TEXT_1,
            justify="left", anchor="w",
        ).pack(padx=10, pady=8)

        create_primary_button(self.dialog, "知道了", self.dialog.destroy).pack(pady=(0, 16))
