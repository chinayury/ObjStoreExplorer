# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/windows/sync_dialog - 同步配置 + 预览 + 冲突解决 UI

三个对话框:
  1. SyncDialog  - 主配置 (方向/桶/prefix/本地目录/选项)
  2. SyncPreviewDialog - 预览差异列表
  3. ConflictDialog  - 单个冲突解决 (with Apply to all)

主流程:
  SyncDialog._on_preview() -> compute plan -> SyncPreviewDialog
  SyncPreviewDialog._on_confirm() -> start execute_plan in background
    -> 每个冲突弹 ConflictDialog (主线程)
"""
from __future__ import annotations
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Callable, Optional

from ...services.sync_service import (
    SyncService, Direction, SyncPlan, SyncConflict,
    RESOLVE_USE_LOCAL, RESOLVE_USE_REMOTE, RESOLVE_SKIP, RESOLVE_CANCEL,
)
from ..widgets.scrollarea import bind_mousewheel
from ..threading_bridge import get_bridge
from ..styles import Brand, Neutral, Status, Space, UIFont
from ..widgets.buttons import (
    create_primary_button, create_secondary_button, create_danger_button
)
from ..widgets.notifications import notify
from ...utils.helpers import format_bytes


# ==================== 主对话框 ====================


class SyncDialog(tk.Toplevel):
    """同步配置弹窗"""

    def __init__(self, parent: tk.Misc, locator, default_bucket: str = "",
                 default_prefix: str = ""):
        super().__init__(parent)
        self.locator = locator
        self.title("同步 - 配置")
        self.geometry("560x640")
        self.minsize(520, 560)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.resizable(True, True)

        # 状态变量
        self.direction = tk.StringVar(value="push")
        self.bucket_var = tk.StringVar(value=default_bucket)
        self.prefix_var = tk.StringVar(value=default_prefix)
        self.local_dir_var = tk.StringVar()
        self.recursive_var = tk.BooleanVar(value=True)
        self.delete_source_var = tk.BooleanVar(value=False)
        self.delete_remote_extras_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._refresh_buckets()

        # 居中
        self.update_idletasks()
        x = parent.winfo_toplevel().winfo_rootx() + 50
        y = parent.winfo_toplevel().winfo_rooty() + 50
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        BG = Neutral.BG_PANEL
        TEXT = Neutral.TEXT_1
        SUB = Neutral.TEXT_2
        BORDER = Neutral.BORDER

        self.configure(bg=BG)

        # ===== 底部固定按钮区 (永远可见) =====
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=Space.LG, pady=Space.LG)

        # 1px 顶部分隔线, 视觉上跟 scroll area 区分
        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(side=tk.BOTTOM, fill=tk.X)

        create_secondary_button(
            btn_frame, "取消", self.destroy, width=8,
        ).pack(side=tk.RIGHT, padx=(Space.SM, 0))
        create_primary_button(
            btn_frame, "开始同步", self._on_start_sync, width=10,
        ).pack(side=tk.RIGHT)
        create_secondary_button(
            btn_frame, "预览差异", self._on_preview, width=10,
        ).pack(side=tk.RIGHT, padx=(0, Space.SM))

        # ===== 顶部可滚动内容区 =====
        # ⚠ 滚动条必须是 canvas 的**兄弟**, 挂在 canvas 里 (旧版) 会跟随
        #   canvas 的滚动坐标系被压到内容底下, 看起来"内容被遮住一截"。
        #   参照 create_user_dialog.py 的 body_outer 写法。
        scroll_outer = tk.Frame(self, bg=BG)
        scroll_outer.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(
            scroll_outer, orient=tk.VERTICAL, command=canvas.yview,
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 内容 frame (装所有配置项)
        content = tk.Frame(canvas, bg=BG)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")

        # 滚动区域更新
        content.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        # 内容 frame 宽度跟 canvas 一样 (实现横向 fill)
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(content_window, width=e.width),
        )

        # 鼠标滚轮 (改用控件级绑定, 原来 Enter/Leave + bind_all 会在
        # 弹窗直接关闭时残留悬空 handler, 后续任意滚轮事件触发 TclError)
        bind_mousewheel(canvas, content)

        # ===== 内容布局 (全部 pack 到 content) =====
        pad = dict(padx=Space.LG, pady=Space.SM)

        # 标题
        tk.Label(
            content, text="同步配置", font=UIFont.h2(),
            bg=BG, fg=TEXT,
        ).pack(anchor=tk.W, padx=Space.LG, pady=(Space.LG, Space.MD))

        # 方向选择
        dir_frame = tk.LabelFrame(
            content, text="方向", font=UIFont.body_sm(),
            bg=BG, fg=SUB, bd=1, relief="solid",
            highlightbackground=BORDER, highlightthickness=1,
        )
        dir_frame.pack(fill=tk.X, **pad)

        for text, val in [
            ("推送 (本地到远端)", "push"),
            ("拉取 (远端到本地)", "pull"),
            ("镜像 (双向, 两端一致)", "mirror"),
        ]:
            ttk.Radiobutton(
                dir_frame, text=text, value=val,
                variable=self.direction,
            ).pack(anchor=tk.W, padx=Space.MD, pady=2)

        # 桶 + prefix
        bucket_frame = tk.Frame(content, bg=BG)
        bucket_frame.pack(fill=tk.X, **pad)
        tk.Label(bucket_frame, text="桶:", font=UIFont.body(),
                 bg=BG, fg=TEXT, width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.bucket_combo = ttk.Combobox(
            bucket_frame, textvariable=self.bucket_var,
            state="readonly", width=24, font=UIFont.body(),
        )
        self.bucket_combo.pack(side=tk.LEFT, padx=(0, Space.MD))

        prefix_frame = tk.Frame(content, bg=BG)
        prefix_frame.pack(fill=tk.X, **pad)
        tk.Label(prefix_frame, text="远端 prefix:", font=UIFont.body(),
                 bg=BG, fg=TEXT, width=8, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(prefix_frame, textvariable=self.prefix_var,
                  font=UIFont.body()).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 本地目录
        local_frame = tk.Frame(content, bg=BG)
        local_frame.pack(fill=tk.X, **pad)
        tk.Label(local_frame, text="本地目录:", font=UIFont.body(),
                 bg=BG, fg=TEXT, width=8, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(local_frame, textvariable=self.local_dir_var,
                  font=UIFont.body()).pack(side=tk.LEFT, fill=tk.X, expand=True,
                                           padx=(0, Space.SM))
        create_secondary_button(
            local_frame, "浏览...", self._on_browse_local, width=8,
        ).pack(side=tk.LEFT)

        # 选项
        opt_frame = tk.LabelFrame(
            content, text="选项", font=UIFont.body_sm(),
            bg=BG, fg=SUB, bd=1, relief="solid",
            highlightbackground=BORDER, highlightthickness=1,
        )
        opt_frame.pack(fill=tk.X, **pad)

        ttk.Checkbutton(
            opt_frame, text="包含子目录 (递归)",
            variable=self.recursive_var,
        ).pack(anchor=tk.W, padx=Space.MD, pady=2)

        self.delete_source_chk = ttk.Checkbutton(
            opt_frame, text="完成后删除源端 (推送成功后自动删本地源文件)",
            variable=self.delete_source_var,
        )
        self.delete_source_chk.pack(anchor=tk.W, padx=Space.MD, pady=2)

        self.delete_remote_chk = ttk.Checkbutton(
            opt_frame, text="删除目标端多余 (镜像模式, rsync --delete)",
            variable=self.delete_remote_extras_var,
        )
        self.delete_remote_chk.pack(anchor=tk.W, padx=Space.MD, pady=2)

        self._update_option_visibility()

        # 联动: 方向切换时, 更新选项可用性
        self.direction.trace_add("write", lambda *_: self._update_option_visibility())

    def _update_option_visibility(self):
        """根据方向启用/禁用选项 checkbox

        ⚠ 旧版只把 checkbox 置灰, BooleanVar 仍为 True —— 切到"拉取"后
        灰着的"删除目标端多余"依然生效 (rsync --delete 会删远端多余文件),
        而用户看到的是"已禁用"。这里同步把 var 置 False。
        """
        d = self.direction.get()
        # 删源: 推送/镜像模式启用
        if d in ("push", "mirror"):
            self.delete_source_chk.state(["!disabled"])
        else:
            self.delete_source_chk.state(["disabled"])
            self.delete_source_var.set(False)
        # 删目标多余: 镜像模式启用
        if d == "mirror":
            self.delete_remote_chk.state(["!disabled"])
        else:
            self.delete_remote_chk.state(["disabled"])
            self.delete_remote_extras_var.set(False)

    def _refresh_buckets(self):
        if not self.locator.is_connected:
            return
        ok, buckets = self.locator.bucket_manager.list_buckets()
        if not ok:
            return
        self.bucket_combo["values"] = buckets
        if self.bucket_var.get() and self.bucket_var.get() in buckets:
            self.bucket_combo.set(self.bucket_var.get())
        elif buckets:
            self.bucket_combo.set(buckets[0])

    def _on_browse_local(self):
        d = filedialog.askdirectory(title="选择本地目录", parent=self)
        if d:
            self.local_dir_var.set(d)

    def _validate(self) -> Optional[str]:
        """返回错误消息, None 表示通过"""
        if not self.bucket_var.get():
            return "请选择桶"
        if not self.local_dir_var.get():
            return "请选择本地目录"
        if not os.path.isdir(self.local_dir_var.get()):
            return f"本地目录不存在: {self.local_dir_var.get()}"
        if not self.locator.is_connected:
            return "请先连接到 S3"
        return None

    def _on_preview(self):
        err = self._validate()
        if err:
            messagebox.showwarning("提示", err, parent=self)
            return

        try:
            svc = SyncService(self.locator)
            plan = svc.compute_plan(
                direction=Direction(self.direction.get()),
                local_dir=self.local_dir_var.get(),
                bucket=self.bucket_var.get(),
                prefix=self.prefix_var.get(),
                recursive=self.recursive_var.get(),
            )
        except Exception as e:
            messagebox.showerror("计算差异失败", str(e), parent=self)
            return

        SyncPreviewDialog(self, self.locator, plan, direction=self.direction.get())

    def _on_start_sync(self):
        err = self._validate()
        if err:
            messagebox.showwarning("提示", err, parent=self)
            return
        # _running 单例位: 防重复启动 (旧版连点"开始同步"会起两个线程,
        # 两个线程同时对同一批对象做上传+删除)
        if getattr(self, "_running", False):
            messagebox.showwarning("提示", "同步已在进行中", parent=self)
            return

        # 计算计划
        try:
            svc = SyncService(self.locator)
            plan = svc.compute_plan(
                direction=Direction(self.direction.get()),
                local_dir=self.local_dir_var.get(),
                bucket=self.bucket_var.get(),
                prefix=self.prefix_var.get(),
                recursive=self.recursive_var.get(),
            )
        except Exception as e:
            messagebox.showerror("计算差异失败", str(e), parent=self)
            return

        # 如果完全无变化, 直接提示
        if (not plan.to_upload and not plan.to_download
                and not plan.to_delete_remote and not plan.conflicts):
            messagebox.showinfo(
                "无变化", f"本地与远端内容一致, 跳过。\n{plan.summary()}",
                parent=self,
            )
            return

        # 确认对话框
        msg = (
            f"将执行同步操作:\n{plan.summary()}\n\n"
            + ("完成后删除源端: 是\n" if self.delete_source_var.get() else "")
            + ("删除目标端多余: 是\n" if self.delete_remote_extras_var.get() else "")
            + "\n确认开始?"
        )
        if not messagebox.askyesno("确认同步", msg, parent=self):
            return

        # 启动后台线程 (保留进度窗口, 不再直接 self.destroy())
        self._start_execute(plan, svc)

    def _start_execute(self, plan: SyncPlan, svc: SyncService):
        """后台执行同步计划, 保留进度窗口直到结束"""
        self._running = True
        # 快照参数: 对话框会关闭, worker 线程不能再读 tk 变量
        opts = {
            "bucket": self.bucket_var.get(),
            "prefix": self.prefix_var.get(),
            "local_dir": self.local_dir_var.get(),
            "direction": self.direction.get(),
            "delete_source": self.delete_source_var.get(),
            "delete_remote_extras": self.delete_remote_extras_var.get(),
        }
        bridge = get_bridge(self, logger=getattr(self.locator, "logger", None))
        # ⚠ 把活着的 bridge 存下来: 收尾回调 (_on_sync_done/_on_sync_error)
        #   不能再调 get_bridge(self) —— 那时 self 已被 destroy,
        #   _resolve_root 对已销毁 widget 抛 TclError → 返回 __new__ 出来的
        #   未初始化空壳 (没有 _lock/_inflight), end_task() 直接 AttributeError,
        #   整个收尾回调中断, 进度窗口永远卡在"正在同步…"。
        self._bridge = bridge

        # ⚠ 进度窗口的 master 不能是 self: 下面 50ms 后 self.destroy() 会
        #   连带销毁它的所有子 toplevel (Tk 语义), 进度窗口一闪即灭 ——
        #   "保留进度窗口直到结束" 形同虚设。挂到 self 的 master
        #   (页面容器 / 主窗口, 生命周期覆盖整个同步过程)。
        prog_parent = self.master if isinstance(self.master, tk.Misc) else self
        prog = SyncProgressWindow(prog_parent, on_close=self._restore_after_sync)
        self._progress_win = prog

        # 配置窗立即关闭, 但进度窗口接管后续反馈 (旧版 destroy 后
        # 用户看不到任何进度, 也没有取消入口)
        self.withdraw()
        self.after(50, self.destroy)

        def _cancel_hook() -> None:
            # SyncService.execute_plan 没有 cancel_event 参数 (不改 services/),
            # 用 TransferService.cancel_all() 在文件+分片两个粒度取消。
            try:
                self.locator.transfer.cancel_all()
            except Exception:
                pass

        prog.set_cancel_hook(_cancel_hook)

        def _pause_hook() -> None:
            # 暂停所有在途任务 (文件 + 分片边界等待), 与 cancel_all 同粒度
            try:
                self.locator.transfer.pause_all()
            except Exception:
                pass

        def _resume_hook() -> None:
            try:
                self.locator.transfer.resume_all()
            except Exception:
                pass

        prog.set_pause_hooks(_pause_hook, _resume_hook)
        # "应用到所有" 的共享决策
        apply_to_all_box: dict = {}
        bridge.begin_task("同步")

        def run():
            # ⚠ worker 线程: 只跑同步 + 投递队列, 绝不碰 Tk
            def progress_cb(current, total, name):
                # ⚠ 旧版在这里裸调 self.locator._main_window.update_status()
                #   —— 最危险的一处跨线程 Tk 调用: 直接进 Tcl 解释器,
                #   同步动辄几分钟, 卡死/抛 TclError 几乎是必然。
                bridge.post(prog.update_progress, current, total, name)

            def conflict_resolver(conflict: SyncConflict) -> str:
                """主线程弹窗解决冲突 (通过桥投递 + 事件等待)"""
                # 已有"应用到所有"的决策: 直接复用, 不再逐个弹窗
                if "choice" in apply_to_all_box:
                    return str(apply_to_all_box["choice"])

                result_holder = [RESOLVE_SKIP]
                event = threading.Event()

                def ask():
                    try:
                        dlg = ConflictDialog(prog, conflict, apply_to_all_box)
                        prog.wait_window(dlg)
                        result_holder[0] = dlg.result
                    except tk.TclError:
                        result_holder[0] = RESOLVE_SKIP
                    finally:
                        event.set()

                bridge.post(ask)
                event.wait()
                return result_holder[0]

            try:
                result = svc.execute_plan(
                    plan,
                    bucket=opts["bucket"],
                    delete_source=opts["delete_source"],
                    delete_remote_extras=opts["delete_remote_extras"],
                    conflict_resolver=conflict_resolver,
                    progress_cb=progress_cb,
                )
            except Exception as e:
                bridge.post(self._on_sync_error, f"同步失败: {e}")
                bridge.end_task()
                return
            bridge.post(self._on_sync_done, result, opts, prog)

        threading.Thread(target=run, daemon=True, name="sync").start()

    def _restore_after_sync(self) -> None:
        self._running = False

    def _on_sync_error(self, msg: str) -> None:
        self._running = False
        # 复用 _start_execute 捕获的活 bridge (self 此时已 destroy,
        # get_bridge(self) 只会拿到没有 _lock 的空壳, 见 _start_execute 注释)
        bridge = getattr(self, "_bridge", None)
        if bridge is None:
            bridge = get_bridge(self, logger=getattr(self.locator, "logger", None))
        bridge.end_task()
        prog = getattr(self, "_progress_win", None)
        if prog is not None:
            prog.finish(msg, ok=False)
        try:
            self.locator.logger.error("sync", "", msg)
        except Exception:
            pass
        try:
            self._main_window().update_status(msg)
        except Exception:
            pass

    def _main_window(self):
        return getattr(self.locator, "_main_window", None)

    def _on_sync_done(self, result, opts: dict, prog) -> None:
        """主线程: 收尾 (记录活动 / 提示 / 刷新页面)"""
        self._running = False
        # 复用 _start_execute 捕获的活 bridge (self 此时已 destroy,
        # get_bridge(self) 只会拿到没有 _lock 的空壳, 见 _start_execute 注释)
        bridge = getattr(self, "_bridge", None)
        if bridge is None:
            bridge = get_bridge(self, logger=getattr(self.locator, "logger", None))
        bridge.end_task()

        # 记录到活动历史 (SyncPage 会自动显示) - 延迟 import 避免循环
        try:
            from ..pages.sync_page import record_sync_activity, SyncActivity
            record_sync_activity(SyncActivity(
                when=time.strftime("%Y-%m-%d %H:%M:%S"),
                direction=opts["direction"],
                bucket=opts["bucket"],
                prefix=opts["prefix"],
                local_dir=opts["local_dir"],
                summary=result.summary(),
                success=(not result.cancelled and not result.errors),
            ))
        except Exception:
            pass

        # 刷新 SyncPage (如果在当前页)
        main = self._main_window()
        if main is not None:
            try:
                page = main.current_page
                if page and page.__class__.__name__ == "SyncPage":
                    page._refresh_log()
            except Exception:
                pass

        if result.cancelled:
            summary = "同步已取消"
            prog.finish(summary, ok=False)
        elif result.errors:
            summary = result.summary()
            prog.finish(summary, ok=False)
            notify(main or self, "warning", summary)
            messagebox.showwarning(
                "同步完成 (有错误)",
                f"{result.summary()}\n\n错误 ({len(result.errors)} 条):\n"
                + "\n".join(result.errors[:10]),
                parent=prog,
            )
        else:
            summary = result.summary()
            prog.finish(summary, ok=True)
            notify(main or self, "success", summary)

        if main is not None:
            try:
                main.update_status("就绪")
                page = main.current_page
                if page is not None and hasattr(page, "refresh"):
                    page.refresh()
            except Exception:
                pass


# ==================== 同步进度窗口 ====================


class SyncProgressWindow(tk.Toplevel):
    """同步执行期间的进度窗口 (进度条 + 取消)

    旧版 `_start_execute` 直接 `self.destroy()`, 配置窗瞬间消失, 用户既
    看不到进度也没有取消入口 —— 同步几分钟像"卡死"了。
    """

    def __init__(self, parent: tk.Misc, on_close: Optional[Callable] = None):
        super().__init__(parent)
        self.title("同步进行中")
        self.geometry("460x220")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self._on_close = on_close
        self._cancel_hook: Optional[Callable] = None
        self._pause_hook: Optional[Callable] = None
        self._resume_hook: Optional[Callable] = None
        self._done = False

        BG = Neutral.BG_PANEL
        self.configure(bg=BG)

        tk.Label(
            self, text="正在同步…", font=UIFont.h2(),
            bg=BG, fg=Neutral.TEXT_1,
        ).pack(anchor=tk.W, padx=Space.LG, pady=(Space.LG, Space.SM))

        self._detail = tk.Label(
            self, text="准备中…", font=UIFont.body(),
            bg=BG, fg=Neutral.TEXT_2, anchor=tk.W,
            wraplength=400, justify=tk.LEFT,
        )
        self._detail.pack(anchor=tk.W, padx=Space.LG, fill=tk.X)

        self._bar = ttk.Progressbar(self, mode="indeterminate")
        self._bar.pack(fill=tk.X, padx=Space.LG, pady=(Space.MD, 0))
        self._bar.start(12)

        self._pct = tk.Label(
            self, text="", font=UIFont.caption(),
            bg=BG, fg=Neutral.TEXT_3, anchor=tk.W,
        )
        self._pct.pack(anchor=tk.W, padx=Space.LG, pady=(Space.XS, 0))

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(fill=tk.X, padx=Space.LG, pady=Space.MD)
        self._cancel_btn = create_secondary_button(
            btn_frame, "取消同步", self._on_cancel, icon="ban", width=10,
        )
        self._cancel_btn.pack(side=tk.RIGHT)
        # 暂停/恢复 (Pail 借鉴): 与取消并列; 窗口只维护 UI 态, 真值在 TransferTask
        self._pause_btn = create_secondary_button(
            btn_frame, "暂停", self._on_pause_toggle, width=8,
        )
        self._pause_btn.pack(side=tk.RIGHT, padx=(0, Space.SM))
        self._paused_ui = False

        # 居中
        try:
            self.update_idletasks()
            top = parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent
            x = top.winfo_rootx() + 80
            y = top.winfo_rooty() + 80
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def set_cancel_hook(self, hook: Callable) -> None:
        self._cancel_hook = hook

    def set_pause_hooks(self, on_pause: Callable, on_resume: Callable) -> None:
        """设置暂停/恢复回调; 按钮文案按窗口 UI 态切换 (真值在 TransferTask)"""
        self._pause_hook = on_pause
        self._resume_hook = on_resume

    def _on_pause_toggle(self) -> None:
        hook = self._resume_hook if self._paused_ui else self._pause_hook
        try:
            self._pause_btn.config(
                text="恢复" if not self._paused_ui else "暂停",
                state=tk.DISABLED,
            )
        except tk.TclError:
            return
        self._paused_ui = not self._paused_ui
        if hook is not None:
            try:
                hook()
            except Exception:
                pass
        try:
            self._pause_btn.config(state=tk.NORMAL)
        except tk.TclError:
            pass

    def update_progress(self, current: int, total: int, name: str) -> None:
        """主线程: 刷新进度 (由 threading_bridge 调用)"""
        if self._done:
            return
        try:
            if total > 0:
                pct = int(current * 100 / total)
                self._bar.stop()
                self._bar.configure(mode="determinate", maximum=total, value=current)
                self._pct.config(text=f"{current} / {total}  ({pct}%)")
            self._detail.config(text=str(name)[:60] or "…")
        except tk.TclError:
            pass

    def _on_cancel(self) -> None:
        try:
            self._cancel_btn.config(state=tk.DISABLED, text="正在取消…")
        except tk.TclError:
            pass
        if self._cancel_hook is not None:
            try:
                self._cancel_hook()
            except Exception:
                pass

    def finish(self, summary: str, ok: bool = True) -> None:
        """同步结束: 停进度条 + 换成结果文案, 由用户自己关"""
        if self._done:
            return
        self._done = True
        try:
            self._bar.stop()
            self._bar.configure(mode="determinate", value=1, maximum=1)
            self._detail.config(
                text=summary[:120],
                fg=Status.SUCCESS if ok else Status.WARNING,
            )
            self._pct.config(text="")
            self._cancel_btn.config(text="关闭", command=self.destroy, state=tk.NORMAL)
            self._pause_btn.config(state=tk.DISABLED)
        except tk.TclError:
            pass

    def destroy(self) -> None:
        try:
            self._bar.stop()
        except tk.TclError:
            pass
        try:
            super().destroy()
        except tk.TclError:
            pass
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                pass


# ==================== 预览对话框 ====================


class SyncPreviewDialog(tk.Toplevel):
    """同步差异预览"""

    def __init__(self, parent, locator, plan: SyncPlan, direction: str):
        super().__init__(parent)
        self.locator = locator
        self.plan = plan
        self.direction = direction
        self.title("同步差异预览")
        self.geometry("720x500")
        self.transient(parent.winfo_toplevel())

        BG = Neutral.BG_PANEL
        TEXT = Neutral.TEXT_1
        BORDER = Neutral.BORDER

        self.configure(bg=BG)

        # 顶部摘要
        tk.Label(
            self, text=f"差异摘要: {plan.summary()}",
            font=UIFont.h3(), bg=BG, fg=TEXT,
        ).pack(anchor=tk.W, padx=Space.LG, pady=(Space.LG, Space.MD))

        # 树形列表
        tree_frame = tk.Frame(
            self, bg=Neutral.BG_PANEL, highlightbackground=BORDER, highlightthickness=1,
        )
        tree_frame.pack(fill=tk.BOTH, expand=True,
                        padx=Space.LG, pady=(0, Space.MD))

        columns = ("kind", "rel", "size", "detail")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=15,
        )
        self.tree.heading("kind", text="操作")
        self.tree.heading("rel", text="相对路径")
        self.tree.heading("size", text="大小", anchor=tk.E)
        self.tree.heading("detail", text="详情")
        self.tree.column("kind", width=80, anchor=tk.CENTER)
        self.tree.column("rel", width=300, anchor=tk.W)
        self.tree.column("size", width=100, anchor=tk.E)
        self.tree.column("detail", width=200, anchor=tk.W)

        scroll = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 填充
        self._populate()

        # 按钮
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(fill=tk.X, padx=Space.LG, pady=Space.LG)
        create_secondary_button(
            btn_frame, "关闭", self.destroy, width=8,
        ).pack(side=tk.RIGHT)

    def _populate(self):
        # 标签配置: 颜色
        self.tree.tag_configure("upload", foreground=Brand.PRIMARY)
        self.tree.tag_configure("download", foreground=Status.SUCCESS)
        self.tree.tag_configure("del_remote", foreground=Status.DANGER)
        self.tree.tag_configure("del_local", foreground=Status.WARNING)
        self.tree.tag_configure("conflict", foreground=Status.DANGER)
        self.tree.tag_configure("skip", foreground=Neutral.TEXT_3)

        # 分组
        for local_path, remote_key in self.plan.to_upload:
            sz = ""
            try:
                sz = format_bytes(os.path.getsize(local_path))
            except OSError:
                pass
            self.tree.insert(
                "", tk.END,
                values=("上传", remote_key, sz, f"本地: {local_path}"),
                tags=("upload",),
            )

        for remote_key, local_path in self.plan.to_download:
            # 需要从 remote 获取 size (这里用 plan 数据)
            self.tree.insert(
                "", tk.END,
                values=("下载", remote_key, "", f"本地: {local_path}"),
                tags=("download",),
            )

        for key in self.plan.to_delete_remote:
            self.tree.insert(
                "", tk.END,
                values=("× 删远端", key, "", "(目标端多余)"),
                tags=("del_remote",),
            )

        for path in self.plan.to_delete_local:
            self.tree.insert(
                "", tk.END,
                values=("× 删本地", path, "", "(本地多余)"),
                tags=("del_local",),
            )

        for c in self.plan.conflicts:
            detail = f"本地 {format_bytes(c.local.size)} vs 远端 {format_bytes(c.remote.size)}"
            self.tree.insert(
                "", tk.END,
                values=("冲突", c.rel, "", detail),
                tags=("conflict",),
            )

        if self.plan.skipped:
            self.tree.insert(
                "", tk.END,
                values=("跳过", f"({self.plan.skipped} 个文件)", "", "内容一致"),
                tags=("skip",),
            )


# ==================== 冲突对话框 ====================


class ConflictDialog(tk.Toplevel):
    """单个冲突解决"""

    def __init__(self, parent, conflict: SyncConflict,
                 apply_to_all_box: Optional[dict] = None):
        super().__init__(parent)
        self.conflict = conflict
        self.result = RESOLVE_SKIP
        # 共享状态: 勾选"应用到所有"时把决策写进这个 dict,
        # SyncDialog 的 resolver 读到就直接复用, 剩余冲突不再逐个弹窗。
        # 旧版只在注释里说"由 SyncDialog 后续读取"却从不写 —— 勾选完全无效。
        self._apply_to_all_box = apply_to_all_box if apply_to_all_box is not None else {}
        self.title(f"冲突: {conflict.rel}")
        self.geometry("560x320")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.resizable(False, False)

        self.apply_to_all_var = tk.BooleanVar(value=False)

        BG = Neutral.BG_PANEL
        TEXT = Neutral.TEXT_1
        SUB = Neutral.TEXT_2
        DANGER = Status.DANGER

        self.configure(bg=BG)

        # 标题
        tk.Label(
            self, text=f"冲突: {conflict.rel}",
            font=UIFont.h3(), bg=BG, fg=DANGER,
        ).pack(anchor=tk.W, padx=Space.LG, pady=(Space.LG, Space.SM))

        # 对比表
        cmp_frame = tk.Frame(self, bg=BG)
        cmp_frame.pack(fill=tk.X, padx=Space.LG, pady=Space.SM)

        # 表头
        for col, w in [("", 8), ("本地", 26), ("远端", 26)]:
            tk.Label(cmp_frame, text=col, font=UIFont.body_sm(),
                     bg=BG, fg=SUB, width=w, anchor=tk.W).grid(
                row=0, column=["", "本地", "远端"].index(col), sticky=tk.W,
            )

        for i, (label, local_val, remote_val) in enumerate([
            ("大小", format_bytes(conflict.local.size), format_bytes(conflict.remote.size)),
            ("修改时间", conflict.local_mtime.strftime("%Y-%m-%d %H:%M:%S"),
             conflict.remote_mtime_str),
            ("路径", conflict.local.path, conflict.remote.key),
        ], start=1):
            tk.Label(cmp_frame, text=label, font=UIFont.body_sm(),
                     bg=BG, fg=SUB, anchor=tk.W).grid(row=i, column=0, sticky=tk.NW)
            tk.Label(cmp_frame, text=local_val, font=UIFont.body(),
                     bg=BG, fg=TEXT, anchor=tk.W, wraplength=180, justify=tk.LEFT,
                     ).grid(row=i, column=1, sticky=tk.NW, padx=Space.SM)
            tk.Label(cmp_frame, text=remote_val, font=UIFont.body(),
                     bg=BG, fg=TEXT, anchor=tk.W, wraplength=180, justify=tk.LEFT,
                     ).grid(row=i, column=2, sticky=tk.NW, padx=Space.SM)

        cmp_frame.columnconfigure(1, weight=1)
        cmp_frame.columnconfigure(2, weight=1)

        # 应用到所有
        ttk.Checkbutton(
            self, text="对所有剩余冲突应用相同选择",
            variable=self.apply_to_all_var,
        ).pack(anchor=tk.W, padx=Space.LG, pady=(Space.SM, 0))

        # 按钮
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(fill=tk.X, padx=Space.LG, pady=Space.LG)

        create_danger_button(
            btn_frame, "取消整次", self._on_cancel, width=10,
        ).pack(side=tk.LEFT)
        create_secondary_button(
            btn_frame, "跳过", self._on_skip, width=8,
        ).pack(side=tk.RIGHT, padx=(Space.SM, 0))
        create_secondary_button(
            btn_frame, "用远端覆盖本地", self._on_use_remote, width=14,
        ).pack(side=tk.RIGHT, padx=(0, Space.SM))
        create_primary_button(
            btn_frame, "用本地覆盖远端", self._on_use_local, width=14,
        ).pack(side=tk.RIGHT, padx=(0, Space.SM))

        # 居中
        self.update_idletasks()
        try:
            x = parent.winfo_toplevel().winfo_rootx() + 60
            y = parent.winfo_toplevel().winfo_rooty() + 60
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _on_use_local(self):
        self.result = RESOLVE_USE_LOCAL
        self._close()

    def _on_use_remote(self):
        self.result = RESOLVE_USE_REMOTE
        self._close()

    def _on_skip(self):
        self.result = RESOLVE_SKIP
        self._close()

    def _on_cancel(self):
        self.result = RESOLVE_CANCEL
        self._close()

    def _close(self):
        # 勾了"应用到所有"就把决策写进共享状态, 供 SyncDialog 的 resolver
        # 复用到剩余冲突 (不实现的话这个复选框就是个摆设)
        if self.apply_to_all_var.get():
            self._apply_to_all_box["choice"] = self.result
        self.destroy()
