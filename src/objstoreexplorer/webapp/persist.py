# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""Web 会话/任务持久化 (SQLite) —— 会话外置化的存储层

v0.1.0 第二轮迭代 (会话外置化):
    旧实现里 WebSession (S3 连接/剪贴板) 与 WebTask 全部在进程内存, 必须
    workers=1 才能工作 (webapp/context.py 旧注释明言)。本模块把三样东西
    落到 data/web/web.db (与 Web 账号库同文件, WAL 模式):

    web_sessions  登录会话行 (sid 主键):
        - 吊销依据: 登出/停用/删除账号 -> revoked=1, 所有 worker 即时生效
          (旧实现登出只清 cookie + 本进程内存, 被偷的 cookie 到期前一直可用);
        - 连接快照: endpoint + Fernet 加密的 AK/SK + ssl。worker 重启或请求
          落到另一个 worker 时, 会话管理器据快照重建 S3 连接;
        - 剪贴板 JSON: 跨 worker 保持复制/剪切内容。
    web_tasks     传输任务注册表: 任务状态/进度/结果路径落库, 任意 worker
        可轮询与取消 (结果 zip 在共享卷上, 路径全局有效)。

    多 worker 并发边界 (对标竞品未踩过的坑):
        - 写路径只有登录/登出/连接变更/任务进度, 频度低; WAL + busy_timeout
          足以承载。行级冲突由 SQLite 文件锁串行化, 应用层不再加跨进程锁。
        - "database is locked" 映射为带中文提示的 TimeoutError (参照 sairo
          mcp/db.py 的成熟模式), 调用方按"读失败视为未登录 (fail closed)、
          写失败仅记日志"分级处理。
        - 每次操作独立连接 (与 WebUserStore 同构), 无常驻连接泄漏面。

    加密: AK/SK 沿用 core.encryption.Encryptor (data/explorer.key Fernet),
    密钥管理不引入新机制 —— 题设"沿用项目现有 data/ 密钥机制"。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.encryption import Encryptor
from .store import WEB_DIR, WEB_DB_FILE

