# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""Web 会话上下文 - 每浏览器会话独立的 S3 连接与业务管理器

为什么不用桌面版 ServiceLocator: 它是进程级单例 (单用户假设),
Web 版多用户/多标签页必须按会话隔离连接状态。

本类实现鸭子类型 locator: 只暴露 TransferService / ClipboardService /
SearchService 实际用到的 `file_manager` 属性, 因此可以直接把 WebSession
传给这三类桌面版服务, 业务逻辑零改动复用。

ConfigManager (连接历史/日志/设置, 加密 SQLite) 与桌面版共享同一个
data/config.db —— 桌面客户端与 Web 端连接历史互通, 属于有意设计。

v0.1.0 第二轮迭代 (会话外置化):
    旧实现会话/连接/剪贴板全在进程内存, workers>1 时请求落到另一个
    worker 即"未连接"。现在:
      - 连接快照 (endpoint + Fernet 加密 AK/SK + ssl) 落 SQLite
        (webapp/persist.py), 内存里的 WebSession 退化为缓存: worker 重启
        或请求落到别的 worker 时按快照重建 S3 连接;
      - 剪贴板 JSON 随操作写库, 跨 worker 保持;
      - 登出改为服务端吊销 (web_sessions.revoked=1), 依赖注入层每请求
        校验, 被偷的 cookie 登出后立即失效 (旧实现只清 cookie);
      - 改连接即新快照, 不复用旧 client 改凭据 (客户端对象不可变)。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional, Tuple, List, Dict, Any

from ..core.s3_client_base import S3ClientBase
from ..core.s3_client_factory import S3ClientFactory
from ..core.bucket_manager import BucketManager
from ..core.file_manager import FileManager
from ..core.admin_manager import AdminManager
from ..core.stats_manager import StatsManager
from ..core.config_manager import ConfigManager
from ..core.validators import validate_endpoint, validate_access_key, validate_external_host
from ..config.exceptions import ConnectionError as OSEConnectionError
from ..services.clipboard_service import ClipboardService
from ..services.search_service import SearchService
from ..services.transfer_service import TransferService

logger = logging.getLogger("ose.web.context")


