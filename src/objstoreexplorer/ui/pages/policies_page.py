# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""策略管理页面"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from ..pages.base_page import BasePage
from ..styles import Neutral, Space, Status, UIFont
from ..threading_bridge import get_bridge
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.buttons import (
    create_primary_button, create_secondary_button, create_danger_ghost_button
)


class PoliciesPage(BasePage):
    """策略管理页面"""

    def __init__(self, parent, locator):
        super().__init__(parent, locator)
        # 策略详情请求令牌: 快速连点时用来丢弃过期响应
        self._req_id: int = 0

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="Policies",
            title="访问策略",
            subtitle="以 JSON 语句描述 S3 权限边界；选择左侧策略查看内容，再附加 / 分离到指定用户。",
            icon="shield-check",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))

        # ⚠ Tk pack 顺序分配 cavity: 右侧按钮组先 pack
        create_danger_ghost_button(
            header.actions, "删除选中", self._on_delete_policy, icon="trash-2",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_primary_button(
            header.actions, "附加到用户", self._on_attach_policy, icon="user",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "编辑", self._on_edit_policy, icon="pencil",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_primary_button(
            header.actions, "创建策略", self._on_create_policy, icon="plus",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "刷新", self.refresh, icon="refresh-cw",
        ).pack(side=tk.LEFT)

        # 提示
        self.tip_var = tk.StringVar()
        tk.Label(
            self.frame, textvariable=self.tip_var,
            font=UIFont.body_sm(), bg=Neutral.BG_APP,
            fg=Status.WARNING,
        ).pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(0, Space.SM))

        # 左侧: 策略列表
        left_card = Card(self.frame, title="策略清单", icon="list")
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                       padx=(Space.HERO_PAD_X, Space.SM),
                       pady=(0, Space.HERO_PAD_Y))
        left_frame = left_card.body

        self.tree = ttk.Treeview(
            left_frame, columns=("name",), show="headings",
            style="Modern.Treeview",
        )
        self.tree.heading("name", text="策略名")
        self.tree.column("name", width=300, anchor=tk.W)

        scroll = ttk.Scrollbar(
            left_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 斑马纹
        self.tree.tag_configure("zebra", background=Neutral.BG_SUBTLE)

        self.tree.bind("<<TreeviewSelect>>", self._on_policy_select)

        # 右键菜单
        self.context_menu = tk.Menu(self.frame, tearoff=0)
        self.context_menu.add_command(label="编辑", command=self._on_edit_policy)
        self.context_menu.add_command(label="复制名称", command=self._on_copy_policy_name)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="删除", command=self._on_delete_policy)
        self.context_menu.add_command(label="刷新", command=self.refresh)
        self.tree.bind("<Button-3>", self._show_policy_context_menu)

        # 右侧: 详情
        right_card = Card(self.frame, title="策略内容 (JSON)", icon="code",
                          actions=[("复制 JSON", self._on_copy_json)],
                          action_icons=["copy"])
        right_card.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True,
                        padx=(Space.SM, Space.HERO_PAD_X),
                        pady=(0, Space.HERO_PAD_Y))
        right_frame = right_card.body

        # ⚠ wrap=NONE 必须配横向滚动条, 否则长 ARN 行看不到尾部
        detail_outer = tk.Frame(right_frame, bg=Neutral.BG_PANEL)
        detail_outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        detail_outer.rowconfigure(0, weight=1)
        detail_outer.columnconfigure(0, weight=1)
        self.detail_text = tk.Text(
            detail_outer, wrap=tk.NONE, font=UIFont.mono(10),
            bg=Neutral.BG_SUBTLE, fg=Neutral.TEXT_1,
            relief="flat", bd=0, highlightthickness=0,
            padx=Space.MD, pady=Space.MD,
        )
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        detail_sb_y = ttk.Scrollbar(
            detail_outer, orient=tk.VERTICAL, command=self.detail_text.yview,
        )
        detail_sb_y.grid(row=0, column=1, sticky="ns")
        detail_sb_x = ttk.Scrollbar(
            detail_outer, orient=tk.HORIZONTAL, command=self.detail_text.xview,
        )
        detail_sb_x.grid(row=1, column=0, sticky="ew")
        self.detail_text.configure(
            yscrollcommand=detail_sb_y.set, xscrollcommand=detail_sb_x.set,
        )
        self.detail_text.insert(tk.END, "请选择左侧策略查看详情")
        self.detail_text.config(state=tk.DISABLED)

    def refresh(self) -> None:
        if not self.locator.is_connected:
            return
        if not self.locator.admin_manager.admin_available:
            self.tip_var.set("当前客户端不支持策略管理")
            for item in self.tree.get_children():
                self.tree.delete(item)
            return

        self.tip_var.set("")
        ok, policies = self.locator.admin_manager.list_policies()
        if not ok:
            messagebox.showerror("错误", str(policies))
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        for i, p in enumerate(policies):
            tag = ("zebra",) if i % 2 == 1 else ()
            self.tree.insert("", tk.END, values=(p,), tags=tag)

        # ⚠ 列表刷新后必须清详情面板, 否则显示的还是上一个策略的 JSON,
        #   配合"已删策略仍显示内容"会误导用户。
        self._req_id += 1          # 让在途的旧请求全部作废
        self.detail_text.config(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        if policies:
            self.detail_text.insert(tk.END, "请选择左侧策略查看详情")
        else:
            self.detail_text.insert(
                tk.END, "(当前没有可访问的策略)\n\n可点击「创建策略」新建。",
            )
        self.detail_text.config(state=tk.DISABLED)

        self.locator.logger.info("policies_refresh", "", f"刷新策略列表,共 {len(policies)} 个")

    # ==================== 附加 / 分离策略 ====================

    def _on_attach_policy(self) -> None:
        """把选中策略附加 / 分离到指定用户

        走 core 的 admin_attach_policy / admin_detach_policy / admin_list_users
        (经 locator.s3_client 调用, 不改 core 公开签名)。
        """
        if not self.locator.is_connected:
            messagebox.showwarning("提示", "请先连接到 S3", parent=self.frame)
            return
        client = self.locator.s3_client
        if client is None or not getattr(client, "admin_available", False):
            messagebox.showwarning(
                "不支持", "当前客户端不支持 Admin API, 无法附加策略",
                parent=self.frame,
            )
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一个策略", parent=self.frame)
            return
        values = self.tree.item(selected[0])["values"]
        if not values:
            return
        policy = str(values[0])

        ok, users = client.admin_list_users()
        if not ok or not users:
            messagebox.showwarning(
                "无法获取用户列表",
                f"读取用户列表失败: {users}\n\n请确认连接使用的是 MinIO 且账号有 Admin 权限。",
                parent=self.frame,
            )
            return

        from ..windows.attach_policy_dialog import AttachPolicyDialog
        AttachPolicyDialog(
            self.frame, self.locator, policy=policy, users=users,
            on_success=self.refresh,
        )

    def _on_policy_select(self, event) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0])["values"]
        if not values:
            return
        name = str(values[0])

        # 请求令牌: 快速连点不同策略时, 先发的请求可能后返回 →
        # 详情面板显示成上一个策略的内容。加自增 id, 回调比对。
        self._req_id += 1
        req_id = self._req_id

        # 实际拉取策略详情
        self.detail_text.config(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, f"加载 {name} 中...")
        self.detail_text.config(state=tk.DISABLED)

        bridge = get_bridge(self.frame, logger=self.locator.logger)

        def _bg():
            # ⚠ worker 线程: 只调 S3 + 投递队列, 不碰 Tk
            try:
                ok, data = self.locator.admin_manager.get_policy(name)
            except Exception as e:
                ok, data = False, str(e)
            bridge.post(self._render_policy_detail, name, ok, data, req_id)

        bridge.submit(_bg, task_name="读取策略详情")

    def _render_policy_detail(
        self, name: str, ok: bool, data, req_id: Optional[int] = None,
    ) -> None:
        """主线程渲染策略详情。req_id 用于丢弃过期响应 (快速连点时)。"""
        # 过期响应: 丢弃, 否则会覆盖用户后来选中策略的详情
        if req_id is not None and req_id != self._req_id:
            return
        import json
        self.detail_text.config(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        if ok:
            try:
                text = json.dumps(data, indent=2, ensure_ascii=False)
            except Exception:
                text = str(data)
            self.detail_text.insert(tk.END, text)
        else:
            self.detail_text.insert(
                tk.END,
                f"策略: {name}\n\n获取详情失败: {data}\n\n"
                "可通过 mc admin policy info <alias> <name> 手动查看",
            )
        self.detail_text.config(state=tk.DISABLED)

    def _show_policy_context_menu(self, event) -> None:
        """策略列表右键菜单"""
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
        else:
            self.tree.selection_set()
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _on_create_policy(self) -> None:
        """创建策略"""
        from ..windows.policy_dialog import PolicyDialog
        PolicyDialog(self.frame, self.locator, mode="create", on_success=self.refresh)

    def _on_edit_policy(self) -> None:
        """编辑策略 (修改 JSON)"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一个策略")
            return
        name = str(self.tree.item(selected[0])["values"][0])
        # 加载现有内容
        ok, content = self.locator.admin_manager.get_policy(name)
        if not ok:
            messagebox.showerror("失败", f"无法加载策略 {name} 详情: {content}")
            return
        from ..windows.policy_dialog import PolicyDialog
        PolicyDialog(
            self.frame, self.locator,
            mode="edit", policy_name=name,
            policy_content=content if isinstance(content, dict) else {},
            on_success=self.refresh,
        )

    def _on_copy_policy_name(self) -> None:
        """复制策略名"""
        selected = self.tree.selection()
        if not selected:
            return
        name = str(self.tree.item(selected[0])["values"][0])
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(name)
            from ..widgets.notifications import notify
            notify(self.frame, "success", f"已复制: {name}")
        except Exception:
            pass

    def _on_copy_json(self) -> None:
        text = self.detail_text.get("1.0", tk.END).strip()
        if not text:
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
            from ..widgets.notifications import notify
            notify(self.frame, "success", "已复制策略 JSON")
        except Exception:
            pass

    def _on_delete_policy(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一个策略")
            return
        name = self.tree.item(selected[0])["values"][0]
        if not messagebox.askyesno("确认", f"确定要删除策略 {name} 吗?"):
            return

        ok, msg = self.locator.admin_manager.delete_policy(name)
        if ok:
            from ..widgets.notifications import notify
            notify(self.frame, "success", msg)
            self.locator.logger.success("delete_policy", name, msg)
            self.refresh()
        else:
            messagebox.showerror("失败", msg)
            self.locator.logger.error("delete_policy", name, msg)