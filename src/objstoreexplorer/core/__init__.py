# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""core - 业务核心层"""
from .encryption import Encryptor
from .config_manager import ConfigManager
from .validators import (
    validate_bucket_name,
    validate_access_key,
    validate_secret_key,
    validate_endpoint,
    validate_filename,
    parse_endpoint,
    sanitize_filename,
)
from .s3_client_base import S3ClientBase
from .s3_client_v1 import S3ClientV1
from .s3_client_v2 import S3ClientV2
from .s3_client_factory import S3ClientFactory
from .bucket_manager import BucketManager
from .file_manager import FileManager
from .admin_manager import AdminManager, generate_strong_password
from .stats_manager import StatsManager

__all__ = [
    # 加密
    "Encryptor",
    # 配置
    "ConfigManager",
    # 校验
    "validate_bucket_name", "validate_access_key",
    "validate_secret_key", "validate_endpoint",
    "validate_filename", "parse_endpoint", "sanitize_filename",
    # S3 客户端
    "S3ClientBase", "S3ClientV1", "S3ClientV2", "S3ClientFactory",
    # 业务管理器
    "BucketManager", "FileManager", "AdminManager", "StatsManager",
    # 工具
    "generate_strong_password",
]
