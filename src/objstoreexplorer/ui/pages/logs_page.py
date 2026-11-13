# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""操作日志页面"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox

from ..pages.base_page import BasePage
from ..styles import Neutral, Space, Status, UIFont
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.buttons import (
    create_secondary_button, create_danger_ghost_button
)
from ..widgets.search_entry import SearchEntry
from ..widgets.notifications import notify


class LogsPage(BasePage):
    """操作日志页面"""

    def __init__(self, parent, locator):
        super().__init__(parent, locator)
        self._all_logs: list[dict] = []
        self._search_kw: str = ""

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="Audit Log",
            title="操作审计",
            subtitle="记录所有用户操作，含连接、传输、权限变更等关键动作，支持筛选与导出。",
            icon="scroll-text",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))

        # ⚠ Tk pack 顺序分配 cavity: 右侧按钮组先 pack
        create_danger_ghost_button(
            header.actions, "清空", self._on_clear, icon="trash-2",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "刷新", self.refresh, icon="refresh-cw",
        ).pack(side=tk.LEFT)

        card = Card(self.frame, title="日志流", icon="activity")
        card.pack(fill=tk.BOTH, expand=True,
                  padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))

        # 过滤条
        filter_frame = tk.Frame(card.body, bg=Neutral.BG_PANEL)
        filter_frame.pack(fill=tk.X, pady=(0, Space.MD))

        tk.Label(
            filter_frame, text="级别", font=UIFont.body_sm(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
        ).pack(side=tk.LEFT, padx=(0, Space.XS))

        self.level_var = tk.StringVar(value="全部")
        level_combo = ttk.Combobox(
            filter_frame, textvariable=self.level_var,
            values=["全部", "INFO", "WARNING", "ERROR"],
            state="readonly", width=10, font=UIFont.body(),
        )
        level_combo.pack(side=tk.LEFT, padx=(0, Space.MD))
        level_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        tk.Label(
            filter_frame, text="条数", font=UIFont.body_sm(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
        ).pack(side=tk.LEFT, padx=(0, Space.XS))

        self.limit_var = tk.StringVar(value="200")
        limit_combo = ttk.Combobox(
            filter_frame, textvariable=self.limit_var,
            values=["50", "100", "200", "500", "1000"],
            state="readonly", width=8, font=UIFont.body(),
        )
        limit_combo.pack(side=tk.LEFT, padx=(0, Space.MD))
        limit_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        # 搜索框 (本地过滤)
        self.search = SearchEntry(
            filter_frame, placeholder="搜索操作 / 目标 / 消息...",
            on_change=self._on_search_change, width=28,
        )
        self.search.pack(side=tk.LEFT)

        # 表格
        table_frame = card.body

        columns = ("time", "level", "operation", "target", "status", "message")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings",
            style="Modern.Treeview",
        )
        self.tree.heading("time", text="时间")
        self.tree.heading("level", text="级别")
        self.tree.heading("operation", text="操作")
        self.tree.heading("target", text="目标")
        self.tree.heading("status", text="状态")
        self.tree.heading("message", text="消息")

        self.tree.column("time", width=160, anchor=tk.CENTER)
        self.tree.column("level", width=80, anchor=tk.CENTER)
        self.tree.column("operation", width=120, anchor=tk.W)
        self.tree.column("target", width=200, anchor=tk.W)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        self.tree.column("message", width=400, anchor=tk.W)

        scroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 颜色 tag
        self.tree.tag_configure("ERROR", foreground=Status.DANGER)
        self.tree.tag_configure("WARNING", foreground=Status.WARNING)
        self.tree.tag_configure("INFO", foreground=Neutral.TEXT_1)
        # 斑马纹 (M4 升级)
        self.tree.tag_configure("zebra", background=Neutral.BG_SUBTLE)

    def refresh(self) -> None:
        level = self.level_var.get()
        if level == "全部":
            level = None
        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 200

        self._all_logs = self.locator.logger.get_history(limit=limit, level=level)
        self._render_filtered()

    def append_live(self, entry: dict) -> None:
        """实时追加一条日志 (由 MainWindow._on_log_event 在本页可见时调用)

        旧版只在切页/手动刷新时才重新拉历史, 用户停在日志页时新日志
        完全不出现, 切走再切回才看得到 —— 像是程序没记日志。
        """
        if self.frame is None:
            return
        level = entry.get("level", "INFO")
        # 保持与 refresh() 的过滤条件一致
        if self.level_var.get() not in ("全部", level):
            return
        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 200
        if len(self._all_logs) >= limit:
            self._all_logs.pop(0)
        self._all_logs.append(entry)

        kw = self._search_kw
        target = str(entry.get("target", "")) + " " + str(entry.get("message", ""))
        if kw and kw not in target.lower():
            return
        # 追加到末尾 (不重排: 历史行保持原序)
        idx = len(self.tree.get_children())
        tags = (level,)
        if idx % 2 == 1:
            tags = (level, "zebra")
        try:
            self.tree.insert("", tk.END, values=(
                entry.get("timestamp", "-"),
                level,
                entry.get("operation", "-"),
                entry.get("target", "-"),
                entry.get("status", "-"),
                entry.get("message", "-"),
            ), tags=tags)
        except tk.TclError:
            pass

    def _on_search_change(self, kw: str) -> None:
        self._search_kw = (kw or "").strip().lower()
        self._render_filtered()

    def _render_filtered(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        kw = self._search_kw
        idx = 0
        for log in self._all_logs:
            if kw:
                hay = " ".join([
                    str(log.get("operation", "")),
                    str(log.get("target", "")),
                    str(log.get("message", "")),
                ]).lower()
                if kw not in hay:
                    continue
            level_tag = log.get("level", "INFO")
            tags = (level_tag,)
            if idx % 2 == 1:
                tags = (level_tag, "zebra")
            self.tree.insert("", tk.END, values=(
                log.get("timestamp", "-"),
                log.get("level", "-"),
                log.get("operation", "-"),
                log.get("target", "-"),
                log.get("status", "-"),
                log.get("message", "-"),
            ), tags=tags)
            idx += 1

    def _on_clear(self) -> None:
        if not messagebox.askyesno("确认", "确定要清空所有日志吗?"):
            return
        try:
            self.locator.config_manager.clear_logs()
            self.refresh()
            notify(self.frame, "success", "日志已清空")
        except Exception as e:
            messagebox.showerror("失败", str(e))