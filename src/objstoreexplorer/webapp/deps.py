# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""FastAPI 依赖注入: 登录校验 / 角色权限 / 会话上下文

页面路由未登录 → 303 重定向 /login
API 路由未登录 → 401 JSON
viewer 写操作 / 非 admin 访问管理 API → 403 JSON

v0.1.0 第二轮迭代 (会话外置化):
    - 登录态 = 签名令牌 cookie (webapp/token_session.py, HMAC-SHA256) +
      服务端会话行校验 (webapp/persist.py web_sessions): 行被吊销
      (登出/停用/删除账号) 或删除后, 即使令牌签名有效也判未登录 ——
      服务端吊销真正生效, 旧实现"偷到 cookie 到期前一直可用"的缺口关闭。
    - must_change (强制改密) 改为从 web_users 行推导, 不再放令牌:
      管理员重置口令立即对在线用户生效, 且令牌载荷更小。
    - 每请求的鉴权结果经 request.state 缓存, 页面链路的重复依赖注入
      不重复查库。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from .state import get_state
from .context import WebSession

logger = logging.getLogger("ose.web.deps")

_MISSING = object()  # request.state 缓存哨兵 (与 None=匿名 区分)


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """取当前 Web 用户 (未登录返回 None)

    校验链 (任一环节失败即 None, fail closed):
        1. 令牌验签 (中间件已完成, 无载荷即匿名);
        2. web_users 行存在且启用未删除 (停用/软删立即失效);
        3. web_sessions 行存在、未吊销、未过期、归属一致 (登出/停用即失效)。
    结果按请求缓存, 避免同一请求内重复查库。
    """
    cached = getattr(request.state, "_ose_user_cached", _MISSING)
    if cached is not _MISSING:
        return cached
    user = _load_current_user(request)
    request.state._ose_user_cached = user
    return user


def _load_current_user(request: Request) -> Optional[Dict[str, Any]]:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = get_state().store.get_user(uid)
    if user is None:
        return None
    sid = request.session.get("sid")
    if not sid:
        return None
    persist = get_state().persist
    try:
        if not persist.is_session_valid(sid, user["username"]):
            return None
    except Exception:
        # 会话行读取失败 (库忙等超时等): fail closed, 宁可让用户重新登录
        logger.warning("会话行校验失败 (sid=%s), 按未登录处理", sid, exc_info=True)
        return None
    return user


def require_page_user(request: Request) -> Dict[str, Any]:
    """页面路由依赖: 未登录重定向到登录页 (抛出 RedirectResponse)"""
    user = get_current_user(request)
    if user is None:
        raise _RedirectException("/login")
    return user


def require_api_user(request: Request) -> Dict[str, Any]:
    """API 路由依赖: 未登录返回 401

    强制改密拦截: must_change (web_users.must_change_password) 会话禁止一切
    写操作 (POST/PUT/PATCH/DELETE), 仅放行改密与登出; GET 只读接口不拦
    (设置页本身要能渲染)。服务端强制 (登录跳转只是体验, 后端拦截才是安全)。
    """
    user = get_current_user(request)
    if user is None:
        raise _APIException(401, "未登录或会话已过期")
    if int(user.get("must_change_password") or 0) and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        path = request.url.path
        if path not in ("/api/web/password", "/logout"):
            raise _APIException(403, "请先修改初始口令后再操作 (password_change_required)")
    return user


def require_admin(request: Request) -> Dict[str, Any]:
    """API 路由依赖: 需要 admin 角色"""
    user = require_api_user(request)
    if user.get("role") != "admin":
        raise _APIException(403, "需要管理员权限")
    return user


def require_writer(request: Request) -> Dict[str, Any]:
    """写操作权限 (两角色模型: admin 可写, viewer 只读)"""
    user = require_api_user(request)
    if user.get("role") != "admin":
        raise _APIException(403, "只读账号无权执行写操作")
    return user


def get_web_session(request: Request) -> WebSession:
    """取/建当前浏览器的 WebSession (每会话独立 S3 连接)"""
    user = require_api_user(request)
    state = get_state()
    sid = request.session.get("sid")
    if not sid:
        # 防御分支: 正常登录都会带 sid; 兜底生成并随响应重签 cookie
        sid = uuid.uuid4().hex
        request.session["sid"] = sid
    return state.sessions.get_or_create(sid, user["username"])


def revoke_web_session(request: Request) -> None:
    """吊销当前会话 (登出): 内存销毁 + web_sessions 吊销 (全 worker 生效)"""
    sid = request.session.get("sid")
    if sid:
        get_state().sessions.revoke(sid)


class _RedirectException(Exception):
    """页面路由重定向信号 (在全局异常处理器中转为 RedirectResponse)"""

    def __init__(self, url: str):
        self.url = url


class _APIException(Exception):
    """API 错误信号 (在全局异常处理器中转为 JSONResponse)"""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message


def redirect_exception_handler(_req: Request, exc: _RedirectException):
    return RedirectResponse(url=exc.url, status_code=303)


def api_exception_handler(_req: Request, exc: _APIException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.message},
    )
