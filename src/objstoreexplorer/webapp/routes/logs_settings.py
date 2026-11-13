# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""日志 / 系统设置 API

v0.1.0: 处理器为同步 def (SQLite 读写与 SMTP 阻塞收发放线程池执行,
不占 workers=1 进程的事件循环)。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...config.settings import MAX_UPLOAD_SIZE
from ..deps import require_api_user, require_admin, _APIException, get_web_session
from ..state import get_state

router = APIRouter(prefix="/api")


@router.get("/logs")
def api_logs(request: Request, level: Optional[str] = None, limit: int = 200):
    """操作日志 (与桌面版共享存储)"""
    require_api_user(request)
    if level not in (None, "", "INFO", "WARNING", "ERROR"):
        raise _APIException(400, "级别只能是 INFO/WARNING/ERROR")
    if limit < 1 or limit > 1000:
        limit = 200
    logs = get_state().config_manager.get_logs(limit=limit, level=level or None)
    return {"success": True, "data": logs}


@router.delete("/logs")
def api_clear_logs(request: Request):
    require_admin(request)
    sess = get_web_session(request)
    get_state().config_manager.clear_logs()
    get_state().config_manager.add_log(
        level="INFO", operation="clear_logs", target="",
        status="success", message=f"[web:{sess.username}] 已清空操作日志",
    )
    return {"success": True, "message": "日志已清空"}


# ==================== 系统设置 ====================


class SettingsIn(BaseModel):
    max_upload_size_mb: int  # 0 = 不限制


@router.get("/settings")
def api_get_settings(request: Request):
    require_api_user(request)
    cm = get_state().config_manager
    return {
        "success": True,
        "data": {
            # 显示口径与上传路径 (_upload_limit_bytes) 一致: 未设置时回退
            # MAX_UPLOAD_SIZE (100MB)。v0.1.0 第二轮修复: 旧默认 0 会让设置页
            # 显示"不限制", 而实际生效的是 100MB 上限 —— 两处口径不一致。
            "max_upload_size_mb": cm.get_setting_int(
                "max_upload_size_mb", MAX_UPLOAD_SIZE // (1024 * 1024)),
        },
    }


@router.put("/settings")
def api_put_settings(request: Request, body: SettingsIn):
    require_admin(request)
    if body.max_upload_size_mb < 0:
        raise _APIException(400, "上传限制不能为负数 (0 表示不限制)")
    cm = get_state().config_manager
    cm.set_setting("max_upload_size_mb", str(int(body.max_upload_size_mb)))
    return {"success": True, "message": "设置已保存"}


# ==================== v2.3 SMTP 邮件服务配置 (admin) ====================


class SmtpIn(BaseModel):
    host: str = ""
    port: int = 465
    user: str = ""
    password: Optional[str] = None   # 留空/None = 保持原值; host 清空 = 停用
    mail_from: str = ""


@router.get("/settings/smtp")
def api_get_smtp(request: Request):
    """读取 SMTP 配置 (密码只回"是否已设置", 永不回传明文/密文)"""
    require_admin(request)
    cm = get_state().config_manager
    # 端口容忍库里的脏值 (手工改库等): 解析失败回退 465, 不让 GET 直接 500
    try:
        port = int(cm.get_setting("smtp_port") or 465)
    except (TypeError, ValueError):
        port = 465
    return {
        "success": True,
        "data": {
            "host": cm.get_setting("smtp_host") or "",
            "port": port,
            "user": cm.get_setting("smtp_user") or "",
            "from": cm.get_setting("smtp_from") or "",
            "password_set": bool(cm.get_setting("smtp_pass_enc")),
            "configured": _mailer_ok(),
        },
    }


def _mailer_ok() -> bool:
    try:
        from .. import mailer
        return mailer.is_configured()
    except Exception:
        return False


@router.put("/settings/smtp")
def api_put_smtp(request: Request, body: SmtpIn):
    require_admin(request)
    cm = get_state().config_manager
    host = body.host.strip()
    if host and not body.user.strip():
        raise _APIException(400, "填写了 SMTP 服务器就必须同时填写登录账号")
    if body.port < 1 or body.port > 65535:
        raise _APIException(400, "端口不合法")
    cm.set_setting("smtp_host", host)
    cm.set_setting("smtp_port", str(body.port or 465))
    cm.set_setting("smtp_user", body.user.strip())
    cm.set_setting("smtp_from", body.mail_from.strip())
    if body.password:
        # Fernet 加密落 app_settings (与 AK/SK 同一密钥体系)
        from ...core.encryption import Encryptor
        cm.set_setting("smtp_pass_enc", Encryptor().encrypt(body.password))
    if not host:
        cm.set_setting("smtp_pass_enc", "")  # 停用邮件服务时连密码一起清掉
    get_state().config_manager.add_log(
        level="INFO", operation="web_smtp_config", target=host or "(停用)",
        status="success", message="更新 SMTP 配置" + (" (密码已更新)" if body.password else ""))
    return {"success": True, "message": "SMTP 配置已保存", "configured": _mailer_ok()}


class SmtpTestIn(BaseModel):
    to: str


@router.post("/settings/smtp/test")
def api_test_smtp(request: Request, body: SmtpTestIn):
    """向指定地址发一封测试邮件, 验证配置真实可用 (admin)"""
    require_admin(request)
    to = body.to.strip().lower()
    if not to or "@" not in to:
        raise _APIException(400, "收件地址不合法")
    from .. import mailer
    ok = mailer.send_mail(to, "ObjStoreExplorer SMTP 测试",
        '<p>这是一封来自 ObjStoreExplorer Web 的测试邮件。</p>'
        '<p>收到本邮件说明邮件服务配置正确, 忘记密码验证码功能可用。</p>')
    get_state().config_manager.add_log(
        level="INFO" if ok else "WARNING", operation="web_smtp_test", target=to,
        status="success" if ok else "failure",
        message="SMTP 测试邮件发送成功" if ok else "SMTP 测试邮件发送失败 (检查配置/网络)")
    return {"success": ok, "message": "测试邮件已发送, 请查收" if ok else "发送失败, 请检查 SMTP 配置"}
