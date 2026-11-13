# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""BucketManager - 桶管理业务

封装桶相关的业务逻辑:
    - 列出/创建/删除桶
    - 桶名校验
    - 桶统计信息 (只统计桶本身,不递归对象)

调用 S3Client 拿到原始数据,做业务包装。
"""
from __future__ import annotations
from typing import List, Dict, Optional, Tuple, Any

from .s3_client_base import S3ClientBase
from .validators import validate_bucket_name_or_raise
from ..config.exceptions import ConnectionError, ValidationError


class BucketManager:
    """桶管理器

    用法:
        bm = BucketManager(s3_client)
        ok, buckets = bm.list_buckets()
        ok, msg = bm.create_bucket("my-bucket")
    """

    def __init__(self, s3_client: S3ClientBase):
        if s3_client is None or not s3_client.is_connected:
            raise ConnectionError("S3 客户端未连接", code="NotConnected")
        self._client = s3_client

    def list_buckets(self) -> Tuple[bool, List[str]]:
        """列出所有桶

        Returns:
            (success, [bucket_name, ...])
        """
        return self._client.list_buckets()

    def bucket_exists(self, bucket: str) -> bool:
        """检查桶是否存在"""
        if not bucket:
            return False
        return self._client.bucket_exists(bucket)

    def create_bucket(self, bucket: str) -> Tuple[bool, str]:
        """创建桶 (含校验)

        Args:
            bucket: 桶名

        Returns:
            (success, message)
        """
        try:
            validate_bucket_name_or_raise(bucket)
        except ValidationError as e:
            return False, e.message

        if self.bucket_exists(bucket):
            return False, f"桶 {bucket} 已存在"

        return self._client.create_bucket(bucket)

    def delete_bucket(self, bucket: str, force: bool = False) -> Tuple[bool, str]:
        """删除桶

        修复: 去掉预检 `self.bucket_exists(bucket)`。
        原因: bucket_exists 走 HEAD bucket 偶发 404 / 异常, 会让 UI
        误报"桶 X 不存在", 但 list_buckets 列表里能看到。直接交给
        S3 客户端, 由 server 端 404 错误判断, 错误消息更准确。

        Args:
            bucket: 桶名
            force: 是否先清空所有对象

        Returns:
            (success, message)
        """
        if not bucket or not bucket.strip():
            return False, "桶名不能为空"
        return self._client.delete_bucket(bucket, force=force)

    def get_bucket_info(self, bucket: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """获取桶的元信息 (含版本控制状态、生命周期规则数)

        Returns:
            (success, {name, exists, versioning, lifecycle, ...})
        """
        if not self.bucket_exists(bucket):
            return False, None

        info: Dict[str, Any] = {
            "name": bucket,
            "exists": True,
        }

        # 尝试获取版本控制状态
        ok, status = self._client.get_bucket_versioning(bucket)
        if ok:
            info["versioning"] = status

        # 尝试获取生命周期配置
        # minio 7.2.20: None=未配置, LifecycleConfig 对象(有 .rules 列表)=已配置
        ok_lc, lc = self._client.get_bucket_lifecycle(bucket)
        if ok_lc and lc is not None:
            rules = getattr(lc, "rules", None)
            info["lifecycle"] = len(rules) if rules is not None else 0
        else:
            info["lifecycle"] = 0

        return True, info

    # ==================== CORS 配置 (D6) ====================

    def get_bucket_cors(self, bucket: str) -> Tuple[bool, Any]:
        """读取桶 CORS 配置 (无配置返回 [])"""
        from . import bucket_ext
        return bucket_ext.get_bucket_cors(self._client, bucket)

    def set_bucket_cors(self, bucket: str,
                        rules: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """写入桶 CORS 配置 (整体覆盖, 前端传 [{origin, methods, headers, max_age}])"""
        from . import bucket_ext
        return bucket_ext.set_bucket_cors(self._client, bucket, rules)

    def delete_bucket_cors(self, bucket: str) -> Tuple[bool, str]:
        """删除桶 CORS 配置"""
        from . import bucket_ext
        return bucket_ext.delete_bucket_cors(self._client, bucket)

    # ==================== 未完成分片清理 (D7) ====================

    def list_multipart_uploads(self, bucket: str) -> Tuple[bool, Any]:
        """列出桶内未完成的分段上传 (中断上传的 invisible 分片会持续计费)"""
        from . import bucket_ext
        return bucket_ext.list_multipart_uploads(self._client, bucket)

    def abort_multipart_upload(self, bucket: str, key: str,
                               upload_id: str) -> Tuple[bool, str]:
        """中止一个未完成的分段上传"""
        from . import bucket_ext
        return bucket_ext.abort_multipart_upload(self._client, bucket, key, upload_id)
