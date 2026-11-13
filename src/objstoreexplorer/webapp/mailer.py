# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""SMTP 邮件发送 (v2.3 新增, 忘记密码验证码)

配置来源 (优先级从高到低):
    1. 应用设置 (config_manager app_settings, 管理后台在线配置, 即时生效):
       smtp_host / smtp_port / smtp_user / smtp_from / smtp_pass_enc (Fernet 密文)
    2. 环境变量 SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM

未配置时 send() 返回 False (调用方决定降级策略), 不抛异常。
纯标准库 smtplib + email.*, 不新增依赖。
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
import threading
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

logger = logging.getLogger("ose.web.mailer")

# Fernet 密文 = urlsafe base64 (含 - 与 _), 必须一并放行, 否则解不开
_KEY_RE = re.compile(r"^[A-Za-z0-9+/\-_=]{20,}$")

# 收件人级限流 (防把 SMTP 当转发器打垮信誉): 每地址每小时最多 6 封
_MAIL_PER_HOUR = 6
_sent_lock = threading.Lock()
_sent_log: dict = {}  # to -> [ts]


def _mail_allowed(to: str) -> bool:
    key = (to or "").lower()
    now = time.time()
    with _sent_lock:
        arr = [t for t in _sent_log.get(key, []) if now - t < 3600]
        if len(arr) >= _MAIL_PER_HOUR:
            _sent_log[key] = arr
            logger.warning("收件人邮件限流触发 (每小时 %d 封), 丢弃: %s", _MAIL_PER_HOUR, key)
            return False
        arr.append(now)
        _sent_log[key] = arr
        if len(_sent_log) > 10000:
            _sent_log.clear()
        return True


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def get_smtp_config() -> Optional[dict]:
    """读 SMTP 配置 (应用设置优先, 环境变量兜底)。不完整返回 None。"""
    host = port = user = pwd = frm = ""
    try:
        from .state import get_state
        cm = get_state().config_manager
        host = (cm.get_setting("smtp_host") or "").strip()
        port = (cm.get_setting("smtp_port") or "").strip()
        user = (cm.get_setting("smtp_user") or "").strip()
        frm = (cm.get_setting("smtp_from") or "").strip()
        enc = (cm.get_setting("smtp_pass_enc") or "").strip()
        if host and user:
            if enc and _KEY_RE.match(enc):
                try:
                    from ..core.encryption import Encryptor
                    pwd = Encryptor().decrypt(enc)
                except Exception:
                    logger.warning("SMTP 密码解密失败 (密钥变更?), 请重新保存邮件配置")
                    return None
    except Exception:
        pass
    if not host:
        host = _env("SMTP_HOST")
        port = _env("SMTP_PORT")
        user = _env("SMTP_USER")
        pwd = _env("SMTP_PASS")
        frm = _env("SMTP_FROM")
    if not (host and user and pwd):
        return None
    try:
        port_i = int(port or 465)
    except ValueError:
        port_i = 465
    return {
        "host": host,
        "port": port_i,
        "user": user,
        "pass": pwd,
        "from": frm or user,
    }


def is_configured() -> bool:
    return get_smtp_config() is not None


def send_mail(to: str, subject: str, html_body: str, timeout: int = 15) -> bool:
    """发送 HTML 邮件, 静默失败返回 False (调用方决定降级)。"""
    cfg = get_smtp_config()
    if cfg is None:
        logger.info("SMTP 未配置, 跳过发送: %s", subject)
        return False
    if not _mail_allowed(to):
        return False
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("ObjStoreExplorer", "utf-8")), cfg["from"]))
    msg["To"] = to
    try:
        ctx = ssl.create_default_context()
        if cfg["port"] == 465:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=timeout, context=ctx) as s:
                s.login(cfg["user"], cfg["pass"])
                s.sendmail(cfg["from"], [to], msg.as_string())
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout) as s:
                s.starttls(context=ctx)
                s.login(cfg["user"], cfg["pass"])
                s.sendmail(cfg["from"], [to], msg.as_string())
        logger.info("邮件发送成功: %s -> %s", subject, to)
        return True
    except Exception as e:
        logger.warning("邮件发送失败: %s (%s)", subject, e)
        return False


def send_password_reset_code(to: str, code: str, ttl_minutes: int = 10) -> bool:
    """忘记密码验证码邮件。主题不含账号信息 (防"邮件即账号存在性证明"枚举)。"""
    safe_code = re.sub(r"\D", "", code or "")[:8]
    body = (
        '<div style="font-family:sans-serif;max-width:560px;margin:0 auto">'
        '<h2 style="color:#2563eb">密码重置验证码</h2>'
        '<p>您 (或有人使用该邮箱) 在 ObjStoreExplorer Web 发起了密码重置。验证码:</p>'
        f'<p style="font-size:30px;letter-spacing:10px;font-weight:700;color:#2563eb;margin:20px 0">{safe_code}</p>'
        f'<p>有效期 <b>{int(ttl_minutes)} 分钟</b>, 仅可使用一次。</p>'
        '<p style="color:#999;font-size:13px">如果这不是您本人的操作, 请忽略本邮件 — '
        '验证码未被提交时, 您的密码不会发生任何变化。</p>'
        '<p style="color:#999;font-size:12px;margin-top:24px">ObjStoreExplorer · 系统邮件请勿回复</p></div>'
    )
    return send_mail(to, "ObjStoreExplorer 密码重置验证码", body)
