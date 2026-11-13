# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""服务定位器 (Service Locator) - 集中管理所有依赖

并发约定:
    - 单例的 `__new__` 与 `__init__` 共用一把类级锁, 且 `_initialized` 提到类属性,
      避免两个线程都进 `__init__` 各建一套字段。
    - manager / service 的 lazy 构造全部在 `_state_lock` (RLock) 内完成,
      杜绝 check-then-act 造出两个 TransferService (各自独立 _tasks, 互相 cancel 不到)。
    - `disconnect()` 先置忙标志拒绝新任务 -> 等在途任务 settle -> 再关客户端,
      避免在途任务往已 close 的 Minio 客户端上写。
"""
from __future__ import annotations
import threading
from typing import Optional, Tuple

from ..core.s3_client_base import S3ClientBase
from ..core.s3_client_factory import S3ClientFactory
from ..core.config_manager import ConfigManager
from ..core.encryption import Encryptor
from ..core.bucket_manager import BucketManager
from ..core.file_manager import FileManager
from ..core.admin_manager import AdminManager
from ..core.stats_manager import StatsManager
from ..config.exceptions import ConnectionError


class ServiceLocator:
    """服务容器 (单例,无继承)"""

    _instance: Optional["ServiceLocator"] = None
    # 类级锁: __new__ 与 __init__ 共用 (RLock 允许同线程重入)
    _singleton_lock = threading.RLock()
    # 实例状态锁: manager / service 的 lazy 构造
    _state_lock = threading.RLock()

    # 类属性而非实例属性: __init__ 执行前就能读到 False
    _initialized: bool = False
    # 断开进行中: 置位期间拒绝新的依赖获取
    _closing: bool = False

    # 断开时等待在途任务的最长时间 (秒)
    DISCONNECT_DRAIN_TIMEOUT = 5.0

    def __new__(cls, *args, **kwargs):
        # 双重检查锁定 — 多线程并发构造时只允许一个实例
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # 注意: 不在这里置 _initialized, 由 __init__ 在锁内完成
        return cls._instance

    def __init__(self):
        # 与 __new__ 共用同一把锁, 防止两个线程同时跑初始化
        with ServiceLocator._singleton_lock:
            if ServiceLocator._initialized:
                return
            self._s3_client: Optional[S3ClientBase] = None
            self._managers: dict = {}
            self._services: dict = {}
            self._config_manager: Optional[ConfigManager] = None
            self._encryptor: Optional[Encryptor] = None
            # 字段全部就位后才置位, 别的线程看到 True 即代表可用
            ServiceLocator._initialized = True

    # ==================== 永远存在的组件 ====================

    @property
    def config_manager(self) -> ConfigManager:
        with self._state_lock:
            if self._config_manager is None:
                self._config_manager = ConfigManager()
            return self._config_manager

    @property
    def encryptor(self) -> Encryptor:
        with self._state_lock:
            if self._encryptor is None:
                self._encryptor = Encryptor()
            return self._encryptor

    # ==================== 连接相关 ====================

    @property
    def s3_client(self) -> Optional[S3ClientBase]:
        return self._s3_client

    @property
    def is_connected(self) -> bool:
        return (self._s3_client is not None
                and self._s3_client.is_connected
                and not self._closing)

    @property
    def is_busy(self) -> bool:
        """正在断开中: UI 可据此禁用新操作入口"""
        return self._closing

    def connect(
        self,
        endpoint: str,
        ak: str,
        sk: str,
        ssl: bool = False,
    ) -> Tuple[bool, str]:
        if self._s3_client is not None:
            self.disconnect()

        try:
            client = S3ClientFactory.create(endpoint, ak, sk, ssl)
            ok, msg = client.connect()
            if not ok:
                return False, msg

            self._s3_client = client
            with self._state_lock:
                self._managers.clear()
            return True, msg
        except Exception as e:
            return False, f"连接失败: {e}"

    def disconnect(self) -> None:
        """断开连接

        顺序至关重要:
            1. 置忙标志 (is_connected 变 False) -> 拒绝新任务进来
            2. 取消在途任务并等它们 settle (worker 用的是已捕获的 fm 引用,
               不等就会撞上 "I/O operation on closed file")
            3. 最后才 close 客户端
        """
        with self._state_lock:
            if self._closing:
                return  # 重入保护
            self._closing = True

        try:
            self._drain_services()

            client = self._s3_client
            self._s3_client = None
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            with self._state_lock:
                self._managers.clear()
        finally:
            with self._state_lock:
                self._closing = False

    def _drain_services(self) -> None:
        """取消并等待所有在途任务, 再 cleanup 释放资源"""
        services = list(self._services.values())
        for svc in services:
            cancel_all = getattr(svc, "cancel_all", None)
            if callable(cancel_all):
                try:
                    cancel_all()
                except Exception:
                    pass
            wait_idle = getattr(svc, "wait_idle", None)
            if callable(wait_idle):
                try:
                    wait_idle(self.DISCONNECT_DRAIN_TIMEOUT)
                except Exception:
                    pass
        for svc in services:
            self._cleanup_one(svc)
        with self._state_lock:
            self._services.clear()

    @staticmethod
    def _cleanup_one(svc) -> None:
        cleanup = getattr(svc, "cleanup", None)
        if cleanup:
            try:
                cleanup()
            except Exception:
                pass

    def shutdown(self) -> None:
        self.disconnect()
        with self._state_lock:
            self._services.clear()

    # ==================== Managers ====================

    def _check_connected(self):
        if self._closing:
            raise ConnectionError("正在断开连接, 请稍后重试", code="Closing")
        if not self.is_connected:
            raise ConnectionError("尚未连接服务器", code="NotConnected")

    @property
    def bucket_manager(self) -> BucketManager:
        with self._state_lock:
            if "bucket" not in self._managers:
                self._check_connected()
                self._managers["bucket"] = BucketManager(self._s3_client)
            return self._managers["bucket"]

    @property
    def file_manager(self) -> FileManager:
        with self._state_lock:
            if "file" not in self._managers:
                self._check_connected()
                self._managers["file"] = FileManager(self._s3_client)
            return self._managers["file"]

    @property
    def admin_manager(self) -> AdminManager:
        with self._state_lock:
            if "admin" not in self._managers:
                self._check_connected()
                self._managers["admin"] = AdminManager(self._s3_client)
            return self._managers["admin"]

    @property
    def stats_manager(self) -> StatsManager:
        with self._state_lock:
            if "stats" not in self._managers:
                self._check_connected()
                self._managers["stats"] = StatsManager(self._s3_client)
            return self._managers["stats"]

    # ==================== Services ====================
    # 全部在 _state_lock 内构造: 否则并发下会造出两个 TransferService,
    # 两者各有独立 _tasks 字典, 一个的 cancel_all() 取消不掉另一个。

    @property
    def connection(self) -> "ConnectionService":
        with self._state_lock:
            if "connection" not in self._services:
                from .connection_service import ConnectionService
                self._services["connection"] = ConnectionService(self)
            return self._services["connection"]

    @property
    def transfer(self) -> "TransferService":
        with self._state_lock:
            if "transfer" not in self._services:
                from .transfer_service import TransferService
                self._services["transfer"] = TransferService(self)
            return self._services["transfer"]

    @property
    def logger(self) -> "LogService":
        with self._state_lock:
            if "logger" not in self._services:
                from .log_service import LogService
                self._services["logger"] = LogService(self.config_manager)
            return self._services["logger"]

    @property
    def clipboard(self) -> "ClipboardService":
        with self._state_lock:
            if "clipboard" not in self._services:
                from .clipboard_service import ClipboardService
                self._services["clipboard"] = ClipboardService(self)
            return self._services["clipboard"]

    @property
    def search(self) -> "SearchService":
        with self._state_lock:
            if "search" not in self._services:
                from .search_service import SearchService
                self._services["search"] = SearchService(self)
            return self._services["search"]

    @property
    def cache(self) -> "CacheService":
        with self._state_lock:
            if "cache" not in self._services:
                from .cache_service import CacheService
                self._services["cache"] = CacheService()
            return self._services["cache"]

    @property
    def permission(self) -> "PermissionService":
        with self._state_lock:
            if "permission" not in self._services:
                from .permission_service import PermissionService
                self._services["permission"] = PermissionService(self)
            return self._services["permission"]

    def reset_services(self) -> None:
        with self._state_lock:
            services = list(self._services.values())
        for svc in services:
            self._cleanup_one(svc)
        with self._state_lock:
            self._services.clear()
