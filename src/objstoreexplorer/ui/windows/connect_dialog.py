# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""连接对话框 - 阶段 4 最小版本

含 endpoint/ak/sk 输入、SSL 选项、历史下拉。
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable, Dict, Any

from ..styles import (
    init_global_styles, Space, Brand, Neutral, UIFont,
)
from ..threading_bridge import get_bridge
from ...utils.icon_manager import get_window_icon
from ...core.validators import (
    validate_endpoint,
    validate_access_key,
    validate_secret_key,
)
from ...services.service_locator import ServiceLocator


class ConnectDialog:
    """连接对话框

    用法:
        ConnectDialog(parent, on_success=lambda: print("connected"))
    """

    def __init__(
        self,
        parent: tk.Tk,
        on_success: Optional[Callable] = None,
    ):
        self._parent = parent
        self._on_success = on_success
        self._locator = ServiceLocator()
        # 生命周期守卫: 关闭后连接完成回调不再写已销毁控件
        self._closed = False

        init_global_styles(parent)

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("连接到 MinIO/S3")
        self.dialog.bind("<Destroy>", lambda _e: setattr(self, "_closed", True))
        self.dialog.geometry("500x470")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self._set_icon()
        self._create_widgets()
        self._load_history()

    def _set_icon(self) -> None:
        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconbitmap(icon)
        except Exception:
            pass

    @staticmethod
    def _field_label(parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(
            parent, text=text, font=UIFont.body_sm(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2, anchor=tk.W,
        )

    @staticmethod
    def _entry(parent: tk.Misc, var: tk.StringVar, show: str = "") -> tk.Entry:
        e = tk.Entry(
            parent, textvariable=var, font=UIFont.mono(10), show=show,
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            insertbackground=Brand.PRIMARY,
            relief="flat", bd=0,
            highlightbackground=Neutral.BORDER_HI, highlightthickness=1,
        )
        e.bind("<FocusIn>", lambda _ev: e.configure(highlightbackground=Brand.PRIMARY))
        e.bind("<FocusOut>", lambda _ev: e.configure(highlightbackground=Neutral.BORDER_HI))
        return e

    def _create_widgets(self) -> None:
        from ...utils.icons import get as get_icon
        from ..widgets.buttons import create_primary_button, create_ghost_button

        # ---- 头部: 白底 + 靛蓝图标块 + 发丝线 ----
        header = tk.Frame(self.dialog, bg=Neutral.BG_PANEL, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        chip = tk.Frame(header, bg=Brand.PRIMARY_50, width=36, height=36)
        chip.pack(side=tk.LEFT, padx=(Space.XL, Space.MD))
        chip.pack_propagate(False)
        img = get_icon("plug", 24, tint=Brand.PRIMARY)
        if img is not None:
            lbl = tk.Label(chip, image=img, bg=Brand.PRIMARY_50)
            lbl.image = img
            lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        head_text = tk.Frame(header, bg=Neutral.BG_PANEL)
        head_text.pack(side=tk.LEFT)
        tk.Label(
            head_text, text="CONNECT", font=UIFont.kicker(),
            bg=Neutral.BG_PANEL, fg=Brand.PRIMARY,
        ).pack(anchor=tk.W)
        tk.Label(
            head_text, text="建立 S3 连接",
            font=UIFont.h2(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
        ).pack(anchor=tk.W)

        tk.Frame(self.dialog, bg=Neutral.BORDER, height=1).pack(fill=tk.X)

        # ---- 内容 ----
        content = tk.Frame(self.dialog, bg=Neutral.BG_PANEL)
        content.pack(fill=tk.BOTH, expand=True, padx=Space.XL, pady=Space.LG)

        self._field_label(content, "历史连接 (可选)").pack(fill=tk.X, pady=(0, 5))
        self.history_var = tk.StringVar()
        self.history_combo = ttk.Combobox(
            content, textvariable=self.history_var,
            state="readonly", font=UIFont.body(),
        )
        self.history_combo.pack(fill=tk.X, pady=(0, Space.MD))
        self.history_combo.bind("<<ComboboxSelected>>", self._on_history_select)

        form = tk.Frame(content, bg=Neutral.BG_PANEL)
        form.pack(fill=tk.X)

        rows = [
            ("服务器地址", "endpoint", False, "minio.example.com:9000"),
            ("Access Key", "ak", False, "例如 minioadmin"),
            ("Secret Key", "sk", True, "至少 8 位"),
        ]
        self.endpoint_var = tk.StringVar()
        self.ak_var = tk.StringVar()
        self.sk_var = tk.StringVar()
        for i, (label, attr, secret, hint) in enumerate(rows):
            self._field_label(form, label).grid(
                row=i, column=0, sticky=tk.W, padx=(0, Space.MD), pady=Space.XS)
            entry = self._entry(form, getattr(self, f"{attr}_var"), "*" if secret else "")
            entry.grid(row=i, column=1, sticky=tk.EW, pady=Space.XS, ipady=6)
            entry.insert(0, "")
            tk.Label(
                form, text=hint, font=UIFont.kicker(),
                bg=Neutral.BG_PANEL, fg=Neutral.TEXT_3,
            ).grid(row=i, column=2, sticky=tk.W, padx=(Space.SM, 0))
        form.columnconfigure(1, weight=1)

        self.ssl_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            form, text="使用 HTTPS (SSL)", variable=self.ssl_var,
            font=UIFont.body(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            activebackground=Neutral.BG_PANEL, activeforeground=Brand.PRIMARY_800,
            highlightthickness=0, bd=0,
        ).grid(row=3, column=1, sticky=tk.W, pady=(Space.SM, 0))

        # ---- 底部按钮 ----
        tk.Frame(self.dialog, bg=Neutral.BORDER, height=1).pack(fill=tk.X)
        foot = tk.Frame(self.dialog, bg=Neutral.BG_SUBTLE)
        foot.pack(fill=tk.X)
        inner = tk.Frame(foot, bg=Neutral.BG_SUBTLE)
        inner.pack(fill=tk.X, padx=Space.XL, pady=Space.MD)

        # ⚠ 直接保存工厂返回值。旧版写 `self.connect_btn = inner.winfo_children()[1]`,
        #    pack 顺序是 取消(0) 在前, [1] 拿到的是**取消按钮** —— 连接中
        #    变灰的是"取消", "连接" 仍可点, 用户能并发连击建多个连接。
        self.connect_btn = create_primary_button(
            inner, "连接", self._on_connect, icon="plug",
        )
        self.connect_btn.pack(side=tk.RIGHT, padx=(Space.SM, 0))
        create_ghost_button(
            inner, "取消", self.dialog.destroy,
        ).pack(side=tk.RIGHT)

    def _load_history(self) -> None:
        """加载历史配置到下拉框"""
        try:
            history = self._locator.connection.list_history(limit=20)
            self._history_data = {h["name"]: h for h in history}
            names = list(self._history_data.keys())
            self.history_combo["values"] = names
        except Exception:
            self._history_data = {}

    def _on_history_select(self, event) -> None:
        """选择历史配置时填充表单"""
        name = self.history_var.get()
        cfg = self._history_data.get(name)
        if cfg:
            self.endpoint_var.set(cfg["endpoint"])
            self.ak_var.set(cfg["access_key"])
            self.sk_var.set(cfg["secret_key"])
            self.ssl_var.set(cfg.get("ssl", False))

    def _on_connect(self) -> None:
        # endpoint 允许剥前后空格(用户可能手抖输入)
        # AK/SK **不剥** — 凭证本身可以包含前导/尾部空格,剥掉会错
        endpoint = self.endpoint_var.get().strip()
        ak = self.ak_var.get()
        sk = self.sk_var.get()
        ssl = self.ssl_var.get()

        # 校验
        ok, msg = validate_endpoint(endpoint)
        if not ok:
            messagebox.showerror("参数错误", msg, parent=self.dialog)
            return
        ok, msg = validate_access_key(ak)
        if not ok:
            messagebox.showerror("参数错误", msg, parent=self.dialog)
            return
        ok, msg = validate_secret_key(sk)
        if not ok:
            messagebox.showerror("参数错误", msg, parent=self.dialog)
            return

        # 禁用按钮防重复点击
        self.connect_btn.config(state=tk.DISABLED, text="连接中...")
        self.dialog.update()

        # 异步连接: MinIO 慢/网络抖时整 UI 卡死的根因
        bridge = get_bridge(self.dialog, logger=self._locator.logger)
        result_holder: Dict[str, Any] = {}

        def worker():
            # ⚠ worker 线程: 只调网络 + 投递队列, 不碰 Tk
            try:
                result_holder["ok"], result_holder["msg"] = \
                    self._locator.connection.connect(endpoint, ak, sk, ssl)
            except Exception as e:  # noqa: BLE001
                result_holder["ok"] = False
                result_holder["msg"] = f"未预期错误: {e}"
            bridge.post(self._on_connect_done, endpoint, dict(result_holder))

        bridge.submit(worker, task_name="连接")

    def _on_connect_done(self, endpoint: str, result: Dict[str, Any]) -> None:
        """连接工作线程完成回调 (主线程)"""
        ok = result.get("ok", False)
        msg = result.get("msg", "")

        # ⚠ 窗口已关闭: 连接其实已经成功, 但不能弹窗 (没人看) 也不能
        #    碰已销毁的按钮。把结果落到主窗口状态栏, 并照样触发 on_success,
        #    否则主窗口徽章永远停在"未连接"。
        if self._closed or not self.dialog.winfo_exists():
            try:
                if ok:
                    self._locator.logger.success("connect", endpoint, msg)
                    main = getattr(self._parent, "update_status", None)
                    if callable(main):
                        main(f"已连接到 {endpoint} (连接窗口已关闭)")
                    if self._on_success:
                        self._on_success()
                else:
                    self._locator.logger.error("connect", endpoint, msg)
            except Exception:
                pass
            return

        self.connect_btn.config(state=tk.NORMAL, text="连接")

        if ok:
            self._locator.logger.success("connect", endpoint, msg)
            messagebox.showinfo("成功", f"已连接到 {endpoint}", parent=self.dialog)
            self.dialog.destroy()
            if self._on_success:
                self._on_success()
        else:
            self._locator.logger.error("connect", endpoint, msg)
            # 人话映射 (未命中规则时原样返回): 把 AccessDenied /
            # SignatureDoesNotMatch 等错误码翻成「原因 + 建议动作」
            from ...core.error_hints import hint_for_error
            messagebox.showerror("连接失败", hint_for_error(msg), parent=self.dialog)
