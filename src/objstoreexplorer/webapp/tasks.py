# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""Web 传输任务管理 - 浏览器上传/下载打包的后台任务与进度跟踪

与桌面版 TransferService 的分工:
    - TransferService (复用): 真正的 S3 传输, 线程池 + 取消
    - WebTaskManager (本模块): 包装成可轮询的 Web 任务
        * 上传: multipart 落临时目录 → 任务上传 → 结果
        * 下载: 单文件走流式响应不经任务; 多选/文件夹 → 任务下载+打包 zip

任务状态机: running -> done / failed / cancelled
任务结果文件 (zip) 保留 TTL 秒后被清理, 超时未取视为放弃。

v0.1.0 第二轮迭代 (会话外置化): 任务注册表落 SQLite (web_tasks 表)。
内存里的 WebTask 是本 worker 的执行副本; 其他 worker 经 TaskView 只读
视图轮询/取消 (取消经 cancel_requested 标志轮询传递给执行 worker)。
结果 zip 在共享卷上, 路径全局有效 —— 多 worker 下任务不丢、可轮询。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..config.settings import TEMP_DIR
from ..core.file_manager import download_verified
from ..core.validators import sanitize_filename
from ..utils.thread_pool import get_thread_pool

logger = logging.getLogger("ose.web.tasks")

RESULT_TTL_SECONDS = 900  # 任务结果 (zip) 保留 15 分钟
TEMP_SESSION_PREFIX = "web_"
# 跨 worker 取消标志的轮询间隔 (执行线程查 DB 的节流)
CANCEL_POLL_SECONDS = 2.0
# 跨 worker 暂停/恢复标志的轮询间隔 (独立短窗口, 见 _sync_pause_flag)
PAUSE_POLL_SECONDS = 0.5
# DB 里每个任务保留的明细条数 (与 to_dict 回传口径一致)
_DB_DETAILS_KEEP = 20


