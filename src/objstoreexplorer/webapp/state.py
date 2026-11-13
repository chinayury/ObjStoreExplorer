# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""Web 应用全局状态 (进程内单例容器)

lifespan 启动时 init() 一次; 路由经 state.xxx 访问。

v0.1.0 第二轮迭代 (会话外置化): AppState 新增 persist (WebStateStore,
SQLite 会话/任务持久化); 会话签名密钥的生成改为 O_CREAT|O_EXCL 原子
创建 —— 多 worker 同时首次启动不再互相覆盖出不同密钥。
进程内仍保留的内存态 (会话管理器缓存/任务线程) 均为持久层的缓存或
执行器, 丢失可由持久层重建 (见 webapp/persist.py 模块注释)。
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi.templating import Jinja2Templates

from ..core.config_manager import ConfigManager
from .store import WebUserStore, WEB_DIR
from .persist import WebStateStore
from .context import SessionManager
from .tasks import WebTaskManager

logger = logging.getLogger("ose.web.state")

_STATE: Optional["AppState"] = None
_STATE_LOCK = threading.Lock()

SESSION_COOKIE_TTL = 7 * 24 * 3600  # 登录态 cookie 有效期 7 天
SECRET_KEY_FILE = "secret.key"
SESSION_IDLE_TTL = 1800  # 30 分钟无活动断开 S3 会话
# last_active 落库节流: 活跃时间写 DB 每 worker 最多一次/30s
# (闲置回收的跨 worker 判定用, 秒级精度足够)
SESSION_ACTIVE_FLUSH_SECONDS = 30


class AppState:
    """全局单例: 用户库 / 会话表 / 任务表 / 模板引擎 / 共享配置库"""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.store = WebUserStore()
        self.persist = WebStateStore()
        self.sessions = SessionManager(
            self.config_manager, ttl_seconds=SESSION_IDLE_TTL,
            persist=self.persist,
        )
        self.tasks = WebTaskManager(persist=self.persist)
        self.templates = Jinja2Templates(directory=str(_template_dir()))
        self._secret_key = self._load_secret_key()

    # ==================== 会话签名密钥 ====================

    def _load_secret_key(self) -> str:
        """加载/生成会话签名密钥 (持久化, 重启不掉登录态, 多 worker 共享)

        v0.1.0 第二轮修复: 旧实现 read → generate → write_text 三步无原子性,
        N 个 worker 同时首次启动时各写一份, 后写者覆盖先写者 —— 各 worker
        内存密钥互不相同, 令牌跨 worker 全部失效。改为 O_CREAT|O_EXCL 原子
        创建, 抢锁失败者轮询等待赢家写完再读 (与 core/encryption.Encryptor
        同一套并发纪律)。
        """
        path = Path(WEB_DIR) / SECRET_KEY_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = self._read_secret_with_retry(path)
            if existing:
                return existing
            key = secrets.token_urlsafe(48)
            try:
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                # 别的 worker 抢到了创建权: 等它写完再读
                raced = self._read_secret_with_retry(path)
                if raced:
                    return raced
                raise RuntimeError(f"会话密钥文件竞争写入失败: {path}")
            except OSError as e:
                raise RuntimeError(f"无法创建会话密钥文件 {path}: {e}") from e
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(key)
                f.flush()
                os.fsync(f.fileno())
            try:
                path.chmod(0o600)
            except OSError:
                pass
            return key
        except RuntimeError as e:
            # 文件存在但两轮等待后仍为空: 判定为残留的截断/损坏文件
            # (旧密钥本就不可用), 直接重写自愈 —— 代价是全部会话重新登录
            try:
                key = secrets.token_urlsafe(48)
                path.write_text(key, encoding="utf-8")
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
                logger.warning("会话密钥文件异常, 已重新生成 (%s): %s", path, e)
                return key
            except OSError:
                logger.warning("无法持久化会话密钥 (%s), 退化为进程内随机密钥", path)
                return secrets.token_urlsafe(48)
        except OSError:
            # 极端情况 (只读盘): 退化为进程内随机密钥, 重启需重新登录
            logger.warning("无法访问会话密钥路径 %s, 退化为进程内随机密钥", path)
            return secrets.token_urlsafe(48)

    @staticmethod
    def _read_secret_with_retry(path: Path, timeout: float = 5.0) -> str:
        """读取密钥文件内容; 文件存在但为空时短暂轮询 (并发创建的中间态)

        返回 '' 表示: 文件不存在 (走创建路径) 或等待超时仍为空 (由调用方
        走损坏自愈分支)。
        """
        deadline = time.monotonic() + timeout
        delay = 0.005
        while True:
            try:
                if path.exists():
                    key = path.read_text(encoding="utf-8").strip()
                    if key:
                        return key
                else:
                    return ""  # 不存在: 无需等待, 直接走原子创建
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return ""
            time.sleep(delay)
            delay = min(delay * 2, 0.1)

    @property
    def secret_key(self) -> str:
        return self._secret_key


def _template_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def get_state() -> AppState:
    """取全局状态 (未初始化时惰性创建, 便于测试直连)"""
    global _STATE
    if _STATE is None:
        with _STATE_LOCK:
            if _STATE is None:
                _STATE = AppState()
    return _STATE


def set_state(state: Optional[AppState]) -> None:
    """测试注入用"""
    global _STATE
    with _STATE_LOCK:
        _STATE = state