logger = logging.getLogger("ose.web.persist")

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS web_sessions (
    sid TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    endpoint TEXT NOT NULL DEFAULT '',
    ak_enc TEXT NOT NULL DEFAULT '',
    sk_enc TEXT NOT NULL DEFAULT '',
    ssl INTEGER NOT NULL DEFAULT 0,
    connected INTEGER NOT NULL DEFAULT 0,
    conn_updated_at REAL NOT NULL DEFAULT 0,
    last_active REAL NOT NULL DEFAULT 0,
    clipboard TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_web_sessions_expires ON web_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(username);
CREATE TABLE IF NOT EXISTS web_tasks (
    id TEXT PRIMARY KEY,
    owner_sid TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    total INTEGER NOT NULL DEFAULT 0,
    current INTEGER NOT NULL DEFAULT 0,
    current_name TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '[]',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    pause_requested INTEGER NOT NULL DEFAULT 0,
    result_path TEXT NOT NULL DEFAULT '',
    result_name TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_web_tasks_created ON web_tasks(created_at);
"""


class SessionStoreTimeout(TimeoutError):
    """SQLite 忙等超时 (database is locked) 的友好包装"""


def _wrap_locked(exc: sqlite3.Error) -> Exception:
    """把锁等待超时翻译成可读提示; 其余 SQLite 错误原样返回"""
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return SessionStoreTimeout("数据库正忙, 请稍后重试 (database is locked)")
    return exc


class WebStateStore:
    """Web 会话与任务持久化存储 (线程安全, 每次操作独立连接)

    同一 worker 内多线程经 RLock 串行; 跨 worker 由 SQLite 文件锁 +
    busy_timeout 承载。web.db 与 WebUserStore 共用文件, 两边都开了 WAL。
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = WEB_DIR / WEB_DB_FILE
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._encryptor = Encryptor()
        self._init_db()

    # ==================== 连接 ====================

    @staticmethod
    def _open(db_path: Path) -> sqlite3.Connection:
        """打开连接并设置多进程友好 PRAGMA (WAL / busy_timeout / NORMAL)"""
        conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        """建表 + 开 WAL + 轻量迁移 (幂等, N 个 worker 同时执行安全)"""
        with self._lock:
            conn = self._open(self.db_path)
            try:
                # journal_mode=WAL: 读写不互斥, 多 worker 读会话行不阻塞写
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.executescript(_INIT_SQL)
                # 迁移: 旧库没有 pause_requested 列 (v0.6.0 跨 worker 暂停)。
                # 新库由 _INIT_SQL 建列, ALTER 报 duplicate column 忽略即可。
                try:
                    conn.execute(
                        "ALTER TABLE web_tasks ADD COLUMN "
                        "pause_requested INTEGER NOT NULL DEFAULT 0")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # 列已存在
            except sqlite3.Error as e:
                raise _wrap_locked(e) from e
            finally:
                conn.close()

    @classmethod
    def _run(cls, db_path: Path, lock: threading.RLock, func):
        """统一执行器: 独立连接 + 提交/回滚 + 锁错误翻译"""
        with lock:
            conn = cls._open(db_path)
            try:
                result = func(conn)
                conn.commit()
                return result
            except sqlite3.Error as e:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise _wrap_locked(e) from e
            finally:
                conn.close()

    # ==================== 会话 ====================

    def create_session(self, sid: str, username: str, ttl_seconds: int) -> None:
        """登录时登记会话行 (expires_at = 现在 + ttl; 重登同 sid 覆盖)"""
        now = time.time()
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "INSERT INTO web_sessions (sid, username, expires_at, conn_updated_at, last_active) "
            "VALUES (?, ?, datetime('now', ?), ?, ?) "
            "ON CONFLICT(sid) DO UPDATE SET username=excluded.username, "
            "expires_at=excluded.expires_at, revoked=0, last_active=excluded.last_active",
            (sid, username, f"+{int(ttl_seconds)} seconds", now, now),
        ))

    def touch_session(self, sid: str) -> None:
        """刷新会话活跃时间 (调用方节流, 见 WebSession.touch)"""
        if not sid:
            return
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "UPDATE web_sessions SET last_active = ? WHERE sid = ?",
            (time.time(), sid),
        ))

    def get_session(self, sid: str) -> Optional[Dict[str, Any]]:
        """取会话行 (dict); 不存在/参数为空返回 None。

        注意: 本方法不做"是否过期/吊销"判定, 由调用方统一裁决
        (is_session_valid), 避免两处口径不一致。
        """
        if not sid:
            return None
        return self._run(self.db_path, self._lock, lambda conn: (
            (lambda row: dict(row) if row else None)(
                conn.execute("SELECT * FROM web_sessions WHERE sid = ?", (sid,)).fetchone()
            )
        ))

    def is_session_valid(self, sid: str, username: str) -> bool:
        """会话行有效性裁决: 存在 + 未吊销 + 未过期 + 归属当前用户

        鉴权依赖 (deps.get_current_user) 每请求调用; WAL 下是纯读, 不阻塞。
        读失败 (库忙等异常) 按"无效"处理 —— fail closed, 宁可让用户重新登录
        也不放行无法核验的会话。
        """
        row = self.get_session(sid)
        if row is None:
            return False
        if row["revoked"]:
            return False
        if row["username"] != username:
            return False
        exp = self._parse_expires(row["expires_at"])
        return exp is not None and exp > time.time()

    @staticmethod
    def _parse_expires(value: Any) -> Optional[float]:
        """解析 expires_at (SQLite datetime('now', ...) 产出的 UTC 字符串)"""
        if not value:
            return None
        try:
            import calendar
            t = time.strptime(str(value), "%Y-%m-%d %H:%M:%S")
            return calendar.timegm(t)  # UTC -> epoch
        except (ValueError, TypeError):
            return None

    def revoke_session(self, sid: str) -> None:
        """吊销单个会话 (登出): 行保留到清理循环物理删除"""
        if not sid:
            return
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "UPDATE web_sessions SET revoked = 1 WHERE sid = ?", (sid,),
        ))

    def revoke_user_sessions(self, username: str) -> int:
        """吊销某用户的全部会话 (停用/删除账号), 返回吊销行数"""
        return self._run(self.db_path, self._lock, lambda conn: (
            conn.execute(
                "UPDATE web_sessions SET revoked = 1 "
                "WHERE username = ? AND revoked = 0", (username,),
            ).rowcount
        ))

    def clear_connection(self, sid: str) -> None:
        """清空会话的连接快照 (断开/闲置回收): cookie 仍有效, 但需重新连接 S3"""
        if not sid:
            return
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "UPDATE web_sessions SET connected = 0, endpoint = '', "
            "ak_enc = '', sk_enc = '', ssl = 0 WHERE sid = ?", (sid,),
        ))

    def update_connection(
        self, sid: str, endpoint: str, access_key: str, secret_key: str, ssl: bool,
    ) -> None:
        """保存连接快照 (AK/SK Fernet 加密; 写失败向上抛, 由调用方记日志)"""
        ak_enc = self._encryptor.encrypt(access_key)
        sk_enc = self._encryptor.encrypt(secret_key)
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "UPDATE web_sessions SET endpoint = ?, ak_enc = ?, sk_enc = ?, "
            "ssl = ?, connected = 1, conn_updated_at = ? WHERE sid = ?",
            (endpoint, ak_enc, sk_enc, 1 if ssl else 0, time.time(), sid),
        ))

    def set_clipboard(self, sid: str, clipboard_json: str) -> None:
        """保存剪贴板 JSON (空串 = 清空)"""
        if not sid:
            return
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "UPDATE web_sessions SET clipboard = ? WHERE sid = ?",
            (clipboard_json or "", sid),
        ))

    def decrypt_field(self, ciphertext: str) -> str:
        """解密快照字段 (密钥轮换等解密失败返回空串, 由调用方按连接失败处理)"""
        if not ciphertext:
            return ""
        try:
            return self._encryptor.decrypt(ciphertext)
        except Exception:
            logger.warning("会话连接快照解密失败 (密钥已轮换?), 该会话需重新连接")
            return ""

    def purge_expired_sessions(self) -> int:
        """清理过期/吊销的会话行 (lifespan 清理循环调用), 返回删除行数"""
        return self._run(self.db_path, self._lock, lambda conn: (
            conn.execute(
                "DELETE FROM web_sessions WHERE revoked = 1 OR expires_at < datetime('now')",
            ).rowcount
        ))

    # ==================== 任务 ====================

    def upsert_task(self, row: Dict[str, Any]) -> None:
        """任务行写入/更新 (注册、进度推进、终态落库共用)"""
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "INSERT INTO web_tasks (id, owner_sid, kind, label, status, total, "
            "current, current_name, error, details, cancel_requested, "
            "result_path, result_name, created_at, finished_at) "
            "VALUES (:id, :owner_sid, :kind, :label, :status, :total, "
            ":current, :current_name, :error, :details, :cancel_requested, "
            ":result_path, :result_name, :created_at, :finished_at) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
            "total=excluded.total, current=excluded.current, "
            "current_name=excluded.current_name, error=excluded.error, "
            "details=excluded.details, "
            "cancel_requested=MAX(web_tasks.cancel_requested, excluded.cancel_requested), "
            "result_path=excluded.result_path, result_name=excluded.result_name, "
            "finished_at=excluded.finished_at",
            row,
        ))

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        if not task_id:
            return None
        return self._run(self.db_path, self._lock, lambda conn: (
            (lambda row: dict(row) if row else None)(
                conn.execute("SELECT * FROM web_tasks WHERE id = ?", (task_id,)).fetchone()
            )
        ))

    def list_tasks(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._run(self.db_path, self._lock, lambda conn: [
            dict(r) for r in conn.execute(
                "SELECT * FROM web_tasks ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            )
        ])

    def request_task_cancel(self, task_id: str) -> None:
        """跨 worker 取消请求: 置 cancel_requested, 执行方轮询到后自行中止"""
        if not task_id:
            return
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "UPDATE web_tasks SET cancel_requested = 1 WHERE id = ?", (task_id,),
        ))

    def is_task_cancel_requested(self, task_id: str) -> bool:
        if not task_id:
            return False
        row = self.get_task(task_id)
        return bool(row and row["cancel_requested"])

    def request_task_pause(self, task_id: str) -> None:
        """跨 worker 暂停请求: 置 pause_requested, 执行方轮询到后自行暂停"""
        if not task_id:
            return
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "UPDATE web_tasks SET pause_requested = 1 WHERE id = ?", (task_id,),
        ))

    def request_task_resume(self, task_id: str) -> None:
        """跨 worker 恢复请求: 清 pause_requested (恢复是可逆开关, 不用 MAX 粘性)"""
        if not task_id:
            return
        self._run(self.db_path, self._lock, lambda conn: conn.execute(
            "UPDATE web_tasks SET pause_requested = 0 WHERE id = ?", (task_id,),
        ))

    def is_task_pause_requested(self, task_id: str) -> bool:
        if not task_id:
            return False
        row = self.get_task(task_id)
        return bool(row and row["pause_requested"])

    def purge_tasks(self, result_ttl_seconds: int, stale_running_seconds: int) -> int:
        """清理任务行: 完成/取消且超 TTL 的 + 长时间无进展的 running 孤儿行

        孤儿行来源: worker 被强杀时 running 行没有终态落库。stale 阈值取
        24h —— 远大于任何正常任务的执行时长。
        """
        now = time.time()
        return self._run(self.db_path, self._lock, lambda conn: (
            conn.execute(
                "DELETE FROM web_tasks WHERE "
                "(finished_at IS NOT NULL AND finished_at < ?) OR "
                "(finished_at IS NULL AND created_at < ?)",
                (now - result_ttl_seconds, now - stale_running_seconds),
            ).rowcount
        ))