class WebTask:
    """一个可轮询的 Web 任务 (本 worker 的执行副本)"""

    def __init__(self, kind: str, label: str, total: int = 0, owner: str = ""):
        self.id = uuid.uuid4().hex
        self.kind = kind  # upload / download_zip / delete
        self.label = label
        self.owner = owner  # 归属会话 ID (跨会话访问由 routes/tasks.py 校验)
        self.status = "running"  # running / done / failed / cancelled
        self.total = total
        self.current = 0
        self.current_name = ""
        self.error = ""
        self.created_at = time.time()
        self.finished_at: Optional[float] = None
        # 完成产物 (下载任务): 打包好的 zip 路径
        self.result_file: Optional[Path] = None
        self.result_name: str = ""
        # 明细: [{key/file, success, message}, ...]
        self.details: List[Dict[str, Any]] = []
        self._cancelled = threading.Event()
        self._paused = threading.Event()
        self._dir: Optional[Path] = None  # 临时工作目录

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    # ---------- 暂停 / 恢复 (Pail 借鉴; 与 cancel 同源事件模型) ----------
    # 暂停只在执行所在 worker 内存中生效; 跨 worker 暂停待后续 (cancel 已支持)

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def is_finished(self) -> bool:
        return self.status != "running"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "owner": self.owner,
            "label": self.label,
            "status": self.status,
            "total": self.total,
            "current": self.current,
            "current_name": self.current_name,
            "progress": round(self.current / self.total, 4) if self.total else 0.0,
            "paused": self.paused,
            "error": self.error,
            "details": self.details[-20:],  # 明细最多回传 20 条
            "failure_count": sum(1 for d in self.details if not d.get("success")),
            "result_ready": self.result_file is not None and self.status == "done",
            "result_name": self.result_name,
        }

    def to_db_row(self) -> Dict[str, Any]:
        """转持久化行 (web_tasks 表 upsert 用)"""
        return {
            "id": self.id,
            "owner_sid": self.owner,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "total": self.total,
            "current": self.current,
            "current_name": self.current_name,
            "error": self.error,
            "details": json.dumps(self.details[-_DB_DETAILS_KEEP:], ensure_ascii=False),
            "cancel_requested": 1 if self._cancelled.is_set() else 0,
            "result_path": str(self.result_file) if self.result_file else "",
            "result_name": self.result_name,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class TaskView:
    """跨 worker 只读任务视图 (由 web_tasks 行构造)

    与 WebTask 的路由面兼容: id/owner/kind/status/result_file/result_name/
    to_dict()/cancel()/pause/resume (v0.6.0 起经 DB 标志跨 worker 生效)。
    """

    def __init__(self, row: Dict[str, Any], persist=None):
        self._row = row
        self._persist = persist
        self.id = row["id"]
        self.owner = row["owner_sid"] or ""
        self.kind = row["kind"]
        self.label = row["label"]
        self.status = row["status"]
        self.result_name = row["result_name"] or ""
        self.created_at = float(row["created_at"] or 0)
        self._result_path = row["result_path"] or ""
        try:
            self._details = json.loads(row["details"] or "[]")
        except Exception:
            self._details = []

    @property
    def result_file(self) -> Optional[Path]:
        return Path(self._result_path) if self._result_path else None

    def cancel(self) -> None:
        """跨 worker 取消: 置 DB 标志, 执行 worker 轮询到后自行中止"""
        if self._persist is not None:
            try:
                self._persist.request_task_cancel(self.id)
            except Exception:
                logger.warning("跨 worker 取消落库失败 (task=%s)", self.id, exc_info=True)

    def to_dict(self) -> Dict[str, Any]:
        rf = self.result_file
        details = self._details if isinstance(self._details, list) else []
        total = int(self._row["total"] or 0)
        current = int(self._row["current"] or 0)
        return {
            "id": self.id,
            "kind": self.kind,
            "owner": self.owner,
            "label": self.label,
            "status": self.status,
            "total": total,
            "current": current,
            "current_name": self._row["current_name"] or "",
            "progress": round(current / total, 4) if total else 0.0,
            "paused": bool(self._row["pause_requested"]),  # v0.6.0: 跨 worker 暂停态落库透出
            "error": self._row["error"] or "",
            "details": details,
            "failure_count": sum(1 for d in details if not d.get("success")),
            "result_ready": rf is not None and self.status == "done",
            "result_name": self.result_name,
        }


class WebTaskManager:
    """Web 任务注册表: 本 worker 内存副本 + SQLite 持久层 (跨 worker 可查)"""

    def __init__(self, temp_root: Optional[Path] = None, persist=None):
        self._tasks: Dict[str, WebTask] = {}
        self._lock = threading.Lock()
        self._executor = get_thread_pool()
        self._temp_root = Path(temp_root) if temp_root else TEMP_DIR
        self._persist = persist
        self._cancel_poll_at: Dict[str, float] = {}  # task.id -> 上次查 DB 取消标志时刻
        self._pause_poll_at: Dict[str, float] = {}  # task.id -> 上次查 DB 暂停标志时刻

    # ==================== 临时目录 ====================

    def new_workdir(self, session_id: str) -> Path:
        """为任务建临时工作目录 (容器重启残留由 lifespan 启动清理兜底)"""
        d = self._temp_root / f"{TEMP_SESSION_PREFIX}{session_id[:8]}_{uuid.uuid4().hex[:8]}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ==================== 注册/查询 ====================

    def _sync(self, task: WebTask) -> None:
        """任务状态写库 (尽力而为: 落库失败只影响跨 worker 可见性)"""
        if self._persist is None:
            return
        try:
            self._persist.upsert_task(task.to_db_row())
        except Exception:
            logger.debug("任务状态落库失败 (task=%s)", task.id, exc_info=True)

    def register(self, task: WebTask, workdir: Optional[Path] = None) -> WebTask:
        if workdir is not None:
            task._dir = workdir
        with self._lock:
            self._tasks[task.id] = task
        self._sync(task)
        return task

    def get(self, task_id: str):
        """取任务: 本 worker 内存副本优先, 否则从 DB 构造只读视图"""
        with self._lock:
            task = self._tasks.get(task_id)
        if task is not None:
            return task
        if self._persist is not None:
            try:
                row = self._persist.get_task(task_id)
            except Exception:
                row = None
            if row is not None:
                return TaskView(row, persist=self._persist)
        return None

    def list_for_session(self) -> List[Any]:
        """列出全部任务 (内存副本 + DB 视图去重合并, 按创建时间倒序);
        会话隔离/role 过滤由调用方 (routes/tasks.py) 保证"""
        with self._lock:
            local = list(self._tasks.values())
        merged: Dict[str, Any] = {t.id: t for t in local}
        if self._persist is not None:
            try:
                for row in self._persist.list_tasks(limit=200):
                    if row["id"] not in merged:
                        merged[row["id"]] = TaskView(row, persist=self._persist)
            except Exception:
                logger.debug("任务列表落库读取失败", exc_info=True)
        return sorted(merged.values(), key=lambda t: t.created_at, reverse=True)

    # ==================== 取消 (本地事件 + 跨 worker 标志) ====================

    def _should_stop(self, task: WebTask) -> bool:
        """执行线程逐项检查: 本地取消事件, 或 (节流) 其他 worker 的取消标志"""
        if task.cancelled:
            return True
        now = time.monotonic()
        if now - self._cancel_poll_at.get(task.id, 0.0) < CANCEL_POLL_SECONDS:
            return False
        self._cancel_poll_at[task.id] = now
        if self._persist is None:
            return False
        try:
            if self._persist.is_task_cancel_requested(task.id):
                task.cancel()
                return True
        except Exception:
            pass
        return False

    def _sync_pause_flag(self, task: WebTask, force: bool = False) -> None:
        """从 DB 同步跨 worker 暂停/恢复标志到本地事件 (独立 0.5s 节流)

        独立于取消的 2s 节流窗口: 暂停等待是 0.1s 量子循环, 若复用 2s 节流,
        每个文件都快于 2s 完成时检查点永远撞在节流窗里, 跨 worker 暂停将
        永远不生效 (2026-11-18 测试实测暴露, 故独立窗口 + 边界强制同步)。
        """
        if self._persist is None:
            return
        now = time.monotonic()
        if not force and now - self._pause_poll_at.get(task.id, 0.0) < PAUSE_POLL_SECONDS:
            return
        self._pause_poll_at[task.id] = now
        try:
            if self._persist.is_task_pause_requested(task.id):
                task.pause()
            else:
                task.resume()
        except Exception:
            pass

    def _wait_while_paused(self, task: WebTask) -> None:
        """文件边界暂停等待: 入口强制同步一次 DB 标志 (能发现上边界之后到达的
        暂停请求), 等待中再按 0.5s 窗口轮询恢复请求; 恢复或取消才返回"""
        self._sync_pause_flag(task, force=True)
        while task.paused and not self._should_stop(task):
            self._sync_pause_flag(task)
            time.sleep(0.1)

    # ==================== 同名冲突策略 (Pail 借鉴 #4) ====================

    def _apply_conflict(self, fm, bucket: str, key: str, conflict: str,
                        task: WebTask, rel: str) -> Optional[str]:
        """上传前同名冲突检查点 (overwrite 策略不经过此函数)。

        返回实际上传 key; skip 命中已存在时记明细并返回 None (调用方跳过)。
        rename 命中时换 name(n).ext 首个空闲名。存在性检查不可用时按原
        行为 (覆盖) 上传——检查点故障不拒绝上传, 如实降级。
        """
        try:
            exists = fm.exists(bucket, key)
        except Exception:
            logger.debug(
                "冲突检查点 exists 调用失败, 按覆盖处理 (task=%s key=%s)",
                task.id, key, exc_info=True)
            return key
        if not exists:
            return key
        if conflict == "skip":
            task.details.append({"file": rel, "key": key, "success": True,
                                 "message": "已存在, 按策略跳过 (未上传)"})
            return None
        if conflict == "rename":
            return self._renamed_key(fm, bucket, key)
        return key  # 未知策略兜底: 与 overwrite 一致

    @staticmethod
    def _renamed_key(fm, bucket: str, key: str) -> str:
        """找首个空闲的 name(1).ext / name(2).ext… (与本地暂存去重同约定);
        连续 100 次撞名则退回原 key (覆盖语义兜底, 不死循环)"""
        head, sep, last = key.rpartition("/")
        stem, dot, ext = last.rpartition(".")
        for n in range(1, 101):
            cand_last = f"{stem}({n}){dot}{ext}" if dot else f"{last}({n})"
            cand = f"{head}{sep}{cand_last}" if sep else cand_last
            try:
                if not fm.exists(bucket, cand):
                    return cand
            except Exception:
                break
        return key

    # ==================== 任务执行 ====================

    def run_upload(
        self,
        task: WebTask,
        session,  # WebSession (鸭子类型 file_manager)
        bucket: str,
        prefix: str,
        file_paths: List[Path],
        rel_paths: Optional[List[str]] = None,
        conflict: str = "overwrite",
    ) -> None:
        """后台执行批量上传 (串行逐个, 进度按文件计数)

        rel_paths: 与 file_paths 等长的对象 key 相对路径列表 (文件夹结构上传);
        为 None 时保持旧行为, 按暂存文件名平铺入桶。
        conflict: 同名冲突策略 (v0.5.0, Pail 借鉴 #4) —— overwrite=直接覆盖
        (默认, 与历史行为一致) / skip=已存在则跳过 / rename=自动加 (n) 后缀。
        """

        def _progress(cur: int, total: int, name: str) -> None:
            task.current = min(cur, total)
            task.current_name = name

        def _do() -> None:
            try:
                fm = session.file_manager
                prefix_norm = prefix if (not prefix or prefix.endswith("/")) else prefix + "/"
                for i, fp in enumerate(file_paths):
                    self._wait_while_paused(task)
                    if self._should_stop(task):
                        break
                    rel = rel_paths[i] if rel_paths and i < len(rel_paths) else fp.name
                    key = f"{prefix_norm}{rel}".replace(os.sep, "/")
                    if conflict != "overwrite":
                        key = self._apply_conflict(fm, bucket, key, conflict,
                                                   task, rel)
                        if key is None:  # skip: 已存在, 记明细后继续下一个
                            _progress(i + 1, task.total, rel)
                            self._sync(task)
                            continue
                    ok, msg = fm.upload_file(str(fp), bucket, key)
                    task.details.append(
                        {"file": rel, "key": key, "success": ok, "message": msg}
                    )
                    _progress(i + 1, task.total, rel)
                    self._sync(task)  # 进度落库 (跨 worker 轮询可见)
                task.status = "cancelled" if task.cancelled else "done"
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
            finally:
                task.finished_at = time.time()
                self._sync(task)
                self._cancel_poll_at.pop(task.id, None)
                self._cleanup_workdir(task)

        self._executor.submit(_do)

    def run_download_zip(
        self,
        task: WebTask,
        session,
        bucket: str,
        keys: List[str],
    ) -> None:
        """后台执行: 下载选中对象 (保留目录结构) → 打包 zip

        H-02: 以 `/` 结尾的 key 是**文件夹占位对象**, 旧实现直接当文件下载,
        落盘只有一个 0 字节文件 —— 用户下到的 zip 里"文件夹是空的"。
        这里先把文件夹 list 展开成真正的子 key 再逐个下载, 并同步修正
        task.total (展开在任务线程里做, 所以 total 会在开跑后不久才准确)。
        """

        def _progress(cur: int, total: int, name: str) -> None:
            task.current = min(cur, total)
            task.current_name = name

        def _do() -> None:
            try:
                fm = session.file_manager
                workdir = task._dir or self.new_workdir("dl")
                content_dir = workdir / "content"
                content_dir.mkdir(parents=True, exist_ok=True)

                # ---- 展开: 文件夹 → 子 key 列表 (不带条数上限, 要下全) ----
                expanded: List[str] = []
                for key in keys:
                    if key.endswith("/"):
                        ok, names = fm.expand_folder_keys(bucket, key)
                        if not ok:
                            task.details.append(
                                {"key": key, "success": False, "message": names}
                            )
                            continue
                        if not names:
                            task.details.append(
                                {"key": key, "success": False,
                                 "message": "文件夹为空或不存在"}
                            )
                            continue
                        expanded.extend(names)
                    else:
                        expanded.append(key)

                task.total = len(expanded)

                failed_any = False
                for i, key in enumerate(expanded):
                    self._wait_while_paused(task)
                    if self._should_stop(task):
                        break
                    rel = key.rstrip("/")
                    dest = (content_dir / rel).resolve()
                    # 防路径穿越: 解析后必须仍在 content_dir 内
                    # (is_relative_to 精确到目录边界, 修复 startswith 的兄弟前缀绕过)
                    if not dest.is_relative_to(content_dir.resolve()):
                        task.details.append(
                            {"key": key, "success": False, "message": "非法对象 key"}
                        )
                        failed_any = True
                        _progress(i + 1, task.total, key)
                        self._sync(task)
                        continue
                    ok, msg = download_verified(fm, bucket, key, str(dest))
                    task.details.append(
                        {"key": key, "success": ok, "message": msg}
                    )
                    if not ok:
                        failed_any = True
                    _progress(i + 1, task.total, key)
                    self._sync(task)

                if task.cancelled:
                    task.status = "cancelled"
                    task.finished_at = time.time()
                    self._sync(task)
                    self._cancel_poll_at.pop(task.id, None)
                    self._cleanup_workdir(task)
                    return

                # 打包
                # v0.1.0 加固: bucket 来自请求体, 未校验即拼本地路径会被
                # "../" 穿出临时目录 —— 先清洗成安全文件名再拼路径
                safe_bucket = sanitize_filename(bucket or "bucket")[:80] or "bucket"
                zip_path = workdir / f"{safe_bucket}.zip"
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for p in sorted(content_dir.rglob("*")):
                        if p.is_file():
                            zf.write(p, p.relative_to(content_dir).as_posix())

                task.result_file = zip_path
                task.result_name = f"{safe_bucket}_download.zip"
                task.status = "done"
                if failed_any:
                    task.error = "部分对象下载失败, 详情见明细"
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
            finally:
                task.finished_at = time.time()
                self._sync(task)
                self._cancel_poll_at.pop(task.id, None)
                # zip 保留 TTL 供前端取走; content 目录可立即清理
                try:
                    if task._dir is not None:
                        content = task._dir / "content"
                        if content.exists():
                            shutil.rmtree(content, ignore_errors=True)
                except Exception:
                    pass

        self._executor.submit(_do)

    def run_delete(
        self,
        task: WebTask,
        session,
        bucket: str,
        keys: List[str],
    ) -> None:
        """后台执行批量删除

        C-01: S3 里"文件夹"只是以 `/` 结尾的 0 字节占位对象。旧实现把所有
        key 一视同仁交给 transfer.delete_keys, 于是删文件夹只删掉了那个
        占位符, 里面的文件全部留在桶里 (界面还显示"删除成功")。
        这里按 key 是否以 `/` 结尾分流:
            - 文件夹 → FileManager.delete_folder (内部 list 展开 + 批量删)
            - 文件   → transfer.delete_keys (线程池并发)
        每批 200 条, 批间检查取消 (H-06)。

        H-06: 旧实现整批一次性交给同步聚合接口, 取消标志在任务线程里根本
        没有检查点 —— 点"取消"后任务照跑完, 还照样报 success。现在每批
        之前查 _should_stop (本地取消事件 + 跨 worker DB 标志), 取消即停,
        未处理的条目如实记"已取消", 不再报 success。
        """

        def _progress(cur: int, total: int, name: str) -> None:
            task.current = min(cur, total)
            task.current_name = name

        # 每批删除的 key 数 (与 TransferService.SUBMIT_BATCH_SIZE 同口径)
        BATCH = 200

        def _do() -> None:
            details: List[Dict[str, Any]] = []
            cancelled = False
            try:
                fm = session.file_manager
                folders = [k for k in keys if k.endswith("/")]
                files = [k for k in keys if not k.endswith("/")]
                # total 按"选中的条目"计 (文件夹算 1 条, 内部对象数由明细体现)
                task.total = max(task.total, len(keys))
                done = 0

                for start in range(0, len(files), BATCH):
                    if self._should_stop(task):
                        cancelled = True
                        break
                    batch = files[start:start + BATCH]
                    base = done
                    res = session.transfer.delete_keys(
                        bucket, batch,
                        progress=lambda cur, total, name, _b=base: _progress(
                            _b + cur, task.total, name),
                    )
                    details.extend(res)
                    done += len(batch)
                    _progress(done, task.total, "")
                    self._sync(task)

                if not cancelled:
                    for prefix in folders:
                        if self._should_stop(task):
                            cancelled = True
                            break
                        ok, msg = fm.delete_folder(bucket, prefix)
                        details.append({
                            "key": prefix, "success": ok, "message": msg,
                        })
                        done += 1
                        _progress(done, task.total, prefix)
                        self._sync(task)

                if cancelled:
                    # 未处理的条目如实记录, 不假装删过
                    handled = {d.get("key") for d in details}
                    for k in files + folders:
                        if k not in handled:
                            details.append({
                                "key": k, "success": False,
                                "message": "已取消, 未处理",
                            })
            except Exception as e:
                task.details = details
                task.status = "failed"
                task.error = str(e)
            else:
                task.details = details
                if cancelled or task.cancelled:
                    task.status = "cancelled"
                else:
                    task.status = "done"
                failed = sum(1 for d in details if not d.get("success"))
                if failed:
                    task.error = f"部分删除失败 ({failed} 项), 详情见明细"
            finally:
                task.finished_at = time.time()
                self._sync(task)
                self._cancel_poll_at.pop(task.id, None)

        self._executor.submit(_do)

    def cancel(self, task_id: str) -> bool:
        """取消任务: 本 worker 副本直接置事件, 跨 worker 经 DB 标志传递"""
        task = self.get(task_id)
        if task is None:
            return False
        task.cancel()
        if isinstance(task, WebTask) and self._persist is not None:
            # 本地取消也同步落库, 让其他 worker 的轮询口径一致
            self._sync(task)
        return True

    # ==================== 暂停 / 恢复 ====================

    def pause_task(self, task_id: str) -> bool:
        """暂停任务: 本 worker 副本置事件 + 落库; 跨 worker 视图仅落库标志
        (执行方轮询到后自行暂停, v0.6.0 起支持)"""
        task = self.get(task_id)
        if task is None:
            return False
        is_local = isinstance(task, WebTask)
        if is_local and task.is_finished:
            return False
        if is_local:
            task.pause()
        if self._persist is not None:
            try:
                self._persist.request_task_pause(task_id)
            except Exception:
                logger.warning("跨 worker 暂停落库失败 (task=%s)", task_id,
                               exc_info=True)
                if not is_local:
                    return False  # 视图只有 DB 一条路, 落库失败如实失败
        return True

    def resume_task(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        if isinstance(task, WebTask):
            task.resume()
        if self._persist is not None:
            try:
                self._persist.request_task_resume(task_id)
            except Exception:
                logger.warning("跨 worker 恢复落库失败 (task=%s)", task_id,
                               exc_info=True)
        return True

    # ==================== 清理 ====================

    def _cleanup_workdir(self, task: WebTask) -> None:
        """清理任务临时目录 (done 的下载任务保留 zip 文件本身)"""
        if task._dir is None or not task._dir.exists():
            return
        try:
            if task.kind == "download_zip" and task.status == "done" and task.result_file:
                for child in task._dir.iterdir():
                    if child != task.result_file:
                        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
            else:
                shutil.rmtree(task._dir, ignore_errors=True)
                task._dir = None
        except Exception:
            pass

    def expire_results(self) -> int:
        """清理超时的已完成任务与其结果文件 (lifespan 定时调用)

        同时清理持久层: 完成/取消超 TTL 的行 + 超过 24h 无终态的孤儿行
        (worker 被强杀时 running 行没有终态落库)。多 worker 并发执行幂等。
        """
        now = time.time()
        expired: List[str] = []
        with self._lock:
            for tid, t in self._tasks.items():
                if t.is_finished and t.finished_at and now - t.finished_at > RESULT_TTL_SECONDS:
                    expired.append(tid)
        n = 0
        for tid in expired:
            with self._lock:
                t = self._tasks.pop(tid, None)
            if t is not None:
                try:
                    if t._dir and t._dir.exists():
                        shutil.rmtree(t._dir, ignore_errors=True)
                except Exception:
                    pass
                n += 1
        # 持久层孤儿行清理 (失败只影响 DB 空间, 不影响功能)
        if self._persist is not None:
            try:
                self._persist.purge_tasks(
                    RESULT_TTL_SECONDS, stale_running_seconds=24 * 3600,
                )
            except Exception:
                logger.debug("任务行清理失败", exc_info=True)
        return n

    def cleanup_session_files(self, session_id: str) -> None:
        """会话销毁时清理其临时目录"""
        root = self._temp_root
        if not root.exists():
            return
        prefix = f"{TEMP_SESSION_PREFIX}{session_id[:8]}"
        try:
            for child in root.glob(f"{prefix}*"):
                shutil.rmtree(child, ignore_errors=True)
        except Exception:
            pass

    def cleanup_stale_dirs(self, max_age_seconds: float = 7200) -> int:
        """兜底清理陈旧临时目录 (v0.1.0 新增)。

        正常路径 (任务完成/超时/会话销毁) 之外仍有两类残留:
          1) 单文件下载依赖 FileResponse 的 BackgroundTask 删目录, 客户端
             中途断开时响应发送中断, 后台任务不执行;
          2) 任务线程异常卡死, 目录永远等不到清理。
        由 lifespan 清理循环每分钟扫描: 目录修改时间早于 max_age_seconds
        的 web_* 工作目录一律删除。返回清理数量。
        """
        root = self._temp_root
        if not root.exists():
            return 0
        now = time.time()
        n = 0
        try:
            for child in root.glob(f"{TEMP_SESSION_PREFIX}*"):
                if not child.is_dir():
                    continue
                try:
                    age = now - child.stat().st_mtime
                except OSError:
                    continue
                if age > max_age_seconds:
                    shutil.rmtree(child, ignore_errors=True)
                    n += 1
        except Exception:
            pass
        return n
