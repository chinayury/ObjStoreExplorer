# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""版本控制配置页面 — 桶级版本化开关 (「暮橙 Emberline」)"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox

from ..pages.base_page import BasePage
from ..styles import Neutral, Space, UIFont
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.badge import Badge
from ..widgets.buttons import create_primary_button, create_secondary_button
from ..widgets.notifications import notify


class VersioningPage(BasePage):
    """桶版本控制配置页面"""

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="Versioning",
            title="版本控制",
            subtitle="为存储桶开启对象版本化；暂停后新写入不再产生版本，但历史版本仍然保留，可随时回滚。",
            icon="history",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))
        create_secondary_button(
            header.actions, "重新加载", self.refresh, icon="refresh-cw",
        ).pack(side=tk.LEFT)

        card = Card(self.frame, title="选择目标存储桶", icon="archive")
        card.pack(fill=tk.BOTH, expand=True,
                  padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))

        inner = card.body

        # 桶选择
        self._field_label(inner, "存储桶").grid(
            row=0, column=0, sticky=tk.W, padx=(0, Space.MD), pady=(0, Space.SM))
        self.bucket_var = tk.StringVar()
        self.bucket_combo = ttk.Combobox(
            inner, textvariable=self.bucket_var,
            state="readonly", font=UIFont.body(), width=36,
        )
        self.bucket_combo.grid(row=0, column=1, sticky=tk.EW, pady=(0, Space.SM))
        self.bucket_combo.bind("<<ComboboxSelected>>", self._on_bucket_select)

        # 当前状态
        self._field_label(inner, "当前状态").grid(
            row=1, column=0, sticky=tk.W, padx=(0, Space.MD), pady=(Space.SM, Space.SM))
        self.status_holder = tk.Frame(inner, bg=Neutral.BG_APP)
        self.status_holder.grid(row=1, column=1, sticky=tk.W, pady=(Space.SM, Space.SM))
        self._set_status_badge("neutral", "选择桶后查看当前状态")

        # 操作
        self._field_label(inner, "操作").grid(
            row=2, column=0, sticky=tk.NW, padx=(0, Space.MD), pady=(Space.LG, Space.SM))
        btn_frame = tk.Frame(inner, bg=Neutral.BG_PANEL)
        btn_frame.grid(row=2, column=1, sticky=tk.W, pady=(Space.LG, Space.SM))
        create_primary_button(
            btn_frame, "启用版本控制", lambda: self._on_set("Enabled"),
            icon="check-circle",
        ).pack(side=tk.LEFT, padx=(0, Space.SM))
        create_secondary_button(
            btn_frame, "暂停 (Suspended)", lambda: self._on_set("Suspended"),
            icon="ban",
        ).pack(side=tk.LEFT)

        # 说明
        tk.Label(
            inner,
            text="启用后，同名对象的旧版本将保留，可通过对象版本号访问历史版本。\n"
                 "暂停后，新写入不会产生新版本，但已有的旧版本仍可访问。",
            font=UIFont.body_sm(), bg=Neutral.BG_PANEL,
            fg=Neutral.TEXT_2, wraplength=620, justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(Space.XL, 0))

        inner.columnconfigure(1, weight=1)

    @staticmethod
    def _field_label(parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(
            parent, text=text, font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W,
        )

    def _set_status_badge(self, kind: str, text: str) -> None:
        for w in self.status_holder.winfo_children():
            w.destroy()
        Badge(self.status_holder, text, kind=kind, dot=True).pack(side=tk.LEFT)

    def refresh(self) -> None:
        if self.frame is None:
            return
        self._load_buckets()

    def _load_buckets(self) -> None:
        try:
            ok, buckets = self.locator.bucket_manager.list_buckets()
            if ok and buckets:
                self.bucket_combo["values"] = buckets
                if not self.bucket_var.get():
                    self.bucket_var.set(buckets[0])
            else:
                self._set_status_badge("neutral", "未连接或没有可访问的存储桶")
                return
        except Exception as e:
            self._set_status_badge("danger", f"加载失败: {e}")
            return
        # ⚠ 无条件刷新当前选中桶: 旧版只在 bucket_var 为空时才调
        #   _on_bucket_select, 点「重新加载」时已选桶的状态完全不变
        #   (刚把状态改成 Enabled, 刷新后仍显示旧值 → 以为没生效)。
        self._on_bucket_select(None)

    def _on_bucket_select(self, event) -> None:
        bucket = self.bucket_var.get()
        if not bucket:
            self._set_status_badge("neutral", "选择桶后查看当前状态")
            return
        ok, status = self.locator.s3_client.get_bucket_versioning(bucket)
        if ok:
            st = (status or "Off").strip()
            mapping = {
                "Enabled": ("success", "已启用 (Enabled)"),
                "Suspended": ("warning", "已暂停 (Suspended)"),
                "Off": ("neutral", "未启用 (Off)"),
            }
            kind, label = mapping.get(st, ("neutral", st))
            self._set_status_badge(kind, label)
        else:
            self._set_status_badge("danger", f"获取失败: {status}")

    def _on_set(self, status: str) -> None:
        bucket = self.bucket_var.get()
        if not bucket:
            messagebox.showwarning("提示", "请先选择桶", parent=self.frame)
            return
        if not messagebox.askyesno(
            "确认", f"确定要将桶 {bucket} 的版本控制设置为 {status} 吗?", parent=self.frame,
        ):
            return

        ok, msg = self.locator.s3_client.set_bucket_versioning(bucket, status)
        if ok:
            notify(self.frame, "success", f"版本控制已设置为 {status}")
            self.locator.logger.success("set_versioning", bucket, msg)
            self._on_bucket_select(None)
        else:
            messagebox.showerror("失败", msg, parent=self.frame)
            self.locator.logger.error("set_versioning", bucket, msg)
