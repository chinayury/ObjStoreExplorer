# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""反馈平台设置对话框 - 新增

对接 MultiFeedbackSystem (接入手册 docs/08-集成手册/):
  - 平台地址 (api_base): 如 https://feedback.itmsky.com
  - App Key: 平台后台「应用管理」发放, 格式 app-xxxxxxxxxxxxxxxx
  - 专属反馈链接: feedback.php?t=<分享令牌>, 可在浏览器直接提交
    (不暴露 app_key, 密钥重置时令牌同步轮换)

参数保存到本地数据库 (config_manager.app_settings 表, 见 feedback_client
的 FEEDBACK_DB_KEYS), 优先级: 数据库 > config/feedback.yaml > 内置默认。

首次点击顶栏 "反馈" 按钮且未检测到参数时自动弹出本窗口 (main_window
_show_feedback_dialog 流程), 保存后继续打开反馈窗口。
"""
from __future__ import annotations
import tkinter as tk
import webbrowser
from tkinter import messagebox
from typing import Callable, Optional

from ..threading_bridge import get_bridge
from ..styles import Neutral, Status, UIFont
from ..widgets.buttons import create_primary_button, create_secondary_button
from ..widgets.notifications import notify
from ...utils.icon_manager import get_window_icon
from ...utils.feedback_client import (
    load_feedback_overrides_from_db, save_feedback_overrides_to_db,
    check_app_key_online,
)


class FeedbackSettingsDialog:
    """反馈平台参数设置"""

    # 内置默认 (本项目官方反馈平台, 用户可在界面上改)
    DEFAULT_API_BASE = "https://feedback.itmsky.com"
    DEFAULT_APP_KEY = "app-5d4f541b89df7709"
    DEFAULT_LINK = (
        "https://feedback.itmsky.com/feedback.php"
        "?t=b85181c3000d66a9ae5f93bcf2812c25"
    )

    def __init__(
        self,
        parent: tk.Misc,
        on_saved: Optional[Callable[[], None]] = None,
    ):
        self.parent = parent
        self._on_saved = on_saved
        # 生命周期守卫: 关闭后测试完成回调不再写已销毁控件
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("反馈平台设置")
        self.dialog.bind("<Destroy>", lambda _e: setattr(self, "_closed", True))
        self.dialog.geometry("560x430")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self.dialog.grab_set()

        self._set_icon()
        self._load_current()
        self._create_body()
        self._create_footer()

    def _set_icon(self) -> None:
        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconbitmap(icon)
        except Exception:
            pass

    # ==================== 数据 ====================

    def _load_current(self) -> None:
        """已有参数 (数据库) 优先, 否则用内置默认"""
        db = load_feedback_overrides_from_db()
        self._api_base = db.get("api_base") or self.DEFAULT_API_BASE
        self._app_key = db.get("app_key") or self.DEFAULT_APP_KEY
        self._link = db.get("link") or self.DEFAULT_LINK

    # ==================== 布局 ====================

    def _create_body(self) -> None:
        body = tk.Frame(self.dialog, bg=Neutral.BG_PANEL)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        tk.Label(
            body, text="反馈平台对接参数",
            font=UIFont.h2(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=24, pady=(18, 4))
        tk.Label(
            body, text="保存在本地数据库, 用于在线提交反馈 (未配置时只能离线打包)",
            font=UIFont.body_sm(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=24, pady=(0, 8))

        rows = (
            ("平台地址:", "_api_base", "如 https://feedback.itmsky.com"),
            ("App Key:", "_app_key", "平台后台「应用管理」发放, app-xxxxxxxx"),
            ("专属反馈链接:", "_link", "浏览器可直接提交的 feedback.php?t= 令牌链接"),
        )
        r = 2
        for label, attr, hint in rows:
            var = tk.StringVar(value=getattr(self, attr))
            setattr(self, attr + "_var", var)
            tk.Label(
                body, text=label, font=UIFont.body(),
                bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W,
            ).grid(row=r, column=0, sticky=tk.W, padx=(24, 8), pady=(10, 0))
            tk.Entry(
                body, textvariable=var, font=UIFont.body(),
                bg=Neutral.BG_APP, relief="solid", bd=1,
            ).grid(row=r, column=1, sticky=tk.EW, padx=(0, 24), pady=(10, 0))
            tk.Label(
                body, text=hint, font=UIFont.body_sm(),
                bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3, anchor=tk.W,
            ).grid(row=r + 1, column=1, sticky=tk.W, padx=(0, 24))
            r += 2

        self._test_label = tk.Label(
            body, text="", font=UIFont.body_sm(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
        )
        self._test_label.grid(row=r, column=0, columnspan=2, sticky=tk.W, padx=24, pady=(12, 0))

    def _create_footer(self) -> None:
        footer = tk.Frame(self.dialog, bg=Neutral.BG_APP)
        footer.pack(fill="x")
        create_secondary_button(
            footer, "打开专属反馈页", self._on_open_link, width=16,
        ).pack(side=tk.LEFT, padx=(20, 4), pady=14)
        create_secondary_button(
            footer, "测试连接", self._on_test, width=10,
        ).pack(side=tk.LEFT, padx=4, pady=14)
        create_secondary_button(
            footer, "取消", self.dialog.destroy, width=8,
        ).pack(side=tk.RIGHT, padx=(4, 20), pady=14)
        self._save_btn = create_primary_button(
            footer, "保存", self._on_save, width=8,
        )
        self._save_btn.pack(side=tk.RIGHT, padx=4, pady=14)

    # ==================== 事件 ====================

    def _on_open_link(self) -> None:
        link = self._link_var.get().strip()
        if not link.startswith("http"):
            messagebox.showwarning("提示", "专属反馈链接格式不对", parent=self.dialog)
            return
        webbrowser.open(link)

    def _on_test(self) -> None:
        api_base = self._api_base_var.get().strip().rstrip("/")
        app_key = self._app_key_var.get().strip()
        if not api_base.startswith("http") or not app_key:
            messagebox.showwarning("提示", "请先填写平台地址和 App Key", parent=self.dialog)
            return
        self._test_label.config(text="测试中…", fg=Neutral.TEXT_2)
        bridge = get_bridge(self.dialog)

        def _bg():
            # ⚠ worker 线程: 只跑网络请求 + 投递队列, 不碰 Tk
            ok, detail = check_app_key_online(api_base, app_key)
            bridge.post(self._on_test_done, ok, detail)

        bridge.submit(_bg, task_name="测试反馈平台")

    def _on_test_done(self, ok: bool, detail: str) -> None:
        """主线程回调: 窗口已关闭时静默丢弃 (结果无意义, 没有界面可显示)"""
        if self._closed:
            try:
                if not self.dialog.winfo_exists():
                    return
            except tk.TclError:
                return
        try:
            if ok:
                self._test_label.config(text=f"连接成功: {detail}", fg=Status.SUCCESS)
            else:
                self._test_label.config(text=f"{detail}", fg=Status.DANGER)
        except tk.TclError:
            pass

    def _on_save(self) -> None:
        api_base = self._api_base_var.get().strip().rstrip("/")
        app_key = self._app_key_var.get().strip()
        link = self._link_var.get().strip()

        if not api_base.startswith(("http://", "https://")):
            messagebox.showerror("参数错误", "平台地址需以 http:// 或 https:// 开头", parent=self.dialog)
            return
        if not app_key.startswith("app-"):
            if not messagebox.askyesno(
                "确认",
                f"App Key 通常以 app- 开头 (当前: {app_key[:24]}), 确定保存吗?",
                parent=self.dialog,
            ):
                return

        try:
            save_feedback_overrides_to_db(
                {"api_base": api_base, "app_key": app_key, "link": link}
            )
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self.dialog)
            return

        notify(self.dialog, "success", "反馈平台参数已保存")
        if self._on_saved:
            self._on_saved()
        self.dialog.destroy()
