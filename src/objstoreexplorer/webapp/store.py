# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""Web 用户账号存储

独立于桌面版的加密 SQLite (config.db), 存 Web 登录账号:
    - bcrypt 哈希口令 (不存明文, 不用 Fernet)
    - admin / viewer 两角色
    - 首次启动自动创建 admin 账号 (密码取 WEB_ADMIN_PASSWORD, 未设置则随机生成打印到 stdout)

v2.1 用户管理增强 (借鉴《用户管理需求说明文档》):
    - 账号级持久化锁定: 连续失败 N 次锁定, 重启不丢 (替代原内存限速)
    - 管理员重置/新建 = 一次性随机临时口令 + 强制改密标记
    - 启用/禁用 (禁用后已有会话立即失效)、管理员手动解锁
    - 软删除 (改名释放唯一键, 数据保留供审计)
    - 口令历史不重复 (最近 N 个哈希, 含当前)

v0.1.0 第二轮加固:
    - M-01: 初始管理员口令只走 stdout (容器 docker logs 可见), **不再写
      logger** —— `ose` logger 挂着 RotatingFileHandler, 口令会落进
      data/logs/app.log 这个全局可读的文件
    - M-02: 所有口令入口统一预校验 72 字节上限 (bcrypt 的硬限制), 超长
      直接给中文提示, 不再让 ValueError 英文堆栈直出到界面
    - M-09: 用户不存在时也对一个固定 dummy 哈希跑一次 bcrypt.checkpw,
      抹平"用户不存在 vs 口令错误"的时序侧信道 (防用户名枚举)

数据库: data/web/web.db
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re as _re_email
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import bcrypt

from ..config.settings import APP_DIR

logger = logging.getLogger("ose.web.store")

WEB_DIR = APP_DIR / "web"
WEB_DB_FILE = "web.db"

ROLES = ("admin", "viewer")

# 账号安全策略常量 (与用户中心设计文档口径一致)
ACCOUNT_FAIL_LIMIT = 5      # 连续失败 N 次锁定
ACCOUNT_LOCK_MINUTES = 15   # 锁定时长(分钟)
PASSWORD_HISTORY_KEEP = 5   # 最近 N 个口令不得重复

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS web_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMP,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    password_history TEXT NOT NULL DEFAULT '[]',
    deleted_at TIMESTAMP,
    email TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_web_users_name ON web_users(username);
