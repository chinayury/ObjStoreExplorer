# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""services/sync_service - 本地与对象存储双向同步

核心模型:
  - 用相对路径 (rel_path) 作为匹配 key (本地路径转 S3 key)
  - 一次同步三步: 1) 扫描差异 2) 用户解决冲突 3) 执行 (上传/下载/删除)

支持的方向:
  - push:   本地 -> 远端 (新增的传, 内容不同的覆盖, 远端多余的保留)
  - pull:   远端 -> 本地 (新增的下, 内容不同的覆盖, 本地多余的保留)
  - mirror: 双向 (rsync 语义, 包含 --delete)

差异比较 (按 rel_path 匹配后):
  - size 不同 -> 直接冲突
  - size 相同 -> 比对 ETag 与本地 MD5 (分块计算); 一致才跳过
  - ETag 不可用 (分片上传的 "xxx-N" 或缺失) -> 退回 mtime 容差
"""
from __future__ import annotations
import hashlib
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple


# ==================== 本地 MD5 辅助 ====================

# 分块计算 MD5 的块大小 (8MB): 足够摊薄磁盘 IO, 又不会把大文件整个读进内存
_MD5_CHUNK = 8 * 1024 * 1024

# (path, size, mtime) -> md5 hex 的小缓存, 避免同一版本文件被反复哈希
_md5_cache: Dict[Tuple[str, int, float], str] = {}
_md5_lock = threading.Lock()
_MD5_CACHE_MAX = 512


def file_md5(path: str) -> str:
    """分块计算本地文件 MD5 (大文件不会整体读入内存)

    同一 (path, size, mtime) 走缓存, 文件一变 (mtime 变) 缓存自动失效。
    """
    try:
        st = os.stat(path)
    except OSError:
        return ""

    cache_key = (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime)
    with _md5_lock:
        cached = _md5_cache.get(cache_key)
    if cached:
        return cached

    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                block = f.read(_MD5_CHUNK)
                if not block:
                    break
                h.update(block)
    except OSError:
        return ""
    digest = h.hexdigest()

    with _md5_lock:
        if len(_md5_cache) >= _MD5_CACHE_MAX:
            _md5_cache.clear()
        _md5_cache[cache_key] = digest
    return digest


# ==================== 数据类 ====================


class Direction(str, Enum):
    PUSH = "push"     # local -> remote
    PULL = "pull"     # remote -> local
    MIRROR = "mirror"  # 双向


@dataclass
class LocalEntry:
    """本地文件元数据"""
    path: str           # 绝对路径
    rel: str            # 相对 local_dir 的路径 (用 / 分隔)
    size: int
    mtime: float        # mtime (epoch seconds)


@dataclass
class RemoteEntry:
    """远端对象元数据"""
    key: str            # S3 key
    rel: str            # 相对 prefix 的路径 (用 / 分隔)
    size: int
    last_modified: Optional[datetime]
    etag: str = ""


@dataclass
class SyncConflict:
    """一个冲突项: 两端都有但内容不同"""
    rel: str
    local: LocalEntry
    remote: RemoteEntry

    @property
    def local_size(self) -> int:
        return self.local.size

    @property
    def remote_size(self) -> int:
        return self.remote.size

    @property
    def local_mtime(self) -> datetime:
        return datetime.fromtimestamp(self.local.mtime)

    @property
    def remote_mtime_str(self) -> str:
        return self.remote.last_modified.isoformat() if self.remote.last_modified else "未知"


# 冲突解决结果
RESOLVE_USE_LOCAL = "use_local"   # 上传覆盖远端
RESOLVE_USE_REMOTE = "use_remote"  # 下载覆盖本地
RESOLVE_SKIP = "skip"             # 跳过
RESOLVE_CANCEL = "cancel"         # 取消整次同步


@dataclass
class SyncPlan:
    """一次同步的计划 (compute_plan 输出, 不含 I/O)"""
    to_upload: List[Tuple[str, str]] = field(default_factory=list)
    """[(local_path, remote_key), ...] 本地 -> 远端 (新增 + 解决冲突用本地)"""

    to_download: List[Tuple[str, str]] = field(default_factory=list)
    """[(remote_key, local_path), ...] 远端 -> 本地 (新增 + 解决冲突用远端)"""

    to_delete_remote: List[str] = field(default_factory=list)
    """[remote_key, ...] mirror 模式: 远端有, 本地无"""

    to_delete_local: List[str] = field(default_factory=list)
    """[local_path, ...] mirror 模式: 本地有, 远端无; 或 push 模式 + 删源选项"""

    conflicts: List[SyncConflict] = field(default_factory=list)
    """待用户逐个确认的冲突"""

    skipped: int = 0
    """扫描阶段判定两端内容一致, 无需处理的条目数"""

    def summary(self) -> str:
        return (
            f"待上传 {len(self.to_upload)} 个, 待下载 {len(self.to_download)} 个, "
            f"待删远端 {len(self.to_delete_remote)} 个, 待删本地 {len(self.to_delete_local)} 个, "
            f"冲突 {len(self.conflicts)} 个, 跳过 {self.skipped} 个"
        )


@dataclass
class SyncResult:
    """执行结果"""
    uploaded: int = 0
    download_failed: int = 0
    upload_failed: int = 0
    deleted_remote: int = 0
    deleted_local: int = 0
    download_ok: int = 0
    upload_ok: int = 0
    skipped: int = 0
    cancelled: bool = False
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.cancelled:
            return f"已取消 (上传成功 {self.upload_ok}, 下载成功 {self.download_ok}, 跳过 {self.skipped})"
        parts = [
            f"上传 {self.upload_ok}/{self.upload_ok + self.upload_failed}",
            f"下载 {self.download_ok}/{self.download_ok + self.download_failed}",
        ]
        if self.deleted_remote:
            parts.append(f"删远端 {self.deleted_remote}")
        if self.deleted_local:
            parts.append(f"删本地 {self.deleted_local}")
        if self.skipped:
            parts.append(f"跳过 {self.skipped}")
        return ", ".join(parts)


# ==================== 核心服务 ====================


class SyncService:
    """同步服务"""

    # mtime 容差 (秒): S3 last_modified 精度 + 时区差异, 2s 足够吸收
    MTIME_TOLERANCE = 2.0

    def __init__(self, locator):
        self._locator = locator

    # ---------- 扫描 ----------

    def scan_local(
        self,
        local_dir: str,
        prefix: str = "",  # 仅在文档中说明, 内部不参与 rel 计算
        recursive: bool = True,
    ) -> Dict[str, LocalEntry]:
        """扫描本地目录, 返回 {rel: LocalEntry}

        rel = 相对 local_dir 的路径, **不带** prefix (prefix 在 compute_plan 时拼上)
        """
        result: Dict[str, LocalEntry] = {}
        if not os.path.isdir(local_dir):
            return result

        if recursive:
            for root, dirs, files in os.walk(local_dir):
                rel_root = os.path.relpath(root, local_dir)
                if rel_root == ".":
                    base = ""
                else:
                    base = rel_root.replace(os.sep, "/") + "/"

                for f in files:
                    full = os.path.join(root, f)
                    rel = base + f
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    result[rel] = LocalEntry(
                        path=full, rel=rel, size=st.st_size, mtime=st.st_mtime,
                    )
        else:
            for f in os.listdir(local_dir):
                full = os.path.join(local_dir, f)
                if not os.path.isfile(full):
                    continue
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                result[f] = LocalEntry(
                    path=full, rel=f, size=st.st_size, mtime=st.st_mtime,
                )
        return result

    def scan_remote(
        self,
        bucket: str,
        prefix: str = "",
        recursive: bool = True,
    ) -> Dict[str, RemoteEntry]:
        """扫描远端 prefix 下所有对象, 返回 {rel: RemoteEntry}

        ⚠ max_items=0 (不限制): 同步必须看到**全量**对象。FileManager.
        list_objects 的默认上限是 MAX_LIST_ITEMS(1000), 不显式放开的话
        大桶只会同步前 1000 个对象, 静默漏数据。
        """
        result: Dict[str, RemoteEntry] = {}
        fm = self._locator.file_manager  # type: ignore

        ok, objs = fm.list_objects(bucket, prefix=prefix, recursive=recursive,
                                   max_items=0)
        if not ok or not isinstance(objs, list):
            return result

        norm_prefix = self._norm_prefix(prefix)

        for obj in objs:
            full_key = obj.get("name", "")
            is_dir = obj.get("is_dir", False)
            if is_dir or not full_key or full_key.endswith("/"):
                continue

            # 防御性: S3 通常会按 prefix 过滤, 但万一 mock/老版本不严格, 这里再过滤一次
            if norm_prefix and not full_key.startswith(norm_prefix):
                continue

            rel = full_key[len(norm_prefix):] if norm_prefix else full_key
            if not rel:
                continue

            result[rel] = RemoteEntry(
                key=full_key,
                rel=rel,
                size=obj.get("size", 0) or 0,
                last_modified=obj.get("last_modified"),
                etag=obj.get("etag", "") or "",
            )
        return result

    # ---------- 差异计算 ----------

    def compute_plan(
        self,
        direction: Direction,
        local_dir: str,
        bucket: str,
        prefix: str = "",
        recursive: bool = True,
    ) -> SyncPlan:
        """计算同步计划 (不执行 I/O, 只算差异)

        Args:
            direction: PUSH / PULL / MIRROR
            local_dir: 本地目录
            bucket: 远端桶
            prefix: 远端 prefix
            recursive: 是否递归子目录/sub-prefix
        """
        local = self.scan_local(local_dir, prefix=prefix, recursive=recursive)
        remote = self.scan_remote(bucket, prefix=prefix, recursive=recursive)

        plan = SyncPlan()
        all_rels = set(local.keys()) | set(remote.keys())

        for rel in all_rels:
            l = local.get(rel)
            r = remote.get(rel)

            if l and not r:
                # 仅本地
                if direction in (Direction.PUSH, Direction.MIRROR):
                    remote_key = self._join_key(prefix, rel)
                    plan.to_upload.append((l.path, remote_key))
                # PULL 模式: 本地多余保留 (不处理)

            elif r and not l:
                # 仅远端
                if direction in (Direction.PULL, Direction.MIRROR):
                    local_path = os.path.join(
                        local_dir, rel.replace("/", os.sep),
                    )
                    plan.to_download.append((r.key, local_path))
                else:
                    # PUSH 模式: 远端多余的保留
                    pass

            else:
                # 两端都有, 检查内容是否一致
                if self._is_same_content(l, r):
                    plan.skipped += 1
                    continue
                # 冲突
                plan.conflicts.append(SyncConflict(
                    rel=rel, local=l, remote=r,
                ))

        # Mirror: 双向收敛 (rsync --delete 语义, 以本地为基准)
        #   - 远端有本地无 -> 删远端
        #   - 本地有远端无 -> 已进 to_upload 推到远端; **不删本地** (本地是基准端,
        #     也没有"删源"语义 —— 删源是 execute_plan(delete_source=True) 的显式选项)
        # v0.1.0 第二轮修复: 旧实现把本地多余文件同时登记进 to_delete_local,
        # 但这些文件必然也在 to_upload 里, execute_plan 的删本地护栏
        # (上传队列中的文件不删) 会把它们全部跳过 —— 登记是死代码, 且让
        # 桌面版同步预览 (ui/windows/sync_dialog) 显示永远不会执行的"× 删本地"
        # 行, 并导致 test_compute_plan_mirror 断言失败。此处保持
        # to_delete_local 为空, 与执行语义/预览语义一致。
        if direction == Direction.MIRROR:
            plan.to_delete_remote = [
                remote[r].key for r in (set(remote.keys()) - set(local.keys()))
            ]

        return plan

    def _is_same_content(self, l: LocalEntry, r: RemoteEntry) -> bool:
        """判断两端内容是否一致

        判定顺序:
          1. size 不同 -> 一定不同
          2. size 相同 -> 用远端 ETag 与本地 MD5 权威比对 (单次上传的 ETag 即内容 MD5)
          3. ETag 拿不到 (分片上传 "xxx-N" / 缺失) -> 退回 mtime 容差 (快速路径)
        """
        if l.size != r.size:
            return False

        # 2) ETag 权威比对: 避免"用户改了内容但 mtime 没差"导致改动被静默丢弃
        remote_etag = self._normalize_etag(r.etag)
        if remote_etag:
            local_etag = file_md5(l.path)
            if local_etag:
                return local_etag == remote_etag

        # 3) 无 ETag 可比 -> 退回 mtime 容差
        if r.last_modified is None:
            return False
        remote_ts = r.last_modified.timestamp()
        return abs(l.mtime - remote_ts) < self.MTIME_TOLERANCE

    @staticmethod
    def _normalize_etag(etag: str) -> str:
        """规范化 ETag: 去引号/连字符大写; 分片上传的 "xxx-N" 与空值视为不可用"""
        if not etag:
            return ""
        e = etag.strip().strip('"').replace("-", "").lower()
        # 分片 ETag 无法和单文件 MD5 直接比, 长度也不等于 32 位 MD5
        if len(e) != 32 or "-" in etag:
            return ""
        return e

    # ---------- 执行 ----------

    def execute_plan(
        self,
        plan: SyncPlan,
        bucket: str,
        delete_source: bool = False,
        delete_remote_extras: bool = False,
        conflict_resolver: Optional[Callable[[SyncConflict], str]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> SyncResult:
        """执行同步计划 (后台线程池)

        Args:
            plan: compute_plan 输出的计划
            bucket: 目标桶
            delete_source: 推送成功后删除本地源 (PUSH/MIRROR 模式意义大)
            delete_remote_extras: 删除远端多余 (MIRROR 模式)
            conflict_resolver: 冲突解决回调, 返回 RESOLVE_* 常量
                - 同步执行时, 此回调会**在主线程被调**, 因为需要弹窗
                - 这里强制主线程弹窗, 实际调用方应在主线程包装
            progress_cb: (current, total, name)
        """
        result = SyncResult()

        # 扫描阶段就判定一致的条目, 直接计入跳过
        result.skipped += plan.skipped

        # 处理冲突 (如果 callback 给出, 否则跳过)
        if plan.conflicts:
            if conflict_resolver is None:
                # 没有 resolver, 全部跳过
                result.skipped += len(plan.conflicts)
                plan.conflicts = []
            else:
                self._resolve_conflicts(plan, conflict_resolver, result)

        # 用户在冲突弹窗里选了"取消": _resolve_conflicts 已清空所有待办,
        # 这里必须早退, 否则会继续跑上传/下载阶段
        if result.cancelled:
            return result

        # 1) 上传
        if plan.to_upload:
            upload_results = self._locator.transfer.upload_objects(
                bucket, plan.to_upload, progress=progress_cb,
            )
            for r in upload_results:
                if r["success"]:
                    result.upload_ok += 1
                    # delete_source: 推送成功后删本地
                    if delete_source and os.path.exists(r["file"]):
                        try:
                            os.remove(r["file"])
                            result.deleted_local += 1
                        except OSError as e:
                            result.errors.append(f"删源失败 {r['file']}: {e}")
                else:
                    result.upload_failed += 1
                    result.errors.append(f"上传失败 {r['file']}: {r['message']}")

        # 2) 下载
        if plan.to_download:
            download_results = self._locator.transfer.download_objects(
                bucket, plan.to_download, progress=progress_cb,
            )
            for r in download_results:
                if r["success"]:
                    result.download_ok += 1
                else:
                    result.download_failed += 1
                    result.errors.append(f"下载失败 {r['key']}: {r['message']}")

        # 3) 删远端多余
        if delete_remote_extras and plan.to_delete_remote:
            del_results = self._locator.transfer.delete_keys(
                bucket, plan.to_delete_remote, progress=progress_cb,
            )
            for r in del_results:
                if r["success"]:
                    result.deleted_remote += 1
                else:
                    result.errors.append(f"删远端失败 {r['key']}: {r['message']}")

        # 4) 删本地多余 (mirror 模式或推送后删源)
        if plan.to_delete_local:
            # 安全护栏: 本轮已排进上传队列的本地文件不能删, 否则
            # "上传成功 -> 立刻被自己删掉", 本地和远端同时丢数据
            protected = {
                os.path.normcase(os.path.abspath(p)) for p, _k in plan.to_upload
            }
            for path in plan.to_delete_local:
                try:
                    if os.path.normcase(os.path.abspath(path)) in protected:
                        continue
                    if os.path.isfile(path):
                        os.remove(path)
                        result.deleted_local += 1
                    elif os.path.isdir(path):
                        # 删空目录
                        try:
                            shutil.rmtree(path)
                            result.deleted_local += 1
                        except OSError:
                            # 非空不删, 跳过
                            pass
                except OSError as e:
                    result.errors.append(f"删本地失败 {path}: {e}")

        return result

    def _resolve_conflicts(
        self,
        plan: SyncPlan,
        resolver: Callable[[SyncConflict], str],
        result: SyncResult,
    ) -> None:
        """逐个调用 resolver 解决冲突, 把结果归入 to_upload / to_download"""
        remaining = []
        for conflict in plan.conflicts:
            action = resolver(conflict)
            if action == RESOLVE_CANCEL:
                result.cancelled = True
                # 取消整次同步: 丢掉此前已累积的待办条目。
                # 之前只置标志不清空, execute_plan 会照常把已累积的项传完
                plan.to_upload.clear()
                plan.to_download.clear()
                plan.to_delete_remote.clear()
                plan.to_delete_local.clear()
                plan.conflicts = []
                return
            elif action == RESOLVE_USE_LOCAL:
                plan.to_upload.append((conflict.local.path, conflict.remote.key))
            elif action == RESOLVE_USE_REMOTE:
                plan.to_download.append((conflict.remote.key, conflict.local.path))
            else:  # SKIP
                result.skipped += 1
        plan.conflicts = remaining

    # ---------- 工具 ----------

    @staticmethod
    def _norm_prefix(prefix: str) -> str:
        """标准化 prefix: 空 -> ''; 否则确保以 / 结尾, 且使用 / 分隔"""
        if not prefix:
            return ""
        prefix = prefix.replace(os.sep, "/").strip("/")
        return prefix + "/"

    @staticmethod
    def _join_key(prefix: str, rel: str) -> str:
        """拼远端 key: prefix + rel"""
        norm = SyncService._norm_prefix(prefix)
        return norm + rel
