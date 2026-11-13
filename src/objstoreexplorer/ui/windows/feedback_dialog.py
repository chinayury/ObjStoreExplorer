# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""反馈对话框 - 提交 Bug / 建议

功能:
  - 标题 / 内容 / 分类 / 联系方式
  - 截图: 截当前窗口 / 全屏 / 剪贴板粘贴 (Ctrl+V) / 选文件
  - 自检: 一键收集联网状态 / 服务状态 / Windows Event Log / 应用日志
  - 浏览器 F12 教程: ObjStoreExplorer 不是浏览器, 写说明教用户怎么取 Web 端 console 日志
  - 提交: 自动判断在线 (POST) / 离线 (打包 zip), 弹窗展示结果

接入手册: docs/08-集成手册/MultiFeedbackSystem-接入手册-v.html
"""
from __future__ import annotations
import io
import platform
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Dict, List, Optional

from PIL import Image, ImageTk

from ..widgets.scrollarea import bind_mousewheel
from ..threading_bridge import get_bridge
from ..styles import Brand, Neutral, Status, UIFont
from ..widgets.buttons import create_primary_button, create_secondary_button
from ..widgets.notifications import notify
from ...utils.icon_manager import get_window_icon
from ...utils.screenshot import capture_screen, capture_active_window, capture_clipboard_image
from ...utils.diagnostics import collect_diagnostics, check_internet
from ...utils.feedback_client import (
    FeedbackPayload, submit_smart, load_feedback_config, is_placeholder_config,
)
from ...config.settings import APP_VERSION, FEEDBACK_MAX_IMAGES, FEEDBACK_MAX_IMAGE_BYTES


CATEGORIES = [
    ("1", "功能异常"),
    ("2", "体验问题"),
    ("3", "使用建议"),
    ("4", "应用授权"),
    ("5", "其他"),
]


class FeedbackDialog:
    """反馈对话框"""

    def __init__(
        self,
        parent: tk.Misc,
        on_success: Optional[Callable[[Dict], None]] = None,
    ):
        self.parent = parent
        self._on_success = on_success
        self._images: List[bytes] = []          # 原始 PNG bytes
        self._thumbs: List[ImageTk.PhotoImage] = []   # tk 引用 (防 GC)
        self._diagnostics: Optional[Dict] = None
        self._online: bool = False
        # 生命周期守卫: 关闭后后台完成回调不再写已销毁控件 (见 _on_destroy)
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("提交反馈")
        self.dialog.bind("<Destroy>", lambda _e: setattr(self, "_closed", True))
        # 按屏幕自适应 (小屏/远程桌面下固定 640x720 会显示不全),
        # 并显式居中定位 (不依赖 WM 自动摆放, 防止弹到屏幕外/任务栏下),
        # 内容区本身可滚动, 超出部分拉滚动条即可
        sw = self.dialog.winfo_screenwidth()
        sh = self.dialog.winfo_screenheight()
        self._fit_w = min(640, max(480, sw - 60))
        self._fit_h = min(720, max(480, sh - 110))
        self.dialog.geometry(
            f"{self._fit_w}x{self._fit_h}"
            f"+{(sw - self._fit_w) // 2}+{max(0, (sh - self._fit_h) // 4)}")
        self.dialog.minsize(min(560, self._fit_w), min(600, self._fit_h))
        self.dialog.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self.dialog.grab_set()

        self._set_icon()
        self._create_widgets()
        # 初始异步检测联网状态
        self.dialog.after(100, self._refresh_online_status)

    def _set_icon(self) -> None:
        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconphoto(False, icon)
        except Exception:
            pass

    def _valid(self) -> bool:
        """对话框是否仍存活 (后台回调首行必查)"""
        if self._closed:
            return False
        try:
            return bool(self.dialog.winfo_exists())
        except tk.TclError:
            return False

    def _report_after_close(self, title: str, lines: List[str]) -> None:
        """窗口已关: 结果落状态栏 (不弹窗 —— 弹了也没人看)"""
        try:
            main = getattr(self.parent, "_main_window", None)
            if main is not None:
                main.update_status(f"[{title}] {lines[0] if lines else ''}")
        except Exception:
            pass

    # ==================== 布局 ====================

    def _create_widgets(self) -> None:
        # 顶部说明
        header = tk.Frame(self.dialog, bg=Brand.PRIMARY, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="提交反馈",
            font=(UIFont.family(), 14, "bold"),
            bg=Brand.PRIMARY, fg=Neutral.TEXT_INV,
        ).pack(side="left", padx=20, pady=12)
        self._online_label = tk.Label(
            header, text="检测中…", font=(UIFont.family(), 10),
            bg=Brand.PRIMARY, fg=Neutral.TEXT_INV,
        )
        self._online_label.pack(side="right", padx=20, pady=12)

        # 主体滚动
        body_outer = tk.Frame(self.dialog)
        body_outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(body_outer, highlightthickness=0, bg=Neutral.BG_PANEL)
        vsb = ttk.Scrollbar(body_outer, orient="vertical", command=canvas.yview)
        self._body = tk.Frame(canvas, bg=Neutral.BG_PANEL)
        self._body.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        self._body_win = canvas.create_window((0, 0), window=self._body, anchor="nw", tags="body")
        # canvas 宽度变化时同步内嵌 body 的宽度, 否则 body 按内容自然宽度渲染,
        # 窄窗口下右侧控件 (粘贴按钮/分类选项) 会被直接裁掉 —— 同 创建用户弹窗的修复
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._body_win, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        # 鼠标滚轮 (改用控件级绑定, 见 widgets/scrollarea.py 的说明)
        bind_mousewheel(canvas, self._body)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._canvas = canvas

        # 表单
        form = tk.Frame(self._body, bg=Neutral.BG_PANEL)
        form.pack(fill="x", padx=20, pady=12)
        form.columnconfigure(1, weight=1)

        # 标题
        self._add_label(form, "标题 * (2-100 字)", 0)
        self.var_title = tk.StringVar()
        self.entry_title = ttk.Entry(form, textvariable=self.var_title, font=(UIFont.family(), 10))
        self.entry_title.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        self._title_hint = tk.Label(form, text="", font=(UIFont.family(), 9), fg=Neutral.TEXT_3, bg=Neutral.BG_PANEL)
        self._title_hint.grid(row=1, column=1, sticky="w")

        # 分类
        self._add_label(form, "分类", 2)
        self.var_category = tk.StringVar(value="1")
        # 单选改 2 列排布, 4 个一行约 356px, 窄窗下同样会被裁
        cat_frame = tk.Frame(form, bg=Neutral.BG_PANEL)
        cat_frame.grid(row=2, column=1, sticky="w", pady=4)
        for i, (val, label) in enumerate(CATEGORIES):
            ttk.Radiobutton(
                cat_frame, text=label, value=val, variable=self.var_category,
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12), pady=1)

        # 联系方式
        self._add_label(form, "联系方式 (≤50 字, 可选)", 3)
        self.var_contact = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_contact, font=(UIFont.family(), 10)).grid(
            row=3, column=1, sticky="ew", pady=4,
        )

        # 内容
        self._add_label(form, "问题描述 * (5-5000 字)", 4)
        text_frame = tk.Frame(form, bg=Neutral.BG_PANEL)
        text_frame.grid(row=4, column=1, sticky="ew", pady=4)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.text_content = tk.Text(
            text_frame, height=6, font=(UIFont.family(), 10),
            wrap="word", relief="solid", bd=1, padx=6, pady=6,
        )
        self.text_content.grid(row=0, column=0, sticky="nsew")
        text_sb = ttk.Scrollbar(text_frame, orient="vertical", command=self.text_content.yview)
        text_sb.grid(row=0, column=1, sticky="ns")
        self.text_content.configure(yscrollcommand=text_sb.set)
        self._content_hint = tk.Label(form, text="0 / 5000", font=(UIFont.family(), 9), fg=Neutral.TEXT_3, bg=Neutral.BG_PANEL)
        self._content_hint.grid(row=5, column=1, sticky="e")
        self.text_content.bind("<KeyRelease>", lambda e: self._update_content_hint())
        self.var_title.trace_add("write", lambda *_: self._update_title_hint())

        # 截图区
        self._build_screenshot_section(form, row=6)

        # 自检区 (折叠)
        self._build_diagnostics_section(form, row=7)

        # 底部按钮
        footer = tk.Frame(self.dialog, bg=Neutral.BG_SUBTLE, height=60)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Label(
            footer, text="* 必填项", font=(UIFont.family(), 9),
            fg=Neutral.TEXT_3, bg=Neutral.BG_SUBTLE,
        ).pack(side="left", padx=20)
        # 平台参数设置入口 (app_key/专属链接, 存本地数据库)
        create_secondary_button(
            footer, "平台设置", self._on_open_settings, width=10,
        ).pack(side="left", padx=4)
        create_secondary_button(footer, "取消", self._on_cancel).pack(side="right", padx=(0, 20), pady=12)
        self.btn_submit = create_primary_button(footer, "提交反馈", self._on_submit)
        self.btn_submit.pack(side="right", padx=(0, 8), pady=12)

        # 全局快捷键: Ctrl+V 粘贴图片
        # 原 bind_all("<Control-v>") 挂在应用级 all 上, 关闭本窗口后不消失,
        # 在别的界面按 Ctrl+V 仍会触发已销毁的回调。改绑到 dialog 自身。
        self.dialog.bind("<Control-v>", lambda e: self._on_paste_clipboard())

    def _add_label(self, parent, text, row):
        tk.Label(
            parent, text=text, font=(UIFont.family(), 10, "bold"),
            fg=Neutral.TEXT_1, bg=Neutral.BG_PANEL, anchor="w",
        ).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=(8, 0))

    # ==================== 截图区 ====================

    def _build_screenshot_section(self, parent, row):
        tk.Label(
            parent, text=f"截图 (0/{FEEDBACK_MAX_IMAGES}, 粘贴 / 截屏 / 上传)",
            font=(UIFont.family(), 10, "bold"),
            fg=Neutral.TEXT_1, bg=Neutral.BG_PANEL, anchor="w",
        ).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=(12, 0))

        wrap = tk.Frame(parent, bg=Neutral.BG_PANEL)
        wrap.grid(row=row, column=1, sticky="ew", pady=(12, 0))
        wrap.columnconfigure(0, weight=1)

        # 按钮区 (改 2x2 排布, 一排 4 个约 445px, 窄窗下列宽不足会把"粘贴"按钮挤出可视区)
        btn_grid = tk.Frame(wrap, bg=Neutral.BG_PANEL)
        btn_grid.grid(row=0, column=0, sticky="w")
        create_secondary_button(btn_grid, "截当前窗口", self._on_capture_window).grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")
        create_secondary_button(btn_grid, "全屏截屏", self._on_capture_screen).grid(row=0, column=1, padx=6, pady=2, sticky="w")
        create_secondary_button(btn_grid, "粘贴 (Ctrl+V)", self._on_paste_clipboard).grid(row=1, column=0, padx=(0, 6), pady=2, sticky="w")
        create_secondary_button(btn_grid, "上传图片", self._on_upload_file).grid(row=1, column=1, padx=6, pady=2, sticky="w")

        # 缩略图列表
        self._thumbs_frame = tk.Frame(wrap, bg=Neutral.BG_PANEL, height=88)
        self._thumbs_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._thumbs_frame.columnconfigure(0, weight=1)
        self._empty_label = tk.Label(
            self._thumbs_frame, text="暂无截图, 截屏或粘贴图片添加 (支持 Ctrl+V)",
            font=(UIFont.family(), 9), fg=Neutral.TEXT_3, bg=Neutral.BG_PANEL,
        )
        self._empty_label.grid(row=0, column=0)

    def _on_capture_window(self):
        self._capture_hidden(capture_active_window)

    def _on_capture_screen(self):
        self._capture_hidden(capture_screen)

    def _capture_hidden(self, capture_fn):
        """截图前先把反馈窗藏起来 (否则截到的就是反馈窗自己),
        截完恢复。藏窗期间临时释放 grab, 避免 withdraw 后事件被卡。"""
        if len(self._images) >= FEEDBACK_MAX_IMAGES:
            notify(self.dialog, "warning", f"已达上限 {FEEDBACK_MAX_IMAGES} 张"); return
        try:
            self.dialog.grab_release()
        except Exception:
            pass
        self.dialog.withdraw()
        self.dialog.update_idletasks()
        self.dialog.update()

        def _do():
            # ⚠ 350ms 里用户可能已关窗 (withdraw 后 Alt+F4 / 程序化关闭):
            #   不校验存活就往已销毁控件写 (恢复窗口 / 加缩略图 / 弹父窗)
            #   → TclError, 与 _DialogGuard 的教训相同。首行先判存活。
            if not self._valid():
                return
            png = None
            err = None
            try:
                png = capture_fn()
            except Exception as e:
                err = e
            # 无论成败先恢复窗口
            self._restore_after_capture()
            if err is not None:
                messagebox.showerror("截屏失败", str(err), parent=self.dialog)
                return
            if png:
                self._add_image(png)

        # 给系统 ~350ms 把窗口真正从屏幕上抹掉再截
        self.dialog.after(350, _do)

    def _restore_after_capture(self):
        try:
            self.dialog.deiconify()
            self.dialog.lift()
            self.dialog.focus_set()
            self.dialog.grab_set()
        except Exception:
            pass

    def _on_paste_clipboard(self):
        if len(self._images) >= FEEDBACK_MAX_IMAGES:
            notify(self.dialog, "warning", f"已达上限 {FEEDBACK_MAX_IMAGES} 张"); return
        try:
            png = capture_clipboard_image()
            if png is None:
                notify(self.dialog, "info", "剪贴板没有图片")
                return
            self._add_image(png)
        except Exception as e:
            messagebox.showerror("粘贴失败", str(e), parent=self.dialog)

    def _on_upload_file(self):
        if len(self._images) >= FEEDBACK_MAX_IMAGES:
            notify(self.dialog, "warning", f"已达上限 {FEEDBACK_MAX_IMAGES} 张"); return
        paths = filedialog.askopenfilenames(
            parent=self.dialog,
            title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")],
        )
        for p in paths:
            if len(self._images) >= FEEDBACK_MAX_IMAGES:
                break
            try:
                with open(p, "rb") as f:
                    data = f.read()
                if len(data) > FEEDBACK_MAX_IMAGE_BYTES:
                    notify(self.dialog, "warning", f"{Path(p).name} 超 5MB, 已跳过")
                    continue
                # 重新编码为 PNG 统一格式
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                self._add_image(buf.getvalue())
            except Exception as e:
                messagebox.showerror("上传失败", f"{Path(p).name}: {e}", parent=self.dialog)

    def _add_image(self, png_bytes: bytes):
        if len(png_bytes) > FEEDBACK_MAX_IMAGE_BYTES:
            notify(self.dialog, "warning", f"图片超 5MB ({len(png_bytes)} bytes)"); return
        self._images.append(png_bytes)
        self._render_thumbs()

    def _remove_image(self, idx: int):
        if 0 <= idx < len(self._images):
            self._images.pop(idx)
            self._render_thumbs()

    def _render_thumbs(self):
        # 清空
        for w in self._thumbs_frame.winfo_children():
            w.destroy()
        self._thumbs = []
        if not self._images:
            self._empty_label = tk.Label(
                self._thumbs_frame, text="暂无截图, 截屏或粘贴图片添加 (支持 Ctrl+V)",
                font=(UIFont.family(), 9), fg=Neutral.TEXT_3, bg=Neutral.BG_PANEL,
            )
            self._empty_label.grid(row=0, column=0)
            # 同步标签
            for child in self._body.winfo_children():
                pass
            return
        # 重建缩略图
        for i, png in enumerate(self._images):
            try:
                img = Image.open(io.BytesIO(png))
                img.thumbnail((120, 80))
                tk_img = ImageTk.PhotoImage(img)
                self._thumbs.append(tk_img)
            except Exception:
                continue
        # 网格显示 (横向 scroll 简化: 用 frame 装)
        row = 0
        col = 0
        for i, tk_img in enumerate(self._thumbs):
            cell = tk.Frame(self._thumbs_frame, bg=Neutral.BG_SUBTLE, bd=1, relief="solid")
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nw")
            tk.Label(cell, image=tk_img, bg=Neutral.BG_SUBTLE).grid(row=0, column=0, padx=2, pady=2)
            tk.Button(
                cell, text="×", font=(UIFont.family(), 8),
                command=lambda idx=i: self._remove_image(idx),
                bg=Status.DANGER, fg=Neutral.TEXT_INV, bd=0, padx=4,
            ).grid(row=0, column=0, sticky="ne", padx=2, pady=2)
            tk.Label(
                cell, text=f"#{i+1} {len(self._images[i])//1024}KB",
                font=(UIFont.family(), 8), fg=Neutral.TEXT_3, bg=Neutral.BG_SUBTLE,
            ).grid(row=1, column=0)
            col += 1
            if col >= 4:
                col = 0
                row += 1
        # 同步截图数量标签
        for child in self._body.winfo_children():
            pass
        # 更新顶部 label
        for w in self._body.grid_slaves(row=6, column=0):
            if w.winfo_class() == "Label":
                w.configure(text=f"截图 ({len(self._images)}/{FEEDBACK_MAX_IMAGES}, 粘贴 / 截屏 / 上传)")

    # ==================== 自检区 ====================

    def _build_diagnostics_section(self, parent, row):
        tk.Label(
            parent, text="自检 (一键收集, 随反馈一起提交)",
            font=(UIFont.family(), 10, "bold"),
            fg=Neutral.TEXT_1, bg=Neutral.BG_PANEL, anchor="w",
        ).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=(12, 0))

        wrap = tk.Frame(parent, bg=Neutral.BG_PANEL, bd=1, relief="solid", highlightthickness=1, highlightbackground=Neutral.BORDER)
        wrap.grid(row=row, column=1, sticky="ew", pady=(12, 0))

        btn_row = tk.Frame(wrap, bg=Neutral.BG_PANEL)
        btn_row.pack(fill="x", padx=8, pady=8)
        create_secondary_button(btn_row, "开始自检", self._on_run_diagnostics).pack(side="left")
        create_secondary_button(btn_row, "F12 取浏览器日志说明", self._on_browser_log_help).pack(side="left", padx=(8, 0))
        self._diag_status = tk.Label(btn_row, text="未运行", font=(UIFont.family(), 9), fg=Neutral.TEXT_3, bg=Neutral.BG_PANEL)
        self._diag_status.pack(side="right")

        # 结果区
        # ⚠ 旧版 bg="#1E293B" (深蓝灰) + fg=Neutral.TEXT_1 (#11142E 深墨)
        #    两个深色几乎同色 → 自检结果整块看不清。改浅底 + 深字。
        self._diag_text = tk.Text(
            wrap, height=8, font=UIFont.mono(9),
            bg=Neutral.BG_SUBTLE, fg=Neutral.TEXT_1, wrap="none",
            relief="flat", padx=8, pady=8, state="disabled",
        )
        self._diag_text.pack(fill="x", padx=8, pady=(0, 8))
        # wrap="none" 时长行 (ARN / 路径) 看不到尾部, 必须配横向滚动条
        self._diag_sb_x = ttk.Scrollbar(
            wrap, orient="horizontal", command=self._diag_text.xview,
        )
        self._diag_sb_x.pack(fill="x", padx=8, pady=(0, 8))
        self._diag_text.configure(xscrollcommand=self._diag_sb_x.set)

    def _on_run_diagnostics(self):
        self._diag_status.configure(text="采集中…", fg=Brand.PRIMARY)
        self.dialog.update_idletasks()
        try:
            cfg = load_feedback_config()
            self._diagnostics = collect_diagnostics(
                ping_target=cfg.get("ping_target", "https://www.baidu.com"),
                eventlog_hours=cfg.get("eventlog_hours", 1),
                app_log_tail=cfg.get("app_log_tail", 200),
                service_names=cfg.get("service_names", []),
            )
            self._online = self._diagnostics.get("online", False)
            self._refresh_online_status()
            self._render_diagnostics()
            self._diag_status.configure(
                text="已完成" if self._online else "无法连接反馈平台 · 走离线打包",
                fg=Status.SUCCESS if self._online else Status.DANGER,
            )
        except Exception as e:
            self._diag_status.configure(text=f"失败: {e}", fg=Status.DANGER)

    def _render_diagnostics(self):
        d = self._diagnostics or {}
        lines = [
            f"联网: {'可联网' if d.get('online') else '不可联网'}",
            f"平台: {d.get('process', {}).get('platform', '?')}",
            f"Python: {d.get('process', {}).get('python_version', '?')}",
            f"进程 PID: {d.get('process', {}).get('pid', '?')}",
        ]
        svcs = d.get("services", [])
        if svcs:
            lines.append("── 服务状态 ──")
            for s in svcs:
                lines.append(f"  {s.get('name')}: {s.get('status')}")
        ev = d.get("eventlog", [])
        if ev:
            lines.append(f"── Windows Event Log (最近 1h, {len(ev)} 条) ──")
            for e in ev[:10]:
                lines.append(f"  [{e.get('level', '?')}] {e.get('time_created', '?')} {e.get('source', '?')} ID={e.get('event_id', '?')}")
                msg = e.get("message", "")
                if msg:
                    lines.append(f"    {msg[:200]}")
            if len(ev) > 10:
                lines.append(f"  ... 还有 {len(ev)-10} 条 (打包时全量保存)")
        else:
            lines.append("── Windows Event Log: 0 条 / 非 Windows 平台 ──")
        ap = d.get("app_log", "")
        if ap:
            lines.append(f"── 应用日志 (尾部, {ap.count(chr(10))} 行) ──")
            for ln in ap.splitlines()[-15:]:
                lines.append(f"  {ln[:200]}")
        self._set_text_widget(self._diag_text, "\n".join(lines))

    def _set_text_widget(self, w, text):
        w.configure(state="normal")
        w.delete("1.0", "end")
        w.insert("1.0", text)
        w.configure(state="disabled")

    def _on_browser_log_help(self):
        from ..windows.browser_log_help_dialog import BrowserLogHelpDialog
        BrowserLogHelpDialog(self.dialog)

    # ==================== 联网状态 ====================

    def _refresh_online_status(self):
        cfg = load_feedback_config()
        if is_placeholder_config(cfg):
            self._online_label.configure(
                text="占位配置 - 走离线",
                bg=Status.WARNING, fg=Neutral.TEXT_INV,
            )
            return
        # 试连
        try:
            ok = check_internet(cfg["api_base"] + "/api/apps.php?app_key=" + cfg["app_key"], timeout=3)
        except Exception:
            ok = False
        self._online = ok
        if ok:
            self._online_label.configure(text="已联网", bg=Status.SUCCESS, fg=Neutral.TEXT_INV)
        else:
            self._online_label.configure(text="无法连接反馈平台", bg=Status.DANGER, fg=Neutral.TEXT_INV)

    # ==================== 提交 ====================

    def _build_submit_manifest(self, payload: "FeedbackPayload") -> str:
        """生成「将发送内容清单」供提交前确认 (D29, 借鉴 r2 一键报障的隐私设计)

        用户过目后才真正外发: 标题 / 分类 / 联系方式 / 正文长度 /
        截图张数与体积 / 日志是否随包 (已脱敏) / 设备信息, 全部列明。
        """
        lines = ["即将发送以下内容, 请确认:", ""]
        lines.append(f"· 标题: {payload.title}")
        lines.append(f"· 分类: {getattr(payload, 'category', 1)}")
        lines.append(f"· 联系方式: {payload.contact or '(未留)'}")
        lines.append(f"· 正文: {len(payload.content)} 字")
        img_total = sum(len(b) for b in payload.images)
        lines.append(
            f"· 截图: {len(payload.images)} 张 (共 {img_total // 1024} KB)"
            if payload.images else "· 截图: 无"
        )
        diag = self._diagnostics or {}
        if diag.get("app_log"):
            lines.append("· 日志: 附带 app.log (已脱敏, 凭据类信息不会外发)")
        else:
            lines.append("· 日志: 不附带")
        lines.append(f"· 设备信息: {payload.device_info}")
        lines.append("")
        lines.append("确定发送? (取消返回编辑)")
        return "\n".join(lines)

    def _on_submit(self):
        # 校验
        title = self.var_title.get().strip()
        content = self.text_content.get("1.0", "end").strip()
        try:
            category = int(self.var_category.get())
        except ValueError:
            category = 1
        contact = self.var_contact.get().strip()

        payload = FeedbackPayload(
            title=title, content=content, category=category,
            contact=contact, images=list(self._images),
            device_info=f"{APP_VERSION} / {platform.platform()} / Python {platform.python_version()}",
        )
        errs = payload.validate()
        if errs:
            messagebox.showwarning("校验失败", "\n".join(errs), parent=self.dialog)
            return

        # D29: 提交前过目清单 (外发内容透明化, 用户确认才发)
        if not messagebox.askyesno(
            "确认发送", self._build_submit_manifest(payload), parent=self.dialog,
        ):
            return

        # 提交 (异步避免阻塞 UI)
        self.btn_submit.configure(state="disabled", text="提交中…")
        bridge = get_bridge(self.dialog)

        def worker():
            # ⚠ worker 线程: 只跑网络/打包 + 投递队列, 不碰 Tk
            try:
                # 重新跑一次自检保证新鲜
                if self._diagnostics is None:
                    cfg = load_feedback_config()
                    self._diagnostics = collect_diagnostics(
                        ping_target=cfg.get("ping_target", "https://www.baidu.com"),
                    )
                result = submit_smart(payload, diagnostics=self._diagnostics)
                bridge.post(self._on_submit_done, result)
            except Exception as e:
                bridge.post(self._on_submit_done, {"ok": False, "msg": str(e)})

        bridge.submit(worker, task_name="提交反馈")

    def _on_submit_done(self, result: Dict):
        # ⚠ 窗口已关闭: 提交其实已经完成, 但结果必须送达用户
        if not self._valid():
            ok = result.get("ok")
            mode = result.get("mode")
            msg = result.get("msg", "")
            if ok and mode == "online":
                self._report_after_close("反馈已提交", [
                    f"反馈已提交 (id={result.get('id', '?')}) — 窗口已关闭",
                ])
            elif ok and mode == "offline":
                self._report_after_close("反馈已打包", [
                    f"离线包: {result.get('path', '')} — 窗口已关闭",
                ])
            else:
                self._report_after_close("反馈提交失败", [str(msg)])
            if ok and self._on_success:
                try:
                    self._on_success(result)
                except Exception:
                    pass
            return

        self.btn_submit.configure(state="normal", text="提交反馈")
        ok = result.get("ok")
        mode = result.get("mode")
        msg = result.get("msg", "")
        if ok:
            if mode == "online":
                fid = result.get("id", "?")
                notify(self.dialog, "success", f"已提交 (id={fid})")
                messagebox.showinfo("提交成功", f"反馈已提交 (id={fid})\n感谢您的支持!", parent=self.dialog)
                if self._on_success:
                    self._on_success(result)
                self.dialog.destroy()
            elif mode == "offline":
                path = result.get("path", "")
                size_kb = result.get("size", 0) // 1024
                messagebox.showinfo(
                    "已打包 (离线模式)",
                    f"无法连接反馈服务器, 已打包到:\n{path}\n\n大小: {size_kb} KB\n\n请将这个文件发给系统管理员, 由运营人员后台导入。",
                    parent=self.dialog,
                )
                if self._on_success:
                    self._on_success(result)
                self.dialog.destroy()
            else:
                # ok=True 但 mode 既非 online 也非 offline: 旧版既不关窗也不提示,
                # 用户看到按钮恢复成"提交反馈"却不知道成没成 —— 只能再点一次。
                mode_text = f"{mode!r}" if mode else "(缺失)"
                messagebox.showwarning(
                    "提交完成 (模式未知)",
                    f"反馈已提交, 但返回的模式无法识别: {mode_text}\n\n"
                    f"服务器返回: {msg or '(无消息)'}\n\n"
                    "请把上面的信息反馈给系统管理员, 确认反馈是否已入库。",
                    parent=self.dialog,
                )
                if self._on_success:
                    self._on_success(result)
        else:
            messagebox.showerror("提交失败", msg, parent=self.dialog)

    def _on_cancel(self):
        self.dialog.destroy()

    def _on_open_settings(self):
        """打开反馈平台设置 (), 保存后刷新联网状态"""
        from ..windows.feedback_settings_dialog import FeedbackSettingsDialog
        FeedbackSettingsDialog(self.dialog, on_saved=self._refresh_online_status)

    # ==================== 字数提示 ====================

    def _update_content_hint(self):
        n = len(self.text_content.get("1.0", "end-1c"))
        self._content_hint.configure(
            text=f"{n} / 5000",
            fg=Status.DANGER if n > 5000 else (Status.WARNING if n < 5 else Neutral.TEXT_3),
        )

    def _update_title_hint(self):
        n = len(self.var_title.get())
        self._title_hint.configure(
            text=f"{n} / 100",
            fg=Status.DANGER if n > 100 or n < 2 else Neutral.TEXT_3,
        )


# ==================== Path 兜底 (用过的导入但避免 import 循环) ====================
from pathlib import Path
