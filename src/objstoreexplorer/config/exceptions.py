# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""统一异常体系

设计原则:
    1. 所有业务异常继承 ObjStoreExplorerError 基类
    2. 异常携带 code (S3 错误码) 和 details (上下文) 便于调试
    3. 提供 map_s3_error() 自动将 minio S3Error 映射为业务异常
    4. 分层处理:
        - Core 层: 抛出具体异常
        - Services 层: 捕获并转为 (bool, str) 元组
        - UI 层: 根据元组决定显示哪种对话框
"""
from __future__ import annotations
from typing import Optional, Dict, Any


class ObjStoreExplorerError(Exception):
    """所有自定义异常的基类

    Attributes:
        message: 人类可读的错误描述
        code: 错误码 (对应 S3 错误码或自定义分类码)
        details: 额外的调试信息 (dict)
    """
    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def __str__(self) -> str:
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (用于日志)"""
        return {
            "type": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


# ==================== 连接类异常 ====================

class ConnectionError(ObjStoreExplorerError):
    """连接错误 (网络问题/DNS 失败/服务不可达)"""
    pass


class AuthenticationError(ObjStoreExplorerError):
    """认证失败 (AK/SK 无效)"""
    pass


class NetworkTimeoutError(ObjStoreExplorerError):
    """网络超时"""
    pass


class ServerUnavailableError(ObjStoreExplorerError):
    """服务不可用 (服务关闭/端口不通)"""
    pass


# ==================== 权限类异常 ====================

class AccessPermissionError(ObjStoreExplorerError):
    """权限不足 (S3 AccessDenied)

    注意:故意避开与 builtins.PermissionError 同名,
    避免在 except 块里混淆(后者是文件/系统权限异常)。
    """
    pass


# ==================== 资源类异常 ====================

class NotFoundError(ObjStoreExplorerError):
    """资源不存在 (桶/对象/用户)"""
    pass


class AlreadyExistsError(ObjStoreExplorerError):
    """资源已存在"""
    pass


class BucketNotEmptyError(ObjStoreExplorerError):
    """桶不为空 (删除前需清空)"""
    pass


# ==================== 校验类异常 ====================

class ValidationError(ObjStoreExplorerError):
    """参数校验失败"""
    pass


# ==================== 业务类异常 ====================

class TransferError(ObjStoreExplorerError):
    """传输失败 (上传/下载)"""
    pass


class CancelledError(ObjStoreExplorerError):
    """操作被用户取消"""
    pass


class ConfigError(ObjStoreExplorerError):
    """配置错误 (保存/读取失败)"""
    pass


class EncryptionError(ObjStoreExplorerError):
    """加密/解密失败"""
    pass


# ==================== S3 错误映射 ====================

# 延迟导入 minio.error 以避免模块加载顺序问题
_S3_ERROR_MAP: Dict[str, type] = {
    "AccessDenied": AccessPermissionError,
    "NoSuchBucket": NotFoundError,
    "NoSuchKey": NotFoundError,
    "BucketAlreadyExists": AlreadyExistsError,
    "BucketAlreadyOwnedByYou": AlreadyExistsError,
    "BucketNotEmpty": BucketNotEmptyError,
    "NoSuchUser": NotFoundError,
    "NoSuchPolicy": NotFoundError,
    "InvalidAccessKeyId": AuthenticationError,
    "SignatureDoesNotMatch": AuthenticationError,
    "InvalidArgument": ValidationError,
    "InvalidBucketName": ValidationError,
}


def map_s3_error(exc: Exception) -> ObjStoreExplorerError:
    """将第三方异常 (minio S3Error / ConnectionError) 映射为业务异常

    支持 duck-typing: 不强制要求 isinstance S3Error,只要有 code/message 即可。

    用法:
        try:
            self._client.make_bucket(bucket)
        except Exception as e:
            raise map_s3_error(e)
    """
    # 尝试导入 minio.error (失败也支持 duck-typing)
    MinioS3Error = None
    try:
        from minio.error import S3Error as _MSE
        MinioS3Error = _MSE
    except ImportError:
        pass

    # 真实 S3Error 或 duck-typed 对象
    if MinioS3Error is not None and isinstance(exc, MinioS3Error):
        code = getattr(exc, "code", "") or ""
        msg = getattr(exc, "message", str(exc))
        exc_class = _S3_ERROR_MAP.get(code, ObjStoreExplorerError)
        return exc_class(msg, code=code)

    # Duck-typed S3Error (有 code/message 属性,不是 ConnectionRefusedError)
    if (hasattr(exc, "code") and hasattr(exc, "message")
            and not isinstance(exc, (ConnectionRefusedError, TimeoutError, OSError))):
        code = getattr(exc, "code", "") or ""
        msg = getattr(exc, "message", str(exc))
        exc_class = _S3_ERROR_MAP.get(code, ObjStoreExplorerError)
        return exc_class(msg, code=code)

    if isinstance(exc, ConnectionRefusedError):
        return ServerUnavailableError(
            f"服务拒绝连接: {exc}",
            code="ConnectionRefused",
        )
    if isinstance(exc, TimeoutError):
        return NetworkTimeoutError(
            f"网络超时: {exc}",
            code="Timeout",
        )
    if isinstance(exc, OSError):
        return ConnectionError(
            f"网络错误: {exc}",
            code="OSError",
        )

    return ObjStoreExplorerError(str(exc))