CREATE TABLE IF NOT EXISTS web_reset_codes (
    key TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    last_sent_at TIMESTAMP NOT NULL,
    fails INTEGER NOT NULL DEFAULT 0
);
"""

# 旧库幂等补列 (v2.1): 列名与声明均为代码内常量, 无外部输入拼接
_MIGRATION_COLS = [
    ("is_active", "INTEGER NOT NULL DEFAULT 1"),
    ("failed_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("locked_until", "TIMESTAMP"),
    ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
    ("password_history", "TEXT NOT NULL DEFAULT '[]'"),
    ("deleted_at", "TIMESTAMP"),
    ("email", "TEXT NOT NULL DEFAULT ''"),
]

_ADMIN_ENV_VAR = "WEB_ADMIN_PASSWORD"

# v2.3 忘记密码 (借鉴用户中心 B/E 能力)
RESET_CODE_TTL_MINUTES = 10    # 验证码有效期
RESET_RESEND_COOLDOWN = 60     # 重发冷却 (秒)
RESET_MAX_CODE_FAILS = 5       # 校验失败上限, 达到即作废

# M-02: bcrypt 只处理密码的前 72 字节, 超过直接 ValueError (英文堆栈直出
# 到界面, 用户完全看不懂)。所有口令入口统一预校验, 给中文提示。
PASSWORD_MAX_BYTES = 72

# M-09: 用户不存在时也跑一次 bcrypt 的"哑哈希"。这不是任何账号的凭据,
# 唯一作用是让"用户不存在"和"口令错误"两条路径的耗时一致, 掐掉枚举侧信道。
_DUMMY_PASSWORD_HASH = (
    "$2b$10$cb.BCoaKyT2DepEwu3jqYex19/nhWOzsS4RRhrrTB3bAW/e3wryzG"
)


def check_password_length(password: str) -> None:
    """预校验口令字节长度 (bcrypt 72 字节硬限制), 超长抛 ValueError"""
    if password and len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(
            f"口令最长 {PASSWORD_MAX_BYTES} 字节 (一个汉字占 3 字节), 请缩短后重试"
        )


_EMAIL_RE = _re_email.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: Any) -> str:
    """邮箱归一化: 小写/去空格/截断; 非法返回 ''"""
    if email is None:
        return ""
    s = str(email).strip().lower()[:254]
    return s if _EMAIL_RE.match(s) else ""


def hash_password(password: str) -> str:
    """bcrypt 哈希口令"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验口令 (格式错误/不匹配一律 False, 不抛异常)

    M-02: bcrypt 对超过 72 字节的密码抛 ValueError, 以前会一路冒到路由层
    直出英文堆栈。这里连同长度预检一起吃掉, 调用方已在本层之前拦过长口令。
    """
    if not password or not password_hash:
        return False
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def generate_temp_password() -> str:
    """12 位一次性临时口令: 去易混字符(I/O/0/1/l), 保证大小写+数字, secrets 随机。"""
    upper = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    lower = "abcdefghjkmnpqrstuvwxyz"
    digit = "23456789"
    pool = upper + lower + digit
    chars = [secrets.choice(upper), secrets.choice(lower), secrets.choice(digit)]
    chars += [secrets.choice(pool) for _ in range(9)]
    out: List[str] = []
    while chars:
        out.append(chars.pop(secrets.randbelow(len(chars))))
    return "".join(out)


def _parse_ts(value: Any) -> Optional[datetime]:
    """解析 SQLite CURRENT_TIMESTAMP 的 UTC 字符串"""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


class WebUserStore:
    """Web 用户存储 (线程安全, 每次操作独立连接)

    注意: 桌面版 ConfigManager 是进程单例, 但它固定指向 config.db;
    Web 用户库是另一套表, 因此这里自建连接管理 (同样 RLock + 独立连接)。
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = WEB_DIR / WEB_DB_FILE
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as conn:
            conn.executescript(_INIT_SQL)
            existing = {r[1] for r in conn.execute("PRAGMA table_info(web_users)")}
            for col, decl in _MIGRATION_COLS:
                if col not in existing:
                    conn.execute(f"ALTER TABLE web_users ADD COLUMN {col} {decl}")
        self._ensure_admin()

    # ==================== 连接 ====================

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(
                str(self.db_path), timeout=10, check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ==================== 初始化 admin ====================

    def _ensure_admin(self) -> None:
        """首次启动创建 admin 账号

        v0.1.0 第二轮 (多 worker): N 个 worker 同时首次启动都会走到这里,
        "先查后插"存在竞窗 —— 两边都查到"无 admin"然后各自 INSERT, 后到者
        撞 username 唯一约束抛 IntegrityError 直接炸掉该 worker 启动。
        这里捕获唯一冲突后复核: admin 已存在即为成功 (先到者生成的随机
        口令才是生效口令, 见 docker logs)。
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM web_users WHERE role = 'admin' AND deleted_at IS NULL"
            ).fetchone()
            has_admin = row["n"] > 0

        if has_admin:
            return

        env_password = os.environ.get(_ADMIN_ENV_VAR, "").strip()
        if env_password:
            password = env_password
            logger.info("已创建管理员账号 admin (密码来自环境变量 %s)", _ADMIN_ENV_VAR)
        else:
            password = secrets.token_urlsafe(9)
            # M-01: 口令绝不进 logger —— `ose` logger 挂了 RotatingFileHandler,
            # 落盘即同机可读 (data/logs 还会被用户当备份拷走)。stdout 不进
            # 轮转文件, 容器 docker logs 也看得到, 是安全且唯一的出口。
            logger.warning(
                "首次启动: 已创建管理员账号 admin (随机初始密码已输出到 stdout, "
                "请查 docker logs / 控制台; 也可用环境变量 %s 指定初始密码)",
                _ADMIN_ENV_VAR,
            )
            # 打印到 stdout, 容器 docker logs 可见
            print(
                f"\n[ObjStoreExplorer Web] 初始管理员账号: admin / {password}\n"
                f"  (请尽快登录后在「系统设置-Web账号」中修改密码)\n",
                flush=True,
            )
        try:
            self.create_user("admin", password, role="admin")
        except (ValueError, sqlite3.IntegrityError) as e:
            # 竞态复核: 另一 worker 已创建。若确实是"已存在"则无事发生;
            # 否则 (口令强度等参数错误) 属于实现 bug, 原样上抛。
            # ⚠ 必须显式捕 sqlite3.IntegrityError: 并发竞态下 INSERT 撞
            # username 唯一约束抛的是 IntegrityError (继承链
            # IntegrityError→DatabaseError→Error→Exception), 不是 ValueError
            # 子类 —— 只捕 ValueError 时异常穿透 _ensure_admin, 后到 worker
            # 启动即崩 (跨进程 barrier 实测复现过)。IntegrityError 兜住后
            # 下方 SELECT 复核是唯一事实裁决。
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM web_users WHERE username = 'admin' "
                    "AND deleted_at IS NULL"
                ).fetchone()
            if row["n"] == 0:
                raise
            logger.info("admin 账号已由并发初始化的 worker 创建 (%s), 跳过", e)

    # ==================== 内部工具 ====================

    @staticmethod
    def _locked_until(row: sqlite3.Row) -> Optional[datetime]:
        ts = _parse_ts(row["locked_until"])
        if ts and ts > datetime.utcnow():
            return ts
        return None

    def _bump_fail(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        """登录失败计数 +1; 达阈值锁定 (DB 持久化, 重启不丢)"""
        n = int(row["failed_attempts"] or 0) + 1
        if n >= ACCOUNT_FAIL_LIMIT:
            conn.execute(
                "UPDATE web_users SET failed_attempts=?, locked_until=datetime('now', ?) WHERE id=?",
                (n, f"+{ACCOUNT_LOCK_MINUTES} minutes", row["id"]),
            )
        else:
            conn.execute("UPDATE web_users SET failed_attempts=? WHERE id=?", (n, row["id"]))

    # ==================== 登录 ====================

    def login_block_reason(self, username: str) -> str:
        """登录前置门槛: 返回锁定/停用的提示文案 ('' = 不拦)。

        口令错误的提示保持统一 (不区分用户不存在/密码错误, 防枚举);
        锁定与停用是运维状态, 如实告知用户等待或找管理员。
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM web_users WHERE username = ? AND deleted_at IS NULL",
                ((username or "").strip(),),
            ).fetchone()
        if row is None:
            return ""
        if not int(row["is_active"] or 0):
            return "账号已被停用, 请联系管理员"
        locked = self._locked_until(row)
        if locked:
            remain = max(1, int((locked - datetime.utcnow()).total_seconds() // 60) + 1)
            return f"连续失败次数过多, 账号已锁定, 请 {remain} 分钟后再试或联系管理员解锁"
        return ""

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """校验登录。成功返回用户信息 (含 must_change) 并刷新 last_login_at;
        失败返回 None (内部完成失败计数与锁定)。停用/锁定账号直接失败。"""
        username = (username or "").strip()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM web_users WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if row is None:
                return None
            if not int(row["is_active"] or 0):
                return None
            if self._locked_until(row):
                return None
            if not verify_password(password, row["password_hash"]):
                self._bump_fail(conn, row)
                return None
            conn.execute(
                "UPDATE web_users SET last_login_at = CURRENT_TIMESTAMP,"
                " failed_attempts = 0, locked_until = NULL WHERE id = ?",
                (row["id"],),
            )
        return {
            "id": row["id"], "username": row["username"], "role": row["role"],
            "must_change": int(row["must_change_password"] or 0),
        }

    # ==================== 查询 ====================

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """取活跃用户 (软删/停用一律视为不存在 → 已有会话立即失效)"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, username, role, created_at, last_login_at, is_active,"
                " must_change_password, failed_attempts, locked_until, email "
                "FROM web_users WHERE username = ? AND deleted_at IS NULL AND is_active = 1",
                ((username or "").strip(),),
            ).fetchone()
        return dict(row) if row else None

    def list_users(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, username, role, created_at, last_login_at, is_active,"
                " must_change_password, failed_attempts, locked_until, email "
                "FROM web_users WHERE deleted_at IS NULL ORDER BY id"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # 过期锁定不显示"锁定"标签 (到期自动解锁, 下次登录时顺带清零)
            d["is_locked"] = self._locked_until(r) is not None
            out.append(d)
        return out

    # ==================== 口令 ====================

    def _check_history(self, conn: sqlite3.Connection, row: sqlite3.Row, new_password: str) -> None:
        hist = json.loads(row["password_history"] or "[]")
        hashes = [row["password_hash"]] + hist
        for h in hashes[:PASSWORD_HISTORY_KEEP]:
            if h and verify_password(new_password, h):
                raise ValueError(f"新口令不能与最近 {PASSWORD_HISTORY_KEEP} 次使用过的口令相同")

    def update_password(self, username: str, new_password: str, check_history: bool = True) -> None:
        """自助改密: 历史校验 + 旧哈希入栈 + 清除强制改密标记"""
        if not new_password or len(new_password) < 6:
            raise ValueError("口令至少 6 位")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT password_hash, password_history FROM web_users "
                "WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if row is None:
                raise ValueError(f"用户不存在: {username}")
            if check_history:
                self._check_history(conn, row, new_password)
            hist = json.loads(row["password_history"] or "[]")
            hist = ([row["password_hash"]] + hist)[:PASSWORD_HISTORY_KEEP]
            conn.execute(
                "UPDATE web_users SET password_hash = ?, password_history = ?,"
                " must_change_password = 0, failed_attempts = 0, locked_until = NULL "
                "WHERE username = ?",
                (hash_password(new_password), json.dumps(hist), username),
            )

    def set_password_by_admin(self, username: str, new_password: str) -> None:
        """管理员代设口令: 跳过历史校验, 但置强制改密 (让用户换成私人口令)"""
        if not new_password or len(new_password) < 6:
            raise ValueError("口令至少 6 位")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT password_hash, password_history FROM web_users "
                "WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if row is None:
                raise ValueError(f"用户不存在: {username}")
            hist = ([row["password_hash"]] + json.loads(row["password_history"] or "[]"))[:PASSWORD_HISTORY_KEEP]
            conn.execute(
                "UPDATE web_users SET password_hash = ?, password_history = ?,"
                " must_change_password = 1 WHERE username = ?",
                (hash_password(new_password), json.dumps(hist), username),
            )

    def reset_password(self, username: str) -> str:
        """管理员重置: 生成一次性随机临时口令 + 强制改密 + 清除锁定。

        返回的明文口令只应展示一次 (响应体), 不落任何日志。
        """
        temp = generate_temp_password()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT password_hash, password_history FROM web_users "
                "WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if row is None:
                raise ValueError(f"用户不存在: {username}")
            hist = ([row["password_hash"]] + json.loads(row["password_history"] or "[]"))[:PASSWORD_HISTORY_KEEP]
            conn.execute(
                "UPDATE web_users SET password_hash = ?, password_history = ?,"
                " must_change_password = 1, failed_attempts = 0, locked_until = NULL "
                "WHERE username = ?",
                (hash_password(temp), json.dumps(hist), username),
            )
        return temp

    # ==================== CRUD ====================

    def create_user(
        self,
        username: str,
        password: str = "",
        role: str = "viewer",
        email: str = "",
    ) -> Dict[str, Any]:
        """创建 Web 用户。password 留空 = 系统生成一次性临时口令 + 强制首登改密。

        email 选填 (v2.3): 忘记密码自助重置的唯一凭据。
        Returns:
            {"username","role","temp_password"} — temp_password 非 None 时仅此一次返回。
        Raises:
            ValueError: 用户名/口令/邮箱不合法、已存在
        """
        username = (username or "").strip()
        if not username or len(username) > 64:
            raise ValueError("用户名不能为空且不超过 64 字符")
        if role not in ROLES:
            raise ValueError(f"角色只能是 {'/'.join(ROLES)}")
        norm_email = normalize_email(email)
        if email and not norm_email:
            raise ValueError("邮箱格式不正确")
        temp: Optional[str] = None
        if not password:
            password = generate_temp_password()
            temp = password
        if len(password) < 6:
            raise ValueError("口令至少 6 位")

        with self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM web_users WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if exists:
                raise ValueError(f"用户已存在: {username}")
            conn.execute(
                "INSERT INTO web_users (username, password_hash, role, must_change_password, email) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, hash_password(password), role, 1 if temp else 0, norm_email),
            )
        return {"username": username, "role": role, "temp_password": temp}

    def update_role(self, username: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError(f"角色只能是 {'/'.join(ROLES)}")
        with self._conn() as conn:
            # 前置保护: 不能降级最后一个管理员 (否则再无人能管理账号)
            if role != "admin":
                row = conn.execute(
                    "SELECT role FROM web_users WHERE username = ? AND deleted_at IS NULL",
                    (username,),
                ).fetchone()
                if row and row["role"] == "admin":
                    admins = conn.execute(
                        "SELECT COUNT(*) AS n FROM web_users WHERE role = 'admin' AND deleted_at IS NULL"
                    ).fetchone()["n"]
                    if admins <= 1:
                        raise ValueError("不能降级最后一个管理员账号")
            cur = conn.execute(
                "UPDATE web_users SET role = ? WHERE username = ? AND deleted_at IS NULL",
                (role, username),
            )
            if cur.rowcount == 0:
                raise ValueError(f"用户不存在: {username}")

    def set_active(self, username: str, active: bool) -> None:
        """启用/禁用。禁用后 get_user 返回 None → 已有会话立即失效。"""
        if username == "admin":
            raise ValueError("内置管理员账号 admin 不可停用")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT role, is_active FROM web_users WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if row is None:
                raise ValueError(f"用户不存在: {username}")
            if not active and row["role"] == "admin":
                admins = conn.execute(
                    "SELECT COUNT(*) AS n FROM web_users "
                    "WHERE role = 'admin' AND deleted_at IS NULL AND is_active = 1"
                ).fetchone()["n"]
                if admins <= 1:
                    raise ValueError("不能停用最后一个可用管理员账号")
            conn.execute(
                "UPDATE web_users SET is_active = ?, failed_attempts = 0, locked_until = NULL "
                "WHERE username = ? AND deleted_at IS NULL",
                (1 if active else 0, username),
            )

    def unlock(self, username: str) -> None:
        """管理员手动解锁: 清除失败计数与锁定"""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE web_users SET failed_attempts = 0, locked_until = NULL "
                "WHERE username = ? AND deleted_at IS NULL",
                (username,),
            )
            if cur.rowcount == 0:
                raise ValueError(f"用户不存在: {username}")

    # ==================== v2.3 邮箱与忘记密码自助重置 ====================

    def set_email(self, operator: str, username: str, email: str) -> str:
        """设置找回邮箱。operator==username 为本人改; 否则须 admin 且目标非 admin
        (邮箱是自助重置凭据, 管理员间隔离, 防"绑邮箱→走找回→接管")。
        email 留空 = 解绑。返回归一化邮箱 (''=已解绑/清除)。"""
        norm = normalize_email(email)
        if email and not norm:
            raise ValueError("邮箱格式不正确")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT role FROM web_users WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if row is None:
                raise ValueError(f"用户不存在: {username}")
            if operator != username:
                op = conn.execute(
                    "SELECT role FROM web_users WHERE username = ? AND deleted_at IS NULL",
                    (operator,),
                ).fetchone()
                if op is None or op["role"] != "admin":
                    raise ValueError("无权修改他人邮箱")
                if row["role"] == "admin":
                    raise ValueError("管理员账号之间相互隔离, 无法代管其他管理员邮箱")
            conn.execute(
                "UPDATE web_users SET email = ? WHERE username = ? AND deleted_at IS NULL",
                (norm, username),
            )
            # 改邮箱后作废旧码 (旧凭据指向的邮箱不再有效)
            if norm:
                conn.execute(
                    "DELETE FROM web_reset_codes WHERE key = ?",
                    (self._reset_key(username, norm),),
                )
        return norm

    @staticmethod
    def _reset_key(username: str, email: str) -> str:
        """重置码存储键: sha256(username|email) 摘要, 表内不落明文"""
        raw = f"{(username or '').strip().lower()}|{(email or '').strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]

    def find_for_password_reset(self, username: str, email: str) -> Optional[Dict[str, Any]]:
        """按用户名+登记邮箱精确匹配活跃账号; 不匹配返回 None (路由据此防枚举)。"""
        norm = normalize_email(email)
        if not norm:
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT username, email, role FROM web_users "
                "WHERE username = ? AND deleted_at IS NULL AND is_active = 1",
                ((username or "").strip(),),
            ).fetchone()
        if row is None or not row["email"] or row["email"] != norm:
            return None
        return dict(row)

    def reset_code_status(self, username: str, email: str) -> Dict[str, Any]:
        """查询该账号当前重置码状态 (路由层判重发冷却)。过期即删。"""
        key = self._reset_key(username, email)
        now = datetime.utcnow()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT expires_at, last_sent_at FROM web_reset_codes WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return {"exists": False}
            exp = _parse_ts(row["expires_at"])
            if exp is None or exp <= now:
                conn.execute("DELETE FROM web_reset_codes WHERE key = ?", (key,))
                return {"exists": False}
            sent = _parse_ts(row["last_sent_at"]) or now
            return {"exists": True, "cooldown_until": sent + timedelta(seconds=RESET_RESEND_COOLDOWN)}

    def issue_reset_code(self, username: str, email: str) -> str:
        """签发 6 位数字码 (同账号重复申请=作废旧码)。返回明文码 (仅入邮件, 不落日志)。"""
        key = self._reset_key(username, email)
        code = f"{secrets.randbelow(900000) + 100000}"  # 100000~999999
        now = datetime.utcnow()
        expires = now + timedelta(minutes=RESET_CODE_TTL_MINUTES)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO web_reset_codes (key, code_hash, expires_at, last_sent_at, fails) "
                "VALUES (?, ?, ?, ?, 0) "
                "ON CONFLICT(key) DO UPDATE SET code_hash=excluded.code_hash,"
                " expires_at=excluded.expires_at, last_sent_at=excluded.last_sent_at, fails=0",
                (key, hash_password(code), expires.strftime("%Y-%m-%d %H:%M:%S"),
                 now.strftime("%Y-%m-%d %H:%M:%S")),
            )
        return code

    def verify_reset_code(self, username: str, email: str, code: str) -> bool:
        """校验并消费重置码 (一次性: 成功即删)。失败计数, 满 RESET_MAX_CODE_FAILS 作废。"""
        code = (code or "").strip()
        if not code.isdigit():
            return False
        key = self._reset_key(username, email)
        now = datetime.utcnow()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT code_hash, expires_at, fails FROM web_reset_codes WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return False
            exp = _parse_ts(row["expires_at"])
            if exp is None or exp <= now:
                conn.execute("DELETE FROM web_reset_codes WHERE key = ?", (key,))
                return False
            if verify_password(code, row["code_hash"]):
                conn.execute("DELETE FROM web_reset_codes WHERE key = ?", (key,))
                return True
            fails = int(row["fails"] or 0) + 1
            if fails >= RESET_MAX_CODE_FAILS:
                conn.execute("DELETE FROM web_reset_codes WHERE key = ?", (key,))
            else:
                conn.execute("UPDATE web_reset_codes SET fails = ? WHERE key = ?", (fails, key))
        return False

    def clear_reset_codes(self, username: str) -> None:
        """删除该用户所有重置码 (改邮箱/重置成功/删除账号后调用)。
        按 key 前缀无法反查 (key 是哈希), 这里靠 username 传入的 email 逐一删不现实;
        实际调用点在改密/重置成功路径, 由路由传入 username+email。此方法保留给软删。"""
        with self._conn() as conn:
            # 软删账号时其 email 仍在行内, 反查后删
            rows = conn.execute(
                "SELECT email FROM web_users WHERE username = ?", (username,),
            ).fetchall()
            for r in rows:
                if r["email"]:
                    conn.execute("DELETE FROM web_reset_codes WHERE key = ?",
                                 (self._reset_key(username, r["email"]),))

    def reset_password_self(self, username: str, new_password: str) -> None:
        """自助重置 (凭邮件验证码, 路由已校验): 强度+历史校验 → 置新密码 →
        清锁定/失败计数 → 解除强制改密。与管理员 reset_password 区别: 用户自设口令,
        must_change_password=0。"""
        if not new_password or len(new_password) < 6:
            raise ValueError("口令至少 6 位")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT password_hash, password_history FROM web_users "
                "WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if row is None:
                raise ValueError(f"用户不存在: {username}")
            self._check_history(conn, row, new_password)
            hist = ([row["password_hash"]] + json.loads(row["password_history"] or "[]"))[:PASSWORD_HISTORY_KEEP]
            conn.execute(
                "UPDATE web_users SET password_hash = ?, password_history = ?,"
                " must_change_password = 0, failed_attempts = 0, locked_until = NULL "
                "WHERE username = ?",
                (hash_password(new_password), json.dumps(hist), username),
            )

    def delete_user(self, username: str) -> None:
        """软删除 Web 用户 (禁止删除最后一个 admin; 先校验后删除)。

        数据保留供审计追溯; 用户名改名释放唯一键 (同名可再注册),
        同时禁用账号使既有会话立即失效。
        """
        if username == "admin":
            raise ValueError("内置管理员账号 admin 不可删除")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, role FROM web_users WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            if row is None:
                raise ValueError(f"用户不存在: {username}")
            if row["role"] == "admin":
                admins = conn.execute(
                    "SELECT COUNT(*) AS n FROM web_users WHERE role = 'admin' AND deleted_at IS NULL"
                ).fetchone()["n"]
                if admins <= 1:
                    raise ValueError("不能删除最后一个管理员账号")
            conn.execute(
                "UPDATE web_users SET deleted_at = CURRENT_TIMESTAMP, is_active = 0, "
                "username = ? WHERE id = ?",
                (f"{username}#del{row['id']}", row["id"]),
            )
