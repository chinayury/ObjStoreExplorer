# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""桶列表页面"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from ..pages.base_page import BasePage
from ..styles import Neutral, Space
from ..threading_bridge import get_bridge
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.empty_state import create_empty_state
from ..widgets.buttons import (
    create_primary_button, create_secondary_button,
    create_danger_ghost_button,
)
from ..widgets.notifications import notify


class BucketsPage(BasePage):
    """桶列表页面"""

    def __init__(self, parent, locator):
        super().__init__(parent, locator)
        # fan-out 守卫: 连续点侧栏/刷新会排队多次"每桶统计"请求
        self._fanout_running = False
        self._empty_state: Optional[tk.Frame] = None

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="Buckets",
            title="存储桶空间",
            subtitle="创建、删除与统计 S3 存储桶；非空桶可强制清空后删除，双击任意一行进入该桶的对象管理。",
            icon="archive",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))

        # ⚠ Tk pack 顺序分配 cavity: 右侧按钮组先 pack
        create_danger_ghost_button(
            header.actions, "删除选中", self._on_delete_bucket, icon="trash-2",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_primary_button(
            header.actions, "创建桶", self._on_create_bucket, icon="plus",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "桶策略", self._on_bucket_policy, icon="shield-check",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "刷新", self.refresh, icon="refresh-cw",
        ).pack(side=tk.LEFT)

        # 表格
        card = Card(self.frame, title="桶列表", icon="server")
        card.pack(fill=tk.BOTH, expand=True,
                  padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))
        table_frame = card.body

        columns = ("name", "size", "objects", "created", "versioning", "lifecycle")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings",
            style="Modern.Treeview",
        )
        self.tree.heading("name", text="桶名")
        self.tree.heading("size", text="大小")
        self.tree.heading("objects", text="对象数")
        self.tree.heading("created", text="状态")
        self.tree.heading("versioning", text="版本控制")
        self.tree.heading("lifecycle", text="生命周期")

        self.tree.column("name", width=280, anchor=tk.W)
        self.tree.column("size", width=130, anchor=tk.E)
        self.tree.column("objects", width=90, anchor=tk.CENTER)
        self.tree.column("created", width=90, anchor=tk.CENTER)
        self.tree.column("versioning", width=110, anchor=tk.CENTER)
        self.tree.column("lifecycle", width=110, anchor=tk.CENTER)

        scroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 斑马纹 tag
        self.tree.tag_configure("zebra", background=Neutral.BG_SUBTLE)

        self.tree.bind("<Double-1>", self._on_double_click)

    def refresh(self) -> None:
        """刷新桶列表 (列表本身同步,统计放后台并发)"""
        if self.frame is None:
            return
        if not self.locator.is_connected:
            self._show_empty("(尚未连接)", "请先在顶栏点击「连接」")
            return
        # ⚠ fan-out 守卫: 旧版每次 refresh 都提交一轮"每桶统计"后台任务,
        #   连续点侧栏 5 次 = 5 轮并发统计, 每个桶都要 list_objects 扫全量。
        if self._fanout_running:
            return

        try:
            ok, buckets = self.locator.bucket_manager.list_buckets()
            if not ok:
                messagebox.showerror("错误", str(buckets), parent=self.frame)
                return

            self._hide_empty()
            for item in self.tree.get_children():
                self.tree.delete(item)

            if not buckets:
                self._show_empty("(没有可访问的存储桶)", "点击右上角「创建桶」新建一个")
                return

            # 先插入桶名占位 (大小/对象数显示"…")
            row_ids = {}
            for i, bucket in enumerate(buckets):
                tag = ("zebra",) if i % 2 == 1 else ()
                row = self.tree.insert("", tk.END, values=(
                    str(bucket), "…", "…", "可用", "…", "…",
                ), tags=tag)
                row_ids[bucket] = row

            self.locator.logger.info(
                "buckets_refresh", "",
                f"刷新桶列表,共 {len(buckets)} 个",
            )

            self._fanout_running = True
            bridge = get_bridge(self.frame, logger=self.locator.logger)
            bridge.submit(
                self._fanout, dict(row_ids), buckets,
                on_ok=lambda _r: setattr(self, "_fanout_running", False),
                on_err=lambda _e: setattr(self, "_fanout_running", False),
                task_name="桶统计",
            )
        except Exception as e:
            messagebox.showerror("错误", f"刷新失败: {e}", parent=self.frame)
            self.locator.logger.error("buckets_refresh", "", str(e))

    def _fanout(self, row_ids: dict, buckets: list) -> None:
        """worker 线程: 并发拉每个桶的统计/版本控制/生命周期, 结果投递回主线程"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        bridge = get_bridge(self.frame, logger=self.locator.logger)

        def _fetch_one(b: str):
            _, info = self.locator.bucket_manager.get_bucket_info(b)
            versioning = (info or {}).get("versioning") or "未启用"
            lc_count = (info or {}).get("lifecycle", 0)
            stats = self.locator.stats_manager.get_bucket_stats(b)
            return b, versioning, lc_count, stats

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(_fetch_one, b): b for b in buckets}
            for fut in as_completed(futs):
                try:
                    b, v, lc, s = fut.result()
                except Exception:
                    continue
                # ⚠ 只投递队列, 不在 worker 里碰 tree
                bridge.post(
                    self._apply_stat, row_ids, b, v, lc, s,
                )

    def _apply_stat(self, row_ids, b: str, versioning: str, lc_count, stats) -> None:
        """主线程: 把单个桶的统计写回对应行"""
        if self.frame is None:
            return
        row = row_ids.get(b)
        if not row:
            return
        try:
            if not self.tree.exists(row):
                return
        except tk.TclError:
            return
        size_str = stats.get("total_size_str", "0 B") if stats else "-"
        obj_count = stats.get("object_count", 0) if stats else "-"
        lc_str = f"{lc_count} 条" if lc_count else "未配置"
        try:
            self.tree.item(row, values=(
                str(b), size_str, obj_count, "可用", versioning, lc_str,
            ))
        except tk.TclError:
            pass

    def _show_empty(self, message: str, hint: str = "") -> None:
        """空状态 (create_empty_state 此前定义了却零调用, 列表空时一片空白)"""
        if self._empty_state is not None:
            return
        try:
            state = create_empty_state(
                self.frame, message, icon="archive", icon_name="archive",
                hint=hint, buttons=[("创建桶", self._on_create_bucket)],
            )
        except tk.TclError:
            return
        self._empty_state = state
        state.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _hide_empty(self) -> None:
        if self._empty_state is not None:
            try:
                self._empty_state.destroy()
            except tk.TclError:
                pass
            self._empty_state = None

    def _on_bucket_policy(self) -> None:
        """打开桶访问策略编辑器 (公共读 / 来源限制 / 请求方式)"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一个桶", parent=self.frame)
            return
        values = self.tree.item(selected[0])["values"]
        if not values:
            return
        bucket = str(values[0])
        if not self.locator.is_connected:
            messagebox.showwarning("未连接", "请先连接对象存储", parent=self.frame)
            return
        from ..windows.bucket_policy_dialog import BucketPolicyDialog
        BucketPolicyDialog(self.frame, self.locator, bucket)

    def _on_create_bucket(self) -> None:
        from tkinter import simpledialog
        name = simpledialog.askstring("创建桶", "请输入桶名称:", parent=self.frame)
        if not name:
            return
        name = name.strip()

        ok, msg = self.locator.bucket_manager.create_bucket(name)
        if ok:
            notify(self.frame, "success", msg)
            self.locator.logger.success("create_bucket", name, msg)
            self.refresh()
        else:
            messagebox.showerror("失败", msg, parent=self.frame)
            self.locator.logger.error("create_bucket", name, msg)

    def _on_delete_bucket(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一个桶", parent=self.frame)
            return

        # ⚠ 旧版只处理 selected[0], 多选时其余静默忽略 —— 用户以为删了 3 个,
        #   实际只删了 1 个, 剩下的还在 (且已被确认框承诺"桶内所有数据删除")。
        buckets: list = []
        for item_id in selected:
            values = self.tree.item(item_id)["values"]
            if values:
                buckets.append(str(values[0]))
        if not buckets:
            return

        if not messagebox.askyesno(
            "确认",
            f"确定要删除 {len(buckets)} 个桶吗?\n\n"
            + "\n".join(f"  • {b}" for b in buckets[:10])
            + ("\n  …" if len(buckets) > 10 else "")
            + "\n\n桶内所有数据将被永久删除!",
            parent=self.frame,
        ):
            return

        failed: list = []
        for bucket in buckets:
            ok, msg = self.locator.bucket_manager.delete_bucket(bucket, force=True)
            if ok:
                notify(self.frame, "success", msg)
                self.locator.logger.success("delete_bucket", bucket, msg)
            else:
                failed.append((bucket, msg))
                self.locator.logger.error("delete_bucket", bucket, msg)

        if failed:
            messagebox.showerror(
                "部分失败",
                "以下桶删除失败:\n\n"
                + "\n".join(f"  {b}: {m}" for b, m in failed),
                parent=self.frame,
            )
        self.refresh()

    def _on_double_click(self, event) -> None:
        """双击切换到对象页面并选中此桶"""
        selected = self.tree.selection()
        if not selected:
            return
        bucket = str(self.tree.item(selected[0])["values"][0])
        # 通知主窗口切换页面
        if hasattr(self.locator, "_main_window"):
            self.locator._main_window.navigate_to_objects(bucket)
