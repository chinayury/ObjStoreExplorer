# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""页面路由 - 登录后 10 个页面 (骨架渲染, 数据由 JS 调 JSON API 异步加载)

H-05: 10 个页面处理器原本都是 `async def`, 却在里面做同步阻塞调用
(require_page_user 查会话库、get_web_session 探连接、Jinja 渲染) ——
在 async 处理器里跑同步 DB/S3 会**霸占事件循环**, 一个页面的慢查询能把
同时打开的其它请求全部卡住。全部改成同步 `def`, FastAPI 会自动把它们
丢进线程池 (anyio to_thread), 阻塞只影响自己那个线程。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..deps import require_page_user, get_web_session
from ..state import get_state
from ...config.settings import APP_VERSION
from .. import __version__ as WEB_VERSION

router = APIRouter()

_PAGES = ["overview", "buckets", "objects", "users", "policies",
          "versioning", "lifecycle", "logs", "settings", "about"]


def _base_ctx(request: Request) -> dict:
    """页面公共上下文: 当前用户 + 连接状态 + 版本"""
    user = require_page_user(request)
    try:
        sess = get_web_session(request)
        connected = sess.is_connected
        endpoint = sess.current_endpoint or ""
        admin_available = bool(connected and sess.s3_client and sess.s3_client.admin_available)
    except Exception:
        connected, endpoint, admin_available = False, "", False

    return {
        "user": user,
        "connected": connected,
        "endpoint": endpoint,
        "admin_available": admin_available,
        "app_version": APP_VERSION,
        "web_version": WEB_VERSION,
        "pages": _PAGES,
    }


@router.get("/", response_class=HTMLResponse)
@router.get("/overview", response_class=HTMLResponse)
def page_overview(request: Request):
    """概览页: 侧边栏导航指向 /overview, 根路径 / 也指向同一页面"""
    return get_state().templates.TemplateResponse(
        request, "overview.html", _base_ctx(request))


@router.get("/buckets", response_class=HTMLResponse)
def page_buckets(request: Request):
    return get_state().templates.TemplateResponse(
        request, "buckets.html", _base_ctx(request))


@router.get("/objects", response_class=HTMLResponse)
def page_objects(request: Request):
    return get_state().templates.TemplateResponse(
        request, "objects.html", _base_ctx(request))


@router.get("/users", response_class=HTMLResponse)
def page_users(request: Request):
    return get_state().templates.TemplateResponse(
        request, "users.html", _base_ctx(request))


@router.get("/policies", response_class=HTMLResponse)
def page_policies(request: Request):
    return get_state().templates.TemplateResponse(
        request, "policies.html", _base_ctx(request))


@router.get("/versioning", response_class=HTMLResponse)
def page_versioning(request: Request):
    return get_state().templates.TemplateResponse(
        request, "versioning.html", _base_ctx(request))


@router.get("/lifecycle", response_class=HTMLResponse)
def page_lifecycle(request: Request):
    return get_state().templates.TemplateResponse(
        request, "lifecycle.html", _base_ctx(request))


@router.get("/logs", response_class=HTMLResponse)
def page_logs(request: Request):
    return get_state().templates.TemplateResponse(
        request, "logs.html", _base_ctx(request))


@router.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    return get_state().templates.TemplateResponse(
        request, "settings.html", _base_ctx(request))


@router.get("/about", response_class=HTMLResponse)
def page_about(request: Request):
    return get_state().templates.TemplateResponse(
        request, "about.html", _base_ctx(request))
