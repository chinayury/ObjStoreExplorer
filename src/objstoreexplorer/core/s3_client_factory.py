# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""S3 客户端工厂 - 自动检测并选择 V1/V2 实现

检测策略 (按优先级):
    1. 尝试导入 minio.admin 模块
    2. 尝试用 V2 客户端连接并验证
    3. 失败则降级到 V1

设计:
    - 工厂是纯静态类,无状态
    - 创建失败时返回错误,不让异常逃逸
"""
from __future__ import annotations
import importlib

from .s3_client_base import S3ClientBase
from .s3_client_v1 import S3ClientV1
from .s3_client_v2 import S3ClientV2


class S3ClientFactory:
    """S3 客户端工厂"""

    @staticmethod
    def create(
        endpoint: str,
        ak: str,
        sk: str,
        ssl: bool = False,
    ) -> S3ClientBase:
        """创建 S3 客户端 (自动选择 V1/V2)

        Args:
            endpoint: 服务器地址
            ak: Access Key
            sk: Secret Key
            ssl: 是否 HTTPS

        Returns:
            S3ClientBase 实例 (V1 或 V2),未连接

        Raises:
            不抛出异常,失败时返回 V1 客户端 (后续 connect 会失败)
        """
        if S3ClientFactory._should_use_v2():
            return S3ClientV2(endpoint, ak, sk, ssl)
        return S3ClientV1(endpoint, ak, sk, ssl)

    @staticmethod
    def _should_use_v2() -> bool:
        """检查是否应使用 V2

        条件:
            1. minio.admin 或 minio.minioadmin 模块可导入
               (新版 minio-py 把类放在 minio.minioadmin)
            2. MinioAdmin 类可实例化
        """
        try:
            importlib.import_module("minio.credentials")
        except ImportError:
            return False

        for mod in ("minio.admin", "minio.minioadmin"):
            try:
                importlib.import_module(mod)
                return True
            except ImportError:
                continue
            except Exception:
                continue
        return False

    @staticmethod
    def detect_version_name() -> str:
        """返回当前会使用的版本名 (用于日志)"""
        return "V2" if S3ClientFactory._should_use_v2() else "V1"
