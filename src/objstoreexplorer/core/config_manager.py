# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""配置管理 - 加密 SQLite 存储

特性:
    - 所有敏感信息 (AK/SK) 用 Fernet 加密存储
    - 线程安全 (RLock)
    - contextmanager 管理连接
    - 自动创建表结构
    - UPSERT 语法 (ON CONFLICT)

存储内容:
    - servers: 服务器连接配置
    - user_history: 用户创建历史
    - logs: 操作日志
"""
from __future__ import annotations
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Optional, Any

from ..config.settings import DB_DIR, DB_FILE_NAME
from ..config.exceptions import ConfigError
from .encryption import Encryptor


# ==================== 表结构 SQL ====================

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    endpoint TEXT NOT NULL,
    access_key TEXT NOT NULL,
    secret_key TEXT NOT NULL,
    ssl INTEGER DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    access_key TEXT NOT NULL,
    bucket_name TEXT,
    policy_name TEXT,
    policy_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level TEXT NOT NULL,
    operation TEXT,
    target TEXT,
    status TEXT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_servers_name ON servers(name);
"""


class ConfigManager:
    """配置管理器 (单例使用)

    用法:
        cfg = ConfigManager()
        cfg.add_server("prod", "192.168.1.1:9000", "ak", "sk")
        servers = cfg.list_servers()  # 自动解密
    """

    _instance: Optional["ConfigManager"] = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: Optional[Path] = None):
        # ⚠ __init__ 也必须持锁。
        # 旧实现只给 __new__ 加了锁, __init__ 里的 `_initialized` 检查-赋值
        # 是裸的。两个线程同时首次构造时会双双通过检查, 各跑一遍
        # Encryptor() + _init_db()。Encryptor 内部已经改成原子创建 key,
        # 但这里仍可能出现"两个半初始化实例交替赋值 _initialized /
        # _db_lock / _encryptor"的交错, 后续任一线程可能拿到一个
        # _encryptor 还是 None 的实例。多实例 (OSE_DATA_DIR) 场景必现。
        with self._singleton_lock:
            if getattr(self, "_initialized", False):
                return

            if db_path is None:
                db_path = DB_DIR / DB_FILE_NAME
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self._db_lock = threading.RLock()
            self._encryptor = Encryptor()
            self._init_db()
            self._initialized = True

    # ==================== 连接管理 ====================

    @contextmanager
    def _conn(self):
        """获取数据库连接 (with 上下文)

        Raises:
            ConfigError: 连接或执行失败
        """
        with self._db_lock:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=10,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                raise ConfigError(
                    f"数据库操作失败: {e}",
                    code="DBError",
                ) from e
            finally:
                conn.close()

    def _init_db(self) -> None:
        """初始化表结构"""
        with self._conn() as conn:
            conn.executescript(_INIT_SQL)

    # ==================== 服务器配置 ====================

    def add_server(
        self,
        name: str,
        endpoint: str,
        access_key: str,
        secret_key: str,
        ssl: bool = False,
        is_admin: bool = False,
    ) -> bool:
        """保存/更新服务器配置 (ak/sk 加密存储)

        Args:
            name: 配置名称 (唯一)
            endpoint: 服务器地址
            access_key: 访问密钥
            secret_key: 密钥
            ssl: 是否使用 HTTPS
            is_admin: 是否为管理员账号

        Returns:
            是否成功
        """
        encrypted_ak = self._encryptor.encrypt(access_key)
        encrypted_sk = self._encryptor.encrypt(secret_key)

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO servers
                    (name, endpoint, access_key, secret_key, ssl, is_admin)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    endpoint=excluded.endpoint,
                    access_key=excluded.access_key,
                    secret_key=excluded.secret_key,
                    ssl=excluded.ssl,
                    is_admin=excluded.is_admin
                """,
                (name, endpoint, encrypted_ak, encrypted_sk,
                 1 if ssl else 0, 1 if is_admin else 0),
            )
        return True

    def list_servers(self) -> List[Dict[str, Any]]:
        """列出所有服务器配置 (自动解密 ak/sk)

        Returns:
            配置字典列表,按最近使用时间倒序
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, name, endpoint, access_key, secret_key,
                       ssl, is_admin, created_at, last_used_at
                FROM servers
                ORDER BY
                    CASE WHEN last_used_at IS NULL THEN 1 ELSE 0 END,
                    last_used_at DESC,
                    name ASC
                """
            ).fetchall()

        return [self._row_to_server(r) for r in rows]

    def get_server(self, name: str) -> Optional[Dict[str, Any]]:
        """按名称获取服务器配置"""
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM servers WHERE name = ?",
                (name,),
            ).fetchone()
        return self._row_to_server(r) if r else None

    def delete_server(self, name: str) -> bool:
        """删除服务器配置"""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM servers WHERE name = ?",
                (name,),
            )
            return cur.rowcount > 0

    def mark_used(self, name: str) -> None:
        """标记最近使用"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE servers SET last_used_at = CURRENT_TIMESTAMP WHERE name = ?",
                (name,),
            )

    def _row_to_server(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转为字典 (含解密)"""
        return {
            "id": row["id"],
            "name": row["name"],
            "endpoint": row["endpoint"],
            "access_key": self._encryptor.decrypt(row["access_key"]),
            "secret_key": self._encryptor.decrypt(row["secret_key"]),
            "ssl": bool(row["ssl"]),
            "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
        }

    # ==================== 用户创建历史 ====================

    def add_user_history(
        self,
        access_key: str,
        bucket_name: str = "",
        policy_name: str = "",
        policy_type: str = "",
    ) -> bool:
        """记录用户创建历史

        access_key 与 servers 表一样走 Fernet 加密。旧实现直接明文落盘,
        库里另外两张表的 AK 是密文、这张表是明文 —— 数据库文件一旦被复制
        或备份, 用户 AK 直接泄露, 加密策略自相矛盾。
        """
        encrypted_ak = self._encryptor.encrypt(access_key) if access_key else ""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO user_history
                    (access_key, bucket_name, policy_name, policy_type)
                VALUES (?, ?, ?, ?)
                """,
                (encrypted_ak, bucket_name, policy_name, policy_type),
            )
        return True

    def get_user_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取用户创建历史 (自动解密 ak)

        兼容库里可能已存在的明文旧记录: 解密失败就原样返回, 不让整页崩掉。
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM user_history
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                raw = d.get("access_key") or ""
                if raw:
                    try:
                        d["access_key"] = self._encryptor.decrypt(raw)
                    except Exception:
                        # 旧版本写入的明文, 或密钥已轮换 —— 原样保留
                        d["access_key"] = raw
                out.append(d)
            return out

    def clear_user_history(self) -> bool:
        """清空用户历史"""
        with self._conn() as conn:
            conn.execute("DELETE FROM user_history")
        return True

    # ==================== 操作日志 ====================

    def add_log(
        self,
        level: str,
        operation: str = "",
        target: str = "",
        status: str = "info",
        message: str = "",
    ) -> bool:
        """添加操作日志

        Args:
            level: 日志级别 (INFO/WARNING/ERROR)
            operation: 操作类型 (connect/upload/...)
            target: 操作目标
            status: 状态 (success/failure)
            message: 消息
        """
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO logs
                    (level, operation, target, status, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (level, operation, target, status, message),
            )
        return True

    def get_logs(
        self,
        limit: int = 100,
        level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取操作日志

        Args:
            limit: 最大返回数量
            level: 按级别过滤 (None/INFO/WARNING/ERROR)
        """
        query = "SELECT * FROM logs"
        params: list = []
        if level:
            query += " WHERE level = ?"
            params.append(level)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def clear_logs(self) -> bool:
        """清空日志"""
        with self._conn() as conn:
            conn.execute("DELETE FROM logs")
        return True

    # ==================== 维护 ====================

    def vacuum(self) -> None:
        """清理数据库碎片"""
        with self._conn() as conn:
            conn.execute("VACUUM")

    # ==================== 应用设置 (key-value) ====================

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """读取应用设置值, 不存在时返回 default"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """写入应用设置 (UPSERT)"""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (key, value),
            )

    def get_setting_int(self, key: str, default: int) -> int:
        """读取整数设置 (解析失败时回退 default)"""
        v = self.get_setting(key)
        if v is None:
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def delete_setting(self, key: str) -> None:
        """删除应用设置 (不存在不报错)"""
        with self._conn() as conn:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