class WebSession:
    """单个浏览器会话的连接上下文 (线程安全)

    生命周期: 登录后首次访问创建 → 会话吊销/登出时 revoke, 闲置回收时
    drop_connection。内存对象可随时丢弃重建 (持久层是事实来源)。
    """

    def __init__(self, session_id: str, username: str, config_manager: ConfigManager,
                 persist=None):
        self.session_id = session_id
        self.username = username
        self._config = config_manager
        self._persist = persist  # WebStateStore (None = 纯内存模式, 测试用)

        self._s3_client: Optional[S3ClientBase] = None
        self._managers: Dict[str, Any] = {}
        self._lock = threading.RLock()

        self.last_active = time.monotonic()
        self.created_at = time.time()
        self._last_active_flushed = 0.0  # last_active 上次落库时间 (节流)

        # 复用桌面版服务: 它们只依赖 locator.file_manager (鸭子类型)
        self.clipboard = ClipboardService(self, on_change=self._persist_clipboard)
        self.search = SearchService(self)
        self.transfer = TransferService(self)

    # ==================== 活跃时间 ====================

    def touch(self) -> None:
        """刷新活跃时间 (每请求); DB 侧节流落库供跨 worker 闲置判定"""
        self.last_active = time.monotonic()
        if self._persist is not None:
            now = time.time()
            if now - self._last_active_flushed > 30.0:
                self._last_active_flushed = now
                try:
                    self._persist.touch_session(self.session_id)
                except Exception:
                    pass  # 落库失败只影响闲置回收的精度, 不影响请求

    # ==================== 剪贴板落库 ====================

    def _persist_clipboard(self) -> None:
        """剪贴板变化写库 (ClipboardService.on_change 回调; 失败不影响操作)"""
        if self._persist is None:
            return
        try:
            items = [
                {"bucket": i.bucket, "key": i.key, "name": i.name, "is_dir": i.is_dir}
                for i in self.clipboard.get_items()
            ]
            payload = json.dumps(
                {"op": self.clipboard.operation, "items": items},
                ensure_ascii=False,
            )
            self._persist.set_clipboard(self.session_id, payload)
        except Exception:
            logger.debug("剪贴板落库失败 (sid=%s)", self.session_id, exc_info=True)

    # ==================== 连接管理 ====================

    @property
    def s3_client(self) -> Optional[S3ClientBase]:
        return self._s3_client

    @property
    def is_connected(self) -> bool:
        return self._s3_client is not None and self._s3_client.is_connected

    @property
    def current_endpoint(self) -> Optional[str]:
        return self._s3_client.endpoint if self._s3_client else None

    def connect(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        ssl: bool = False,
        save: bool = True,
        log_action: bool = True,
        external_host: str = "",
    ) -> Tuple[bool, str]:
        """建立 S3 连接 (可选保存到共享连接历史)

        log_action=False 用于按快照静默重建 (worker 重启/跨 worker),
        不重复记操作日志。
        external_host: 预签名外链 Host (D9), 空 = 不启用; 容器内网
        部署时连接走内网地址, 分享链接按外网主机名签名。
        """
        ok, msg = validate_endpoint(endpoint)
        if not ok:
            return False, msg
        ok, msg = validate_external_host(external_host)
        if not ok:
            return False, msg
        ok, msg = validate_access_key(access_key)
        if not ok:
            return False, msg
        if not secret_key:
            return False, "Secret Key 不能为空"

        with self._lock:
            try:
                client = S3ClientFactory.create(endpoint, access_key, secret_key, ssl)
                ok, msg = client.connect()
                if not ok:
                    return False, msg
                client.external_host = (external_host or "").strip()
                # 替换旧连接 (旧 client 整体废弃, 不复用改凭据)
                if self._s3_client is not None:
                    try:
                        self._s3_client.close()
                    except Exception:
                        pass
                self._s3_client = client
                self._managers.clear()
                self.clipboard.clear()
            except Exception as e:
                return False, f"连接失败: {e}"

        # 连接快照落库 (多 worker 重建依据); 失败只影响跨 worker 重建
        if self._persist is not None:
            try:
                self._persist.update_connection(
                    self.session_id, endpoint, access_key, secret_key, ssl,
                )
            except Exception:
                logger.warning(
                    "连接快照落库失败 (sid=%s), 该会话跨 worker 需重新连接",
                    self.session_id, exc_info=True,
                )

        if save:
            # 与桌面版相同的历史命名: endpoint@ak
            ep_short = endpoint.replace("http://", "").replace("https://", "")
            name = f"{ep_short}@{access_key}" if access_key else ep_short
            try:
                is_admin = False
                try:
                    is_admin = self._s3_client.probe_admin()
                except Exception:
                    is_admin = False
                self._config.add_server(
                    name=name, endpoint=endpoint, access_key=access_key,
                    secret_key=secret_key, ssl=ssl, is_admin=is_admin,
                )
                self._config.mark_used(name)
            except Exception:
                pass  # 保存历史失败不影响连接

        if log_action:
            self._config.add_log(
                level="INFO", operation="connect", target=endpoint,
                status="success", message=f"[web:{self.username}] 连接成功",
            )
        return True, msg

    def disconnect(self, drop_snapshot: bool = True) -> None:
        """断开 S3 (内存清空); drop_snapshot=False 仅清内存、保留持久层快照

        drop_snapshot=False 供"会话回收但连接可重建"路径使用
        (worker 关停 / 跨 worker 内存回收), 直接断开 (用户操作) 恒清快照。
        """
        with self._lock:
            if self._s3_client is not None:
                try:
                    self._s3_client.close()
                except Exception:
                    pass
            self._s3_client = None
            self._managers.clear()
            self.clipboard.clear()
            self.transfer.cancel_all()
        # 快照同步清空: 断开后 cookie 仍有效, 但重连需要用户重新输入
        if drop_snapshot and self._persist is not None:
            try:
                self._persist.clear_connection(self.session_id)
            except Exception:
                pass

    def _check_connected(self) -> None:
        if not self.is_connected:
            raise OSEConnectionError("尚未连接服务器", code="NotConnected")

    # ==================== Managers (惰性创建) ====================

    @property
    def file_manager(self) -> FileManager:
        with self._lock:
            self._check_connected()
            if "file" not in self._managers:
                self._managers["file"] = FileManager(self._s3_client)
            return self._managers["file"]

    @property
    def bucket_manager(self) -> BucketManager:
        with self._lock:
            self._check_connected()
            if "bucket" not in self._managers:
                self._managers["bucket"] = BucketManager(self._s3_client)
            return self._managers["bucket"]

    @property
    def admin_manager(self) -> AdminManager:
        with self._lock:
            self._check_connected()
            if "admin" not in self._managers:
                self._managers["admin"] = AdminManager(self._s3_client)
            return self._managers["admin"]

    @property
    def stats_manager(self) -> StatsManager:
        with self._lock:
            self._check_connected()
            if "stats" not in self._managers:
                self._managers["stats"] = StatsManager(self._s3_client)
            return self._managers["stats"]

    # ==================== 连接历史 (共享 config.db) ====================

    def list_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """连接历史 (隐藏 SK 明文, 前端只需名称/endpoint/ssl)"""
        servers = self._config.list_servers()[:limit]
        return [
            {
                "name": s["name"],
                "endpoint": s["endpoint"],
                "ssl": s["ssl"],
                "is_admin": s["is_admin"],
                "last_used_at": s["last_used_at"],
            }
            for s in servers
        ]

    def connect_from_history(self, name: str) -> Tuple[bool, str]:
        """从共享历史配置连接 (SK 由服务端解密, 不回传前端)"""
        cfg = self._config.get_server(name)
        if not cfg:
            return False, f"未找到配置: {name}"
        ok, msg = self.connect(
            endpoint=cfg["endpoint"],
            access_key=cfg["access_key"],
            secret_key=cfg["secret_key"],
            ssl=cfg["ssl"],
            save=False,
        )
        if ok:
            self._config.mark_used(name)
        return ok, msg

    def delete_history(self, name: str) -> bool:
        return self._config.delete_server(name)

    def cleanup(self, drop_snapshot: bool = True) -> None:
        """会话内存资源终态回收: 断开 S3 + 取消任务 + 释放传输线程池 + 清临时文件

        v0.1.0 修复: 旧实现只 disconnect (其中仅 cancel_all), TransferService
        自有的 12 线程执行器从不关闭 —— 每个执行过删除/粘贴的过期会话
        都会泄漏一批常驻线程。cleanup 是会话终态方法 (销毁后不再复用),
        在这里关闭执行器是安全的。

        drop_snapshot=False: 保留持久层连接快照 (worker 关停/跨 worker
        纯内存回收), 仅释放本进程资源。
        """
        self.disconnect(drop_snapshot=drop_snapshot)
        try:
            self.transfer.cleanup()
        except Exception:
            pass
        # 该会话名下的临时目录 (上传/打包工作目录) 立即清理,
        # 不等 TTL 与重启兜底
        try:
            from .state import get_state  # 惰性导入避免环
            get_state().tasks.cleanup_session_files(self.session_id)
        except Exception:
            pass


