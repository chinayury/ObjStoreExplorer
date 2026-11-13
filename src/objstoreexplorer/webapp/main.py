# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""Web 应用入口 (FastAPI)

组装:
    - TokenSessionMiddleware (HMAC-SHA256 签名 cookie 登录态, 会话外置化)
    - 全局状态 (webapp.state.get_state)
    - 路由: auth / pages / connection / buckets / objects / admin / features / logs_settings / tasks
    - lifespan: 首次启动建 admin + 定时清理过期会话/任务/陈旧临时文件
    - 全局异常: 业务异常转 JSON, 未登录页面转 303

启动:
    uvicorn webapp.main:app --host 0.0.0.0 --port 8000
    # workers 数用环境变量 WEB_WORKERS 控制 (见 Dockerfile CMD / docker-compose.yml),
    # v0.1.0 第二轮起会话/连接/任务均已外置 SQLite, 支持多 worker。
"""
from __future__ import annotations
import asyncio
import logging
import logging.handlers
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from ..config.exceptions import ObjStoreExplorerError
from ..config.settings import LOG_DIR, APP_VERSION, APP_NAME, TEMP_DIR
from . import __version__ as WEB_VERSION
from .deps import (
    _RedirectException,
    _APIException,
    redirect_exception_handler,
    api_exception_handler,
)
from .state import get_state, SESSION_COOKIE_TTL
from .token_session import TokenSessionMiddleware
from .tasks import TEMP_SESSION_PREFIX, RESULT_TTL_SECONDS

logger = logging.getLogger("ose.web")

_CLEAN_INTERVAL_SECONDS = 60
# 陈旧临时目录兜底清理阈值: 上传/打包工作目录超过该时长仍未被正常路径
# 清掉 (客户端中途断开导致 BackgroundTask 未执行 / 任务卡死) 视为残留
STALE_TEMP_DIR_MAX_AGE_SECONDS = 2 * 3600


def _setup_logging() -> None:
    """Web 版日志: 文件 (data/logs/web.log) + stdout"""
    if logging.getLogger("ose.web").handlers:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        Path(LOG_DIR) / "web.log", maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    console = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    handler.setFormatter(fmt)
    console.setFormatter(fmt)
    root = logging.getLogger("ose")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(console)


async def _cleanup_loop() -> None:
    """定时清理: 过期 Web 会话 / 超时任务结果 / 陈旧临时目录 / 持久层孤儿行

    多 worker 下每个 worker 都会跑本循环, 各项清理均为幂等操作
    (DELETE/目录清除), 并发执行安全。
    """
    state = get_state()
    while True:
        await asyncio.sleep(_CLEAN_INTERVAL_SECONDS)
        try:
            n1 = state.sessions.expire_idle()
            n2 = state.tasks.expire_results()
            n3 = state.tasks.cleanup_stale_dirs(STALE_TEMP_DIR_MAX_AGE_SECONDS)
            # 持久层: 过期/吊销会话行 + 超时任务行 (多 worker 共享, 幂等)
            n4 = state.persist.purge_expired_sessions()
            n5 = state.persist.purge_tasks(
                RESULT_TTL_SECONDS, stale_running_seconds=24 * 3600,
            )
            if n1 or n2 or n3 or n4 or n5:
                logger.info(
                    "清理完成: 闲置会话 %d 个, 超时任务 %d 个, 陈旧临时目录 %d 个,"
                    " 过期会话行 %d 条, 过期任务行 %d 条",
                    n1, n2, n3, n4, n5,
                )
        except Exception:
            logger.exception("清理循环异常")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _setup_logging()
    state = get_state()  # 首次访问: 创建 admin 账号 / 初始化加密库

    # 清理上次运行残留的 Web 临时文件 (下载/上传工作目录)
    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        for child in TEMP_DIR.glob(f"{TEMP_SESSION_PREFIX}*"):
            shutil.rmtree(child, ignore_errors=True)
    except OSError:
        pass

    cleaner = asyncio.create_task(_cleanup_loop())
    logger.info(
        "%s Web v%s (core v%s) 启动完成", APP_NAME, WEB_VERSION, APP_VERSION,
    )
    yield
    cleaner.cancel()
    state.sessions.shutdown()
    logger.info("%s Web 已停止", APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(title=f"{APP_NAME} Web", version=WEB_VERSION, lifespan=lifespan)

    # 会话中间件 (HMAC-SHA256 签名 cookie, v0.1.0 第二轮自实现取代
    # starlette SessionMiddleware —— SHA256 + 显式过期 + 常数时间比较;
    # 服务端吊销由 deps 层查 web_sessions 表完成)
    app.add_middleware(
        TokenSessionMiddleware,
        secret_key=get_state().secret_key,
        cookie_name="ose_web_session",
        max_age=SESSION_COOKIE_TTL,
        same_site="lax",
        https_only=False,  # 反代终止 TLS 时可自行加环境开关
    )

    # 安全响应头 (v0.1.0 加固: 防 MIME 嗅探 / 点击劫持 / Referer 泄露,
    # CSP 限制脚本样式仅来自本站与内联 <script>, 静态资源同源)
    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'",
        )
        return response

    # 静态资源
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 全局异常处理
    app.add_exception_handler(_RedirectException, redirect_exception_handler)
    app.add_exception_handler(_APIException, api_exception_handler)

    @app.exception_handler(ObjStoreExplorerError)
    async def _biz_error(_req: Request, exc: ObjStoreExplorerError):
        # 业务异常 (未连接/校验失败等) 统一 409 + 可读消息
        return JSONResponse(
            status_code=409,
            content={"success": False, "message": exc.message, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        # 只回传字段/类型/原因, 剥离 pydantic v2 errors 里的 input(原始输入)
        # 与 ctx(内部细节) —— 校验失败不应把请求体里的口令等值回显给客户端
        safe_errors = []
        for e in exc.errors()[:3]:
            safe_errors.append({
                "field": ".".join(str(p) for p in e.get("loc", [])),
                "type": e.get("type", ""),
                "message": e.get("msg", ""),
            })
        return JSONResponse(
            status_code=422,
            content={"success": False, "message": f"参数校验失败: {safe_errors}"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception):
        # 详情只进服务端日志; 客户端拿到统一文案, 避免内部信息泄露
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "服务器内部错误, 请稍后重试或查看服务端日志"},
        )

    # 路由
    from .routes import auth, pages, connection, buckets, objects, admin, features, logs_settings, tasks
    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(connection.router)
    app.include_router(buckets.router)
    app.include_router(objects.router)
    app.include_router(admin.router)
    app.include_router(features.router)
    app.include_router(logs_settings.router)
    app.include_router(tasks.router)

    # 健康检查 (容器探针 / 部署验收): 只读, 不要求登录, 不暴露连接信息
    @app.get("/api/health")
    async def health() -> dict:
        return {
            "success": True,
            "status": "ok",
            "name": APP_NAME,
            "version": WEB_VERSION,
            "core_version": APP_VERSION,
        }

    return app


app = create_app()
