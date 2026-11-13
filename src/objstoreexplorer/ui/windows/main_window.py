# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""主窗口 —「暮橙 Emberline」外壳

结构 (自上而下):
    ┌──────────────── 顶栏 (白底 + 底部发丝线) ────────────────┐
    │ [连接] [断开] [刷新] [一键创建] [反馈]        ● 已连接  │
    ├──────────┬───────────────────────────────────────────────┤
    │ 侧栏      │ 页面区                                        │
    │ 品牌块    │   PageHeader(kicker + 巨型标题 + 操作区)      │
    │ 数据资产  │   Card / StatCard / Treeview                 │
    │ 访问控制  │                                               │
    │ 存储治理  │                                               │
    │ 系统运维  │                                               │
    │ 用户卡片  │                                               │
    ├──────────┴───────────────────────────────────────────────┤
    │ 状态栏 (点击看完整消息)                                  │
    └──────────────────────────────────────────────────────────┘

功能面与重构前完全一致: 页面切换 / 全局快捷键 / 连接管理 / 日志订阅。
"""
from __future__ import annotations
import traceback
import tkinter as tk
from tkinter import messagebox
from typing import Optional, Dict, List, Tuple

from ..styles import init_global_styles, Brand, Neutral, Status, Space, UIFont
from ..widgets.buttons import (
    create_secondary_button,
)
from ..widgets.badge import Badge
from ..widgets.notifications import notify
from ..widgets.sidebar import SidebarItem
from ..threading_bridge import get_bridge, shutdown_bridge
from ...utils.icons import get as get_icon
from ..pages import (
    BasePage, OverviewPage, BucketsPage, ObjectsPage,
    UsersPage, PoliciesPage, LogsPage,
    VersioningPage, LifecyclePage, SettingsPage, AboutPage,
    SyncPage,
)
from ..windows.connect_dialog import ConnectDialog
from ..windows.create_user_dialog import OneClickSetupDialog, CreateUserDialog
from ...services.service_locator import ServiceLocator
from ...config.settings import APP_DISPLAY_NAME, SIDEBAR_WIDTH


# 菜单定义: (兼容位, 标签, cmd_id, Lucide 图标名)
MENU_ITEMS: List[Tuple[str, str, str, str]] = [
    ("", "概览",      "overview",   "layout-dashboard"),
    ("", "存储桶",    "buckets",    "archive"),
    ("", "对象管理",  "objects",    "folder"),
    ("", "同步",      "sync",       "refresh-cw"),
    ("", "用户管理",  "users",      "users"),
    ("", "策略管理",  "policies",   "shield-check"),
    ("", "版本控制",  "versioning", "history"),
    ("", "生命周期",  "lifecycle",  "timer"),
    ("", "操作日志",  "logs",       "scroll-text"),
    ("", "系统设置",  "settings",   "settings"),
    ("", "关于",      "about",      "info"),
]

# 侧栏分组 (数据资产 / 访问控制 / 存储治理 / 系统运维)
MENU_GROUPS: List[Tuple[str, List[str]]] = [
    ("数据资产", ["overview", "buckets", "objects", "sync"]),
    ("访问控制", ["users", "policies"]),
    ("存储治理", ["versioning", "lifecycle"]),
    ("系统运维", ["logs", "settings", "about"]),
]

_MENU_BY_ID = {m[2]: m for m in MENU_ITEMS}


class MainWindow:
    """主窗口"""

    def __init__(self, root: tk.Tk, locator: ServiceLocator):
        self.root = root
        self.locator = locator

        # 把 self 注入到 locator,以便页面访问主窗口
        self.locator._main_window = self  # type: ignore

        init_global_styles(self.root)

        # ---- 页面刷新节流 (必须早于 _register_pages) ----
        # 旧版每次 show_page 都无条件 after(100, page.refresh), 连续点侧栏
        # 5 次就排队 5 次全量刷新, 越点越卡。_register_pages 内部就会调
        # show_page("overview"), 所以这两个字段必须先建好。
        self._refresh_pending: Dict[str, str] = {}
        self._shutting_down = False

        self._setup_window()
        self._create_layout()
        self._create_status_bar()
        self._register_pages()
        self._bind_shortcuts()

        # 订阅日志
        self.locator.logger.subscribe(self._on_log_event)

        # ---- Tk 回调异常兜底 ----
        # 不重写 report_callback_exception 的话, 任何未捕获异常只往 stderr
        # 打印; GUI 版 (pythonw / PyInstaller) 根本没有 stderr, 用户只看到
        # "点了没反应"。重写后弹窗 + 写日志。
        self.root.report_callback_exception = self._on_tk_callback_error

    # ==================== 初始化 ====================

    def _setup_window(self) -> None:
        self.root.title(APP_DISPLAY_NAME)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_layout(self) -> None:
        """顶栏 + 侧边栏 + 内容区"""
        self._create_topbar()

        body = tk.Frame(self.root, bg=Neutral.BG_APP)
        body.pack(fill=tk.BOTH, expand=True)

        self._create_sidebar(body)

        self.content_frame = tk.Frame(body, bg=Neutral.BG_APP)
        self.content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ---------------- 顶栏 ----------------

    def _create_topbar(self) -> None:
        """白底顶栏: 左侧操作组 + 右侧连接徽章, 底部 1px 发丝线"""
        toolbar = tk.Frame(self.root, bg=Neutral.BG_PANEL, height=Space.TOOLBAR_H)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        toolbar.pack_propagate(False)

        # ⚠ Tk pack 是"顺序分配 cavity"的: 左侧 expand 的 Frame 必须最后 pack,
        #   否则它会把 cavity 吃光, 之后 pack 的右侧控件宽度变成 0。
        #   所以右侧徽章先 pack, 左侧操作区后 pack。
        self.connection_badge_frame = tk.Frame(toolbar, bg=Neutral.BG_PANEL)
        self.connection_badge_frame.pack(side=tk.RIGHT, padx=(0, Space.LG), pady=Space.MD)

        inner = tk.Frame(toolbar, bg=Neutral.BG_PANEL)
        inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=Space.MD)

        from ..widgets.buttons import create_primary_button

        create_primary_button(
            inner, "连接", self._show_connect_dialog, icon="plug",
        ).pack(side=tk.LEFT, padx=(0, Space.XS), pady=Space.MD)
        create_secondary_button(
            inner, "断开", self._disconnect, icon="power",
        ).pack(side=tk.LEFT, padx=Space.XS, pady=Space.MD)
        create_secondary_button(
            inner, "刷新", self._refresh_current, icon="refresh-cw",
        ).pack(side=tk.LEFT, padx=Space.XS, pady=Space.MD)

        tk.Frame(inner, bg=Neutral.BORDER, width=1, height=24).pack(
            side=tk.LEFT, padx=Space.MD, pady=Space.MD,
        )

        create_secondary_button(
            inner, "一键创建", self._show_one_click_setup, icon="zap",
        ).pack(side=tk.LEFT, padx=Space.XS, pady=Space.MD)
        create_secondary_button(
            inner, "反馈", self._show_feedback_dialog, icon="message",
        ).pack(side=tk.LEFT, padx=Space.XS, pady=Space.MD)

        # 右侧: 恒显连接状态徽章
        self.connection_badge: Optional[Badge] = None
        self._set_connection_badge(connected=False, text="未连接")

        # 底部发丝线
        tk.Frame(self.root, bg=Neutral.BORDER, height=1).pack(side=tk.TOP, fill=tk.X)

    # ---------------- 侧边栏 ----------------

    def _create_sidebar(self, parent) -> None:
        """浅底侧栏: 品牌块 + 分组导航 + 底部用户卡"""
        width = SIDEBAR_WIDTH or Space.SIDEBAR_W
        sidebar = tk.Frame(
            parent, bg=Neutral.BG_PANEL, width=width,
            highlightbackground=Neutral.BORDER, highlightthickness=0,
        )
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        self._sidebar = sidebar

        # ---- 品牌块 (陶土橙方块 + 深色内描边, 表达"橙→赭渐变"层次) ----
        logo_frame = tk.Frame(sidebar, bg=Neutral.BG_PANEL, height=Space.TOOLBAR_H)
        logo_frame.pack(fill=tk.X)
        logo_frame.pack_propagate(False)

        # 外层深主色 = 渐变意象的暗端 (Tk 无真渐变, 用两层叠出色阶)
        mark = tk.Frame(logo_frame, bg=Brand.MARK_TO, width=32, height=32)
        mark.pack(side=tk.LEFT, padx=(Space.LG, Space.MD))
        mark.pack_propagate(False)
        # 内层亮主色, 四周留 2px 深色边 = 层次描边
        mark_in = tk.Frame(mark, bg=Brand.MARK_FROM)
        mark_in.place(relx=0.5, rely=0.5, anchor=tk.CENTER,
                      width=28, height=28)
        # 品牌块图标: 图标集只有 16/24 两档, 取 24 (旧代码请求 22,
        # 资源里没有 @22 变体, 图标一直静默缺失 —— v0.1.0 第五轮修复)
        img = get_icon("layers", 24, tint=Neutral.TEXT_INV)
        if img is not None:
            m_lbl = tk.Label(mark_in, image=img, bg=Brand.MARK_FROM)
            m_lbl.image = img
            m_lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            tk.Label(
                mark_in, text="◆", font=("Segoe UI Symbol", 13, "bold"),
                bg=Brand.MARK_FROM, fg=Neutral.TEXT_INV,
            ).place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        text_col = tk.Frame(logo_frame, bg=Neutral.BG_PANEL)
        text_col.pack(side=tk.LEFT)
        tk.Label(
            text_col, text="ObjStoreExplorer",
            font=UIFont.h3(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
        ).pack(anchor=tk.W)
        tk.Label(
            text_col, text="OBJECT STORAGE CONSOLE",
            font=UIFont.kicker(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
        ).pack(anchor=tk.W)

        tk.Frame(sidebar, bg=Neutral.DIVIDER, height=1).pack(fill=tk.X)

        # ---- 分组导航 ----
        self.menu_items: Dict[str, SidebarItem] = {}
        self.current_menu: str = ""

        menu_frame = tk.Frame(sidebar, bg=Neutral.BG_PANEL)
        menu_frame.pack(fill=tk.BOTH, expand=True, pady=(Space.SM, 0))

        for group_name, ids in MENU_GROUPS:
            tk.Label(
                menu_frame, text=group_name, font=UIFont.kicker(),
                bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
            ).pack(anchor=tk.W, padx=Space.LG, pady=(Space.MD, Space.XS))

            for cmd_id in ids:
                entry = _MENU_BY_ID.get(cmd_id)
                if entry is None:
                    continue
                _, label, _, icon_name = entry
                item = SidebarItem(
                    menu_frame,
                    label=label,
                    icon=icon_name,
                    on_click=lambda c=cmd_id: self._on_menu_selected_v2(c),
                )
                item.pack(fill=tk.X, padx=Space.XS, pady=1)
                self.menu_items[cmd_id] = item

        # ---- 底部用户卡 ----
        tk.Frame(sidebar, bg=Neutral.DIVIDER, height=1).pack(fill=tk.X, side=tk.BOTTOM)
        foot = tk.Frame(sidebar, bg=Neutral.BG_SUBTLE, height=54)
        foot.pack(fill=tk.X, side=tk.BOTTOM)
        foot.pack_propagate(False)
        av = tk.Frame(foot, bg=Brand.PRIMARY_100, width=28, height=28)
        av.pack(side=tk.LEFT, padx=(Space.MD, Space.SM))
        av.pack_propagate(False)
        tk.Label(
            av, text="本", font=(UIFont.family(), 9, "bold"),
            bg=Brand.PRIMARY_100, fg=Brand.PRIMARY_700,
        ).place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        meta = tk.Frame(foot, bg=Neutral.BG_SUBTLE)
        meta.pack(side=tk.LEFT, fill=tk.Y, pady=Space.MD)
        tk.Label(
            meta, text="本地桌面版", font=UIFont.body_sm(),
            bg=Neutral.BG_SUBTLE, fg=Neutral.TEXT_1, anchor=tk.W,
        ).pack(anchor=tk.W)
        tk.Label(
            meta, text="", font=UIFont.kicker(),
            bg=Neutral.BG_SUBTLE, fg=Neutral.TEXT_3, anchor=tk.W,
        ).pack(anchor=tk.W)

    # ---------------- 状态栏 ----------------

    def _create_status_bar(self) -> None:
        """浅底状态栏: 左侧可换行消息 (点击看全文) + 右侧当前页"""
        status = tk.Frame(self.root, bg=Neutral.BG_PANEL)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_frame = status
        self._status_full_text = ""

        # 顶部分隔线
        tk.Frame(status, bg=Neutral.BORDER, height=1).pack(side=tk.TOP, fill=tk.X)

        self.page_label = tk.Label(
            status, text="", font=UIFont.caption(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
        )
        self.page_label.pack(side=tk.RIGHT, padx=(0, Space.LG), pady=Space.SM)

        self.status_label = tk.Label(
            status, text="就绪", font=UIFont.body_sm(),
            bg=Neutral.BG_PANEL, fg=Status.SUCCESS,
            anchor=tk.W, justify=tk.LEFT, wraplength=600,
            cursor="question_arrow",
        )
        self.status_label.pack(
            side=tk.LEFT, fill=tk.X, expand=True,
            padx=(Space.LG, Space.SM), pady=Space.SM,
        )
        self.status_label.bind("<Button-1>", lambda e: self._show_full_status())

        def _sync_wrap(event):
            self.status_label.configure(wraplength=max(200, event.width - 260))

        status.bind("<Configure>", _sync_wrap)

    def _register_pages(self) -> None:
        """注册所有页面"""
        self.pages: Dict[str, BasePage] = {
            "overview": OverviewPage(self.content_frame, self.locator),
            "buckets": BucketsPage(self.content_frame, self.locator),
            "objects": ObjectsPage(self.content_frame, self.locator),
            "sync": SyncPage(self.content_frame, self.locator),
            "users": UsersPage(self.content_frame, self.locator),
            "policies": PoliciesPage(self.content_frame, self.locator),
            "logs": LogsPage(self.content_frame, self.locator),
            "versioning": VersioningPage(self.content_frame, self.locator),
            "lifecycle": LifecyclePage(self.content_frame, self.locator),
            "settings": SettingsPage(self.content_frame, self.locator),
            "about": AboutPage(self.content_frame, self.locator),
        }
        self.current_page: Optional[BasePage] = None
        self.show_page("overview")

    def _bind_shortcuts(self) -> None:
        """全局快捷键

        ⚠ Delete / F2 只在这里绑。对象页的 tree 上**不要**再绑一份:
        Tk 按 bindtag 顺序派发, 事件会冒泡到 root, 两个 handler 都跑 →
        连弹两个确认框 (旧代码 objects_page.py 与这里各绑了一份)。
        """
        self.root.bind("<F5>", lambda e: self._refresh_current())
        self.root.bind("<Control-r>", lambda e: self._refresh_current())
        self.root.bind("<Control-o>", lambda e: self._on_shortcut_upload())
        self.root.bind("<Control-d>", lambda e: self._on_shortcut_download())
        self.root.bind("<Control-n>", lambda e: self._on_shortcut_new())
        self.root.bind("<Delete>", lambda e: self._on_shortcut_delete())
        self.root.bind("<F2>", lambda e: self._on_shortcut_rename())

    # ==================== 页面切换 ====================

    def _on_menu_selected_v2(self, menu_id: str) -> None:
        """侧边栏点击回调 (SidebarItem 直接调)"""
        for cmd, item in self.menu_items.items():
            item.set_selected(cmd == menu_id)
        self.current_menu = menu_id
        self.show_page(menu_id)

    def _on_menu_selected(self, menu_id, frame=None, indicator=None, label=None) -> None:
        """兼容旧签名"""
        self._on_menu_selected_v2(menu_id)

    def show_page(self, page_id: str) -> None:
        """显示指定页面"""
        if self.current_page is not None:
            self.current_page.hide()

        page = self.pages.get(page_id)
        if page is None:
            return
        page.show()
        self.current_page = page
        # 自动刷新数据 (节流: 同一页 250ms 内的重复切换只刷新一次)
        self._schedule_refresh(page_id, page)
        # 状态栏显示当前页
        entry = _MENU_BY_ID.get(page_id)
        if entry is not None:
            self.page_label.config(text=entry[1])
        if hasattr(self, "menu_items"):
            for cmd, item in self.menu_items.items():
                item.set_selected(cmd == page_id)
            self.current_menu = page_id

    def _schedule_refresh(self, page_id: str, page: BasePage) -> None:
        """去抖刷新: 同一页重复切换 (连点侧栏) 不排队多次全量刷新"""
        token = self._refresh_pending.get(page_id)
        if token is not None:
            try:
                self.root.after_cancel(token)
            except tk.TclError:
                pass
        try:
            self._refresh_pending[page_id] = self.root.after(
                250, lambda: self._do_refresh(page_id, page),
            )
        except tk.TclError:
            self._refresh_pending.pop(page_id, None)

    def _do_refresh(self, page_id: str, page: BasePage) -> None:
        self._refresh_pending.pop(page_id, None)
        if self._shutting_down:
            return
        try:
            page.refresh()
        except Exception:
            # 单页刷新失败不该拖垮整窗
            self._log_and_report("页面刷新", traceback.format_exc(), notify_only=True)

    def navigate_to_objects(self, bucket: str) -> None:
        """切换到对象页面并选中指定桶"""
        self.show_page("objects")
        page = self.pages["objects"]
        if hasattr(page, "set_bucket"):
            page.set_bucket(bucket)

    # ==================== 事件处理 ====================

    def _show_connect_dialog(self) -> None:
        ConnectDialog(self.root, on_success=self._on_connected)

    def _on_connected(self) -> None:
        endpoint = self.locator.connection.current_endpoint or ""
        short = endpoint.replace("http://", "").replace("https://", "")
        self._set_connection_badge(connected=True, text=f"已连接 · {short}")
        self.update_status(f"已连接到 {endpoint}")
        # 只刷"当前页 + buckets + objects"。
        # 旧版遍历全部 11 个页面串行 refresh() (概览要全量扫每个桶, 能跑
        # 数十秒), 主窗口整个冻结 10+ 秒, 而且异常被 `except: pass` 吞掉,
        # 失败页面永远停在旧数据。其余页面等用户切过去时再刷。
        for page_id in ("buckets", "objects"):
            page = self.pages.get(page_id)
            if page is None or page.frame is None:
                continue
            try:
                page.refresh()
            except Exception:
                self._log_and_report(
                    "连接后刷新", traceback.format_exc(), notify_only=True,
                )
        # 当前页若是别的页面, 补刷一次
        if self.current_page is not None and self.current_page.frame is not None:
            try:
                self.current_page.refresh()
            except Exception:
                self._log_and_report(
                    "连接后刷新", traceback.format_exc(), notify_only=True,
                )

    def _disconnect(self) -> None:
        if not self.locator.is_connected:
            notify(self.root, "info", "尚未连接")
            return
        self.locator.disconnect()
        self._set_connection_badge(connected=False, text="未连接")
        self.update_status("已断开连接")
        self.locator.logger.info("disconnect", "", "用户主动断开")
        notify(self.root, "info", "已断开连接")

        # ⚠ 必须清掉对象页的 current_bucket: 断开后它仍留着旧桶名, 用户
        #   按 F5 会走 _load_objects(), 拿已关闭的客户端发请求 (旧代码该
        #   分支没有 is_connected 检查), 表现为"断开后再刷新就报错/卡住"。
        objects_page = self.pages.get("objects")
        if objects_page is not None:
            try:
                objects_page.current_bucket = None
                objects_page.current_prefix = ""
                objects_page.prefix_var.set("")
            except Exception:
                pass

        for page in self.pages.values():
            try:
                if hasattr(page, "tree"):
                    for item in page.tree.get_children():
                        page.tree.delete(item)
            except Exception:
                pass

    def _set_connection_badge(self, connected: bool, text: str) -> None:
        """重建连接状态徽章 (Badge 的 kind 不可变, 重建一遍即可)"""
        if self.connection_badge is not None:
            try:
                self.connection_badge.destroy()
            except Exception:
                pass
        kind = "success" if connected else "neutral"
        self.connection_badge = Badge(
            self.connection_badge_frame, text=text,
            kind=kind, dot=True,
        )
        self.connection_badge.pack()

    def _refresh_current(self) -> None:
        if self.current_page is not None:
            self.current_page.refresh()
            entry = _MENU_BY_ID.get(self.current_menu)
            self.update_status(f"已刷新: {entry[1] if entry else self.current_menu}")

    def _show_feedback_dialog(self) -> None:
        """打开反馈对话框 (在线 POST / 离线打包 zip)"""
        from ...utils.feedback_client import has_feedback_config
        if not has_feedback_config():
            from ..windows.feedback_settings_dialog import FeedbackSettingsDialog
            FeedbackSettingsDialog(self.root, on_saved=self._show_feedback_dialog)
            return
        from ..windows.feedback_dialog import FeedbackDialog
        FeedbackDialog(self.root, on_success=lambda r: self.update_status(
            f"反馈已{'提交' if r.get('mode') == 'online' else '打包'}: {r.get('msg', '')}"
        ))

    def _show_one_click_setup(self) -> None:
        """打开一键创建对话框 (桶+用户+策略+附加)"""
        if not self.locator.is_connected:
            notify(self.root, "warning", "请先连接 MinIO")
            return
        OneClickSetupDialog(
            self.root, self.locator,
            on_success=lambda: self._refresh_current(),
        )

    def _show_create_user(self) -> None:
        if not self.locator.is_connected:
            notify(self.root, "warning", "请先连接")
            return
        CreateUserDialog(
            self.root, self.locator,
            on_success=lambda: self.pages["users"].refresh(),
        )

    def _show_about(self) -> None:
        from ...config.settings import APP_VERSION
        messagebox.showinfo(
            "关于",
            f"ObjStoreExplorer v{APP_VERSION}\n\n"
            "融合重构版 MinIO/S3 对象存储管理工具\n\n"
            "特性:\n"
            "  • 工厂模式自动适配 minio-py V1/V2\n"
            "  • Fernet 加密本地存储\n"
            "  • 后台线程池 + 可取消传输\n"
            "  • 4 层架构 (config/core/services/ui)\n"
            "  • 完整功能: 搜索/剪贴板/缓存/预览\n"
            "  • 用户/策略/版本控制/生命周期管理\n\n"
            "Icons: Lucide (ISC License) — https://lucide.dev\n\n"
            "Copyright (C) 2026 智维ITMSKY\n"
            "开发者: 智维ITMSKY    官网: http://www.itmsky.com\n"
            "License: AGPL-3.0-or-later\n"
            "SPDX-License-Identifier: AGPL-3.0-or-later",
        )

    def _on_close(self) -> None:
        # ⚠ 后台任务在途时直接 destroy: 同步/上传/删除线程还在跑, 并继续
        #   往已销毁的控件投递 → TclError, 甚至写到已释放内存。
        #   所以这里先问一次, 并在 destroy 前取消所有轮询器。
        bridge = get_bridge(self.root)
        if bridge.has_inflight:
            names = "、".join(bridge.inflight_names[:5]) or "后台任务"
            if not messagebox.askyesno(
                "退出",
                f"当前还有后台任务在执行:\n{names}\n\n"
                "强制退出会中断传输, 已完成的部分不会回滚。确定要退出吗?",
                parent=self.root,
            ):
                return

        if not messagebox.askyesno("退出", "确定要退出程序吗?", parent=self.root):
            return

        self._shutting_down = True
        # 取消页面刷新去抖器, 避免 destroy 后回调触发
        for page_id, token in list(self._refresh_pending.items()):
            try:
                self.root.after_cancel(token)
            except tk.TclError:
                pass
        self._refresh_pending.clear()
        # 停掉线程桥的轮询器 (悬空 after 脚本的根源)
        shutdown_bridge(self.root)
        try:
            self.locator.shutdown()
        finally:
            self.root.destroy()

    # ==================== 全局异常兜底 ====================

    def _on_tk_callback_error(self, exc_type, exc_value, exc_tb) -> None:
        """root.report_callback_exception: Tk 回调里未捕获的异常

        默认实现只往 stderr 打印, GUI 版没有 stderr → 用户看到"点了没反应"。
        这里改成: 写日志 + 弹窗 (退出时静默, 避免 destroy 过程中弹模态框卡死)。
        """
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        self._log_and_report("界面回调", detail)
        if self._shutting_down:
            return
        try:
            messagebox.showerror(
                "程序出错",
                f"{exc_type.__name__}: {exc_value}\n\n"
                "操作已中断, 详情已写入日志。可尝试重试该操作。",
                parent=self.root,
            )
        except tk.TclError:
            pass

    def _log_and_report(
        self,
        op: str,
        detail: str,
        notify_only: bool = False,
    ) -> None:
        """统一日志出口 (Logger 自身异常时静默, 不再二次抛出)"""
        try:
            self.locator.logger.error(op, "", detail.strip().splitlines()[-1][:200])
        except Exception:
            pass
        if notify_only:
            try:
                self.update_status(f"[错误] {op} 失败, 详见日志")
            except tk.TclError:
                pass

    # ==================== 快捷键处理 ====================

    def _on_shortcut_upload(self) -> None:
        if self.current_page and hasattr(self.current_page, "on_upload"):
            self.current_page.on_upload()

    def _on_shortcut_download(self) -> None:
        if self.current_page and hasattr(self.current_page, "on_download"):
            self.current_page.on_download()

    def _on_shortcut_new(self) -> None:
        if not self.locator.is_connected:
            return
        if self.current_menu == "buckets":
            self.pages["buckets"]._on_create_bucket()
        elif self.current_menu == "objects":
            self.pages["objects"]._on_create_folder()
        elif self.current_menu == "users":
            self._show_create_user()

    def _on_shortcut_delete(self) -> None:
        if self.current_page == self.pages.get("objects"):
            self.pages["objects"]._on_delete()

    def _on_shortcut_rename(self) -> None:
        if self.current_page == self.pages.get("objects"):
            self.pages["objects"]._on_rename()

    # ==================== 状态/日志 ====================

    def update_status(self, message: str) -> None:
        """更新状态栏消息 (超长截断, 点击看全文)"""
        self._status_full_text = message or ""
        if len(message) > 500:
            shown = message[:500] + " …(点击查看完整内容)"
        else:
            shown = message
        self.status_label.config(text=shown)

    def _show_full_status(self) -> None:
        if getattr(self, "_status_full_text", ""):
            messagebox.showinfo("状态消息详情", self._status_full_text)

    def _on_log_event(self, entry) -> None:
        """日志事件回调 (写入 GUI 状态栏 + 日志页实时追加)"""
        level = entry.get("level", "INFO")
        msg = entry.get("message", "")
        op = entry.get("operation", "")
        prefix = {"ERROR": "[错误]", "WARNING": "[警告]", "INFO": "[信息]"}.get(level, "[信息]")
        self.update_status(f"{prefix} {op} · {msg}".strip())

        # 日志页正在显示时实时追加一行, 避免切回来看到旧日志
        try:
            page = self.pages.get("logs")
            if page is not None and page is self.current_page and page.frame is not None:
                page.append_live(entry)
        except Exception:
            pass

    # ==================== 入口 ====================

    def show(self) -> None:
        """启动主窗口"""
        self.root.mainloop()
