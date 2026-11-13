# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/widgets/toast - 非阻塞 Toast 通知

特性:
    - Toplevel(overrideredirect=True),无边框,右上角弹出
    - 不调 grab_set,不抢焦点
    - 同时多个 Toast 垂直堆叠
    - 计时关闭 + 点击立即关闭
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional, Literal

from ..styles import Status, Neutral, UIFont, Space
from ...utils.icons import get as get_icon


_KIND_THEME = {
    "success": (Status.SUCCESS, Status.SUCCESS_BG, "check"),
    "info":    (Status.INFO,    Status.INFO_BG,    "info"),
    # 注意图标名必须与 resources/icons/ 里的真实文件一致:
    # 实际是 triangle-alert@16.png, 旧版写的 "alert-triangle" 永远缺图,
    # 警告 toast 只能退回纯色圆点。
    "warning": (Status.WARNING, Status.WARNING_BG, "triangle-alert"),
    "error":   (Status.DANGER,  Status.DANGER_BG,  "x"),
}

# 历史调用点传过 "warn" (见 feedback_dialog), 主题表里只有 "warning"。
# 静默降级成蓝色 info 会让 "已达上限" 这类提示看起来像普通信息, 故显式做别名。
_KIND_ALIASES = {
    "warn": "warning",
    "err": "error",
    "ok": "success",
    "danger": "error",
}


def _resolve_kind(kind: str) -> str:
    """把 kind 归一到主题表里的键, 查不到时打日志并降级为 info"""
    k = (kind or "info").strip().lower()
    k = _KIND_ALIASES.get(k, k)
    if k not in _KIND_THEME:
        print(f"[toast] 未知 kind={kind!r}, 降级为 info")
        return "info"
    return k


# 全局堆栈: 跟踪当前可见 toast 的纵向偏移
_ACTIVE_TOASTS: list = []


