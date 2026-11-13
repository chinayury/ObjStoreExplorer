# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/threading_bridge — Tk 跨线程回调的唯一安全通道

背景 (本项目最大的随机崩溃源):
    Tcl 解释器**不是线程安全的**。绝大多数 Tk 调用 (widget.after /
    .config() / messagebox / .destroy) 只能发生在创建该 widget 的线程。
    在 worker 线程里直接调它们, 典型后果是:
        - 随机卡死 (Tcl 内部锁互相等待, 主线程再去 update() 就死锁)
        - TclError: invalid command name ".!toplevel2.canvas"
          (widget 已被销毁, 但后台线程还拿着引用往里投递)

    注意 `widget.after(0, cb)` **并不安全** —— 跨线程调 after 本身
    就要进 Tcl 解释器, 只是把崩溃概率从 100% 降到"看运气"。

正确做法 (本模块):
    1. worker 线程只做一件事: `queue.put(...)`, 纯 Python 操作, 不碰 Tcl;
    2. 主线程用 `root.after(POLL_MS, drain)` 轮询队列, 把回调搬到主线程执行;
    3. 轮询器在 root destroy 前 `after_cancel`, 不留悬空回调。

用法 (一站式):
    from .threading_bridge import run_async

    def worker():
        return locator.bucket_manager.list_buckets()

    run_async(self.frame, worker,
              on_ok=lambda ok, buckets: self._render(buckets),
              on_err=lambda e: messagebox.showerror("错误", str(e)))

用法 (手动控制):
    from .threading_bridge import get_bridge

    bridge = get_bridge(self.frame)
    bridge.post(self._update_status, "就绪")     # 跨线程安全
    bridge.submit(do_work, on_ok=self._done)     # 后台跑 + 主线程回调

在途任务登记 (配合 main_window 的退出确认):
    bridge.begin_task("上传")
    ...
    bridge.end_task()
