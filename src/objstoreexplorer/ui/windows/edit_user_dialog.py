# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""编辑用户对话框 - 重置 Secret Key

minio-py 没有 set_user_secret_key, 改密码 = remove + add(新 SK)。
保留用户附加的策略, 自动重新附加。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import messagebox
from typing import Optional, Callable

from ..styles import Brand, Neutral, Space, UIFont
from ..widgets.notifications import notify
from ...utils.icon_manager import get_window_icon
from ...core.admin_manager import generate_strong_password
from ...core.validators import validate_secret_key
from ...services.service_locator import ServiceLocator


class EditUserDialog:
    """编辑用户: 重置 Secret Key"""

    def __init__(
        self,
        parent: tk.Misc,
        locator: ServiceLocator,
        access_key: str,
        on_success: Optional[Callable] = None,
    ):
        self.parent = parent
        self.locator = locator
        self.access_key = access_key
        self._on_success = on_success
        # 定时器句柄 (遮罩恢复 / 剪贴板清空), 用于取消而非堆积
        self._reveal_token = None
        self._clip_clear_token = None

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f"重置密码 - {access_key}")
        self.dialog.geometry("480x360")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self.dialog.grab_set()

        self._set_icon()
        self._create_widgets()

    def _set_icon(self) -> None:
        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconbitmap(icon)
        except Exception:
            pass

    def _create_widgets(self) -> None:
        # 头部 (白底 + 靛蓝图标块 + 发丝线)
        from ..widgets.dialog import DialogChrome
        chrome = DialogChrome(self.dialog, "Reset Secret", "重置 Secret Key", "key")
        chrome.pack(fill=tk.BOTH, expand=True)
        content = chrome.body

        # 用户名 (只读)
        tk.Label(
            content, text="用户名 (Access Key)", font=UIFont.body_sm(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2, anchor=tk.W,
        ).grid(row=0, column=0, sticky=tk.W, padx=(0, Space.MD), pady=Space.XS)

        ak_entry = tk.Entry(
            content, font=UIFont.mono(10), bg=Neutral.BG_SUBTLE,
            fg=Neutral.TEXT_2, relief="flat", bd=0,
            highlightbackground=Neutral.BORDER, highlightthickness=1,
        )
        ak_entry.insert(0, self.access_key)
        ak_entry.config(state="readonly")
        ak_entry.grid(row=0, column=1, sticky=tk.EW, pady=Space.XS, ipady=6)

        # 新密码
        tk.Label(
            content, text="新 Secret Key", font=UIFont.body_sm(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2, anchor=tk.W,
        ).grid(row=1, column=0, sticky=tk.W, padx=(0, Space.MD), pady=Space.XS)

        self.sk_var = tk.StringVar()
        self.sk_entry = tk.Entry(
            content, textvariable=self.sk_var, font=UIFont.mono(10),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            insertbackground=Brand.PRIMARY,
            relief="flat", bd=0, show="*",
            highlightbackground=Neutral.BORDER_HI, highlightthickness=1,
        )
        self.sk_entry.grid(row=1, column=1, sticky=tk.EW, pady=Space.XS, ipady=6)
        content.columnconfigure(1, weight=1)

        # 自动生成 + 复制
        gen_frame = tk.Frame(content, bg=Neutral.BG_PANEL)
        gen_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(Space.SM, 0))

        tk.Button(
            gen_frame, text="自动生成强密码",
            font=UIFont.body_sm(), bg=Brand.PRIMARY_50,
            fg=Brand.PRIMARY_800, relief="flat", cursor="hand2",
            highlightthickness=0, bd=0,
            padx=12, pady=4, command=self._on_generate,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            gen_frame, text="复制",
            font=UIFont.body_sm(), bg=Neutral.BG_SUBTLE,
            fg=Neutral.TEXT_1, relief="flat", cursor="hand2",
            highlightthickness=0, bd=0,
            padx=12, pady=4, command=self._on_copy,
        ).pack(side=tk.LEFT)

        # 提示
        tk.Label(
            content,
            text="重置密码会重建用户, 用户附加的策略会自动重新附加。\n"
                 "MinIO 限制无法显示当前密码, 只能重置。",
            font=UIFont.caption(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
            justify=tk.LEFT, anchor=tk.W,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(Space.MD, 0))

        # 底部
        chrome.set_actions([
            ("取消", self.dialog.destroy),
            ("重置密码", self._on_reset, True),
        ])

        # 自动聚焦密码框
        self.sk_entry.focus_set()

    def _on_generate(self) -> None:
        pwd = generate_strong_password(16)
        self.sk_var.set(pwd)
        # 临时取消遮罩
        self.sk_entry.config(show="")
        # 旧版 3 秒后无条件 config(show="*"), 窗口已关时抛 TclError;
        # 连续点还会排多个定时器。取消上一个再排。
        if self._reveal_token is not None:
            try:
                self.dialog.after_cancel(self._reveal_token)
            except tk.TclError:
                pass
        try:
            self._reveal_token = self.dialog.after(
                3000, lambda: self.sk_entry.config(show="*"),
            )
        except tk.TclError:
            pass

    def _clear_clipboard(self) -> None:
        """30 秒后清空剪贴板里的明文 Secret Key"""
        try:
            self.dialog.clipboard_clear()
        except tk.TclError:
            pass
        try:
            if self.dialog.winfo_exists():
                notify(self.dialog, "info", "剪贴板中的密码已自动清空")
        except tk.TclError:
            pass

    def _on_copy(self) -> None:
        pwd = self.sk_var.get()
        if not pwd:
            messagebox.showwarning("提示", "请先生成或输入密码", parent=self.dialog)
            return
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(pwd)
        try:
            self.dialog.after_cancel(self._clip_clear_token)
        except (tk.TclError, AttributeError):
            pass
        try:
            self._clip_clear_token = self.dialog.after(30000, self._clear_clipboard)
        except tk.TclError:
            pass
        notify(self.dialog, "success", "密码已复制 (30 秒后自动清空)")

    def _on_reset(self) -> None:
        new_sk = self.sk_var.get().strip()
        ok, msg = validate_secret_key(new_sk)
        if not ok:
            messagebox.showerror("参数错误", msg, parent=self.dialog)
            return
        if not messagebox.askyesno(
            "确认重置",
            f"确定要重置用户 {self.access_key} 的 Secret Key 吗?\n"
            f"(会重建用户, 附加的策略自动重新附加)\n\n"
            f"注意: MinIO 限制, 原密码不可恢复, 请确保已保存新密码。",
            parent=self.dialog,
        ):
            return

        try:
            ok, msg = self.locator.admin_manager.reset_user_secret(
                self.access_key, new_sk,
            )
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self.dialog)
            return

        if ok:
            self.locator.logger.success(
                "reset_user_secret", self.access_key, msg,
            )
            messagebox.showinfo(
                "重置成功",
                f"用户 {self.access_key} 密码已重置。\n\n"
                f"新 Secret Key:\n{new_sk}\n\n"
                f"（建议立即复制保存，关闭此窗口后无法再次查看）",
                parent=self.dialog,
            )
            if self._on_success:
                self._on_success()
            self.dialog.destroy()
        else:
            messagebox.showerror("失败", msg, parent=self.dialog)
            self.locator.logger.error("reset_user_secret", self.access_key, msg)
