# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

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
