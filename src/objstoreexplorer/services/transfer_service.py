# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""services/transfer_service - 传输服务

封装上传/下载/删除的批量逻辑:
    - 自持独立线程池 (不与 UI / 其他后台任务抢全局 4 线程)
    - 分批 submit 背压, 十万级任务也不会一次性压爆内存
    - 失败重试 (指数退避 + 抖动, 仅对 5xx / 网络类错误)
    - 取消: 文件粒度 + **分片粒度** (上传走自管分片, 每片检查取消标志)

=== 线程契约 (调用方必读) ===

1. 进度回调 `progress(current, total, name)` **在本方法的调用线程** 上被调用
   (即调用 upload_files/download_files/... 的那个线程, 通常是 UI 后台线程),
   **不是** worker 线程。tkinter 只能在主线程改控件, 所以 UI 侧必须自己切线程:
       root.after(0, lambda: bar.configure(value=current))
   参考 ui/pages/objects_page.py 的正确用法。

2. 字节级进度 (minio 内部线程产生) **不会**转发给 progress 回调 —— 否则会从
   minio 的上传线程直接打到 UI。它汇总在 TransferTask 上, 需要时用
   `transfer_service.byte_progress_snapshot()` 拉取。

3. 本服务**不直接触碰任何 UI 对象**, 只通过回调把控制权交回调用方。
"""
from __future__ import annotations
import builtins
import mimetypes
import os
import random
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config.exceptions import (
    CancelledError,
    ConnectionError as AppConnectionError,
    NetworkTimeoutError,
    ServerUnavailableError,
)


# ==================== 可调参数 ====================

# 传输线程池大小: 传输是 IO 密集, 独立于全局 THREAD_POOL_WORKERS(=4),
# 否则大文件上传会把 UI 刷新等后台任务饿死。
TRANSFER_WORKERS = 12

# 一次 submit 的批大小 (背压): 一批跑完再提交下一批
SUBMIT_BATCH_SIZE = 200

# 失败重试
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.5   # 秒
RETRY_JITTER = 0.5       # 抖动比例 (0~0.5)

# S3 5xx / 可重试的服务端错误码
_RETRYABLE_S3_CODES = {
    "InternalError", "SlowDown", "ServiceUnavailable", "RequestTimeout",
    "OperationAborted", "RequestTimeTooSkewed",
}

# core 层 map_s3_error 把异常吃成 (False, msg) 时, msg 里留下的可重试痕迹。
# 只认 core/config.exceptions.py 里稳定产出的措辞, 不做模糊猜测。
_RETRYABLE_MSG_MARKERS = (
    "网络错误", "网络超时", "服务不可用", "连接失败",
    "InternalError", "SlowDown", "ServiceUnavailable", "RequestTimeout",
    "timed out", "timeout", "Connection reset", "Connection aborted",
    "Remote end closed", "Server disconnected",
)


# 进度回调类型
TransferProgressFn = Callable[[int, int, str], None]
"""progress(current_index, total, file_name) —— 在调用线程执行, 见模块 docstring"""


# ==================== minio 协议适配 ====================

class _CancellableReader:
    """包一层文件对象, 让分片上传能在**分片边界**响应取消/暂停/限速

    minio SDK 的 fput_object 内部没有取消检查点, 只能等整个文件传完。
    改为自管分片 (put_object + 我们的 reader) 后, 每次 read() 前检查取消标志,
    抛 CancelledError 打断 minio 的分片循环; minio 会自动 AbortMultipartUpload
    回收已上传的分片, 桶里不会留下半截对象。

    v0.3.0 起同一检查点兼做暂停等待与限速节流: 暂停时在分片边界阻塞
    (已建连接不拆, 恢复后续传), 限速按累计字节平滑补眠。
    """

    def __init__(self, fp, is_cancelled: Callable[[], bool],
                 is_paused: Optional[Callable[[], bool]] = None,
                 pacer: Optional[Callable[[int], None]] = None):
        self._fp = fp
        self._is_cancelled = is_cancelled
        self._is_paused = is_paused
        self._pacer = pacer

    def read(self, size: int = -1) -> bytes:
        if self._is_cancelled():
            raise CancelledError("用户取消")
        # 暂停检查点: 阻塞到恢复/取消为止 (不占 CPU, 量子轮询)
        while self._is_paused is not None and self._is_paused():
            if self._is_cancelled():
                raise CancelledError("用户取消")
            time.sleep(0.1)
        if self._is_cancelled():
            raise CancelledError("用户取消")
        data = self._fp.read(size)
        if self._pacer is not None and data:
            self._pacer(len(data))
        return data

    def close(self) -> None:
        try:
            self._fp.close()
        except Exception:  # noqa: BLE001 - 关闭失败不影响结果
            pass


class _ByteProgressAdapter:
    """适配 minio 的 progress 协议 (set_meta/update) -> 归一化为 0.0-1.0

    minio 会在**自己的上传线程**里调 update, 这里只做算术 + 写 TransferTask,
    不触发任何用户回调 (避免跨线程打到 UI)。
    """

    def __init__(self, callback: Optional[Callable[[float], None]] = None):
        self._cb = callback
        self._total = 0
        self._sent = 0

    def set_meta(self, total_length: int, object_name: str = "") -> None:
        self._total = max(0, int(total_length or 0))
        self._sent = 0

    def update(self, length: int) -> None:
        if length <= 0:
            return
        self._sent += length
        if self._cb and self._total > 0:
            self._cb(min(1.0, self._sent / self._total))


# ==================== 任务 ====================

class TransferTask:
    """单个传输任务的状态"""

    def __init__(self, operation: str, bucket: str, key: str,
                 local_path: str, size: int = 0):
        self.operation = operation
        self.bucket = bucket
        self.key = key
        self.local_path = local_path
        self.size = size
        self.task_id: str = ""
        self._cancelled = threading.Event()
        self._paused = threading.Event()
        self._completed = threading.Event()
        self.error: Optional[Exception] = None
        self.progress = 0.0

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    # ---------- 暂停 / 恢复 (Pail 借鉴: 传输队列可暂停) ----------
    # 暂停只是让传输线程在检查点等待, 已建连接不拆; cancel 优先于 pause

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def is_paused(self) -> bool:
        return self._paused.is_set()

    def is_completed(self) -> bool:
        return self._completed.is_set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._completed.wait(timeout=timeout)

    def mark_done(self, error: Optional[Exception] = None) -> None:
        # 已有错误时不覆盖: 取消时先标 CancelledError, 收尾时再标 None
        if error is not None or self.error is None:
            self.error = error
        self._completed.set()

    def update_progress(self, value: float) -> None:
        self.progress = max(0.0, min(1.0, value))


# ==================== 传输服务 ====================

class TransferService:
    """传输服务"""

    def __init__(self, locator):
        self._locator = locator
        self._tasks: Dict[str, TransferTask] = {}
        self._lock = threading.Lock()
        # 自持线程池: 与全局 4 线程池隔离, 退出时随 cleanup() 一起关
        self._executor = ThreadPoolExecutor(
            max_workers=TRANSFER_WORKERS,
            thread_name_prefix="ose-transfer",
        )
        self._executor_closed = False
        self._cancelled_all = threading.Event()
        # 全局限速 (字节/秒, None=不限); pacer 每次 read 时读取, 改动即时生效
        self._rate_bps: Optional[int] = None

    # ==================== 任务登记 ====================

    def _register(self, task: TransferTask) -> str:
        # 用 uuid 而不是 id(task): CPython 回收对象后会复用 id,
        # 不同时期两个任务可能撞号, 导致 cancel_all 误取消
        task_id = f"{task.operation}_{uuid.uuid4().hex}"
        task.task_id = task_id
        with self._lock:
            self._tasks[task_id] = task
        return task_id

    def _unregister(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    def cancel_all(self) -> None:
        """取消所有未完成任务 (文件粒度 + 分片粒度)"""
        self._cancelled_all.set()
        with self._lock:
            for task in list(self._tasks.values()):
                if not task.is_completed():
                    task.cancel()

    def _reset_cancel(self) -> None:
        self._cancelled_all.clear()

    def _is_cancelled(self, task: TransferTask) -> bool:
        return self._cancelled_all.is_set() or task.is_cancelled()

    # ==================== 暂停 / 恢复 / 限速 ====================

    def _wait_while_paused(self, task: TransferTask) -> None:
        """文件边界暂停等待: 恢复或取消才返回 (worker 线程内调用)"""
        while task.is_paused() and not self._is_cancelled(task):
            time.sleep(0.1)

    def get_task(self, task_id: str) -> Optional[TransferTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def pause_task(self, task_id: str) -> bool:
        """暂停任务 (在途任务才可暂停); 返回是否生效"""
        task = self.get_task(task_id)
        if task is None or task.is_completed():
            return False
        task.pause()
        return True

    def resume_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        task.resume()
        return True

    def set_rate_limit(self, bytes_per_sec: Optional[int]) -> None:
        """全局上传限速 (字节/秒); None 或非正值 = 不限速。

        即时生效 (pacer 每次 read 重新读取); 只约束自管分片上传路径,
        退回 core 路径的小文件不走此限速。
        """
        with self._lock:
            if bytes_per_sec is not None and bytes_per_sec <= 0:
                bytes_per_sec = None
            self._rate_bps = bytes_per_sec

    def get_rate_limit(self) -> Optional[int]:
        with self._lock:
            return self._rate_bps

    def _make_pacer(self, task: TransferTask) -> Callable[[int], None]:
        """构造限速 pacer (平滑漏桶): 按累计字节折算应耗时, 不足则补眠。

        补眠期间持续检查取消 —— 取消后立即放行, 让下一次 read() 抛
        CancelledError; 暂停不在这里处理 (reader 的 read 已有暂停检查点)。
        """
        state = {"sent": 0, "t0": time.monotonic()}

        def pace(n: int) -> None:
            with self._lock:
                bps = self._rate_bps
            if not bps or bps <= 0:
                return
            state["sent"] += n
            expected = state["t0"] + state["sent"] / bps
            while True:
                remain = expected - time.monotonic()
                if remain <= 0:
                    return
                if self._is_cancelled(task):
                    return
                time.sleep(min(0.1, remain))

        return pace

    # ---------- 在途任务观测 (供 ServiceLocator 断开时等待) ----------

    def active_count(self) -> int:
        """当前在途 (已登记未完成) 任务数"""
        with self._lock:
            return sum(1 for t in self._tasks.values() if not t.is_completed())

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """等待在途任务结束 (cancel_all 之后调用)

        Returns:
            True = 已全部结束; False = 超时仍有在途任务
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if self.active_count() == 0:
                return True
            time.sleep(0.05)
        return self.active_count() == 0

    def byte_progress_snapshot(self) -> Dict[str, float]:
        """快照: {task_id: 0.0-1.0} 当前每个在途任务的字节进度

        字节进度从 minio 内部线程更新, 不适合直接丢给 UI, 所以只提供拉取式接口。
        """
        with self._lock:
            return {tid: t.progress for tid, t in self._tasks.items()}

    # ==================== 取消 / 重试 ====================

    def _sleep_or_cancel(self, seconds: float, task: TransferTask) -> bool:
        """可被取消打断的 sleep

        Returns:
            True = 期间被取消
        """
        deadline = time.monotonic() + seconds
        while True:
            if self._is_cancelled(task):
                return True
            remain = deadline - time.monotonic()
            if remain <= 0:
                return False
            time.sleep(min(0.1, remain))

    def _is_retryable(self, exc: Exception) -> bool:
        """判断异常是否值得重试

        重试: 5xx (含 S3 5xx 错误码) + 网络类 (连接重置/超时/连接被拒)
        不重试: 4xx (AccessDenied / NoSuchKey / 签名错 等确定性失败) 和业务异常
        """
        if isinstance(exc, CancelledError):
            return False
        if isinstance(exc, (NetworkTimeoutError, ServerUnavailableError,
                            AppConnectionError)):
            return True

        # 网络类 (config.exceptions.ConnectionError 已在上方单独处理, 不含 builtin)
        if isinstance(exc, (builtins.ConnectionError, TimeoutError, socket.timeout,
                            ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError)):
            return True

        # minio / urllib3 的 HTTP 错误
        code = str(getattr(exc, "code", "") or "")
        if code in _RETRYABLE_S3_CODES:
            return True
        status = getattr(getattr(exc, "response", None), "status", None)
        if isinstance(status, int) and status >= 500:
            return True
        raw_status = getattr(exc, "status", None)
        if raw_status is not None:
            try:
                if int(raw_status) >= 500:
                    return True
            except (TypeError, ValueError):
                pass

        try:
            from urllib3.exceptions import HTTPError as _U3HTTPError
            if isinstance(exc, _U3HTTPError):
                return True
        except Exception:  # noqa: BLE001 - urllib3 缺失不影响判断
            pass

        return False

    def _is_retryable_message(self, message: str) -> bool:
        """core 把异常吃成 (False, msg) 时, 靠 msg 判断能否重试"""
        low = (message or "").lower()
        return any(marker.lower() in low for marker in _RETRYABLE_MSG_MARKERS)

    def _with_retry(
        self,
        call: Callable[[], Tuple[bool, str]],
        task: TransferTask,
    ) -> Tuple[bool, str]:
        """带指数退避 + 抖动的重试包装 (最多 MAX_ATTEMPTS 次)

        - 抛异常且异常可重试 -> 退避后重试
        - 返回 (False, msg) 且 msg 命中可重试痕迹 (core 吞了异常) -> 退避后重试
        - 4xx / 确定性失败 -> 立刻返回, 不浪费用户时间
        """
        last = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._is_cancelled(task):
                raise CancelledError("用户取消")
            try:
                ok, msg = call()
            except CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - 统一转成 (bool, str)
                if not self._is_retryable(e):
                    return False, str(e)
                last = str(e)
            else:
                if ok or not self._is_retryable_message(msg):
                    return ok, msg
                last = msg

            if attempt >= MAX_ATTEMPTS:
                break
            # 指数退避 + 抖动
            delay = (RETRY_BASE_DELAY * (2 ** (attempt - 1))
                     * (1.0 + random.random() * RETRY_JITTER))
            if self._sleep_or_cancel(delay, task):
                raise CancelledError("用户取消")

        return False, f"{last} (已重试 {MAX_ATTEMPTS} 次仍失败)"

    # ==================== 单项操作 ====================

    def _raw_minio_client(self, fm) -> Any:
        """取出底层 minio.Minio 客户端 (用于自管分片上传)

        FileManager._client -> S3ClientV1._client -> minio.Minio。
        取不到就返回 None, 调用方退回 core 的 fput_object。
        """
        try:
            s3 = getattr(fm, "_client", None)
            client = getattr(s3, "_client", None)
            if client is not None and hasattr(client, "put_object"):
                return client
        except Exception:  # noqa: BLE001 - 结构变了就退回老路径
            pass
        return None

    def _upload_one(self, fm, local_path: str, bucket: str, key: str,
                    task: TransferTask) -> Tuple[bool, str]:
        """上传单个文件 (可分片取消)"""
        if not os.path.exists(local_path):
            return False, f"文件不存在: {local_path}"

        file_size = os.path.getsize(local_path)

        # 与 core 的 FileManager.upload_file 保持一致的单文件大小限制
        resolve_limit = getattr(fm, "_resolve_upload_limit", None)
        if callable(resolve_limit):
            try:
                limit = resolve_limit()
                if limit and limit > 0 and file_size > limit:
                    return False, f"文件超过 {limit // 1024 // 1024}MB 限制"
            except Exception:  # noqa: BLE001 - 读不到限制就放行
                pass

        if not key:
            key = os.path.basename(local_path)

        client = self._raw_minio_client(fm)
        if client is None or file_size == 0:
            # 拿不到原始客户端 / 空文件: 退回 core 路径 (取消只到文件粒度)
            return fm.upload_file(
                local_path, bucket, key,
                progress=lambda p, t=task: t.update_progress(p),
            )

        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        adapter = _ByteProgressAdapter(lambda p, t=task: t.update_progress(p))
        with open(local_path, "rb") as fp:
            reader = _CancellableReader(
                fp,
                lambda t=task: self._is_cancelled(t),
                is_paused=lambda t=task: t.is_paused(),
                pacer=self._make_pacer(task),
            )
            # 异常 (含 CancelledError) 直接向上抛:
            # minio 内部会 AbortMultipartUpload 回收分片, 重试逻辑也靠它拿类型
            client.put_object(
                bucket, key, reader, file_size,
                content_type=content_type,
                progress=adapter,
            )
        return True, "上传成功"

    # ==================== 通用批处理引擎 ====================

    def _do_one(
        self,
        fm,
        item: Any,
        task: TransferTask,
        invoke: Callable[[Any, TransferTask, Any], Tuple[bool, str]],
    ) -> Tuple[bool, str]:
        """worker 线程体: 取消检查 -> 带重试执行 -> 收尾

        fm 由 _run_batch 在提交前取好并直接传进来, worker 不再回头访问
        locator, 避免 disconnect 清缓存瞬间取不到 file_manager。
        """
        try:
            if self._is_cancelled(task):
                task.mark_done(CancelledError("用户取消"))
                return False, "已取消"
            # 文件边界暂停检查点 (分片上传的中途暂停在 reader 内处理)
            self._wait_while_paused(task)
            if self._is_cancelled(task):
                task.mark_done(CancelledError("用户取消"))
                return False, "已取消"
            return self._with_retry(lambda: invoke(item, task, fm), task)
        except CancelledError as e:
            # 保留异常原文在 task.error 里, 对外统一回 "已取消"
            task.mark_done(e)
            return False, "已取消"
        except Exception as e:  # noqa: BLE001
            return False, str(e)
        finally:
            task.mark_done()
            self._unregister(task.task_id)

    def _run_batch(
        self,
        items: List[Any],
        make_task: Callable[[int], TransferTask],
        invoke: Callable[[Any, TransferTask, Any], Tuple[bool, str]],
        make_result: Callable[[int, bool, str], Dict[str, Any]],
        progress: Optional[TransferProgressFn] = None,
        name_of: Optional[Callable[[int], str]] = None,
    ) -> List[Dict[str, Any]]:
        """所有批量传输方法的公共实现

        Args:
            items: 待处理条目
            make_task: 按下标造 TransferTask
            invoke: 真正干活 (item, task, fm) -> (ok, msg)
            make_result: (index, ok, msg) -> 结果字典 (形状由各方法自己定)
            progress: 进度回调 (在**本调用线程**执行)
            name_of: 按下标取展示名, 供进度回调使用

        Returns:
            与 items 等长、顺序一致的结果列表
        """
        self._reset_cancel()
        total = len(items)
        if total == 0:
            if progress:
                progress(0, 0, "完成")
            return []

        tasks: List[TransferTask] = [make_task(i) for i in range(total)]
        for task in tasks:
            self._register(task)

        results: List[Optional[Dict[str, Any]]] = [None] * total
        completed = 0

        # 先取 fm 再提交: worker 只用这份引用, 断开竞态交给 disconnect() 等待处理
        try:
            fm = self._locator.file_manager  # type: ignore
        except Exception as e:  # noqa: BLE001 - 未连接时给每个条目一个明确原因
            msg = f"文件管理器不可用: {e}"
            for i, task in enumerate(tasks):
                task.mark_done()
                self._unregister(task.task_id)
                results[i] = make_result(i, False, msg)
            if progress:
                progress(total, total, "完成")
            return [r for r in results if r is not None]

        try:
            # 分批提交 (背压): 一批跑完再提交下一批, 不让十万级任务撑爆内存
            for start in range(0, total, SUBMIT_BATCH_SIZE):
                end = min(start + SUBMIT_BATCH_SIZE, total)

                # 已取消: 剩下的不再 submit, 直接标记
                if self._cancelled_all.is_set():
                    for i in range(start, total):
                        task = tasks[i]
                        task.mark_done(CancelledError("用户取消"))
                        self._unregister(task.task_id)
                        results[i] = make_result(i, False, "已取消")
                    break

                futures = {
                    self._executor.submit(self._do_one, fm, items[i], tasks[i],
                                          invoke): i
                    for i in range(start, end)
                }
                for fut in as_completed(futures):
                    idx = futures[fut]
                    try:
                        ok, msg = fut.result()
                    except CancelledError:
                        ok, msg = False, "已取消"
                    except Exception as e:  # noqa: BLE001
                        ok, msg = False, str(e)
                    results[idx] = make_result(idx, ok, msg)
                    completed += 1
                    if progress:
                        name = name_of(idx) if name_of else ""
                        progress(completed, total, name)
        finally:
            # 兜底: 异常路径下也不能让 task 泄漏在 _tasks 里
            leftover = [t for t in tasks if not t.is_completed()]
            if leftover:
                self.cancel_all()
                self.wait_idle(timeout=3.0)
            for task in tasks:
                if not task.is_completed():
                    task.mark_done()
                self._unregister(task.task_id)
            if progress:
                progress(total, total, "完成")

        return [r for r in results if r is not None]

    # ==================== 公开 API ====================

    def upload_files(
        self,
        bucket: str,
        prefix: str,
        file_paths: List[str],
        progress: Optional[TransferProgressFn] = None,
    ) -> List[Dict[str, Any]]:
        """批量上传 (线程池并发)

        Returns:
            [{file, key, success, message}, ...] - 顺序与 file_paths 对应
        """
        keys = [f"{prefix}{os.path.basename(p)}".replace(os.sep, "/")
                for p in file_paths]

        def make_task(i: int) -> TransferTask:
            size = (os.path.getsize(file_paths[i])
                    if os.path.exists(file_paths[i]) else 0)
            return TransferTask("upload", bucket, keys[i], file_paths[i], size=size)

        def invoke(item: str, task: TransferTask, fm) -> Tuple[bool, str]:
            return self._upload_one(fm, item, bucket, task.key, task)

        def make_result(idx: int, ok: bool, msg: str) -> Dict[str, Any]:
            return {"file": file_paths[idx], "key": keys[idx],
                    "success": ok, "message": msg}

        return self._run_batch(
            file_paths, make_task, invoke, make_result,
            progress=progress,
            name_of=lambda i: os.path.basename(file_paths[i]),
        )

    def download_files(
        self,
        bucket: str,
        keys: List[str],
        save_dir: str,
        progress: Optional[TransferProgressFn] = None,
    ) -> List[Dict[str, Any]]:
        """批量下载 (线程池并发)

        Returns:
            [{key, local_path, success, message}, ...]
        """
        os.makedirs(save_dir, exist_ok=True)
        paths = [os.path.join(save_dir, os.path.basename(k.rstrip("/")))
                 for k in keys]

        def invoke(item: str, task: TransferTask, fm) -> Tuple[bool, str]:
            return fm.download_file(
                bucket=bucket, key=item, save_path=task.local_path,
                progress=lambda p, t=task: t.update_progress(p),
            )

        def make_result(idx: int, ok: bool, msg: str) -> Dict[str, Any]:
            return {"key": keys[idx], "local_path": paths[idx],
                    "success": ok, "message": msg}

        return self._run_batch(
            keys,
            lambda i: TransferTask("download", bucket, keys[i], paths[i]),
            invoke, make_result,
            progress=progress,
            name_of=lambda i: os.path.basename(keys[i].rstrip("/")),
        )

    def download_objects(
        self,
        bucket: str,
        items: List[Tuple[str, str]],
        progress: Optional[TransferProgressFn] = None,
    ) -> List[Dict[str, Any]]:
        """批量下载到指定本地路径(支持保留目录结构)

        Args:
            bucket: 桶名
            items: [(object_key, local_full_path), ...]
            progress: 进度回调 (completed_count, total, current_filename)

        Returns:
            [{key, local_path, success, message}, ...] 顺序与 items 对应
        """
        keys = [k for k, _p in items]
        paths = [p for _k, p in items]

        def invoke(item: Tuple[str, str], task: TransferTask,
                   fm) -> Tuple[bool, str]:
            return fm.download_file(
                bucket=bucket, key=item[0], save_path=item[1],
                progress=lambda p, t=task: t.update_progress(p),
            )

        def make_result(idx: int, ok: bool, msg: str) -> Dict[str, Any]:
            return {"key": keys[idx], "local_path": paths[idx],
                    "success": ok, "message": msg}

        return self._run_batch(
            list(items),
            lambda i: TransferTask("download", bucket, keys[i], paths[i]),
            invoke, make_result,
            progress=progress,
            name_of=lambda i: os.path.basename(keys[i].rstrip("/")),
        )

    def upload_objects(
        self,
        bucket: str,
        items: List[Tuple[str, str]],
        progress: Optional[TransferProgressFn] = None,
    ) -> List[Dict[str, Any]]:
        """批量上传到指定 key (支持保留目录结构, 用于同步)

        Args:
            bucket: 桶名
            items: [(local_full_path, object_key), ...]
            progress: 进度回调 (completed_count, total, current_filename)

        Returns:
            [{file, key, success, message}, ...] 顺序与 items 对应
        """
        paths = [p for p, _k in items]
        keys = [k for _p, k in items]

        def invoke(item: Tuple[str, str], task: TransferTask,
                   fm) -> Tuple[bool, str]:
            return self._upload_one(fm, item[0], bucket, item[1], task)

        def make_result(idx: int, ok: bool, msg: str) -> Dict[str, Any]:
            return {"file": paths[idx], "key": keys[idx],
                    "success": ok, "message": msg}

        return self._run_batch(
            list(items),
            lambda i: TransferTask(
                "upload", bucket, keys[i], paths[i],
                size=os.path.getsize(paths[i]) if os.path.exists(paths[i]) else 0,
            ),
            invoke, make_result,
            progress=progress,
            name_of=lambda i: os.path.basename(paths[i]),
        )

    def delete_keys(
        self,
        bucket: str,
        keys: List[str],
        progress: Optional[TransferProgressFn] = None,
    ) -> List[Dict[str, Any]]:
        """并发删除一组对象(后台线程池,不阻塞 UI)

        Args:
            bucket: 桶名
            keys: 要删除的 key 列表(单个文件即可,文件夹会逐个)
            progress: 进度回调 (completed_count, total, current_name)
        """
        def invoke(item: str, task: TransferTask, fm) -> Tuple[bool, str]:
            return fm.delete_object(bucket, item)

        def make_result(idx: int, ok: bool, msg: str) -> Dict[str, Any]:
            return {"key": keys[idx], "success": ok, "message": msg}

        return self._run_batch(
            keys,
            lambda i: TransferTask("delete", bucket, keys[i], ""),
            invoke, make_result,
            progress=progress,
            name_of=lambda i: os.path.basename(keys[i].rstrip("/")),
        )

    def cleanup(self) -> None:
        """应用退出 / 断开连接时调用

        顺序很关键: 先取消 -> 等在途任务真正结束 -> 再关线程池。
        否则在途任务会往已关闭的 Minio 客户端上写, 报
        "ValueError: I/O operation on closed file"。
        """
        self.cancel_all()
        self.wait_idle(timeout=5.0)
        with self._lock:
            already_closed = self._executor_closed
            self._executor_closed = True
        if not already_closed:
            self._executor.shutdown(wait=False)
