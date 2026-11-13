# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""用户管理页面"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Tuple

from ..pages.base_page import BasePage
from ..styles import Neutral, Space, Status, UIFont
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.buttons import (
    create_primary_button, create_secondary_button, create_danger_ghost_button
)
from ..widgets.notifications import notify


class UsersPage(BasePage):
    """用户管理页面 (需要 Admin 权限)"""

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="Identities",
            title="MinIO 用户",
            subtitle="创建 S3 账号、切换启用状态、重置 Secret Key；支持一键创建整套授权（需 Admin API 权限）。",
            icon="users",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))

        # ⚠ Tk pack 顺序分配 cavity: 右侧按钮组先 pack
        create_danger_ghost_button(
            header.actions, "删除选中", self._on_delete_user, icon="trash-2",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        self.toggle_btn = create_secondary_button(
            header.actions, "启用/禁用", self._on_toggle_status, icon="power",
        )
        self.toggle_btn.pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "重置密码", self._on_edit_user, icon="key",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_primary_button(
            header.actions, "创建用户", self._on_create_user, icon="user",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "刷新", self.refresh, icon="refresh-cw",
        ).pack(side=tk.LEFT)

        # 提示标签 (如不支持)
        self.tip_var = tk.StringVar()
        tk.Label(
            self.frame, textvariable=self.tip_var,
            font=UIFont.body_sm(), bg=Neutral.BG_APP,
            fg=Status.WARNING,
        ).pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(0, Space.SM))

        # 表格
        card = Card(self.frame, title="账号列表", icon="user")
        card.pack(fill=tk.BOTH, expand=True,
                  padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))
        table_frame = card.body

        columns = ("access_key", "status", "policy")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings",
            style="Modern.Treeview",
        )
        self.tree.heading("access_key", text="Access Key")
        self.tree.heading("status", text="状态")
        self.tree.heading("policy", text="策略")

        self.tree.column("access_key", width=300, anchor=tk.W)
        self.tree.column("status", width=120, anchor=tk.CENTER)
        self.tree.column("policy", width=300, anchor=tk.W)

        scroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 斑马纹 + 状态色 tag (M4)
        self.tree.tag_configure("zebra", background=Neutral.BG_SUBTLE)
        self.tree.tag_configure("enabled", foreground=Status.SUCCESS)
        self.tree.tag_configure("disabled", foreground=Neutral.TEXT_3)

        # 右键菜单 (走 _toggle_status(ak, action) 签名, 跟 toolbar 复用)
        self.context_menu = tk.Menu(self.frame, tearoff=0)
        self.context_menu.add_command(label="编辑 (重置密码)", command=self._on_edit_user)

        def _ctx_enable():
            info = self._get_selected_user_info()
            if info:
                self._toggle_status(info[0], "enable")

        def _ctx_disable():
            info = self._get_selected_user_info()
            if info:
                self._toggle_status(info[0], "disable")

        self.context_menu.add_command(label="启用", command=_ctx_enable)
        self.context_menu.add_command(label="禁用", command=_ctx_disable)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="删除", command=self._on_delete_user)
        self.context_menu.add_command(label="刷新", command=self.refresh)
        self.tree.bind("<Button-3>", self._show_context_menu)

        # 选中变化时, 动态更新 启用/禁用 按钮标签
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_toggle_btn_label())

    def _show_context_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    def refresh(self) -> None:
        """刷新用户列表"""
        if not self.locator.is_connected:
            return

        if not self.locator.admin_manager.admin_available:
            self.tip_var.set("当前客户端不支持用户管理 (需要 minio-py >= 7.1 + Admin 权限)")
            for item in self.tree.get_children():
                self.tree.delete(item)
            return

        self.tip_var.set("")
        ok, users = self.locator.admin_manager.list_users()
        if not ok:
            messagebox.showerror("错误", str(users))
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        for i, user in enumerate(users):
            status = str(user.get("status", "-")).lower()
            if status == "enabled":
                status_display = "● 已启用"
                status_tag = "enabled"
            elif status == "disabled":
                status_display = "○ 已禁用"
                status_tag = "disabled"
            else:
                status_display = user.get("status", "-")
                status_tag = ""
            tags = []
            if status_tag:
                tags.append(status_tag)
            if i % 2 == 1:
                tags.append("zebra")
            self.tree.insert("", tk.END, values=(
                user.get("access_key", "-"),
                status_display,
                user.get("policy", "-"),
            ), tags=tuple(tags))

        self.locator.logger.info("users_refresh", "", f"刷新用户列表,共 {len(users)} 个")
        # refresh 后刷新 启用/禁用 按钮标签 (selection 可能丢了)
        self._update_toggle_btn_label()

    def _on_create_user(self) -> None:
        """仅创建用户 (AK/SK); 整套创建走顶栏「一键创建」 (拆分)"""
        from ..windows.create_user_dialog import CreateUserDialog
        CreateUserDialog(self.frame, self.locator, on_success=self.refresh)

    def _on_edit_user(self) -> None:
        """编辑用户: 重置 Secret Key"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一个用户")
            return
        values = self.tree.item(selected[0])["values"]
        if not values:
            messagebox.showwarning("提示", "该行数据不完整, 请刷新后重试")
            return
        ak = str(values[0])
        from ..windows.edit_user_dialog import EditUserDialog
        EditUserDialog(self.frame, self.locator, access_key=ak, on_success=self.refresh)

    def _on_delete_user(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一个用户")
            return
        values = self.tree.item(selected[0])["values"]
        if not values:
            messagebox.showwarning("提示", "该行数据不完整, 请刷新后重试")
            return
        ak = str(values[0])
        if not messagebox.askyesno("确认", f"确定要删除用户 {ak} 吗?"):
            return

        ok, msg = self.locator.admin_manager.delete_user(ak)
        if ok:
            notify(self.frame, "success", msg)
            self.locator.logger.success("delete_user", ak, msg)
            self.refresh()
        else:
            messagebox.showerror("失败", msg)
            self.locator.logger.error("delete_user", ak, msg)

    def _on_toggle_status(self) -> None:
        """根据当前选中用户状态, 智能启用/禁用"""
        info = self._get_selected_user_info()
        if not info:
            messagebox.showwarning("提示", "请先选中一个用户")
            return
        ak, status = info
        if status == "enabled":
            self._toggle_status(ak, "disable")
        else:
            self._toggle_status(ak, "enable")

    def _get_selected_user_info(self) -> Optional[Tuple[str, str]]:
        """获取当前选中用户的 (access_key, status) 元组"""
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0])["values"]
        if not values or len(values) < 2:
            return None
        ak = str(values[0])
        # status 形如 "● 已启用" / "○ 已禁用" / 原样 status
        status_raw = str(values[1])
        if "已启用" in status_raw:
            status = "enabled"
        elif "已禁用" in status_raw:
            status = "disabled"
        else:
            status = status_raw.lower()
        return ak, status

    def _toggle_status(self, access_key: str, action: str) -> None:
        """切换用户状态 (action='enable' / 'disable')"""
        if action == "enable":
            ok, msg = self.locator.admin_manager.enable_user(access_key)
        else:
            ok, msg = self.locator.admin_manager.disable_user(access_key)
        if ok:
            notify(self.frame, "success", msg)
            self.locator.logger.success(f"{action}_user", access_key, msg)
            self.refresh()
        else:
            messagebox.showerror("失败", msg)
            self.locator.logger.error(f"{action}_user", access_key, msg)

    def _update_toggle_btn_label(self) -> None:
        """根据当前选中用户状态, 动态更新 启用/禁用 按钮标签"""
        info = self._get_selected_user_info()
        if not info:
            self.toggle_btn.config(text="启用/禁用")
            return
        _, status = info
        if status == "enabled":
            self.toggle_btn.config(text="○ 禁用")
        else:
            self.toggle_btn.config(text="● 启用")