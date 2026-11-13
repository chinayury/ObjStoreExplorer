# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""对象管理页面 - 核心页面 (浏览/上传/下载/删除)"""
from __future__ import annotations
import hashlib
import os
import platform
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from typing import List, Dict, Optional, Any, Tuple

from ..pages.base_page import BasePage
from ..styles import Neutral, Space, Status, UIFont
from ..threading_bridge import get_bridge
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.buttons import (
    create_secondary_button, create_danger_ghost_button
)
from ..widgets.breadcrumb import Breadcrumb
from ..widgets.notifications import notify
from ..widgets.search_entry import SearchEntry
from ..widgets.text_viewer import show_text_viewer as _show_text_window
from ...utils.helpers import format_bytes, format_timestamp
from ..windows.sync_dialog import SyncDialog


# 双击直接打开的体积上限 (MB)。更大的文件先问"下载还是只保存",
# 否则双击一个 2GB 的 iso 就是静默下载 + 卡住界面。
OPEN_DIRECT_MAX_MB = 5

# 单次批量插入 tree 的最大行数 (分页/虚拟滚动用)
PAGE_SIZE = 200

# 需要确认后才能直接打开的扩展名 (非文本类)
_BINARY_EXTS = frozenset({
    ".exe", ".dll", ".msi", ".iso", ".zip", ".rar", ".7z", ".gz", ".tar",
    ".bz2", ".xz", ".bin", ".img", ".dmg", ".pdf", ".apk", ".jar", ".war",
    ".so", ".dylib", ".class", ".pyc", ".mov", ".mp4", ".avi", ".mkv",
    ".mp3", ".wav", ".flac", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
    ".pptx", ".psd", ".ai",
})