"""
from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Tuple


# 主线程轮询间隔 (ms)。50ms 兼顾"回调不迟滞"与"空队列时几乎不耗 CPU"。
POLL_MS = 50


def _resolve_root(parent: Optional[tk.Misc]) -> Optional[tk.Misc]:
    """把任意 widget / Toplevel 归一到它的 Tk 根窗口"""
    if parent is None:
        return None
    try:
        root = parent.winfo_toplevel()
        if root is not None:
            return root
    except tk.TclError:
        return None
    return None


class ThreadingBridge:
    """把后台线程的回调安全地搬回主线程执行。

    每个 Tk 根窗口对应一个桥 (由 :func:`get_bridge` 缓存)。
    """

    def __init__(self, root: tk.Misc, logger=None):
        self.root = root
        self._logger = logger
        self._queue: "queue.Queue[Tuple[str, tuple, Callable, Any]]" = queue.Queue()
        self._after_token: Optional[str] = None
        self._lock = threading.Lock()
        self._destroyed = False
        # 在途任务: 用于退出程序前提示 "还有 N 个后台任务在跑"
        self._inflight: Dict[int, str] = {}
        self._seq = 0

    # ==================== 生命周期 ====================

    def start(self) -> None:
        """启动主线程轮询器 (幂等)"""
        if self._after_token is not None or self._destroyed:
            return
        self._schedule()

    def _schedule(self) -> None:
        if self._destroyed:
            return
        try:
            self._after_token = self.root.after(POLL_MS, self._drain)
        except tk.TclError:
            # root 已被销毁 —— 桥随之作废
            self._after_token = None
            self._destroyed = True

    def shutdown(self) -> None:
        """停止轮询 (root destroy 前调用, 避免悬空 after 脚本)"""
        self._destroyed = True
        token = self._after_token
        self._after_token = None
        if token is not None:
            try:
                self.root.after_cancel(token)
            except tk.TclError:
                pass

    # ==================== 队列投递 (任何线程可调) ====================

    def post(self, fn: Callable, *args, **kwargs) -> None:
        """把一次主线程调用排进队列。worker 线程里只调这个, 绝不碰 Tk。"""
        if self._destroyed:
            return
        self._queue.put(("call", (fn, args, kwargs), None, None))
    def submit(
        self,
        fn: Callable,
        *args,
        on_ok: Optional[Callable] = None,
        on_err: Optional[Callable] = None,
        task_name: str = "",
        **kwargs,
    ) -> None:
        """在 daemon 线程里跑 fn, 完成后在**主线程**调 on_ok / on_err。

        Args:
            fn:         后台函数, 其返回值作为 on_ok 的第一个参数
            on_ok:      主线程回调 on_ok(result)
            on_err:     主线程回调 on_err(exception)
            task_name:  在途任务名 (退出提示用), 可留空
        """
        if self._destroyed:
            return
        name = task_name or getattr(fn, "__name__", "后台任务")
        self.begin_task(name)

        def _runner() -> None:
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - 兜住一切, 交给 on_err
                self._log_error(name, exc)
                # 在途标记必须等**主线程回调跑完**再撤, 否则退出确认框
                # 会认为"没有在途任务"而直接销毁 root, 回调仍往已销毁
                # 控件投递。
                self.post(self.end_task)
                self._queue.put(("err", (exc,), on_err, None))
            else:
                self.post(self.end_task)
                self._queue.put(("ok", (result,), on_ok, None))

        threading.Thread(target=_runner, daemon=True, name=name).start()

    # ==================== 在途任务 ====================

    def begin_task(self, name: str = "任务") -> None:
        with self._lock:
            self._seq += 1
            self._inflight[self._seq] = name

    def end_task(self) -> None:
        with self._lock:
            if self._inflight:
                self._inflight.pop(max(self._inflight), None)

    @property
    def inflight_names(self) -> List[str]:
        with self._lock:
            return list(self._inflight.values())

    @property
    def has_inflight(self) -> bool:
        with self._lock:
            return bool(self._inflight)

    # ==================== 主线程轮询 ====================

    def _drain(self) -> None:
        """主线程: 取出队列里所有待执行项并执行"""
        self._after_token = None
        if self._destroyed:
            return
        # 单轮最多处理 200 条, 防止一次性灌入大量任务把界面卡住
        for _ in range(200):
            try:
                kind, args, cb_ok, _cb_err = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if kind == "call":
                    fn, call_args, call_kwargs = args
                    fn(*call_args, **call_kwargs)
                elif kind in ("ok", "err"):
                    if cb_ok is not None:
                        cb_ok(*args)
            except tk.TclError:
                # 回调里碰了已销毁的 widget —— 吞掉, 继续处理下一条,
                # 绝不让一条坏回调把整个轮询器带走。
                continue
            except Exception:
                self._log_error("线程桥回调", traceback.format_exc())
                continue
        self._schedule()

    # ==================== 日志 ====================

    def _log_error(self, task_name: str, exc: BaseException) -> None:
        if self._logger is None:
            return
        try:
            detail = f"{type(exc).__name__}: {exc}"
            self._logger.error(task_name or "async_task", "", detail)
        except Exception:
            pass


# ==================== 模块级桥缓存 ====================

_BRIDGES: Dict[int, ThreadingBridge] = {}


def get_bridge(parent: Optional[tk.Misc], logger=None) -> ThreadingBridge:
    """取得 (或创建) 该 Tk 根窗口对应的桥"""
    root = _resolve_root(parent)
    if root is None:
        # 没有 Tk 上下文 (如单元测试) —— 给一个惰性失效的壳, 调用不会崩
        return ThreadingBridge.__new__(ThreadingBridge)
    try:
        key = int(root.winfo_id())
    except tk.TclError:
        return ThreadingBridge.__new__(ThreadingBridge)

    bridge = _BRIDGES.get(key)
    if bridge is None or bridge._destroyed:
        bridge = ThreadingBridge(root, logger=logger)
        _BRIDGES[key] = bridge
        bridge.start()
    elif logger is not None and bridge._logger is None:
        bridge._logger = logger
    return bridge


def shutdown_bridge(parent: Optional[tk.Misc]) -> None:
    """root destroy 前调用: 取消所有轮询器"""
    root = _resolve_root(parent)
    if root is None:
        return
    try:
        key = int(root.winfo_id())
    except tk.TclError:
        return
    bridge = _BRIDGES.pop(key, None)
    if bridge is not None:
        bridge.shutdown()


def run_async(
    parent: Optional[tk.Misc],
    fn: Callable,
    on_ok: Optional[Callable] = None,
    on_err: Optional[Callable] = None,
    task_name: str = "",
) -> None:
    """一站式封装: 后台跑 fn, 结果回主线程。

    on_ok 收到 fn 的返回值; 抛异常则调 on_err(exception) 并写日志。
    """
    logger = None
    try:
        loc = getattr(parent, "locator", None)
        logger = getattr(loc, "logger", None)
    except Exception:
        logger = None
    get_bridge(parent, logger=logger).submit(
        fn, on_ok=on_ok, on_err=on_err, task_name=task_name,
    )
