# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""config - 全局配置层

包含:
    - settings: 全局常量配置
    - exceptions: 统一异常体系
"""
from .settings import (
    APP_NAME,
    APP_VERSION,
    DB_DIR,
    CACHE_DIR,
    LOG_DIR,
    KEY_FILE_NAME,
    DB_FILE_NAME,
    MAX_UPLOAD_SIZE,
    DEFAULT_CACHE_SIZE_MB,
    DEFAULT_CACHE_EXPIRE_HOURS,
    WINDOW_DEFAULT_SIZE,
    SIDEBAR_WIDTH,
    STATUS_BAR_HEIGHT,
    PROGRESS_POLL_INTERVAL,
    MINIO_V2_MIN_VERSION,
)
from .exceptions import (
    ObjStoreExplorerError,
    # 连接类
    ConnectionError,
    AuthenticationError,
    NetworkTimeoutError,
    ServerUnavailableError,
    # 权限类
    AccessPermissionError,
    # 资源类
    NotFoundError,
    AlreadyExistsError,
    BucketNotEmptyError,
    # 校验类
    ValidationError,
    # 业务类
    TransferError,
    CancelledError,
    ConfigError,
    EncryptionError,
    # 工具函数
    map_s3_error,
)

__all__ = [
    # settings
    "APP_NAME", "APP_VERSION",
    "DB_DIR", "CACHE_DIR", "LOG_DIR",
    "KEY_FILE_NAME", "DB_FILE_NAME",
    "MAX_UPLOAD_SIZE",
    "DEFAULT_CACHE_SIZE_MB", "DEFAULT_CACHE_EXPIRE_HOURS",
    "WINDOW_DEFAULT_SIZE", "SIDEBAR_WIDTH",
    "STATUS_BAR_HEIGHT",
    "PROGRESS_POLL_INTERVAL",
    "MINIO_V2_MIN_VERSION",
    # exceptions
    "ObjStoreExplorerError",
    "ConnectionError", "AuthenticationError",
    "NetworkTimeoutError", "ServerUnavailableError",
    "AccessPermissionError",
    "NotFoundError", "AlreadyExistsError", "BucketNotEmptyError",
    "ValidationError",
    "TransferError", "CancelledError",
    "ConfigError", "EncryptionError",
    "map_s3_error",
]