class ObjectsPage(BasePage):
    """对象管理页面"""

    def __init__(self, parent: tk.Misc, locator):
        super().__init__(parent, locator)
        # 状态属性在 __init__ 里初始化 (防止 UI 未构建时被外部访问)
        self.current_bucket: Optional[str] = None
        self.current_prefix: str = ""
        # Tree iid ↔ S3 key 映射。S3 允许 key 含特殊字符(/、空格、emoji 等),
        # 但 Tk 的 iid 在某些场景下对这些字符处理有限制,所以用自增的 iid,
        # 真实 key 存在这两张表里。
        self._iid_to_key: Dict[str, str] = {}
        self._key_to_iid: Dict[str, str] = {}
        self._iid_counter: int = 0
        # 在途守卫: 上传/下载/删除进行中禁止重复触发
        self._busy: Optional[str] = None
        # 剪贴板源桶 (剪切后跨桶粘贴用)
        self._clip_source_bucket: Optional[str] = None
        # 最近一次批量失败项 (用于"重试失败项")
        self._last_failures: List[Dict[str, Any]] = []
        # 本地过滤关键词
        self._filter_kw: str = ""
        # 分页: 当前已加载的对象元组 + 是否还有更多
        self._page_items: List[Dict[str, Any]] = []
        self._page_shown: int = 0
        self._page_token: int = 0
        self._pending_pager = None

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="Objects",
            title="对象资源管理",
            subtitle="上传、下载、在线预览、重命名、复制 / 剪切 / 粘贴与批量删除；双击进入目录，右键查看更多操作。",
            icon="folder",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))

        # ⚠ Tk pack 顺序分配 cavity: 右侧按钮组先 pack, 否则被左侧 expand 挤成 0 宽
        self._btn_delete = create_danger_ghost_button(
            header.actions, "删除", self._on_delete, icon="trash-2",
        )
        self._btn_delete.pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "同步…", self._on_sync, icon="refresh-cw",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "刷新", self.refresh, icon="refresh-cw",
        ).pack(side=tk.LEFT, padx=(0, Space.XS))
        self._btn_download = create_secondary_button(
            header.actions, "下载", self._on_download, icon="download",
        )
        self._btn_download.pack(side=tk.LEFT, padx=(0, Space.XS))
        self._btn_upload = create_secondary_button(
            header.actions, "上传", self._on_upload, icon="upload",
        )
        self._btn_upload.pack(side=tk.LEFT, padx=(0, Space.XS))
        self._btn_retry = create_secondary_button(
            header.actions, "重试失败项", self._on_retry_failures, icon="refresh-cw",
        )
        self._btn_retry.pack(side=tk.LEFT, padx=(0, Space.XS))
        create_secondary_button(
            header.actions, "新建文件夹", self._on_create_folder, icon="folder-plus",
        ).pack(side=tk.LEFT)

        # 定位工具条 (桶 + 面包屑)
        toolbar = tk.Frame(self.frame, bg=Neutral.BG_APP)
        toolbar.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(0, Space.SM))

        tk.Label(
            toolbar, text="桶", font=UIFont.body_sm(),
            bg=Neutral.BG_APP, fg=Neutral.TEXT_2,
        ).pack(side=tk.LEFT, padx=(0, Space.XS))

        self.bucket_var = tk.StringVar()
        self.bucket_combo = ttk.Combobox(
            toolbar, textvariable=self.bucket_var,
            state="readonly", width=22, font=UIFont.body(),
        )
        self.bucket_combo.pack(side=tk.LEFT, padx=(0, Space.MD))
        self.bucket_combo.bind("<<ComboboxSelected>>", self._on_bucket_changed)

        # 面包屑路径
        self.breadcrumb = Breadcrumb(
            toolbar, on_click=self._on_breadcrumb_click,
            bg=Neutral.BG_APP,
        )
        self.breadcrumb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=Space.XS)

        # 本地过滤框 (对当前目录已加载的对象做名称模糊过滤)
        self.search = SearchEntry(
            toolbar, placeholder="按名称过滤…", width=18,
            on_change=self._on_filter_change,
        )
        self.search.pack(side=tk.RIGHT, padx=(0, Space.XS))

        # 兼容旧代码 (某些方法读 prefix_var, 保留一个隐藏 var)
        self.prefix_var = tk.StringVar(value="")

        # 对象表格
        card = Card(self.frame, title="对象列表", icon="layers")
        card.pack(fill=tk.BOTH, expand=True,
                  padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))
        table_frame = card.body

        columns = ("name", "size", "modified", "type")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="tree headings",
            style="Modern.Treeview",
        )
        self.tree.heading("#0", text="")
        self.tree.heading("name", text="名称")
        self.tree.heading("size", text="大小")
        self.tree.heading("modified", text="修改时间")
        self.tree.heading("type", text="类型")

        self.tree.column("#0", width=40, anchor=tk.CENTER)
        self.tree.column("name", width=400, anchor=tk.W)
        self.tree.column("size", width=120, anchor=tk.E)
        self.tree.column("modified", width=180, anchor=tk.CENTER)
        self.tree.column("type", width=100, anchor=tk.CENTER)

        scroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 底部分页条 (5 万对象一次性 tree.insert 5 万行会冻结界面数十秒)
        pager = tk.Frame(card.body, bg=Neutral.BG_PANEL)
        pager.pack(side=tk.BOTTOM, fill=tk.X, pady=(Space.XS, 0))
        self._empty_hint = tk.Label(
            pager, text="", font=UIFont.body_sm(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
        )
        self._empty_hint.pack(side=tk.LEFT, padx=(Space.MD, 0))
        self._pager_label = tk.Label(
            pager, text="", font=UIFont.caption(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
        )
        self._pager_label.pack(side=tk.LEFT)
        self._btn_more = create_secondary_button(
            pager, "加载更多", self._load_more, icon="chevron-down",
        )
        self._btn_more.pack(side=tk.RIGHT)

        # 事件绑定
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)  # Windows / Linux
        self.tree.bind("<Button-2>", self._on_right_click)  # macOS

        # 快捷键
        # ⚠ Delete / F2 **不在这里绑**: root 上已有一份 (main_window
        #   _bind_shortcuts)。Tk 按 bindtag 顺序派发, tree 的 handler 先跑,
        #   事件继续冒泡到 root 又跑一遍 → 连弹两个确认框。
        self.tree.bind("<Return>", lambda e: self._on_double_click(None))
        self.tree.bind("<Control-c>", lambda e: self._on_copy())
        self.tree.bind("<Control-x>", lambda e: self._on_cut())
        self.tree.bind("<Control-v>", lambda e: self._on_paste())

        # 斑马纹 tag
        self.tree.tag_configure("zebra", background=Neutral.BG_SUBTLE)

        # 右键菜单
        self.context_menu = tk.Menu(self.frame, tearoff=0)
        self.context_menu.add_command(label="打开", command=self._on_double_click_action)
        self.context_menu.add_command(label="下载", command=self._on_download)
        self.context_menu.add_command(label="重命名", command=self._on_rename)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="复制", command=self._on_copy)
        self.context_menu.add_command(label="剪切", command=self._on_cut)
        self.context_menu.add_command(label="粘贴", command=self._on_paste)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="属性", command=self._on_properties)
        self.context_menu.add_command(label="删除", command=self._on_delete)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="刷新", command=self.refresh)
        self.context_menu.add_command(label="同步...", command=self._on_sync)

    # ==================== 公共方法 ====================

    def set_bucket(self, bucket: str) -> None:
        """从外部设置当前桶"""
        self.bucket_var.set(bucket)
        self.current_bucket = bucket
        self.current_prefix = ""
        self.prefix_var.set("")
        self._load_objects()

    def refresh(self) -> None:
        """刷新当前桶的对象列表"""
        if self.frame is None:
            return
        # 断开后 current_bucket 会被清空, 这里再兜一层 is_connected,
        # 避免走 _load_objects 用已关闭的客户端发请求
        if not self.locator.is_connected:
            self._clear_tree()
            return
        if self.current_bucket:
            self._load_objects()
        else:
            self._load_buckets()

    def on_upload(self) -> None:
        self._on_upload()

    def on_download(self) -> None:
        self._on_download()

    def on_sync(self) -> None:
        """同步事件 (Ctrl+N 或工具栏触发)"""
        self._on_sync()

    # ==================== 内部方法 ====================

    def _load_buckets(self) -> None:
        """加载桶列表到下拉框"""
        if not self.locator.is_connected:
            return
        ok, buckets = self.locator.bucket_manager.list_buckets()
        if not ok:
            return
        self.bucket_combo["values"] = buckets
        if buckets and not self.current_bucket:
            self.set_bucket(buckets[0])

    def _on_bucket_changed(self, event) -> None:
        bucket = self.bucket_var.get()
        if bucket and bucket != self.current_bucket:
            self.current_bucket = bucket
            self.current_prefix = ""
            self.prefix_var.set("")
            self._load_objects()

    # ---------- 面包屑/Prefix 控制 (M3 新增) ----------

    def set_prefix(self, prefix: str) -> None:
        """切换到指定 prefix (面包屑回调 / 外部调用统一入口)"""
        self.current_prefix = prefix
        self.prefix_var.set(prefix)
        self._load_objects()

    def _update_breadcrumb(self) -> None:
        """根据 current_bucket + current_prefix 更新面包屑"""
        if not hasattr(self, "breadcrumb") or self.breadcrumb is None:
            return
        segs: list[str] = []
        if self.current_bucket:
            segs.append(self.current_bucket)
        if self.current_prefix:
            for part in self.current_prefix.rstrip("/").split("/"):
                if part:
                    segs.append(part)
        if not segs:
            segs = ["(未选择桶)"]
        self.breadcrumb.set_segments(segs)

    def _on_breadcrumb_click(self, idx: int) -> None:
        """点击面包屑第 idx 段 (0 = 桶根)"""
        if not self.current_bucket:
            return
        if idx <= 0:
            # 回桶根
            self.set_prefix("")
            return
        # 重建 prefix 到第 idx 段
        parts = [p for p in self.current_prefix.rstrip("/").split("/") if p]
        new_parts = parts[:idx]   # 第 0 段是桶根,所以 idx 直接对应 parts 切片
        new_prefix = "/".join(new_parts) + "/" if new_parts else ""
        self.set_prefix(new_prefix)

    def _load_objects(self) -> None:
        """加载对象列表 (首批 PAGE_SIZE 行, 其余点"加载更多")"""
        # ⚠ 断开连接后 current_bucket 仍可能残留旧桶名, 这个分支原来没有
        #   连接检查 → 拿已关闭的客户端发请求。
        if not self.locator.is_connected:
            self._clear_tree()
            self._set_pager("", hide_more=True)
            return
        if not self.current_bucket:
            return

        ok, objects = self.locator.file_manager.list_objects(
            self.current_bucket,
            prefix=self.current_prefix,
            recursive=False,
        )
        if not ok:
            messagebox.showerror("错误", str(objects), parent=self.frame)
            return

        self._clear_tree()
        self._page_items = list(objects or [])
        self._page_shown = 0

        from ...utils.icons import get as get_icon
        # 上级目录行: 用 arrow-up (语义是"回到上层"), 不是 arrow-left
        self._img_parent = get_icon("arrow-up", 16, tint=Neutral.TEXT_3)
        # 文件夹图标着色统一走 Status.WARNING (琥珀), 不再硬编码 hex
        self._img_dir = get_icon("folder", 16, tint=Status.WARNING)
        self._img_file = get_icon("file", 16, tint=Neutral.TEXT_3)

        # "上级目录"项 (不在根时)
        if self.current_prefix:
            self._iid_counter += 1
            parent_iid = f"__row_{self._iid_counter:06d}"
            self._iid_to_key[parent_iid] = "__parent__"  # 哨兵
            self.tree.insert(
                "", tk.END, iid=parent_iid,
                text="", image=self._img_parent,
                values=(".. (上级目录)", "", "", "文件夹"),
            )

        self._render_page(reset=True)
        # 更新面包屑
        self._update_breadcrumb()

    def _load_more(self) -> None:
        """再渲染一页 (避免一次性插入上万行)"""
        if self._page_shown >= len(self._page_items):
            return
        self._render_page(reset=False)

    def _render_page(self, reset: bool = True) -> None:
        """把 _page_items 中 (尚未展示的) 一页插入 tree"""
        if reset:
            # 只删数据行, 保留"上级目录"哨兵行
            for iid in list(self._iid_to_key.keys()):
                if self._iid_to_key[iid] == "__parent__":
                    continue
                try:
                    self.tree.delete(iid)
                except tk.TclError:
                    pass
            for key in list(self._key_to_iid.keys()):
                self._key_to_iid.pop(key, None)
            self._page_shown = 0

        kw = self._filter_kw
        rows = self._page_items
        if kw:
            rows = [o for o in rows if kw in str(o.get("display_name", o.get("name", ""))).lower()]

        start = self._page_shown
        chunk = rows[start:start + PAGE_SIZE]
        if not chunk:
            if start >= len(rows):
                self._set_pager(
                    f"共 {len(rows)} 项" + (f" (过滤自 {len(self._page_items)})" if kw else ""),
                    hide_more=True,
                )
            return

        # 重新编号 zebra, 保证条纹连续
        for obj in chunk:
            i = self._page_shown
            name = obj.get("display_name", obj.get("name", ""))
            full_name = obj.get("name", "")
            is_dir = obj.get("is_dir", False)
            icon = self._img_dir if is_dir else self._img_file
            size_str = obj.get("size_str", "") if not is_dir else ""
            modified = format_timestamp(obj.get("last_modified"))
            type_str = "文件夹" if is_dir else "文件"

            kind_tag = "dir" if is_dir else "file"
            tags: tuple = (kind_tag,)
            if i % 2 == 1:
                tags = (kind_tag, "zebra")

            self._iid_counter += 1
            row_iid = f"__row_{self._iid_counter:06d}"
            self._iid_to_key[row_iid] = full_name
            self._key_to_iid[full_name] = row_iid
            self.tree.insert(
                "", tk.END, iid=row_iid, text="", image=icon,
                values=(str(name), str(size_str), str(modified), str(type_str)),
                tags=tags,
            )
            self._page_shown += 1

        total = len(rows)
        shown = self._page_shown
        label = f"已显示 {shown} / {total} 项"
        if kw:
            label += f" (过滤自 {len(self._page_items)})"
        self._set_pager(label, hide_more=(shown >= total))
        if total == 0:
            self._empty_hint.config(
                text="(没有匹配的对象)" if kw else "(该目录为空)",
            )
        else:
            self._empty_hint.config(text="")

    def _set_pager(self, text: str, hide_more: bool = True) -> None:
        try:
            self._pager_label.config(text=text)
            if hide_more:
                self._btn_more.pack_forget()
            else:
                # pack_forget 之后再 pack 会丢失原有顺序, 一律回到 RIGHT 侧
                self._btn_more.pack(side=tk.RIGHT, export=True)
        except tk.TclError:
            pass

    def _clear_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._iid_to_key.clear()
        self._key_to_iid.clear()
        self._page_items = []
        self._page_shown = 0

    def _on_filter_change(self, kw: str) -> None:
        """搜索框本地过滤 (不重新发 S3 请求)"""
        self._filter_kw = (kw or "").strip().lower()
        self._render_page(reset=True)

    def _get_key(self, item_id: str) -> Optional[str]:
        """从 tree iid 拿 S3 key。特殊 iid 返回 None。"""
        if not item_id:
            return None
        return self._iid_to_key.get(item_id)

    def _is_parent_iid(self, item_id: str) -> bool:
        return self._iid_to_key.get(item_id) == "__parent__"

    # ==================== 右键菜单和快捷键 ====================

    def _on_right_click(self, event) -> None:
        """右键弹出菜单"""
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
        else:
            # 在空白处右键 -> 清空选择
            self.tree.selection_set()

        # 弹出菜单
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _on_double_click(self, event) -> None:
        self._on_double_click_action()

    def _on_double_click_action(self) -> None:
        """双击或菜单打开"""
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        values = self.tree.item(item_id)["values"]
        if not values:
            return

        # iid 是自增的 row id,真实 key 通过 _get_key 取
        # values[0] 是 display_name (Tcl 可能会把 "06" 转成 int 6,丢前导 0)
        type_str = str(values[3]) if len(values) > 3 else ""

        if self._is_parent_iid(item_id):
            # 上级目录
            parts = self.current_prefix.rstrip("/").split("/")
            if len(parts) > 1:
                self.current_prefix = "/".join(parts[:-1]) + "/"
            else:
                self.current_prefix = ""
            self.prefix_var.set(self.current_prefix)
            self._load_objects()
            return

        full = self._get_key(item_id)
        if not full:
            return

        if type_str == "文件夹":
            # key 形如 "cnesa/cnesa/2026/06/",加到 current_prefix 后面
            if full.startswith(self.current_prefix):
                increment = full[len(self.current_prefix):]
            else:
                increment = full
            self.current_prefix = self.current_prefix + increment
            if not self.current_prefix.endswith("/"):
                self.current_prefix += "/"
            self.prefix_var.set(self.current_prefix)
            self._load_objects()
        else:
            # 文件 -> 下载/预览,传完整 key 避免 "06" → 6
            self._preview_object(full)

    def _on_create_folder(self) -> None:
        if not self.current_bucket:
            messagebox.showwarning("提示", "请先选择桶", parent=self.frame)
            return
        name = simpledialog.askstring("新建文件夹", "请输入文件夹名称:", parent=self.frame)
        if not name:
            return
        name = name.strip()

        ok, msg = self.locator.file_manager.create_folder(
            self.current_bucket, name, parent=self.current_prefix,
        )
        if ok:
            self.locator.logger.success("create_folder", name, msg)
            self._load_objects()
        else:
            messagebox.showerror("失败", msg, parent=self.frame)
            self.locator.logger.error("create_folder", name, msg)

    def _on_sync(self) -> None:
        """打开同步配置弹窗"""
        if not self.locator.is_connected:
            messagebox.showwarning("提示", "请先连接到 S3", parent=self.frame)
            return
        SyncDialog(
            self.frame, self.locator,
            default_bucket=self.current_bucket or "",
            default_prefix=self.current_prefix,
        )

    def _on_upload(self) -> None:
        if self._busy:
            notify(self.frame, "warning", f"「{self._busy}」正在进行, 请稍候")
            return
        if not self.current_bucket:
            messagebox.showwarning("提示", "请先选择桶", parent=self.frame)
            return

        paths = filedialog.askopenfilenames(title="选择要上传的文件")
        if not paths:
            return

        bucket = self.current_bucket
        prefix = self.current_prefix
        bridge = get_bridge(self.frame, logger=self.locator.logger)
        self._set_busy("上传")

        def do_upload():
            # ⚠ worker 线程: 只调 S3 + 往队列投递, 绝不碰 Tk。
            #   旧代码在后台线程里直接 widget.after() → Tcl 解释器跨线程,
            #   随机卡死 / TclError: invalid command name。
            def progress_cb(current, total, name):
                bridge.post(
                    self._update_upload_status, current, total, name,
                )

            results = self.locator.transfer.upload_files(
                bucket, prefix, list(paths), progress=progress_cb,
            )
            success = sum(1 for r in results if r["success"])
            failed = len(results) - success
            bridge.post(self._upload_done, success, failed, results)

        bridge.submit(do_upload, task_name="上传")

    def _set_busy(self, label: Optional[str]) -> None:
        """在途守卫: 置位后禁用上传/下载/删除按钮, 防并发重复触发"""
        self._busy = label
        state = tk.DISABLED if label else tk.NORMAL
        for name in ("_btn_upload", "_btn_download", "_btn_delete"):
            btn = getattr(self, name, None)
            if btn is None:
                continue
            try:
                btn.config(state=state)
            except tk.TclError:
                pass

    def _update_upload_status(self, current, total, name) -> None:
        if hasattr(self.locator, "_main_window"):
            self.locator._main_window.update_status(
                f"上传中 ({current}/{total}): {name}",
            )

    def _upload_done(self, success, failed, results) -> None:
        self._set_busy(None)
        self._last_failures = [
            {"kind": "upload", "file": r.get("file", ""), "message": r.get("message", "")}
            for r in results if not r.get("success")
        ]
        if failed == 0:
            notify(self.frame, "success", f"全部上传成功,共 {success} 个文件")
        else:
            detail = "\n".join(
                f"{r.get('file', '?')}: {r.get('message', '')}"
                for r in results if not r.get("success")
            )
            messagebox.showwarning(
                "完成",
                f"上传完成: {success} 成功, {failed} 失败\n\n失败详情:\n{detail}\n\n"
                "可在下方「重试失败项」中重新提交。",
                parent=self.frame,
            )
        self._load_objects()
        if hasattr(self.locator, "_main_window"):
            self.locator._main_window.update_status("就绪")

    def _on_download(self) -> None:
        if self._busy:
            notify(self.frame, "warning", f"「{self._busy}」正在进行, 请稍候")
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中要下载的对象", parent=self.frame)
            return

        save_dir = filedialog.askdirectory(title="选择保存目录")
        if not save_dir:
            return

        # 准备下载项 (key, local_path), 文件夹内的文件保留子目录结构
        items: List[Tuple[str, str]] = []
        for item_id in selected:
            values = self.tree.item(item_id)["values"]
            if not values or self._is_parent_iid(item_id):
                continue
            full_key = self._get_key(item_id)
            if not full_key:
                continue
            type_str = str(values[3]) if len(values) > 3 else ""
            if type_str == "文件夹":
                # 文件夹: 递归列出, 保留以该文件夹为根的子结构
                ok, objs = self.locator.file_manager.list_objects(
                    self.current_bucket, prefix=full_key, recursive=True,
                )
                if ok:
                    folder_name = full_key.rstrip("/").rsplit("/", 1)[-1]
                    folder_root = os.path.join(save_dir, folder_name)
                    for o in objs:
                        obj_key = o.get("name", "")
                        if not obj_key or obj_key.endswith("/"):
                            continue
                        # 计算相对路径(以所选文件夹的根为基)
                        if obj_key.startswith(full_key):
                            rel = obj_key[len(full_key):].lstrip("/")
                        else:
                            rel = obj_key
                        local_path = os.path.join(folder_root, rel) if rel else \
                            os.path.join(folder_root, os.path.basename(obj_key))
                        items.append((obj_key, local_path))
            else:
                # 单个文件: 直接放到 save_dir
                local_name = os.path.basename(full_key)
                items.append((full_key, os.path.join(save_dir, local_name)))

        if not items:
            notify(self.frame, "info", "无可下载对象")
            return

        self._download_keys(items, save_dir)

    def _download_keys(self, items: List[Tuple[str, str]], save_dir: str) -> None:
        """后台下载给定 (key, local_path) 列表 (上传/下载/重试共用入口)"""
        bucket = self.current_bucket
        bridge = get_bridge(self.frame, logger=self.locator.logger)
        self._set_busy("下载")

        def do_download():
            # ⚠ worker 线程: 只调 S3 + 投递队列, 不碰 Tk
            def progress_cb(current, total, name):
                bridge.post(
                    self._update_download_status, current, total, name,
                )

            results = self.locator.transfer.download_objects(
                bucket, items, progress=progress_cb,
            )
            success = sum(1 for r in results if r["success"])
            failed = len(results) - success
            bridge.post(self._download_done, success, failed, results, save_dir)

        bridge.submit(do_download, task_name="下载")

    def _update_download_status(self, current, total, name) -> None:
        if hasattr(self.locator, "_main_window"):
            self.locator._main_window.update_status(
                f"下载中 ({current}/{total}): {name}",
            )

    def _download_done(self, success, failed, results, save_dir) -> None:
        self._set_busy(None)
        self._last_failures = [
            {"kind": "download", "key": r.get("key", ""), "message": r.get("message", "")}
            for r in results if not r.get("success")
        ]
        if failed == 0:
            notify(self.frame, "success", f"全部下载成功,共 {success} 个文件\n保存到: {save_dir}")
        else:
            detail = "\n".join(
                f"{r.get('key', '?')}: {r.get('message', '')}"
                for r in results if not r.get("success")
            )
            messagebox.showwarning(
                "完成",
                f"下载完成: {success} 成功, {failed} 失败\n\n失败详情:\n{detail}\n\n"
                "可在下方「重试失败项」中重新下载。",
                parent=self.frame,
            )
        if hasattr(self.locator, "_main_window"):
            self.locator._main_window.update_status("就绪")

    def _on_rename(self) -> None:
        selected = self.tree.selection()
        if len(selected) != 1:
            messagebox.showwarning("提示", "重命名仅支持单个对象", parent=self.frame)
            return
        item_id = selected[0]
        if self._is_parent_iid(item_id):
            return
        values = self.tree.item(item_id)["values"]
        if not values:
            messagebox.showwarning("提示", "该行数据不完整, 无法重命名", parent=self.frame)
            return
        old_display = str(values[0])  # 给用户看的 (可能缺前导 0,别用于 key)
        type_str = str(values[3]) if len(values) > 3 else ""

        new_name = simpledialog.askstring(
            "重命名", f"请输入新{type_str}名称 (原名: {old_display}):",
            initialvalue=old_display, parent=self.frame,
        )
        if not new_name or new_name == old_display:
            return
        new_name = new_name.strip()
        if not new_name:
            return

        # iid 是自增 row id,真实 key 通过 _get_key 取
        old_key = self._get_key(item_id) or ""
        if type_str == "文件夹" and not old_key.endswith("/"):
            old_key += "/"

        # ⚠ 严格比对 basename: 旧版 key 末段与显示名对不上时**静默回退**到
        #   `current_prefix + new_name`, 于是"重命名"实际变成"移动到当前层",
        #   对象被搬到别处而用户毫无察觉。这里改成不匹配就报错。
        old_base = old_key.rstrip("/").rsplit("/", 1)[-1]
        if old_base != old_display:
            messagebox.showerror(
                "无法重命名",
                f"对象真实名称与列表显示不一致, 已中止以免误移动。\n\n"
                f"真实 key 末段: {old_base}\n"
                f"列表显示名称: {old_display}\n\n"
                "该对象名可能含前导零或特殊字符, 请用复制/剪切/粘贴方式移动。",
                parent=self.frame,
            )
            return

        parent_part = old_key[: len(old_key) - len(old_base)]
        new_key = parent_part + new_name
        if type_str == "文件夹" and not new_key.endswith("/"):
            new_key += "/"

        ok, msg = self.locator.file_manager.move_object(
            self.current_bucket, old_key, new_key,
        )
        # 日志里用 iid 拼出真实名字 (避免 "06" 被记成 "6")
        old_real = os.path.basename(old_key.rstrip("/"))
        if ok:
            self.locator.logger.success("rename", old_real, f"-> {new_name}")
            self._load_objects()
        else:
            messagebox.showerror("失败", msg, parent=self.frame)
            self.locator.logger.error("rename", old_real, msg)

    def _on_delete(self) -> None:
        if self._busy:
            notify(self.frame, "warning", f"「{self._busy}」正在进行, 请稍候")
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中要删除的对象", parent=self.frame)
            return

        items_info = []
        for item_id in selected:
            if self._is_parent_iid(item_id):
                continue
            values = self.tree.item(item_id)["values"]
            if not values:
                continue
            # iid 是 row id,真实 key 通过 _get_key 取
            key = self._get_key(item_id)
            if not key:
                continue
            type_str = str(values[3]) if len(values) > 3 else ""
            if type_str == "文件夹" and not key.endswith("/"):
                key += "/"
            items_info.append({"name": str(values[0]), "type": type_str, "key": key})

        if not items_info:
            return

        file_count = sum(1 for i in items_info if i["type"] == "文件")
        folder_count = sum(1 for i in items_info if i["type"] == "文件夹")

        if not messagebox.askyesno(
            "确认删除",
            f"确定要删除选中的 {len(items_info)} 个对象吗?\n"
            f"文件: {file_count}, 文件夹: {folder_count}\n\n删除后无法恢复!",
            parent=self.frame,
        ):
            return

        bucket = self.current_bucket
        bridge = get_bridge(self.frame, logger=self.locator.logger)
        self._set_busy("删除")

        def do_delete():
            # ⚠ worker 线程: 只调 S3 + 投递队列, 不碰 Tk
            def progress_cb(current, total, name):
                bridge.post(
                    self._update_delete_status, current, total, name,
                )

            # 1) 文件: 用 transfer 后台线程池并发删 (不阻塞 UI)
            file_keys = [
                i["key"] for i in items_info if i["type"] == "文件"
            ]
            folder_items = [i for i in items_info if i["type"] == "文件夹"]

            results: List[Dict[str, Any]] = []
            if file_keys:
                results.extend(
                    self.locator.transfer.delete_keys(
                        bucket, file_keys, progress=progress_cb,
                    )
                )
            # 2) 文件夹: 走 file_manager.delete_folder (内部用批量 remove_objects)
            #    也在后台线程跑, 避免大文件夹 list_objects 卡 UI
            for item in folder_items:
                ok, msg = self.locator.file_manager.delete_folder(
                    bucket, item["key"],
                )
                results.append({
                    "key": item["key"], "success": ok, "message": msg,
                })
            bridge.post(self._delete_done, results)

        bridge.submit(do_delete, task_name="删除")

    def _update_delete_status(self, current, total, name) -> None:
        if hasattr(self.locator, "_main_window"):
            self.locator._main_window.update_status(
                f"删除中 ({current}/{total}): {name}",
            )

    def _delete_done(self, results) -> None:
        self._set_busy(None)
        success = sum(1 for r in results if r["success"])
        failed = len(results) - success
        for r in results:
            if not r["success"]:
                self.locator.logger.error(
                    "delete", r.get("key", "?"), r.get("message", ""),
                )
        self._last_failures = [
            {"kind": "delete", "key": r.get("key", ""), "message": r.get("message", "")}
            for r in results if not r.get("success")
        ]
        if failed == 0:
            notify(self.frame, "success", f"已删除 {success} 个对象")
        else:
            detail = "\n".join(
                f"{r.get('key', '?')}: {r.get('message', '')}"
                for r in results if not r.get("success")
            )
            messagebox.showwarning(
                "完成",
                f"删除完成: {success} 成功, {failed} 失败\n\n失败详情:\n{detail}\n\n"
                "失败项未被删除 (仍可重试), 可点击「重试失败项」。",
                parent=self.frame,
            )
        if hasattr(self.locator, "_main_window"):
            self.locator._main_window.update_status("就绪")
        self._load_objects()

    def _on_retry_failures(self) -> None:
        """重试上一次批量操作里的失败项 (删除失败最常见)"""
        if not self._last_failures:
            notify(self.frame, "info", "没有可重试的失败项")
            return
        if self._busy:
            notify(self.frame, "warning", f"「{self._busy}」正在进行, 请稍候")
            return

        keys = [
            f["key"] for f in self._last_failures
            if f.get("kind") == "delete" and f.get("key")
        ]
        if not keys:
            notify(self.frame, "info", "当前失败项不支持自动重试 (仅删除可重试)")
            return

        if not messagebox.askyesno(
            "重试删除",
            f"将重新尝试删除 {len(keys)} 个失败对象:\n"
            + "\n".join(keys[:10])
            + ("\n…" if len(keys) > 10 else ""),
            parent=self.frame,
        ):
            return

        bucket = self.current_bucket
        bridge = get_bridge(self.frame, logger=self.locator.logger)
        self._set_busy("删除")

        def do_retry():
            def progress_cb(current, total, name):
                bridge.post(self._update_delete_status, current, total, name)
            results = self.locator.transfer.delete_keys(
                bucket, keys, progress=progress_cb,
            )
            bridge.post(self._delete_done, results)

        bridge.submit(do_retry, task_name="重试删除")

    def _on_copy(self) -> None:
        self._clipboard_operation("copy")

    def _on_cut(self) -> None:
        self._clipboard_operation("cut")

    def _clipboard_operation(self, op: str) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中对象", parent=self.frame)
            return

        items = []
        for item_id in selected:
            if self._is_parent_iid(item_id):
                continue
            values = self.tree.item(item_id)["values"]
            if not values:
                continue
            key = self._get_key(item_id)  # 真实 key (含前缀)
            if not key:
                continue
            type_str = str(values[3]) if len(values) > 3 else ""
            is_dir = (type_str == "文件夹")
            if is_dir and not key.endswith("/"):
                key += "/"
            items.append({
                "bucket": self.current_bucket,
                "key": key,
                "name": str(values[0]),
                "is_dir": is_dir,
            })

        if not items:
            return

        if op == "copy":
            self.locator.clipboard.copy(items)
        else:
            self.locator.clipboard.cut(items)
        # 记源桶: 剪切后切到别的桶, 粘贴时要明确目标桶并二次确认
        self._clip_source_bucket = self.current_bucket
        self.locator.logger.info(op, "", f"已{('复制' if op == 'copy' else '剪切')} {len(items)} 个对象")

    def _on_paste(self) -> None:
        if self.locator.clipboard.is_empty:
            notify(self.frame, "info", "剪贴板为空")
            return
        if not self.current_bucket:
            messagebox.showwarning("提示", "请先选择目标桶", parent=self.frame)
            return

        # 跨桶粘贴确认: 源桶与目标桶不同时, 明确提示目标桶 (剪切=移动语义)
        src = self._clip_source_bucket
        if src and src != self.current_bucket:
            target_prefix = self.current_prefix or "(桶根)"
            if not messagebox.askyesno(
                "跨桶粘贴确认",
                f"剪贴板中的对象来自桶:\n  {src}\n\n"
                f"将粘贴到桶:\n  {self.current_bucket} / {target_prefix}\n\n"
                "继续?",
                parent=self.frame,
            ):
                return

        try:
            results = self.locator.clipboard.paste(
                self.current_bucket, self.current_prefix,
            )
        except Exception as e:
            messagebox.showerror("失败", f"粘贴出错: {e}", parent=self.frame)
            return

        success = sum(1 for r in results if r["success"])
        failed = len(results) - success
        for r in results:
            if not r["success"]:
                self.locator.logger.error(
                    "paste", r.get("key", "?"), r.get("message", ""),
                )

        if failed == 0:
            notify(self.frame, "success", f"已粘贴 {success} 个对象")
        else:
            detail = "\n".join(
                f"{r.get('key', '?')}: {r.get('message', '')}"
                for r in results if not r["success"]
            )
            messagebox.showwarning(
                "完成",
                f"粘贴: {success} 成功, {failed} 失败\n\n失败详情:\n{detail}",
            )
        self._load_objects()

    def _on_properties(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        if self._is_parent_iid(item_id):
            return
        values = self.tree.item(item_id)["values"]
        if not values:
            return
        # iid 是 row id,values[0] 是 display_name (可能缺前导 0)
        name = str(values[0])
        key = self._get_key(item_id) or ""

        def _fallback(reason: str = "") -> None:
            tip = f"类型: {values[3] if len(values) > 3 else ''}"
            if reason:
                tip = f"{reason}\n\n{tip}"
            messagebox.showinfo("属性", f"名称: {name}\n{tip}", parent=self.frame.winfo_toplevel())

        ok, info = self.locator.file_manager.stat_object(self.current_bucket, key)
        if not ok or not info:
            _fallback("读取对象信息失败, 只显示列表里的信息")
            return

        # 原来只有 6 个字段, 拿不到自定义元数据与标签, 这块数据一直是空转
        lines = [
            f"名称:   {info.get('name', name)}",
            f"大小:   {format_bytes(info.get('size', 0))}",
            f"类型:   {info.get('content_type', '-')}",
            f"ETag:   {info.get('etag', '-')}",
            f"修改:   {format_timestamp(info.get('last_modified'))}",
        ]
        meta = info.get("metadata") or {}
        if meta:
            lines.append("")
            lines.append("自定义元数据:")
            for k, v in sorted(meta.items()):
                lines.append(f"  {k} = {v}")
        else:
            lines.append("")
            lines.append("自定义元数据: (无)")

        tags = info.get("tags") or {}
        if tags:
            lines.append("")
            lines.append("标签:")
            for k, v in sorted(tags.items()):
                lines.append(f"  {k} = {v}")
        else:
            lines.append("")
            lines.append("标签: (无)")

        _show_text_window(
            self.frame.winfo_toplevel(),
            title=f"对象属性 — {name}" if len(name) <= 40 else f"对象属性 — {name[:37]}...",
            text="\n".join(lines),
        )

    def _preview_object(self, name: str) -> None:
        """下载文件并用系统默认程序打开

        Args:
            name: 完整的 object key (从 tree iid 传过来,保证前导 0 不丢)
        """
        key = name
        cache_key = f"{self.current_bucket}:{key}"

        # 优先使用缓存
        cached = self.locator.cache.get(cache_key)
        if cached and cached.exists():
            self._open_with_system(cached)
            return

        # ⚠ 本地缓存名用 key 的 md5 前 12 位, 不用 basename。
        #   旧版用 basename: a/2026/report.pdf 和 b/2026/report.pdf 都写进
        #   cache_dir/report.pdf —— 先下载的被覆盖, 缓存命中时可能打开**另一个
        #   对象的内容**; 且 key 含 ':' 等 Windows 非法字符时下载直接失败。
        temp_dir = self.locator.cache._cache_dir
        ext = os.path.splitext(key)[1]
        # 扩展名只保留安全的字母数字, 避免 .tar.gz 被截断成 .gz
        safe_ext = "".join(ch for ch in ext if ch.isalnum() or ch == ".")[:12]
        digest = hashlib.md5(cache_key.encode("utf-8", "replace")).hexdigest()[:12]
        local_name = f"{digest}{safe_ext}"
        temp_path = temp_dir / local_name

        if not self._confirm_open(key):
            return

        ok, msg = self.locator.file_manager.download_file(
            self.current_bucket, key, str(temp_path),
        )
        if ok:
            self.locator.cache.put(cache_key, temp_path)
            self._open_with_system(temp_path)
            self.locator.logger.info("preview", key, "已用系统程序打开")
        else:
            messagebox.showerror("失败", msg, parent=self.frame)

    def _confirm_open(self, key: str) -> bool:
        """大文件 / 非文本类型先问"下载还是直接打开"

        旧版双击就静默下载 + 调用系统程序打开: 2GB 的 iso 会把界面卡住
        几十秒, 用户完全不知道发生了什么。
        """
        base = os.path.basename(key.rstrip("/"))
        ext = os.path.splitext(base)[1].lower()
        if ext in _BINARY_EXTS:
            need_confirm = True
        else:
            try:
                ok, info = self.locator.file_manager.stat_object(
                    self.current_bucket, key,
                )
                size_mb = (info or {}).get("size", 0) / 1024 / 1024
                need_confirm = (not ok) or size_mb > OPEN_DIRECT_MAX_MB
            except Exception:
                need_confirm = True

        if not need_confirm:
            return True

        choice = messagebox.askyesnocancel(
            "打开方式",
            f"「{base}」体积较大或不是文本文件。\n\n"
            f"是: 直接下载并用系统默认程序打开\n"
            f"否: 仅下载到本地 (不自动打开)\n"
            f"取消: 不做任何操作",
            parent=self.frame,
        )
        if choice is None:
            return False
        if choice is False:
            # 仅下载: 走正常下载流程
            save_dir = filedialog.askdirectory(title="选择保存目录")
            if not save_dir:
                return False
            self._download_keys([(key, os.path.join(save_dir, base))], save_dir)
            return False
        return True

    def _open_with_system(self, file_path) -> None:
        """用系统默认程序打开文件"""
        path_str = str(file_path)
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(path_str)  # type: ignore
            elif system == "Darwin":
                subprocess.Popen(["open", path_str])
            else:
                subprocess.Popen(["xdg-open", path_str])
        except Exception as e:
            messagebox.showerror("失败", f"无法打开文件: {e}", parent=self.frame)
