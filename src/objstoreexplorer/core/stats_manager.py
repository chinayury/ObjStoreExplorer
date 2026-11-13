# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""StatsManager - 统计管理业务

封装统计相关操作:
    - 单个桶统计
    - 所有桶统计
    - 整体概览
    - 文件类型分布
"""
from __future__ import annotations
from collections import defaultdict
from typing import List, Dict, Tuple, Any, Optional

from .s3_client_base import S3ClientBase, list_objects_with_limit
from ..config.exceptions import ConnectionError
from ..config.settings import MAX_LIST_ITEMS
from ..utils.helpers import format_bytes as _format_size


class StatsManager:
    """统计管理器"""

    def __init__(self, s3_client: S3ClientBase):
        if s3_client is None or not s3_client.is_connected:
            raise ConnectionError("S3 客户端未连接", code="NotConnected")
        self._client = s3_client

    def get_bucket_stats(self, bucket: str) -> Dict[str, Any]:
        """获取单个桶的统计信息

        ⚠ 旧实现无上限地物化整个桶的对象列表, 概览页 4 线程并发对每个桶
        各拉一次, 大桶直接把内存吃光 (OOM)。这里显式传
        MAX_LIST_ITEMS 上限, 超限时结果带 `truncated: True`。

        Returns:
            {
                bucket_name, object_count, folder_count,
                total_size, total_size_mb, total_size_gb,
                total_size_str, file_types, truncated, error
            }
        """
        result: Dict[str, Any] = {
            "bucket_name": bucket,
            "object_count": 0,
            "folder_count": 0,
            "total_size": 0,
            "total_size_mb": 0.0,
            "total_size_gb": 0.0,
            "total_size_str": "0 B",
            "file_types": {},
            "truncated": False,
        }

        ok, objects = list_objects_with_limit(
            self._client, bucket, "", True, MAX_LIST_ITEMS
        )
        if not ok:
            result["error"] = objects if isinstance(objects, str) else "获取对象失败"
            return result

        getter = getattr(self._client, "last_list_truncated", None)
        if callable(getter):
            try:
                result["truncated"] = bool(getter())
            except Exception:  # noqa: BLE001 - 探测失败按未截断处理
                pass

        total_size = 0
        object_count = 0
        folder_count = 0
        file_types: Dict[str, int] = defaultdict(int)
        folders = set()

        for obj in objects:
            name = obj.get("name", "")
            is_dir = obj.get("is_dir", False)
            size = obj.get("size", 0)

            if is_dir:
                folder_path = name.rstrip("/")
                if folder_path:
                    folders.add(folder_path)
                continue

            total_size += size
            object_count += 1

            # 文件类型
            if "." in name:
                ext = name.rsplit(".", 1)[-1].lower()
                file_types[ext] += 1
            else:
                file_types["(无扩展名)"] += 1

        folder_count = len(folders)
        result.update({
            "object_count": object_count,
            "folder_count": folder_count,
            "total_size": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "total_size_gb": round(total_size / 1024 / 1024 / 1024, 2),
            "total_size_str": _format_size(total_size),
            "file_types": dict(file_types),
        })

        return result

    def get_all_buckets_stats(self) -> Tuple[bool, List[Dict[str, Any]]]:
        """获取所有桶的统计信息 (并发)"""
        ok, buckets = self._client.list_buckets()
        if not ok:
            return False, []

        if not buckets:
            return True, []

        from concurrent.futures import as_completed
        from ..utils.thread_pool import get_thread_pool

        executor = get_thread_pool()
        # 预创建占位,保持顺序与 buckets 一致
        results: List[Optional[Dict[str, Any]]] = [None] * len(buckets)
        futures = {
            executor.submit(self.get_bucket_stats, b): i
            for i, b in enumerate(buckets)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = {
                    "bucket_name": buckets[i],
                    "error": str(e),
                    "object_count": 0,
                    "folder_count": 0,
                    "total_size": 0,
                    "total_size_str": "0 B",
                    "file_types": {},
                }
        return True, [r for r in results if r is not None]

    def get_overview(self) -> Dict[str, Any]:
        """获取整体概览

        Returns:
            {
                total_buckets, total_objects, total_folders,
                total_size, total_size_str,
                largest_bucket: {name, size_str, objects},
                buckets: [各桶统计]
            }
        """
        ok, stats_list = self.get_all_buckets_stats()
        if not ok:
            return {"error": "获取统计失败"}

        total_objects = sum(s.get("object_count", 0) for s in stats_list)
        total_folders = sum(s.get("folder_count", 0) for s in stats_list)
        total_size = sum(s.get("total_size", 0) for s in stats_list)

        # 找最大桶
        largest = max(
            stats_list,
            key=lambda s: s.get("total_size", 0),
            default={},
        )

        return {
            "total_buckets": len(stats_list),
            "total_objects": total_objects,
            "total_folders": total_folders,
            "total_size": total_size,
            "total_size_str": _format_size(total_size),
            "largest_bucket": {
                "name": largest.get("bucket_name", "-"),
                "size_str": largest.get("total_size_str", "0 B"),
                "objects": largest.get("object_count", 0),
            } if largest else {},
            "buckets": stats_list,
        }

    def get_file_type_distribution(self, bucket: str) -> Dict[str, int]:
        """获取桶的文件类型分布 (按数量降序)"""
        stats = self.get_bucket_stats(bucket)
        file_types = stats.get("file_types", {})
        return dict(sorted(file_types.items(), key=lambda x: x[1], reverse=True))
