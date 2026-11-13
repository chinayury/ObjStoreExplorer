# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""一键创建对话框 - 创建桶 → 创建用户 → 创建策略 → 附加

拆分:
  - 本文件新增 CreateUserDialog (仅创建用户 AK/SK), 用户管理页
    "创建用户" 按钮用它; 顶栏「一键创建」仍用 OneClickSetupDialog
    (桶+用户+策略+附加 4 步), 两个入口互不影响。
    (早期版本 期间 CreateUserDialog 只是 OneClickSetupDialog 的别名,
    用户反馈"用户管理里只想建个用户, 不想走整套")

修复 (用户反馈: 填完点确定没反应, 无法创建):
  - 根因: _on_create 调 admin_manager.create_full_setup() 传了 auth_bucket=,
    而 manager 侧签名没有该参数 → 每次确认都 TypeError, 创建从未执行。
    修法: create_full_setup 增加 auth_bucket 参数 (授权桶), 新桶名留空时
    对已有桶建用户+策略; 两者都填时策略授予新桶。
  - _set_busy 改递归遍历子树: 旧版只扫 2 层, footer 按钮在第 3 层
    (footer → btn_frame → button), 从未被禁用到; 且创建中把按钮文案
    改为 "创建中…" 给用户即时反馈。

重写:
  - 改用 grid 布局 (header / flow / body / footer 4 行), 不再用 scrollable canvas。
    之前 scrollable canvas 的 bind 顺序有 bug, canvas <Configure> 触发时
    "body" item 还没建, itemconfig 静默失败, 子 widget width=0 不可见。
  - 默认尺寸 720x780, minsize (640, 720), 内容在小屏可能需滚动, 但 1080p
    及以上不需要滚动。
  - 用 dialog-level <MouseWheel> 绑 (Canvas 内部), 不再 bind_all (污染其他
    dialog 的滚轮事件)。
  - body 内所有字段用 columnconfigure(1, weight=1) 自动拉宽, 跟随 dialog resize。

改进 (已废弃):
  - scrollable canvas 双 bind 模板 (经验证不够, 仍出现 width=0 问题)

历史:
  - 原 create_user_dialog.py 仅创建用户+策略 (2 步)
  - 另写 one_click_setup_dialog.py 做完整 4 步一键创建 (与本文件功能重复)
  - 合并为 OneClickSetupDialog (本类), 删 one_click_setup_dialog.py
  - 彻底重构, 改用 grid 布局
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Optional, Callable

from ..widgets.scrollarea import bind_mousewheel
from ..threading_bridge import get_bridge
from ..styles import Brand, Neutral, Space, UIFont
from ..widgets.buttons import create_primary_button, create_secondary_button
from ..widgets.notifications import notify
from ...utils.icon_manager import get_window_icon
from ...core.admin_manager import generate_strong_password
from ...core.validators import validate_access_key, validate_secret_key
from ...services.service_locator import ServiceLocator


class _DialogGuard:
    """对话框生命周期守卫 (OneClickSetupDialog / CreateUserDialog 共用)

    背景: 用户点"取消"或窗口 X 关掉后, 后台线程仍会把结果投递回来,
    旧代码直接在 `self.dialog.after(...)` 里调 `_on_create_done`, 于是
    对已销毁的 Toplevel 调 clipboard/config → TclError。

    更严重的是: TclError 被 report_callback_exception 吞掉后**用户拿不到
    凭据** —— 一键创建成功了, 但弹窗不出现, 用户以为失败。

    修法:
      1. <Destroy> 绑里置 _closed;
      2. 回调首行 _valid() 判定, 失效就走"落日志/状态栏"路径而不是弹窗;
      3. 所有 Tk 投递改走 threading_bridge (跨线程安全)。
    """

    def _init_guard(self, dialog: tk.Toplevel) -> None:
        self.dialog = dialog
        self._closed = False
        self._after_tokens: List[str] = []
        dialog.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, _event=None) -> None:
        self._closed = True
        for token in self._after_tokens:
            try:
                self.dialog.after_cancel(token)
            except tk.TclError:
                pass
        self._after_tokens.clear()

    def _valid(self) -> bool:
        """回调前置条件: 对话框还活着?"""
        if self._closed:
            return False
        try:
            return bool(self.dialog.winfo_exists())
        except tk.TclError:
            return False

    def _schedule(self, ms: int, fn) -> None:
        """受守卫的 after: 对话框已关则不排"""
        if not self._valid():
            return
        try:
            self._after_tokens.append(self.dialog.after(ms, fn))
        except tk.TclError:
            pass

    def _report_after_close(self, title: str, lines: List[str]) -> None:
        """对话框已关闭时的结果落地: 写日志 + 状态栏 (不弹窗, 弹了也没人看)"""
        text = "\n".join(lines)
        try:
            self.locator.logger.warning(title, "", text[:300])
        except Exception:
            pass
        try:
            main = getattr(self.locator, "_main_window", None)
            if main is not None:
                main.update_status(f"[{title}] {lines[0] if lines else ''} (详情见日志)")
        except Exception:
            pass


