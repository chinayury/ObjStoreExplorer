# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""附加策略到用户对话框

关于页宣称「用户/策略: 附加/分离策略」, 但策略页此前没有任何附加入口,
功能在 core/s3_client_v1.py 里已实现 (admin_attach_policy /
admin_detach_policy) 却调不到。本对话框补上这个入口。

用法 (由 PoliciesPage 调用):
    AttachPolicyDialog(parent, locator, policy="readonly", users=[...],
                       on_success=page.refresh)
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable, List, Optional

from ..styles import Brand, Neutral, Space, UIFont
from ..widgets.buttons import create_primary_button, create_secondary_button
from ..widgets.notifications import notify
from ...utils.icon_manager import get_window_icon


def _user_display(u: Any) -> str:
    """兼容 dict / 对象两种 admin_list_users 返回"""
    if isinstance(u, dict):
        return str(u.get("accessKey") or u.get("access_key") or u.get("username") or u)
    for attr in ("accessKey", "access_key", "username", "status"):
        if hasattr(u, attr):
            return str(getattr(u, attr))
    return str(u)


def _user_key(u: Any) -> str:
    if isinstance(u, dict):
        return str(u.get("accessKey") or u.get("access_key") or u.get("username") or u)
    for attr in ("accessKey", "access_key", "username"):
        if hasattr(u, attr):
            return str(getattr(u, attr))
    return str(u)


class AttachPolicyDialog:
    """选择用户 → 附加或分离指定策略"""

    def __init__(
        self,
        parent: tk.Misc,
        locator,
        policy: str,
        users: List[Any],
        on_success: Optional[Callable] = None,
    ):
        self.parent = parent
        self.locator = locator
        self.policy = policy
        self.users = list(users or [])
        self._on_success = on_success
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f"附加策略 - {policy}")
        self.dialog.bind("<Destroy>", lambda _e: setattr(self, "_closed", True))
        sw = self.dialog.winfo_screenwidth()
        sh = self.dialog.winfo_screenheight()
        w, h = min(460, max(360, sw - 80)), min(420, max(320, sh - 140))
        self.dialog.geometry(
            f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 4)}"
        )
        self.dialog.resizable(False, False)
        self.dialog.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self.dialog.grab_set()

        self._set_icon()
        self._create_body()
        self._create_footer()

    def _set_icon(self) -> None:
        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconbitmap(icon)
        except Exception:
            pass

    def _create_body(self) -> None:
        body = tk.Frame(self.dialog, bg=Neutral.BG_PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=Space.XL, pady=Space.LG)

        tk.Label(
            body, text="附加策略", font=UIFont.h2(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W,
        ).pack(anchor=tk.W)
        tk.Label(
            body, text=f"策略: {self.policy}", font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Brand.PRIMARY, anchor=tk.W,
        ).pack(anchor=tk.W, pady=(Space.XS, Space.MD))

        tk.Label(
            body, text="选择用户", font=UIFont.body_sm(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2, anchor=tk.W,
        ).pack(anchor=tk.W, pady=(0, Space.XS))

        list_frame = tk.Frame(
            body, bg=Neutral.BG_SUBTLE,
            highlightbackground=Neutral.BORDER, highlightthickness=1,
        )
        list_frame.pack(fill=tk.BOTH, expand=True)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            list_frame, columns=("ak", "status"), show="headings",
            style="Modern.Treeview", selectmode="browse",
        )
        self.tree.heading("ak", text="Access Key")
        self.tree.heading("status", text="状态")
        self.tree.column("ak", width=250, anchor=tk.W)
        self.tree.column("status", width=90, anchor=tk.CENTER)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        for i, u in enumerate(self.users):
            status = ""
            if isinstance(u, dict):
                status = str(u.get("status", ""))
            elif hasattr(u, "status"):
                status = str(getattr(u, "status", ""))
            tag = ("zebra",) if i % 2 == 1 else ()
            self.tree.insert(
                "", tk.END, iid=f"u{i:04d}",
                values=(_user_display(u), status or "-"), tags=tag,
            )
        self.tree.tag_configure("zebra", background=Neutral.BG_SUBTLE)

    def _create_footer(self) -> None:
        tk.Frame(self.dialog, bg=Neutral.BORDER, height=1).pack(fill=tk.X)
        footer = tk.Frame(self.dialog, bg=Neutral.BG_SUBTLE)
        footer.pack(fill=tk.X, padx=Space.XL, pady=Space.MD)
        create_secondary_button(
            footer, "关闭", self.dialog.destroy, width=8,
        ).pack(side=tk.RIGHT)
        self._detach_btn = create_secondary_button(
            footer, "分离策略", self._on_detach, icon="x", width=10,
        )
        self._detach_btn.pack(side=tk.RIGHT, padx=(0, Space.XS))
        create_primary_button(
            footer, "附加到用户", self._on_attach, icon="check", width=10,
        ).pack(side=tk.RIGHT)

    def _selected_user(self) -> Optional[str]:
        sel = self.tree.selection()
        if not sel:
            return None
        values = self.tree.item(sel[0])["values"]
        if not values:
            return None
        return str(values[0])

    def _on_attach(self) -> None:
        ak = self._selected_user()
        if not ak:
            messagebox.showwarning("提示", "请先选择一个用户", parent=self.dialog)
            return
        client = self.locator.s3_client
        try:
            ok, msg = client.admin_attach_policy(self.policy, ak)
        except Exception as e:
            messagebox.showerror("附加失败", str(e), parent=self.dialog)
            return
        if ok:
            notify(self.dialog, "success", msg or f"策略已附加到 {ak}")
            self.locator.logger.success("attach_policy", ak, msg)
            if self._on_success:
                self._on_success()
            self.dialog.destroy()
        else:
            messagebox.showerror("附加失败", msg, parent=self.dialog)
            self.locator.logger.error("attach_policy", ak, msg)

    def _on_detach(self) -> None:
        ak = self._selected_user()
        if not ak:
            messagebox.showwarning("提示", "请先选择一个用户", parent=self.dialog)
            return
        if not messagebox.askyesno(
            "确认分离",
            f"确定要把策略「{self.policy}」从用户 {ak} 分离吗?\n\n"
            "分离后该用户将立即失去此策略授予的权限。",
            parent=self.dialog,
        ):
            return
        client = self.locator.s3_client
        try:
            ok, msg = client.admin_detach_policy(self.policy, ak)
        except Exception as e:
            messagebox.showerror("分离失败", str(e), parent=self.dialog)
            return
        if ok:
            notify(self.dialog, "success", msg or f"策略已从 {ak} 分离")
            self.locator.logger.success("detach_policy", ak, msg)
            if self._on_success:
                self._on_success()
            self.dialog.destroy()
        else:
            messagebox.showerror("分离失败", msg, parent=self.dialog)
            self.locator.logger.error("detach_policy", ak, msg)
