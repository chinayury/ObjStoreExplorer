# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""概览页面 — 统计卡 + 分桶明细表 (「暮橙 Emberline」)"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any

from ..pages.base_page import BasePage
from ..styles import Brand, Neutral, Status, Space
from ..threading_bridge import get_bridge
from ..widgets.page_header import PageHeader
from ..widgets.buttons import create_secondary_button
from ..widgets.card import Card
from ..widgets.stat_card import StatCard
from ..widgets.skeleton import SkeletonRow


class OverviewPage(BasePage):
    """概览页面"""

    # 4 张统计卡: (中文标签, 英文小标, 数值 key, 主色, 图标名)
    CARD_DEFS = [
        ("存储桶数量", "BUCKETS",   "bucket_count", Brand.PRIMARY,  "archive"),
        ("对象总数",   "OBJECTS",   "object_count", Status.SUCCESS, "layers"),
        ("文件夹总数", "FOLDERS",   "folder_count", Status.INFO,    "folder-tree"),
        ("总容量占用", "TOTAL SIZE", "size_count",   Brand.PRIMARY_400, "hard-drive"),
    ]

    def _build_ui(self) -> None:
        self.frame.configure(bg=Neutral.BG_APP)

        # === 页眉 (kicker + 巨型标题 + 操作区) ===
        header = PageHeader(
            self.frame,
            kicker="Overview",
            title="存储总览",
            subtitle="并发扫描全部存储桶，一屏掌握对象数、文件夹数与容量占比；桶较多时首次加载需要数十秒。",
            icon="layout-dashboard",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.MD))
        create_secondary_button(
            header.actions, "刷新", self.refresh, icon="refresh-cw",
        ).pack(side=tk.LEFT)

        # === 统计卡 ===
        cards_frame = tk.Frame(self.frame, bg=Neutral.BG_APP)
        cards_frame.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(0, Space.LG))

        self.cards: Dict[str, StatCard] = {}
        self.card_skeletons: Dict[str, SkeletonRow] = {}
        self.card_containers: Dict[str, tk.Frame] = {}

        for i, (label, sublabel, key, accent, icon_name) in enumerate(self.CARD_DEFS):
            cards_frame.columnconfigure(i, weight=1, uniform="stat")
            card = StatCard(
                cards_frame, label, sublabel, icon=icon_name, accent=accent,
            )
            card.grid(row=0, column=i,
                      padx=(0, Space.MD) if i < len(self.CARD_DEFS) - 1 else 0,
                      sticky=tk.NSEW)
            self.cards[key] = card
            self.card_containers[key] = card.value_holder

        # === 明细表 ===
        detail = Card(self.frame, title="分桶容量明细", icon="server")
        detail.pack(fill=tk.BOTH, expand=True,
                    padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))

        columns = ("bucket", "folders", "objects", "size", "files")
        self.tree = ttk.Treeview(
            detail.body, columns=columns, show="headings",
            style="ModernV2.Treeview", height=15,
        )
        self.tree.heading("bucket",  text="桶名")
        self.tree.heading("folders", text="文件夹")
        self.tree.heading("objects", text="对象数")
        self.tree.heading("size",    text="大小")
        self.tree.heading("files",   text="文件类型数")
        self.tree.column("bucket",  width=260, anchor=tk.W)
        self.tree.column("folders", width=110, anchor=tk.CENTER)
        self.tree.column("objects", width=110, anchor=tk.CENTER)
        self.tree.column("size",    width=150, anchor=tk.E)
        self.tree.column("files",   width=130, anchor=tk.CENTER)

        scroll = ttk.Scrollbar(
            detail.body, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.tag_configure("zebra", background=Neutral.BG_SUBTLE)
        self.tree.tag_configure("link", foreground=Brand.PRIMARY_700)
        self.tree.bind("<Double-1>", self._on_row_activate)

    def _on_row_activate(self, _event=None) -> None:
        """双击行 → 跳到对象管理页并选中该桶"""
        sel = self.tree.selection()
        if not sel:
            return
        values = self.tree.item(sel[0], "values")
        if not values:
            return
        main = getattr(self.locator, "_main_window", None)
        if main is not None:
            try:
                main.navigate_to_objects(str(values[0]))
            except Exception:
                pass

    # ==================== 数据加载 ====================

    def refresh(self) -> None:
        """刷新概览数据 (后台跑统计, 避免卡 UI)"""
        if self.frame is None:
            return
        if not self.locator.is_connected:
            self._show_empty()
            return

        self._show_skeletons()

        bridge = get_bridge(self.frame, logger=self.locator.logger)

        def _bg():
            # ⚠ worker 线程: 只跑统计 + 投递队列, 不碰 Tk
            #   (旧版在后台线程里直接 self.frame.after(0, ...): 跨线程进
            #    Tcl 解释器, 概览统计要跑数十秒, 卡死概率很高)
            try:
                overview = self.locator.stats_manager.get_overview()
            except Exception as e:
                msg = str(e)
                bridge.post(self._show_empty, msg)
                try:
                    self.locator.logger.error("overview_refresh", "", msg)
                except Exception:
                    pass
                return
            bridge.post(self._apply_overview, overview)

        bridge.submit(_bg, task_name="概览统计")

    def _show_skeletons(self) -> None:
        """在 4 个数值位置盖一层骨架

        走 StatCard 公开的 show_placeholder(), 不再直接摸私有 `card._value`:
        旧版 `self.cards[key]._value.pack_forget()` 只藏了数值 Label, 而
        SkeletonRow 塞进从未 pack 的 value_holder 里 —— 骨架屏永远不显示。
        """
        self._clear_skeletons()
        for key, holder in self.card_containers.items():
            self.cards[key].show_placeholder(True)
            sk = SkeletonRow(holder, width=80, height=20)
            sk.pack(side=tk.LEFT)
            self.card_skeletons[key] = sk

    def _clear_skeletons(self) -> None:
        for key, sk in list(self.card_skeletons.items()):
            try:
                sk.destroy()
            except Exception:
                pass
            self.cards[key].show_placeholder(False)
        self.card_skeletons.clear()

    def _apply_overview(self, overview: Dict[str, Any]) -> None:
        """主线程回调: 把统计写入卡片和表格"""
        if self.frame is None:
            return
        self._clear_skeletons()
        if "error" in overview:
            self._show_empty(overview["error"])
            return

        self.cards["bucket_count"].set_value(str(overview["total_buckets"]))
        self.cards["object_count"].set_value(str(overview["total_objects"]))
        self.cards["folder_count"].set_value(str(overview["total_folders"]))
        self.cards["size_count"].set_value(overview["total_size_str"])

        for item in self.tree.get_children():
            self.tree.delete(item)

        for i, stat in enumerate(overview.get("buckets", [])):
            if "error" in stat:
                continue
            tag = ("zebra",) if i % 2 == 1 else ()
            self.tree.insert("", tk.END, values=(
                str(stat.get("bucket_name", "-")),
                stat.get("folder_count", 0),
                stat.get("object_count", 0),
                stat.get("total_size_str", "0 B"),
                len(stat.get("file_types", {})),
            ), tags=tag)

        self.locator.logger.info(
            "overview_refresh", "",
            f"刷新概览,共 {overview['total_buckets']} 个桶"
        )

    def _show_empty(self, msg: str = "") -> None:
        """显示空状态"""
        self._clear_skeletons()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for card in self.cards.values():
            card.set_value("—")
        if msg:
            self.locator.logger.warning("overview", "", msg)
