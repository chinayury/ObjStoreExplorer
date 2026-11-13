# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/pages/sync_page - 独立同步页

提供比 SyncDialog 更完整的同步工作区:
  - 新建同步任务 (弹 SyncDialog)
  - 同步预设管理 (保存常用桶+prefix+本地目录组合)
  - 最近同步活动 (内存记录, 不持久化)

注意: 实际同步逻辑都在 services/sync_service.py,
本页面只负责 UI 入口和历史展示。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List

from ..pages.base_page import BasePage
from ..styles import Neutral, Status, Space, UIFont
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.buttons import (
    create_primary_button
)
from ..windows.sync_dialog import SyncDialog


# 同步活动记录 (内存, 不持久化)
class SyncActivity:
    """单次同步活动"""
    def __init__(self, when: str, direction: str, bucket: str, prefix: str,
                 local_dir: str, summary: str, success: bool):
        self.when = when
        self.direction = direction
        self.bucket = bucket
        self.prefix = prefix
        self.local_dir = local_dir
        self.summary = summary
        self.success = success


# 进程内活动历史 (Singleton)
_activity_log: List[SyncActivity] = []


def record_sync_activity(activity: SyncActivity) -> None:
    """由 SyncDialog 在同步完成后调用, 记录到全局历史"""
    _activity_log.append(activity)
    # 最多保留 50 条
    if len(_activity_log) > 50:
        del _activity_log[0]


def get_activity_log() -> List[SyncActivity]:
    return list(_activity_log)


class SyncPage(BasePage):
    """同步管理页"""

    def _build_ui(self) -> None:
        bg = Neutral.BG_APP
        self.frame.configure(bg=bg)

        header = PageHeader(
            self.frame,
            kicker="Sync",
            title="同步管理",
            subtitle="本地与远端双向同步：推送 / 拉取 / 镜像三种方向，冲突逐个确认。",
            icon="refresh-cw",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))
        create_primary_button(
            header.actions, "新建同步任务", self._on_new_sync, icon="plus",
        ).pack(side=tk.LEFT)

        # 说明卡片
        intro = Card(self.frame, title="同步说明", icon="info")
        intro.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(0, Space.MD))
        intro_body = intro.body

        tip_text = (
            "• 三种方向: 推送 (本地到远端) / 拉取 (远端到本地) / 镜像 (双向一致)\n"
            "• 冲突处理: 内容不同 (size/mtime 不一致) 时, 弹窗让用户逐个决定\n"
            "• 选项:\n"
            "    - 完成后删除源端: 推送成功后自动删除本地源文件 (类似剪切)\n"
            "    - 删除目标端多余: 镜像模式, 远端有但本地没有的文件会被删除 (rsync --delete 语义)\n"
            "• 支持递归子目录 / 保留目录结构\n"
            "• 工具栏入口: 对象管理页的「同步...」按钮 / 右键菜单也有"
        )
        tk.Label(
            intro_body, text=tip_text, font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
            justify=tk.LEFT, anchor=tk.W,
        ).pack(anchor=tk.W, fill=tk.X)

        # 活动历史区
        history_card = Card(self.frame, title="最近同步活动", icon="activity",
                            actions=[("清空", self._on_clear_log)],
                            action_icons=["trash-2"])
        history_card.pack(fill=tk.BOTH, expand=True,
                          padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))
        list_frame = history_card.body

        columns = ("when", "direction", "bucket", "prefix", "summary", "status")
        self.tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", height=10,
            style="Modern.Treeview",
        )
        self.tree.heading("when", text="时间")
        self.tree.heading("direction", text="方向")
        self.tree.heading("bucket", text="桶")
        self.tree.heading("prefix", text="远端 prefix")
        self.tree.heading("summary", text="结果摘要")
        self.tree.heading("status", text="状态")
        self.tree.column("when", width=150, anchor=tk.W)
        self.tree.column("direction", width=80, anchor=tk.CENTER)
        self.tree.column("bucket", width=120, anchor=tk.W)
        self.tree.column("prefix", width=150, anchor=tk.W)
        self.tree.column("summary", width=320, anchor=tk.W)
        self.tree.column("status", width=80, anchor=tk.CENTER)

        scroll = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 颜色
        self.tree.tag_configure("ok", foreground=Status.SUCCESS)
        self.tree.tag_configure("warn", foreground=Status.WARNING)
        self.tree.tag_configure("err", foreground=Status.DANGER)

        # 初次填充
        self._refresh_log()

    def _on_new_sync(self):
        if not self.locator.is_connected:
            messagebox.showwarning("提示", "请先连接到 S3", parent=self.frame)
            return
        SyncDialog(self.frame, self.locator)

    def refresh(self) -> None:
        """重载最近同步活动

        ⚠ 本页此前没有重写 refresh(), 落到基类的空 pass → main_window
        每次 show_page 调的 page.refresh() 什么也不做, "最近同步活动"
        在同步完成后永远不会更新, 必须重启应用才看得到。
        """
        if not hasattr(self, "tree"):
            return
        self._refresh_log()

    def _on_clear_log(self):
        if not _activity_log:
            return
        if messagebox.askyesno("确认", "清空所有同步历史记录?", parent=self.frame):
            _activity_log.clear()
            self._refresh_log()

    def _refresh_log(self):
        """从 _activity_log 重新填充 tree"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not _activity_log:
            return
        for a in reversed(_activity_log):  # 最新在上
            status_text = "成功" if a.success else "出错"
            tag = "ok" if a.success else "err"
            dir_text = {
                "push": "推送",
                "pull": "拉取",
                "mirror": "镜像",
            }.get(a.direction, a.direction)
            self.tree.insert(
                "", tk.END,
                values=(
                    a.when, dir_text, a.bucket, a.prefix or "(根)",
                    a.summary, status_text,
                ),
                tags=(tag,),
            )
