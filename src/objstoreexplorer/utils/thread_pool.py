# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""utils/thread_pool - 全局线程池

使用 concurrent.futures 替代 MinFSExplorer 的 TaskManager + cancel_flag 闭包,
更标准、更易测试。
"""
from __future__ import annotations
import atexit
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from ..config.settings import THREAD_POOL_WORKERS


_pool: Optional[ThreadPoolExecutor] = None
_pool_lock = threading.Lock()


def get_thread_pool(max_workers: int = THREAD_POOL_WORKERS) -> ThreadPoolExecutor:
    """获取全局线程池 (单例,延迟初始化)"""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="ose-worker",
            )
        return _pool


def shutdown_pool() -> None:
    """关闭线程池"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=True)
            _pool = None


# 全仓搜过: shutdown_pool 此前零调用, 进程退出时线程池不回收 (工作线程挂着
# 等队列, 解释器退出前可能残留线程 / 资源不释放)。注册 atexit 兜底。
atexit.register(shutdown_pool)