class OneClickSetupDialog(_DialogGuard):
    """一键创建 桶+用户+策略 (grid 布局 + 异步执行 + 失败回滚)"""

    DEFAULT_SIZE = "720x780"    # 640x720 → 720x780 (适配 grid 内容)
    MIN_SIZE = (640, 720)       # 防止拖太小字段看不见

    def __init__(
        self,
        parent: tk.Misc,
        locator: ServiceLocator,
        on_success: Optional[Callable] = None,
    ):
        self.parent = parent
        self.locator = locator
        self._on_success = on_success

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("一键创建 - 桶 + 用户 + 策略")
        self._init_guard(self.dialog)
        # 按屏幕自适应: 固定 780 高在 1366x768 笔记本上底部按钮直接跑到
        # 屏幕外 (任务栏之下), 底部"取消/一键创建"点不到。
        sw = self.dialog.winfo_screenwidth()
        sh = self.dialog.winfo_screenheight()
        self._fit_h = min(780, max(560, sh - 110))
        self._fit_w = min(720, max(560, sw - 80))
        self.dialog.geometry(
            f"{self._fit_w}x{self._fit_h}"
            f"+{max(0, (sw - self._fit_w) // 2)}+{max(0, (sh - self._fit_h) // 4)}"
        )
        self.dialog.minsize(min(640, self._fit_w), min(560, self._fit_h))
        self.dialog.resizable(True, True)
        self.dialog.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self.dialog.grab_set()

        # ===== 关键: 顶层 4 行 grid =====
        # row 0: header (固定高)
        # row 1: flow   (固定高)
        # row 0: header  (固定 64)
        # row 1: 发丝线
        # row 2: flow    (固定 32)
        # row 3: 发丝线
        # row 4: body    (扩展, 滚动)
        # row 5: 发丝线
        # row 6: footer  (固定)
        self.dialog.columnconfigure(0, weight=1)
        self.dialog.rowconfigure(0, minsize=64)   # header
        self.dialog.rowconfigure(1, minsize=1)    # 分隔线
        self.dialog.rowconfigure(2, minsize=32)   # flow
        self.dialog.rowconfigure(3, minsize=1)    # 分隔线
        self.dialog.rowconfigure(4, weight=1)     # body (扩)
        self.dialog.rowconfigure(5, minsize=1)    # 分隔线
        self.dialog.rowconfigure(6, minsize=58)   # footer

        self._set_icon()
        self._create_header()
        self._create_flow()
        self._create_body()
        self._create_footer()
        self._load_buckets()

    def _set_icon(self) -> None:
        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconbitmap(icon)
        except Exception:
            pass

    # ==================== 头部 (固定, 不滚动) ====================
    def _create_header(self) -> None:
        from ...utils.icons import get as get_icon

        header = tk.Frame(self.dialog, bg=Neutral.BG_PANEL, height=64)
        header.grid(row=0, column=0, sticky="nsew")
        header.pack_propagate(False)

        chip = tk.Frame(header, bg=Brand.PRIMARY_50, width=36, height=36)
        chip.pack(side=tk.LEFT, padx=(Space.LG, Space.MD), pady=Space.MD)
        chip.pack_propagate(False)
        img = get_icon("zap", 24, tint=Brand.PRIMARY)
        if img is not None:
            lbl = tk.Label(chip, image=img, bg=Brand.PRIMARY_50)
            lbl.image = img
            lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        col = tk.Frame(header, bg=Neutral.BG_PANEL)
        col.pack(side=tk.LEFT, fill=tk.Y, pady=Space.MD)
        tk.Label(
            col, text="ONE-CLICK SETUP", font=UIFont.kicker(),
            bg=Neutral.BG_PANEL, fg=Brand.PRIMARY,
        ).pack(anchor=tk.W)
        tk.Label(
            col, text="一键创建整套", font=UIFont.h2(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
        ).pack(anchor=tk.W)

        tk.Frame(self.dialog, bg=Neutral.BORDER, height=1).grid(row=1, column=0, sticky="ew")

    # ==================== 流程指示条 (固定) ====================
    def _create_flow(self) -> None:
        flow = tk.Frame(self.dialog, bg=Brand.PRIMARY_50)
        flow.grid(row=2, column=0, sticky="nsew")
        flow.pack_propagate(False)
        for i, s in enumerate(("选桶", "用户", "策略", "附加")):
            tk.Label(
                flow, text=f"{i + 1}. {s}", font=UIFont.body_sm(),
                bg=Brand.PRIMARY_50, fg=Brand.PRIMARY_800,
            ).pack(side=tk.LEFT, padx=20, pady=7)
            if i < 3:
                tk.Label(
                    flow, text="›", font=UIFont.body(),
                    bg=Brand.PRIMARY_50, fg=Brand.PRIMARY_300,
                ).pack(side=tk.LEFT)
        tk.Frame(self.dialog, bg=Neutral.BORDER, height=1).grid(row=3, column=0, sticky="ew")

    # ==================== 主体 (scrollable canvas) ====================
    def _create_body(self) -> None:
        """关键修复: create_window 必须先于 bind <Configure>"""
        body_outer = tk.Frame(self.dialog, bg=Neutral.BG_PANEL)
        body_outer.grid(row=4, column=0, sticky="nsew", padx=0, pady=0)

        # 滚动 canvas
        canvas = tk.Canvas(body_outer, highlightthickness=0, bg=Neutral.BG_PANEL)
        vsb = ttk.Scrollbar(body_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        # 内部 frame (真正放表单的)
        self._scroll_frame = tk.Frame(canvas, bg=Neutral.BG_PANEL)

        # 关键修复 #1: 先 create_window, 再 bind <Configure>。
        # 否则 canvas 第一次配置时 "body" item 还不存在, itemconfig 静默失败,
        # 子 widget 全部 width=0 不可见 (的 bug)。
        self._scroll_window_id = canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw",
        )

        # 关键修复 #2: scrollregion 跟随内部 frame 高度
        self._scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        # 关键修复 #3: canvas 配置时同步 _scroll_frame 宽度
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._scroll_window_id, width=e.width),
        )

        # 关键修复 #4: 鼠标滚轮绑到**控件**上, 不再 bind_all。
        # 修正: 注释声称已改, 但下面代码其实仍是 bind_all/unbind_all ——
        # 弹窗直接关闭时 <Leave> 不会触发, all 上残留悬空 handler 引用已销毁的 canvas。
        bind_mousewheel(canvas, self._scroll_frame)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas = canvas

        # 内部 frame 列配置: col 0 = label, col 1 = 输入
        self._scroll_frame.columnconfigure(0, minsize=120)
        self._scroll_frame.columnconfigure(1, weight=1, minsize=240)
        content = self._scroll_frame

        # ===== 桶名 (新桶) =====
        tk.Label(
            content, text="新桶名:",
            font=UIFont.body(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            anchor=tk.W,
        ).grid(row=0, column=0, sticky=tk.W, padx=(20, 8), pady=(20, 8))
        self.bucket_var = tk.StringVar()
        self.bucket_entry = tk.Entry(
            content, textvariable=self.bucket_var, font=UIFont.body(),
            bg=Neutral.BG_APP, relief="solid", bd=1,
        )
        self.bucket_entry.grid(row=0, column=1, sticky=tk.EW, padx=(0, 20), pady=(20, 8))
        tk.Label(
            content, text="(留空表示不创建新桶, 只为现有桶创建用户)",
            font=UIFont.body_sm(), fg=Neutral.TEXT_2, bg=Neutral.BG_PANEL,
        ).grid(row=1, column=1, sticky=tk.W, padx=(0, 20))

        # ===== Access Key =====
        tk.Label(
            content, text="Access Key:",
            font=UIFont.body(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            anchor=tk.W,
        ).grid(row=2, column=0, sticky=tk.W, padx=(20, 8), pady=(12, 8))
        self.ak_var = tk.StringVar()
        self.ak_entry = tk.Entry(
            content, textvariable=self.ak_var, font=UIFont.body(),
            bg=Neutral.BG_APP, relief="solid", bd=1,
        )
        self.ak_entry.grid(row=2, column=1, sticky=tk.EW, padx=(0, 20), pady=(12, 8))

        # ===== Secret Key + 自动生成 + 复制 =====
        tk.Label(
            content, text="Secret Key:",
            font=UIFont.body(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            anchor=tk.W,
        ).grid(row=3, column=0, sticky=tk.W, padx=(20, 8), pady=(8, 4))
        self.sk_var = tk.StringVar()
        self.sk_entry = tk.Entry(
            content, textvariable=self.sk_var, font=UIFont.body(),
            bg=Neutral.BG_APP, relief="solid", bd=1, show="*",
        )
        self.sk_entry.grid(row=3, column=1, sticky=tk.EW, padx=(0, 20), pady=(8, 4))
        gen_row = tk.Frame(content, bg=Neutral.BG_PANEL)
        gen_row.grid(row=4, column=1, sticky=tk.W, padx=(0, 20), pady=(0, 8))
        tk.Button(
            gen_row, text="自动生成强密码",
            font=UIFont.body_sm(), bg=Brand.PRIMARY_LIGHT,
            fg=Brand.PRIMARY, relief="flat", cursor="hand2",
            padx=12, pady=4, command=self._on_generate_password,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            gen_row, text="复制",
            font=UIFont.body_sm(), bg=Neutral.BG_APP,
            fg=Neutral.TEXT_1, relief="flat", cursor="hand2",
            padx=12, pady=4, command=self._on_copy_password,
        ).pack(side=tk.LEFT)

        # ===== 授权桶 (下拉, 已有桶列表) =====
        tk.Label(
            content, text="授权桶:",
            font=UIFont.body(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            anchor=tk.W,
        ).grid(row=5, column=0, sticky=tk.W, padx=(20, 8), pady=(12, 8))
        self.auth_bucket_var = tk.StringVar()
        self.bucket_combo = ttk.Combobox(
            content, textvariable=self.auth_bucket_var,
            state="readonly", font=UIFont.body(),
        )
        self.bucket_combo.grid(row=5, column=1, sticky=tk.EW, padx=(0, 20), pady=(12, 8))

        # ===== 权限类型 (3 个 radio) =====
        tk.Label(
            content, text="权限类型:",
            font=UIFont.body(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            anchor=tk.NW,
        ).grid(row=6, column=0, sticky=tk.NW, padx=(20, 8), pady=(12, 8))
        self.policy_var = tk.StringVar(value="readwrite")
        policy_frame = tk.Frame(content, bg=Neutral.BG_PANEL)
        policy_frame.grid(row=6, column=1, sticky=tk.W, padx=(0, 20), pady=(12, 8))
        for value, label in [
            ("readonly",  "只读 (查看/下载)"),
            ("readwrite", "读写 (上传/下载/删除) - 推荐"),
            ("full",      "完全控制"),
        ]:
            tk.Radiobutton(
                policy_frame, text=label, variable=self.policy_var,
                value=value, font=UIFont.body(),
                bg=Neutral.BG_PANEL, anchor=tk.W,
            ).pack(anchor=tk.W, pady=2)

        # ===== 流程提示 =====
        tk.Label(
            content, text="执行流程 (任一步失败自动回滚):",
            font=UIFont.body(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            anchor=tk.W,
        ).grid(row=7, column=0, sticky=tk.NW, padx=(20, 8), pady=(16, 4))
        tk.Label(
            content, text=(
                "  1. 创建桶 (如果填写了新桶名)\n"
                "  2. 创建用户 + 生成密码\n"
                "  3. 创建策略 (<桶名>-<权限>-policy)\n"
                "  4. 附加策略到用户\n\n"
                "凭据 (Access Key + Secret Key) 会在成功后自动复制到剪贴板"
            ),
            font=UIFont.body_sm(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
            justify=tk.LEFT, anchor=tk.W,
        ).grid(row=7, column=1, sticky=tk.W, padx=(0, 20), pady=(16, 4))

    # ==================== 底部 (固定, 不滚动) ====================
    def _create_footer(self) -> None:
        tk.Frame(self.dialog, bg=Neutral.BORDER, height=1).grid(row=5, column=0, sticky="ew")
        footer = tk.Frame(self.dialog, bg=Neutral.BG_SUBTLE)
        footer.grid(row=6, column=0, sticky="nsew")
        footer.pack_propagate(False)
        btn_frame = tk.Frame(footer, bg=Neutral.BG_SUBTLE)
        btn_frame.pack(padx=Space.LG, pady=Space.MD, side=tk.RIGHT)
        create_secondary_button(
            btn_frame, "取消", self.dialog.destroy,
        ).pack(side=tk.LEFT, padx=Space.XS)
        self._create_btn = create_primary_button(
            btn_frame, "一键创建", self._on_create, icon="zap",
        )
        self._create_btn.pack(side=tk.LEFT, padx=Space.XS)

    # ==================== 数据加载 ====================

    def _load_buckets(self) -> None:
        """加载已有桶列表到授权桶下拉"""
        try:
            ok, buckets = self.locator.bucket_manager.list_buckets()
            if ok and buckets:
                self.bucket_combo["values"] = buckets
                self.auth_bucket_var.set(buckets[0])
        except Exception:
            pass

    # ==================== 按钮事件 ====================

    def _on_generate_password(self) -> None:
        pwd = generate_strong_password(16)
        self.sk_var.set(pwd)
        self.sk_entry.config(show="")  # 临时显示
        self._schedule(3000, lambda: self.sk_entry.config(show="*"))

    def _clear_clipboard(self) -> None:
        """30 秒后清空剪贴板里的明文 Secret Key"""
        try:
            self.dialog.clipboard_clear()
        except tk.TclError:
            pass
        if self._valid():
            try:
                notify(self.dialog, "info", "剪贴板中的凭据已自动清空")
            except tk.TclError:
                pass

    def _on_copy_password(self) -> None:
        pwd = self.sk_var.get()
        if not pwd:
            messagebox.showwarning("提示", "请先生成或输入密码", parent=self.dialog)
            return
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(pwd)
        self._schedule(30000, self._clear_clipboard)
        notify(self.dialog, "success", "密码已复制 (30 秒后自动清空)")

    def _on_create(self) -> None:
        new_bucket = self.bucket_var.get().strip()
        ak = self.ak_var.get().strip()
        sk = self.sk_var.get().strip() or generate_strong_password(16)
        auth_bucket = self.auth_bucket_var.get().strip()
        policy_type = self.policy_var.get()

        # 校验
        ok, msg = validate_access_key(ak)
        if not ok:
            messagebox.showerror("参数错误", msg, parent=self.dialog); return
        ok, msg = validate_secret_key(sk)
        if not ok:
            messagebox.showerror("参数错误", msg, parent=self.dialog); return
        if not auth_bucket:
            messagebox.showerror("参数错误", "请选择授权桶", parent=self.dialog); return

        # 确认弹窗 (策略授予的桶: 新桶优先, 没填新桶则授权选中的已有桶)
        target_bucket = new_bucket or auth_bucket
        flow_text = []
        if new_bucket:
            flow_text.append(f"  1. 创建桶: {new_bucket}")
        else:
            flow_text.append(f"  1. 跳过创建桶 (授权已有桶 {auth_bucket})")
        flow_text.append(f"  2. 创建用户: {ak}")
        flow_text.append(f"  3. 创建策略: {target_bucket}-{policy_type}-policy")
        flow_text.append("  4. 附加策略到用户")
        if not messagebox.askyesno(
            "确认一键创建",
            "将执行以下操作 (任一失败自动回滚):\n\n" + "\n".join(flow_text) + "\n\n继续?",
            parent=self.dialog,
        ):
            return

        # 后台异步执行 (避免 UI 卡死)
        self._set_busy(True)
        bridge = get_bridge(self.dialog, logger=self.locator.logger)

        def _bg():
            # ⚠ worker 线程: 只跑 S3 + 投递队列, 绝不碰 Tk
            try:
                result = self.locator.admin_manager.create_full_setup(
                    bucket_name=new_bucket,  # 可空
                    access_key=ak,
                    policy_type=policy_type,
                    secret_key=sk,
                    auth_bucket=auth_bucket,
                )
            except Exception as e:
                bridge.post(
                    self._on_create_done,
                    {"success": False, "error": str(e), "steps": []},
                )
                return
            bridge.post(self._on_create_done, result)

        bridge.submit(_bg, task_name="一键创建")

    def _set_busy(self, busy: bool) -> None:
        """忙状态: 禁用所有按钮防止重复点击

        修复: 旧版只扫 dialog 下 2 层 widget, 而 footer 的按钮在
        btn_frame (第 3 层), 从来没被真正禁用过; 改为递归遍历全部子树。
        """
        state = tk.DISABLED if busy else tk.NORMAL

        def _walk(widget: tk.Misc) -> None:
            for sub in widget.winfo_children():
                if isinstance(sub, tk.Button):
                    try:
                        sub.config(state=state)
                    except Exception:
                        pass
                _walk(sub)

        _walk(self.dialog)
        try:
            self._create_btn.config(text="创建中…" if busy else "一键创建")
        except Exception:
            pass

    def _on_create_done(self, result: dict) -> None:
        # ⚠ 对话框已关闭 (用户点了取消/X): 不碰任何控件, 但结果不能丢 ——
        #   落日志 + 状态栏, 否则用户以为创建失败了。
        if not self._valid():
            if result.get("success"):
                self._report_after_close("一键创建成功", [
                    f"桶 {result.get('bucket_name', '-')} / "
                    f"用户 {result.get('access_key', '-')} 已创建 (窗口已关闭)",
                    f"策略: {result.get('policy_name', '-')}",
                    "凭据请在用户管理页重置密码后重新获取",
                ])
                if self._on_success:
                    try:
                        self._on_success()
                    except Exception:
                        pass
            else:
                self._report_after_close("一键创建失败", [
                    str(result.get("error", "未知错误")),
                ])
            return

        self._set_busy(False)
        if not result.get("success"):
            # 失败: 展示每步详情
            detail = "操作失败:\n\n"
            for step in result.get("steps", []):
                icon = "成功" if step.get("ok") else "失败"
                detail += f"  {icon} {step.get('step', '?')}: {step.get('message', '')}\n"
            detail += f"\n错误: {result.get('error', '未知')}"
            messagebox.showerror("失败", detail, parent=self.dialog)
            try:
                self.locator.logger.error("one_click_setup", "", result.get("error", ""))
            except Exception:
                pass
            return

        # 成功
        steps_text = "\n".join(f"  - {s.get('step', '?')}" for s in result.get("steps", []))
        detail = (
            f"一键创建成功！\n\n{steps_text}\n\n"
            f"桶名: {result.get('bucket_name', '-')}\n"
            f"用户: {result.get('access_key')}\n"
            f"密码: {result.get('secret_key')}\n"
            f"策略: {result.get('policy_name')}\n"
        )
        if result.get("existing_user"):
            detail += "\n(用户已存在, 密码未重置)"

        # 自动复制凭据 (30 秒后自动清空, 避免 SK 长期驻留剪贴板)
        cred = f"{result.get('access_key')}\n{result.get('secret_key')}"
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(cred)
        self._schedule(30000, self._clear_clipboard)
        detail += "\n\n(凭据已自动复制到剪贴板, 30 秒后自动清空)"

        messagebox.showinfo("成功", detail, parent=self.dialog)
        try:
            self.locator.logger.success(
                "one_click_setup", result.get("bucket_name", ""),
                "桶+用户+策略 全部创建完成",
            )
        except Exception:
            pass

        if self._on_success:
            self._on_success()
        self.dialog.destroy()


class CreateUserDialog(_DialogGuard):
    """仅创建用户 (Access Key + Secret Key) — 新增.

    用户管理页的 "创建用户" 入口用本类; 顶栏「一键创建」仍走
    OneClickSetupDialog (桶+用户+策略+附加 4 步), 两者互不影响。
    """

    DEFAULT_SIZE = "460x340"

    def __init__(
        self,
        parent: tk.Misc,
        locator: ServiceLocator,
        on_success: Optional[Callable] = None,
    ):
        self.parent = parent
        self.locator = locator
        self._on_success = on_success

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("创建用户")
        self._init_guard(self.dialog)
        self.dialog.geometry(self.DEFAULT_SIZE)
        self.dialog.resizable(False, False)
        self.dialog.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self.dialog.grab_set()

        self._set_icon()
        self._create_body()
        self._create_footer()

    def _set_icon(self) -> None:
        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconbitmap(icon)
        except Exception:
            pass

    def _create_body(self) -> None:
        body = tk.Frame(self.dialog, bg=Neutral.BG_PANEL)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        tk.Label(
            body, text="创建用户 (仅建账号, 不建桶 / 策略)",
            font=UIFont.h2(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=24, pady=(20, 4))
        tk.Label(
            body, text="需要整套（桶 + 用户 + 策略）请用顶栏的「一键创建」",
            font=UIFont.body_sm(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2,
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=24, pady=(0, 8))

        tk.Label(
            body, text="Access Key:", font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W,
        ).grid(row=2, column=0, sticky=tk.W, padx=(24, 8), pady=8)
        self.ak_var = tk.StringVar()
        self.ak_entry = tk.Entry(
            body, textvariable=self.ak_var, font=UIFont.body(),
            bg=Neutral.BG_APP, relief="solid", bd=1,
        )
        self.ak_entry.grid(row=2, column=1, sticky=tk.EW, padx=(0, 24), pady=8)

        tk.Label(
            body, text="Secret Key:", font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W,
        ).grid(row=3, column=0, sticky=tk.W, padx=(24, 8), pady=(8, 4))
        self.sk_var = tk.StringVar()
        self.sk_entry = tk.Entry(
            body, textvariable=self.sk_var, font=UIFont.body(),
            bg=Neutral.BG_APP, relief="solid", bd=1, show="*",
        )
        self.sk_entry.grid(row=3, column=1, sticky=tk.EW, padx=(0, 24), pady=(8, 4))

        gen_row = tk.Frame(body, bg=Neutral.BG_PANEL)
        gen_row.grid(row=4, column=1, sticky=tk.W, padx=(0, 24), pady=(0, 8))
        tk.Button(
            gen_row, text="自动生成强密码", font=UIFont.body_sm(),
            bg=Brand.PRIMARY_LIGHT, fg=Brand.PRIMARY, relief="flat",
            cursor="hand2", padx=12, pady=4, command=self._on_generate_password,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            gen_row, text="复制", font=UIFont.body_sm(),
            bg=Neutral.BG_APP, fg=Neutral.TEXT_1, relief="flat",
            cursor="hand2", padx=12, pady=4, command=self._on_copy_password,
        ).pack(side=tk.LEFT)

    def _create_footer(self) -> None:
        footer = tk.Frame(self.dialog, bg=Neutral.BG_APP)
        footer.pack(fill="x")
        create_secondary_button(
            footer, "取消", self.dialog.destroy, width=10,
        ).pack(side=tk.RIGHT, padx=(4, 20), pady=14)
        self._create_btn = create_primary_button(
            footer, "创建用户", self._on_create, width=12,
        )
        self._create_btn.pack(side=tk.RIGHT, padx=4, pady=14)

    # ==================== 按钮事件 ====================

    def _on_generate_password(self) -> None:
        self.sk_var.set(generate_strong_password(16))
        self.sk_entry.config(show="")  # 临时显示
        self._schedule(3000, lambda: self.sk_entry.config(show="*"))

    def _clear_clipboard(self) -> None:
        """30 秒后清空剪贴板里的明文 Secret Key"""
        try:
            self.dialog.clipboard_clear()
        except tk.TclError:
            pass
        if self._valid():
            try:
                notify(self.dialog, "info", "剪贴板中的密码已自动清空")
            except tk.TclError:
                pass

    def _on_copy_password(self) -> None:
        pwd = self.sk_var.get()
        if not pwd:
            messagebox.showwarning("提示", "请先生成或输入密码", parent=self.dialog)
            return
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(pwd)
        self._schedule(30000, self._clear_clipboard)
        notify(self.dialog, "success", "密码已复制 (30 秒后自动清空)")

    def _on_create(self) -> None:
        ak = self.ak_var.get().strip()
        sk = self.sk_var.get().strip()
        ok, msg = validate_access_key(ak)
        if not ok:
            messagebox.showerror("参数错误", msg, parent=self.dialog); return
        ok, msg = validate_secret_key(sk)
        if not ok:
            messagebox.showerror("参数错误", msg, parent=self.dialog); return

        # 后台异步执行 (避免 UI 卡死)
        self._set_busy(True)
        bridge = get_bridge(self.dialog, logger=self.locator.logger)

        def _bg():
            # ⚠ worker 线程: 只调 S3 + 投递队列, 不碰 Tk
            try:
                result = self.locator.admin_manager.create_user(ak, sk)
            except Exception as e:
                bridge.post(self._on_create_done, False, str(e))
                return
            bridge.post(self._on_create_done, result[0], result[1])

        bridge.submit(_bg, task_name="创建用户")

    def _set_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL

        def _walk(widget: tk.Misc) -> None:
            for sub in widget.winfo_children():
                if isinstance(sub, tk.Button):
                    try:
                        sub.config(state=state)
                    except Exception:
                        pass
                _walk(sub)

        _walk(self.dialog)
        try:
            self._create_btn.config(text="创建中…" if busy else "创建用户")
        except Exception:
            pass

    def _on_create_done(self, ok: bool, msg: str) -> None:
        # ⚠ 对话框已关闭: 不碰控件, 结果落日志/状态栏 (见 _DialogGuard)
        if not self._valid():
            if ok:
                self._report_after_close("创建用户成功", [
                    f"用户 {self.ak_var.get().strip()} 已创建 (窗口已关闭)",
                ])
                if self._on_success:
                    try:
                        self._on_success()
                    except Exception:
                        pass
            else:
                self._report_after_close("创建用户失败", [msg])
            return

        self._set_busy(False)
        if not ok:
            messagebox.showerror("创建失败", msg, parent=self.dialog)
            try:
                self.locator.logger.error("create_user", self.ak_var.get(), msg)
            except Exception:
                pass
            return
        messagebox.showinfo(
            "创建成功",
            f"用户 {self.ak_var.get().strip()} 已创建。\n\n"
            "Secret Key 已复制到剪贴板, 30 秒后自动清空, 请妥善保存。",
            parent=self.dialog,
        )
        try:
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(self.sk_var.get())
            self._schedule(30000, self._clear_clipboard)
            self.locator.logger.success("create_user", self.ak_var.get().strip(), msg)
        except Exception:
            pass
        if self._on_success:
            self._on_success()
        self.dialog.destroy()