class Toast(tk.Toplevel):
    """非模态通知窗口"""

    MARGIN_TOP = 16
    MARGIN_RIGHT = 24
    GAP = 8

    def __init__(
        self,
        parent: tk.Misc,
        message: str,
        kind: Literal["success", "info", "warning", "error"] = "info",
        duration: int = 2500,
    ):
        # ⚠ master 一律用 Tk 根窗口, 不用 parent.winfo_toplevel()。
        #   传对话框做 master 时, 对话框一 destroy, toast 作为它的子窗口
        #   一起被销毁 —— 表现就是"成功提示一闪即灭", 用户什么都看不到。
        root = _root_of(parent)
        super().__init__(root)
        self.overrideredirect(True)
        try:
            # Tk 8.6+: 顶层 hint,使 toast 始终在前
            self.attributes("-topmost", True)
        except Exception:
            pass

        # 计时器句柄: 手动点关闭时必须 after_cancel, 否则控制台刷
        # "invalid command name ... after script" 悬空噪声
        self._timer: Optional[str] = None

        kind = _resolve_kind(kind)
        fg, bg, icon_name = _KIND_THEME[kind]
        self.configure(bg=bg)

        # 边框模拟
        border = tk.Frame(self, bg=fg, padx=0, pady=0)
        border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(border, bg=Neutral.BG_PANEL)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 左侧色条
        tk.Frame(inner, bg=fg, width=4).pack(side=tk.LEFT, fill=tk.Y)

        # 内容
        content = tk.Frame(inner, bg=Neutral.BG_PANEL)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                     padx=Space.MD, pady=Space.SM)

        # 图标按状态色着色 (视觉重构: 与浅底/色条同色系)
        img = get_icon(icon_name, 16, tint=fg)
        if img is not None:
            lbl_icon = tk.Label(content, image=img, bg=Neutral.BG_PANEL)
            lbl_icon.image = img
            lbl_icon.pack(side=tk.LEFT, padx=(0, Space.SM))
        else:
            # 缺图兜底: 用纯色圆点 (tk.Canvas), 不退回 Emoji
            dot = tk.Canvas(content, width=12, height=12,
                            bg=Neutral.BG_PANEL, highlightthickness=0, bd=0)
            dot.create_oval(1, 1, 11, 11, fill=fg, outline=fg)
            dot.pack(side=tk.LEFT, padx=(2, Space.SM))

        tk.Label(
            content, text=message, font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            wraplength=320, justify=tk.LEFT, anchor=tk.W,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 点击关闭
        for w in (self, border, inner, content):
            w.bind("<Button-1>", lambda _e: self._close())

        # 定位
        self.update_idletasks()
        self._position()

        _ACTIVE_TOASTS.append(self)
        # 计时关闭
        if duration > 0:
            self._timer = self.after(duration, self._close)

    def _position(self) -> None:
        # ⚠ 每一条 Tcl 调用都要包 try: 堆栈里的兄弟 toast 可能刚被销毁
        #   (点掉一个 toast 后, 新 toast 立刻创建, 对已销毁 toplevel 调
        #    winfo_exists()/winfo_reqheight() 会抛 TclError, 之前这个异常
        #    冒到 notify() 被兜底成 messagebox, 突然弹出模态框打断用户)
        try:
            sw = self.winfo_screenwidth()
            w = self.winfo_reqwidth()
            h = self.winfo_reqheight()
        except tk.TclError:
            return
        x = sw - w - self.MARGIN_RIGHT
        # 堆叠: 已存在的 toast 高度累加
        y = self.MARGIN_TOP
        for t in list(_ACTIVE_TOASTS):
            if t is self:
                continue
            try:
                if t.winfo_exists():
                    y += t.winfo_reqheight() + self.GAP
            except tk.TclError:
                # 兄弟已销毁, 从堆栈里剔掉
                try:
                    _ACTIVE_TOASTS.remove(t)
                except ValueError:
                    pass
        try:
            self.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass

    def _close(self) -> None:
        # 先取消计时器, 避免 destroy 后 after 脚本再触发一次悬空回调
        if self._timer is not None:
            try:
                self.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        try:
            _ACTIVE_TOASTS.remove(self)
        except ValueError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
        # 重排剩余 toast
        _reflow()


def _root_of(parent: Optional[tk.Misc]) -> Optional[tk.Misc]:
    """上溯到 Tk 根窗口 (master 用 root, toast 才不会被对话框带死)

    ⚠ 不能用 `while: w = w.winfo_toplevel()` 上溯 ——
    `winfo_toplevel()` 对一个 Toplevel 自身就返回它自己, 循环第一轮
    `parent_tl is w` 成立直接返回, 于是传进来的对话框原样被当成 root,
    "对话框一 destroy, toast 跟着死" 这个症状一点没解决。
    tkinter 自带的 `Misc._root()` 才是正确的上溯 (沿 master 链一路到 root)。
    它是私有 API 但极稳定, 且项目里 icon_manager 已在用同类手法。
    """
    if parent is None:
        return None
    try:
        w = parent._root()
    except Exception:
        w = None
    if w is not None:
        return w
    # 兜底: _root() 不可用时, 沿 master 链手工上溯 (不用 winfo_toplevel)
    try:
        w = parent
        while w is not None:
            parent = w.master
            if parent is None or parent is w:
                return w
            w = parent
    except tk.TclError:
        return None
    return None


def _reflow() -> None:
    """剩余 toast 上移填补"""
    y = Toast.MARGIN_TOP
    for t in list(_ACTIVE_TOASTS):
        try:
            if not t.winfo_exists():
                _ACTIVE_TOASTS.remove(t)
                continue
            w = t.winfo_reqwidth()
            h = t.winfo_reqheight()
            sw = t.winfo_screenwidth()
            x = sw - w - Toast.MARGIN_RIGHT
            t.geometry(f"{w}x{h}+{x}+{y}")
            y += h + Toast.GAP
        except tk.TclError:
            # 该 toast 已销毁: 摘掉并继续排下一个
            try:
                _ACTIVE_TOASTS.remove(t)
            except ValueError:
                pass
            continue
