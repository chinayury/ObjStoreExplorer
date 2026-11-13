# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/notifications - notify() shim

统一入口: notify(parent, kind, msg) -> 用 Toast 显示;失败回退 messagebox。
"""
from __future__ import annotations
import tkinter as tk
from typing import Literal

from ..widgets.toast import Toast


KindStr = Literal["success", "info", "warning", "error"]


def notify(
    parent: tk.Misc,
    kind: KindStr,
    message: str,
    duration: int = 2500,
) -> None:
    """显示 Toast 通知。

    与 messagebox.showinfo 互为替代,但不阻塞:
        - 成功反馈 ("已上传/已删除/已粘贴/已断开") 全用 notify
        - 错误/警告/确认仍用 messagebox

    parent 可以是任意 widget,内部会找 winfo_toplevel()。
    """
    try:
        Toast(parent, message, kind=kind, duration=duration)
    except Exception:
        # 兜底: 异常时退回 messagebox (避免 silently swallow)
        try:
            from tkinter import messagebox
            title_map = {"success": "成功", "info": "提示",
                         "warning": "警告", "error": "错误"}
            if kind == "error":
                messagebox.showerror(title_map[kind], message)
            elif kind == "warning":
                messagebox.showwarning(title_map[kind], message)
            else:
                messagebox.showinfo(title_map.get(kind, "提示"), message)
        except Exception:
            pass
