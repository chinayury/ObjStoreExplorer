# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""FileManager - 文件/对象管理业务

封装对象相关的业务逻辑:
    - 列表/上传/下载/删除/复制/移动
    - 文件夹管理
    - 路径处理 (prefix)
    - 进度回调包装
"""
from __future__ import annotations
import os
from typing import List, Dict, Optional, Tuple, Any, Callable
from urllib.parse import unquote

from .s3_client_base import (
    S3ClientBase,
    list_objects_with_limit,
)
from ..config.settings import MAX_UPLOAD_SIZE, MAX_LIST_ITEMS
from ..config.exceptions import (
    ConnectionError,
)
from .validators import sanitize_filename, validate_filename
from .config_manager import ConfigManager
from ..utils.helpers import format_bytes as _format_size


# 进度回调类型
ProgressFn = Callable[[float], None]


class FileManager:
    """文件管理器"""

    def __init__(self, s3_client: S3ClientBase):
        if s3_client is None or not s3_client.is_connected:
            raise ConnectionError("S3 客户端未连接", code="NotConnected")
        self._client = s3_client

    def _resolve_upload_limit(self) -> int:
        """解析单文件上传大小限制, 单位字节。

        - 从 ConfigManager 读 `max_upload_size_mb` (MB 单位)
        - 显式设置为 **0** 才表示**不限制**, 返回 0
        - **未设置时回退默认 `MAX_UPLOAD_SIZE` (100 MB)**

        ⚠ 旧实现用 `get_setting_int("max_upload_size_mb", 0)` —— 第二个参数
        既是"键不存在时的默认值"又是"0 = 不限制"的哨兵, 于是新装用户(该项从未
        被写过)拿到 0, 上传限制直接失效, 而 docstring 承诺的是 100MB。
        另外负值也会被 `:135` 的 `upload_limit > 0` 判为"不限制", 配置写错
        反而关掉了保护。两者都改掉: 未设置走默认值, 负值视为非法并回退。
        """
        try:
            mb = ConfigManager().get_setting_int("max_upload_size_mb", -1)
            if mb < 0:
                # -1 = 该项从未设置 -> 用文档承诺的默认值
                return MAX_UPLOAD_SIZE
            if mb == 0:
                # 显式选择"不限制"
                return 0
            return mb * 1024 * 1024
        except Exception:
            return MAX_UPLOAD_SIZE

    # ==================== 列表 ====================

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        recursive: bool = False,
        max_items: Optional[int] = None,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """列出对象 (业务层包装,补充 display_name 等展示字段)

        透传 recursive 给 minio-py。S3 ListObjectsV2 在 delimiter='/'
        下,服务端会正确返回:
            - 当前 prefix 下的直接子文件 (不以 '/' 结尾)
            - 当前 prefix 下的子目录 common prefix (以 '/' 结尾)
        不需要客户端再做聚合。

        Args:
            max_items: 单次列表条数上限。**默认 None = MAX_LIST_ITEMS(1000)**;
                       传 0 = 不限制 (delete_folder / rename_folder 等需要
                       看全量的内部场景必须显式传 0)。

        ⚠ 旧实现不传上限, 无上限物化曾让概览页 (每桶一次 recursive 全量 +
        4 线程并发) 把大桶内存吃到 GB 级。config/settings.py 里的
        MAX_LIST_ITEMS 定义了却从未被引用 —— 这里接上。

        Returns:
            (success, [{
                name, display_name, size, size_kb, last_modified,
                is_dir, etag
            }, ...])
            截断状态用 last_list_truncated() 查询。
        """
        limit = MAX_LIST_ITEMS if max_items is None else int(max_items or 0)
        ok, raw = list_objects_with_limit(
            self._client, bucket, prefix, recursive, limit
        )
        if not ok:
            self._last_list_truncated = False
            return False, raw if isinstance(raw, str) else []

        # 截断标志: 客户端给了就用客户端的 (线程本地, 权威), 否则按条数推断
        truncated = False
        getter = getattr(self._client, "last_list_truncated", None)
        if callable(getter):
            try:
                truncated = bool(getter())
            except Exception:  # noqa: BLE001 - 探测失败不当成截断
                truncated = False
        elif limit and len(raw) >= limit:
            truncated = True
        self._last_list_truncated = truncated

        result = []
        for obj in raw:
            name = obj.get("name", "")
            is_dir = obj.get("is_dir", False)
            size = obj.get("size", 0)
            display_name = self._make_display_name(name, prefix, is_dir)

            result.append({
                "name": name,
                "display_name": display_name,
                "size": size,
                "size_kb": round(size / 1024, 2) if size else 0,
                "size_str": _format_size(size) if not is_dir else "",
                "last_modified": obj.get("last_modified"),
                "is_dir": is_dir,
                "etag": obj.get("etag"),
            })
        return True, result

    def last_list_truncated(self) -> bool:
        """最近一次 list_objects 是否被条数上限截断 (供路由回传 truncated 标志)"""
        return bool(getattr(self, "_last_list_truncated", False))

    def _make_display_name(self, full_name: str, prefix: str, is_dir: bool) -> str:
        """生成显示名 (去掉 prefix 前缀和末尾 /)"""
        name = full_name
        if prefix and name.startswith(prefix):
            name = name[len(prefix):]
        if is_dir and name.endswith("/"):
            name = name[:-1]
        return unquote(name) if name else "/"

    # ==================== 上传 ====================

    def upload_file(
        self,
        local_path: str,
        bucket: str,
        key: str,
        progress: ProgressFn = None,
    ) -> Tuple[bool, str]:
        """上传单个文件

        Args:
            local_path: 本地文件路径
            bucket: 目标桶
            key: 对象 key (含路径)
            progress: 进度回调 (0.0-1.0)
        """
        if not os.path.exists(local_path):
            return False, f"文件不存在: {local_path}"

        file_size = os.path.getsize(local_path)
        upload_limit = self._resolve_upload_limit()
        if upload_limit > 0 and file_size > upload_limit:
            return False, f"文件超过 {upload_limit // 1024 // 1024}MB 限制"

        if not key:
            key = os.path.basename(local_path)

        return self._client.upload(local_path, bucket, key, progress)

    def upload_files(
        self,
        bucket: str,
        prefix: str,
        file_paths: List[str],
        progress: Callable[[int, int, str], None] = None,
    ) -> List[Dict[str, Any]]:
        """批量上传(同步,主线程串行)

        一般业务代码请用 TransferService.upload_files(后台线程池),
        本方法适合: 已经在后台线程,或者只需要简单同步批量。

        ⚠ 参数顺序与 TransferService.upload_files **保持一致**
          (bucket, prefix, file_paths)。两侧曾是反的, 错位后 file_paths
          收到的是字符串 prefix 会被逐字符迭代, 把 prefix 的每个字符
          当文件名去上传 —— 全静默失败。(v0.1.0 端到端实测时踩到)

        Args:
            bucket: 目标桶
            prefix: 桶内路径前缀
            file_paths: 本地文件路径列表
            progress: 文件级进度回调 (current, total, file_name)
        """
        results = []
        total = len(file_paths)

        for i, local_path in enumerate(file_paths):
            file_name = os.path.basename(local_path)
            # 标准化: prefix 若不以 / 结尾,补上
            if prefix and not prefix.endswith("/"):
                normalized_prefix = prefix + "/"
            else:
                normalized_prefix = prefix
            key = (normalized_prefix + file_name).replace(os.sep, "/")

            if progress:
                progress(i, total, file_name)

            # 单文件级 byte 进度: 包一层把 file-level 进度和 byte 进度分开
            def per_file_progress(p: float, _idx: int = i) -> None:
                # 把 byte 进度反映到 file-level (总进度)
                if progress:
                    progress(_idx + p, total, file_name)

            ok, msg = self.upload_file(local_path, bucket, key, per_file_progress)
            results.append({
                "file": local_path,
                "key": key,
                "success": ok,
                "message": msg,
            })

        if progress:
            progress(total, total, "完成")

        return results

    # ==================== 下载 ====================

    def download_file(
        self,
        bucket: str,
        key: str,
        save_path: str,
        progress: ProgressFn = None,
    ) -> Tuple[bool, str]:
        """下载单个文件

        Args:
            bucket: 桶名
            key: 对象 key
            save_path: 本地保存路径
            progress: 进度回调
        """
        if not key:
            return False, "对象 key 不能为空"

        save_dir = os.path.dirname(save_path)
        if save_dir and not os.path.exists(save_dir):
            try:
                os.makedirs(save_dir, exist_ok=True)
            except OSError as e:
                return False, f"无法创建目录: {e}"

        return self._client.download(bucket, key, save_path, progress)

    @staticmethod
    def _dedup_name(name: str, used: set) -> str:
        """同名去重: 已用过的名字加 (2)/(3) 后缀, 避免平铺下载时互相覆盖"""
        if name not in used:
            used.add(name)
            return name
        stem, ext = os.path.splitext(name)
        n = 2
        while True:
            candidate = f"{stem}({n}){ext}"
            if candidate not in used:
                used.add(candidate)
                return candidate
            n += 1

    def download_files(
        self,
        bucket: str,
        keys: List[str],
        save_dir: str,
        progress: Callable[[int, int, str], None] = None,
    ) -> List[Dict[str, Any]]:
        """批量下载(同步,主线程串行,文件夹结构会**丢失** — 所有文件平铺到 save_dir)

        一般业务代码请用 TransferService.download_objects(保留结构 + 后台线程池)。
        """
        os.makedirs(save_dir, exist_ok=True)
        results: List[Dict[str, Any]] = []
        total = len(keys)
        # 同名对象去重: 批量下载会把所有文件平铺到 save_dir, 不同目录下的
        # 同名对象 (a/2026/report.pdf 与 b/2026/report.pdf) 会互相覆盖 ——
        # 静默丢数据。已用过的名字加序号后缀。
        used_names: set = set()
        for i, key in enumerate(keys):
            if not key:
                continue
            # ⚠ 旧代码直接用 os.path.basename 拼路径。桶里若存在用非 Windows
            #   客户端上传的、带 Windows 非法字符 (: * ? < > |) 或保留名
            #   (CON / PRN / NUL / COM1) 的对象, 落盘直接失败, 整批中断。
            #   core/validators.py 里 sanitize_filename 早就写好了却【全库零调用】,
            #   设计上缺了最后一环 —— 这里接上。
            file_name = sanitize_filename(os.path.basename(key.rstrip("/")))
            file_name = self._dedup_name(file_name, used_names)
            local_path = os.path.join(save_dir, file_name)
            if progress:
                progress(i, total, file_name)

            def per_file_progress(p: float, _idx: int = i) -> None:
                if progress:
                    progress(_idx + p, total, file_name)

            ok, msg = self.download_file(bucket, key, local_path, per_file_progress)
            results.append({
                "key": key, "local_path": local_path,
                "success": ok, "message": msg,
            })
        if progress:
            progress(total, total, "完成")
        return results

    # ==================== 删除 ====================

    def delete_object(self, bucket: str, key: str) -> Tuple[bool, str]:
        """删除单个对象"""
        if not key:
            return False, "对象 key 不能为空"
        return self._client.delete(bucket, key)

    def delete_objects(
        self,
        bucket: str,
        keys: List[str],
        progress: Callable[[int, int, str], None] = None,
    ) -> List[Dict[str, Any]]:
        """批量删除"""
        results = []
        total = len(keys)

        for i, key in enumerate(keys):
            name = os.path.basename(key.rstrip("/"))
            if progress:
                progress(i, total, name)

            ok, msg = self.delete_object(bucket, key)
            results.append({
                "key": key,
                "success": ok,
                "message": msg,
            })

        if progress:
            progress(total, total, "完成")
        return results

    def delete_folder(self, bucket: str, prefix: str) -> Tuple[bool, str]:
        """删除文件夹 (递归删除所有以 prefix 开头的对象,优先批量 API)

        ⚠ 必须**不带上限**地列举 (max_items=0): 上限会把"还有对象没列到"
        误报成"文件夹已删干净", 留下半个文件夹 —— 数据完整性事故。
        """
        ok, objects = list_objects_with_limit(
            self._client, bucket, prefix, True, 0
        )
        if not ok:
            return False, objects if isinstance(objects, str) else "获取对象列表失败"

        if not objects:
            return True, "文件夹为空"

        names = [obj.get("name", "") for obj in objects if obj.get("name")]
        if not names:
            return True, "文件夹为空"

        # 优先用 minio 的批量 remove_objects (服务端一次性 1000 条)
        raw_client = getattr(self._client, "_client", None)
        failed = 0
        try:
            if raw_client is not None and hasattr(raw_client, "remove_objects"):
                from minio.deleteobjects import DeleteObject
                # 分批 1000 条,避免一次太大
                BATCH = 1000
                for start in range(0, len(names), BATCH):
                    batch = [DeleteObject(n) for n in names[start:start + BATCH]]
                    errs = raw_client.remove_objects(bucket, batch)
                    for _del_err in errs:
                        # iterator,每个元素是 DeleteError (只计数, 不用元素)
                        failed += 1
            else:
                # 兜底: 并发逐个删
                from concurrent.futures import as_completed
                from ..utils.thread_pool import get_thread_pool
                executor = get_thread_pool()
                futs = {
                    executor.submit(self._client.delete, bucket, n): n
                    for n in names
                }
                for fut in as_completed(futs):
                    try:
                        ok2, _ = fut.result()
                        if not ok2:
                            failed += 1
                    except Exception:
                        failed += 1
        except Exception as e:
            return False, f"批量删除失败: {e}"

        total = len(names)
        if failed:
            return False, f"删除完成: 成功 {total - failed} / 失败 {failed}"
        return True, f"已删除 {total} 个对象"

    # ==================== 复制/移动 ====================

    def copy_object(
        self,
        src_bucket: str,
        src_key: str,
        dst_bucket: str,
        dst_key: str,
    ) -> Tuple[bool, str]:
        return self._client.copy(src_bucket, src_key, dst_bucket, dst_key)

    def move_object(
        self,
        bucket: str,
        old_key: str,
        new_key: str,
    ) -> Tuple[bool, str]:
        return self._client.move(bucket, old_key, new_key)

    def move_object_cross_bucket(
        self,
        src_bucket: str,
        src_key: str,
        dst_bucket: str,
        dst_key: str,
    ) -> Tuple[bool, str]:
        """跨桶移动 = 复制 + 删除"""
        ok, msg = self._client.copy(src_bucket, src_key, dst_bucket, dst_key)
        if not ok:
            return False, msg
        return self._client.delete(src_bucket, src_key)

    # ==================== 文件夹 (批量展开) ====================

    @staticmethod
    def _norm_prefix(prefix: str) -> str:
        """统一把文件夹 prefix 规范成以 / 结尾"""
        p = prefix or ""
        return p if p.endswith("/") else p + "/"

    def _expand_folder(self, bucket: str, prefix: str) -> Tuple[bool, Any]:
        """列出文件夹下的全部对象 key (含占位对象本身, 不带上限)

        递归列举通常会连 `/` 结尾的占位对象一起返回; 个别服务端/老版本不返回
        时, 用一次 stat 确认真实存在才补上 —— **不能盲目补**: 没有占位对象的
        "虚拟文件夹" (只有 a/b.txt, 没有 a/) 补一个不存在的 key 会让后续
        copy 直接失败。

        Returns:
            (True, [对象 key, ...]) / (False, 错误消息)
        """
        norm = self._norm_prefix(prefix)
        ok, objects = list_objects_with_limit(self._client, bucket, norm, True, 0)
        if not ok:
            return False, objects if isinstance(objects, str) else "获取对象列表失败"
        names = [o.get("name", "") for o in objects if o.get("name")]
        if norm not in names and self.exists(bucket, norm):
            names.append(norm)
        return True, names

    def expand_folder_keys(self, bucket: str, prefix: str) -> Tuple[bool, Any]:
        """列出文件夹下的全部**子对象** key (不含占位对象本身)

        供批量下载/打包使用: 占位对象是 0 字节的空 key, 下它只会往 zip 里
        塞一个空文件。
        """
        ok, names = self._expand_folder(bucket, prefix)
        if not ok:
            return False, names
        norm = self._norm_prefix(prefix)
        return True, [n for n in names if n != norm]

    def rename_folder(
        self,
        bucket: str,
        old_prefix: str,
        new_prefix: str,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, str]:
        """重命名/移动文件夹 (整棵子树)

        S3 里"文件夹"只是以 / 结尾的 0 字节占位对象, 单个 key 的
        move_object 只会挪走这个占位符, 里面的文件原封不动 —— 用户看到的是
        "重命名成功了但内容全没了"。

        做法: list 展开 → 逐条 copy 到新前缀 → **每条 copy 成功后立即删该条
        旧 key** (逐源成功语义, 借鉴 bucketdock) → 全部完成即结束。
        任一步失败即中止并如实报告: 已迁移的在新前缀, 未处理的仍在旧前缀,
        两端都不会丢数据; 个别「复制成功但删除失败」的对象会短暂同时存在于
        新旧两处 (报告明示 key, 用户可手动清理)。

        Args:
            bucket: 桶名
            old_prefix: 旧文件夹前缀 (以 / 结尾或会被自动补上)
            new_prefix: 新文件夹前缀
            is_cancelled: 可选取消谓词, 每条操作前检查 (取消则中止, 已删的不再恢复)
        """
        old_norm = self._norm_prefix(old_prefix)
        new_norm = self._norm_prefix(new_prefix)
        if old_norm == new_norm:
            return True, "源与目标相同, 无需移动"

        ok, names = self._expand_folder(bucket, old_norm)
        if not ok:
            return False, names
        if not names:
            return False, f"文件夹不存在或为空: {old_norm}"

        total = len(names)
        moved = 0
        failed: List[str] = []
        orphans: List[str] = []   # 复制成功但删除失败的 key (新旧各有一份)
        for name in names:
            if is_cancelled is not None and is_cancelled():
                return False, (
                    f"已取消: 已迁移 {moved}/{total} 个对象; "
                    f"已迁移部分位于 {new_norm}, 其余仍在 {old_norm}"
                )
            rel = name[len(old_norm):] if name.startswith(old_norm) else name
            dst = f"{new_norm}{rel}"
            if name == dst:
                moved += 1
                continue
            ok_c, msg_c = self._client.copy(bucket, name, bucket, dst)
            if not ok_c:
                failed.append(f"{name}: {msg_c}")
                break
            # 逐源删除: 该条已在新前缀落定, 立刻删旧 key, 不等全部复制完
            ok_d, msg_d = self._client.delete(bucket, name)
            if not ok_d:
                # 复制成功但删除失败: 数据不丢, 但会短暂双份, 记账待报告
                orphans.append(f"{name} (删除失败: {msg_d})")
            moved += 1

        if failed or moved != total:
            # 未完成: 已迁移的在新前缀, 未处理的仍在旧前缀, 数据零丢失
            detail = failed[0] if failed else ""
            return False, (
                f"移动文件夹未完成: 已迁移 {moved}/{total} 个对象, 已中止; "
                f"已迁移部分位于 {new_norm}, 其余仍在 {old_norm} ({detail})"
            )

        if orphans:
            return False, (
                f"已移动 {total} 个对象到 {new_norm}, 但有 {len(orphans)} 个对象"
                f"复制后删除失败, 新旧位置各存一份, 请手动清理: "
                + "; ".join(orphans[:5])
                + (f" 等 {len(orphans)} 个" if len(orphans) > 5 else "")
            )
        return True, f"已移动 {total} 个对象到 {new_norm}"

    def copy_folder(
        self,
        src_bucket: str,
        src_prefix: str,
        dst_bucket: str,
        dst_prefix: str,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, str]:
        """复制文件夹 (整棵子树, 支持跨桶)

        Args 同 rename_folder; 失败时同样如实报告已复制数量。
        """
        src_norm = self._norm_prefix(src_prefix)
        dst_norm = self._norm_prefix(dst_prefix)
        if src_bucket == dst_bucket and src_norm == dst_norm:
            return True, "源与目标相同, 无需复制"

        ok, names = self._expand_folder(src_bucket, src_norm)
        if not ok:
            return False, names
        if not names:
            return False, f"文件夹不存在或为空: {src_norm}"

        total = len(names)
        copied = 0
        failed: List[str] = []
        for name in names:
            if is_cancelled is not None and is_cancelled():
                return False, (
                    f"已取消: 已复制 {copied}/{total} 个对象"
                )
            rel = name[len(src_norm):] if name.startswith(src_norm) else name
            dst = f"{dst_norm}{rel}"
            if src_bucket == dst_bucket and name == dst:
                copied += 1
                continue
            ok_c, msg_c = self._client.copy(src_bucket, name, dst_bucket, dst)
            if not ok_c:
                failed.append(f"{name}: {msg_c}")
                break
            copied += 1

        if failed or copied != total:
            detail = failed[0] if failed else ""
            return False, (
                f"复制文件夹未完成: 已复制 {copied}/{total} 个对象, 已中止 ({detail})"
            )
        return True, f"已复制 {total} 个对象到 {dst_bucket}/{dst_norm}"

    # ==================== 文件夹 ====================

    def create_folder(self, bucket: str, folder_name: str, parent: str = "") -> Tuple[bool, str]:
        """创建文件夹

        Args:
            bucket: 桶名
            folder_name: 文件夹名 (不含路径分隔符)
            parent: 父目录 prefix
        """
        ok, msg = validate_filename(folder_name)
        if not ok:
            return False, msg

        if "/" in folder_name or "\\" in folder_name:
            return False, "文件夹名不能包含路径分隔符"

        prefix = f"{parent}{folder_name}/" if parent else f"{folder_name}/"
        return self._client.create_folder(bucket, prefix)

    # ==================== 元数据 ====================

    def stat_object(self, bucket: str, key: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        return self._client.stat_object(bucket, key)

    def preview_object(
        self,
        bucket: str,
        key: str,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> Tuple[bool, Any]:
        """读取对象头部字节用于在线预览 (不落盘)。

        先 stat 拿 content_type / size, 再 ranged 读前 max_bytes 字节。
        返回 (ok, stat_dict[+preview_bytes] / 错误消息)。
        """
        ok, info = self.stat_object(bucket, key)
        if not ok or not isinstance(info, dict):
            return False, info if isinstance(info, str) else "对象不存在"
        ok2, data = self._client.read_object_bytes(bucket, key, max_bytes)
        if not ok2:
            return False, data
        info["preview_bytes"] = data
        info["preview_size"] = len(data)
        size = info.get("size") or 0
        info["truncated"] = size > len(data)
        return True, info

    def exists(self, bucket: str, key: str) -> bool:
        """检查对象是否存在"""
        ok, _ = self._client.stat_object(bucket, key)
        return ok