class SessionManager:
    """会话注册表: 进程内缓存 + SQLite 持久层 (webapp/persist.py)

    v0.1.0 第二轮迭代: 内存 dict 只是活跃会话的缓存。请求落到没有缓存的
    worker (重启后/多 worker), 会话管理器按 web_sessions 行重建 WebSession:
    快照 connected=1 则静默重连 S3, 剪贴板一并恢复 —— 对用户表现为
    "会话还在", 这是多 worker 可用的关键路径。
    """

    def __init__(self, config_manager: ConfigManager, ttl_seconds: int = 1800,
                 persist=None):
        self._config = config_manager
        self._persist = persist
        self._sessions: Dict[str, WebSession] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    # ==================== 内部 ====================

    def _new_session(self, session_id: str, username: str) -> WebSession:
        return WebSession(session_id, username, self._config, persist=self._persist)

    def _hydrate_from_row(self, session_id: str, username: str) -> WebSession:
        """按持久化行重建 WebSession (快照重连 + 剪贴板恢复)"""
        row = None
        if self._persist is not None:
            try:
                row = self._persist.get_session(session_id)
            except Exception:
                row = None
            if row is not None and row["username"] != username:
                row = None  # 归属不符 (换账号): 当作全新会话, 登录路由会重建行
        s = self._new_session(session_id, username)
        if row is not None and row["connected"]:
            ak = self._persist.decrypt_field(row["ak_enc"])
            sk = self._persist.decrypt_field(row["sk_enc"])
            endpoint = row["endpoint"] or ""
            if ak and sk and endpoint:
                ok, _msg = s.connect(
                    endpoint=endpoint, access_key=ak, secret_key=sk,
                    ssl=bool(row["ssl"]), save=False, log_action=False,
                )
                if not ok:
                    # 快照已连不上 (服务器下线/凭证失效): 清快照,
                    # 会话保留为未连接态, 用户重新连接即可
                    try:
                        self._persist.clear_connection(session_id)
                    except Exception:
                        pass
        if row is not None and row["clipboard"]:
            try:
                s.clipboard.hydrate(json.loads(row["clipboard"]))
                # 重建后回写一次: 上面 connect() 内的 clipboard.clear() 会把
                # DB 行清空, 不回写的话二次重启剪贴板就丢了
                s._persist_clipboard()
            except Exception:
                pass
        return s

    # ==================== 取/建 ====================

    def get_or_create(self, session_id: str, username: str) -> WebSession:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is not None:
                # 会话归属者校验: cookie 被复用/换账号登录时重建
                if s.username != username:
                    try:
                        s.cleanup()
                    except Exception:
                        pass
                    s = self._new_session(session_id, username)
                    self._sessions[session_id] = s
                s.touch()
                return s

        # 内存未命中: 本 worker 重启后首个请求 / 请求落到另一个 worker
        s = self._hydrate_from_row(session_id, username)
        with self._lock:
            # 双重检查: 并发请求同时未命中时只保留一个实例
            existing = self._sessions.get(session_id)
            if existing is not None:
                s_cleanup = s
                try:
                    s_cleanup.disconnect()
                except Exception:
                    pass
                existing.touch()
                return existing
            self._sessions[session_id] = s
            s.touch()
            return s

    def get(self, session_id: str) -> Optional[WebSession]:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is not None:
                s.touch()
            return s

    # ==================== 生命周期 (三种语义) ====================

    def revoke(self, session_id: str) -> None:
        """吊销会话 (登出): 内存销毁 + DB 吊销 —— 所有 worker 即时失效"""
        self.destroy(session_id)
        if self._persist is not None:
            try:
                self._persist.revoke_session(session_id)
            except Exception:
                logger.warning("会话吊销落库失败 (sid=%s)", session_id, exc_info=True)

    def drop_connection(self, session_id: str) -> bool:
        """闲置回收: 销毁本进程副本; 快照按"全局活跃度"决定是否清除

        判据是持久层 last_active (所有 worker 的 touch 都会节流落库):
        其他 worker 最近仍在用 -> 只回收本地内存、保留快照, 返回 True;
        全局都闲置 -> 连快照一并清除 (用户需重新连接), 返回 False。
        cookie 本身不受影响 (闲置回收 ≠ 登出)。
        """
        with self._lock:
            s = self._sessions.pop(session_id, None)
        keep_snapshot = False
        if self._persist is not None:
            try:
                row = self._persist.get_session(session_id)
                last_active = float(row["last_active"] or 0) if row else 0.0
                keep_snapshot = (
                    row is not None and (time.time() - last_active) <= self._ttl
                )
            except Exception:
                keep_snapshot = False
        if s is not None:
            try:
                s.cleanup(drop_snapshot=not keep_snapshot)
            except Exception:
                pass
        if self._persist is not None and not keep_snapshot:
            # 无内存副本 (或已回收) 的兜底: 快照确实该清
            try:
                self._persist.clear_connection(session_id)
            except Exception:
                pass
        return keep_snapshot

    def destroy(self, session_id: str) -> None:
        """仅销毁本进程内存副本 (worker 关停/防御重建): 保留快照, 重启后可续"""
        with self._lock:
            s = self._sessions.pop(session_id, None)
        if s is not None:
            try:
                s.cleanup(drop_snapshot=False)
            except Exception:
                pass

    def expire_idle(self) -> int:
        """清理超过 TTL 未活跃的本地会话副本, 返回清理数 (lifespan 定时调用)"""
        now = time.monotonic()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.last_active > self._ttl
        ]
        for sid in expired:
            self.drop_connection(sid)
        return len(expired)

    def shutdown(self) -> None:
        """进程关停: 只清内存副本 (断开 S3 客户端), 保留持久层快照"""
        for sid in list(self._sessions.keys()):
            self.destroy(sid)
