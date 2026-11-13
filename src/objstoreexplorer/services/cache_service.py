# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""services/cache_service - 缓存服务

提供本地文件缓存 (用于文件预览),支持:
    - MD5 key 哈希
    - 大小限制
    - 过期清理
"""
from __future__ import annotations
import os
import time
import hashlib
import shutil
import threading
from typing import Optional
from pathlib import Path

from ..config.settings import CACHE_DIR, DEFAULT_CACHE_SIZE_MB, DEFAULT_CACHE_EXPIRE_HOURS


class CacheService:
    """缓存服务"""

    def __init__(self):
        self._cache_dir = CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # 启动时清一次过期项 (否则 clean_expired 全项目零调用, 缓存只增不减)
        self.clean_expired()

    def get_path(self, key: str) -> Path:
        """获取 key 对应的缓存文件路径"""
        h = hashlib.md5(key.encode("utf-8")).hexdigest()
        return self._cache_dir / h

    def exists(self, key: str) -> bool:
        return self.get_path(key).exists()

    def get(self, key: str) -> Optional[Path]:
        """获取缓存文件路径 (不存在返回 None)"""
        path = self.get_path(key)
        if path.exists():
            return path
        return None

    def put(self, key: str, source: Path) -> Optional[Path]:
        """将文件放入缓存

        复制在**锁外**做 (大文件不阻塞其他缓存操作), 锁内只做原子改名,
        顺带保证读者不会看到写了一半的文件。

        Returns:
            缓存文件路径,失败返回 None
        """
        dest = self.get_path(key)
        tmp: Optional[Path] = None
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            # 1) 锁外: 慢 IO
            tmp = dest.with_name(f"{dest.name}.{threading.get_ident()}.tmp")
            shutil.copy2(source, tmp)
            # 2) 锁内: 只做 rename, 临界区极短
            with self._lock:
                os.replace(tmp, dest)
            tmp = None
        except Exception:
            if tmp is not None:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
            return None

        # 3) 锁外: 触发容量回收 (之前全项目零调用, 缓存只增不减)
        self.limit_size()
        return dest

    def remove(self, key: str) -> bool:
        try:
            with self._lock:
                path = self.get_path(key)
                if path.exists():
                    path.unlink()
                    return True
        except Exception:
            pass
        return False

    def clear(self) -> bool:
        """清空缓存"""
        try:
            with self._lock:
                if self._cache_dir.exists():
                    shutil.rmtree(self._cache_dir)
                    self._cache_dir.mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False

    def clean_expired(self, max_age_hours: int = DEFAULT_CACHE_EXPIRE_HOURS) -> int:
        """清理过期缓存,返回删除数量"""
        count = 0
        try:
            cutoff = time.time() - max_age_hours * 3600
            with self._lock:
                if not self._cache_dir.exists():
                    return 0
                for path in self._cache_dir.iterdir():
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        try:
                            path.unlink()
                            count += 1
                        except Exception:
                            pass
        except Exception:
            pass
        return count

    def get_size(self) -> int:
        """获取缓存总大小 (字节)"""
        total = 0
        try:
            with self._lock:
                if self._cache_dir.exists():
                    for path in self._cache_dir.rglob("*"):
                        if path.is_file():
                            total += path.stat().st_size
        except Exception:
            pass
        return total

    def limit_size(self, max_size_mb: int = DEFAULT_CACHE_SIZE_MB) -> int:
        """限制缓存大小,返回删除文件数"""
        max_bytes = max_size_mb * 1024 * 1024
        count = 0
        try:
            with self._lock:
                # 在锁内重新计算,避免外部 get_size 读到 stale 值
                current = 0
                for path in self._cache_dir.rglob("*"):
                    if path.is_file():
                        current += path.stat().st_size
                if current <= max_bytes:
                    return 0

                files = []
                for path in self._cache_dir.iterdir():
                    if path.is_file():
                        files.append((path.stat().st_mtime, path))
                files.sort()  # 旧的在前

                for _mtime, path in files:
                    if current <= max_bytes:
                        break
                    try:
                        size = path.stat().st_size
                        path.unlink()
                        current -= size
                        count += 1
                    except Exception:
                        pass
        except Exception:
            pass
        return count

    def cleanup(self) -> None:
        self.clear()
