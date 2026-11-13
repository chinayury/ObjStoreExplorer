# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""登录 / 登出 / 自助改密 / 忘记密码 (v2.3)

登录页: GET /login (表单提交, 失败返回页面错误提示)
登录动作: POST /login
登出动作: POST /logout (销毁 WebSession + 清 cookie 会话)
改密: PUT /api/web/password (任何登录用户, 需旧口令)
找回: GET/POST /forgot-password → GET/POST /reset-password (邮件验证码两步)

v2.1 用户管理增强:
    - 双层防爆破: ①内存 IP 限速 (username@ip 维度, 覆盖"用户不存在"的枚举/喷洒,
      重启即清、不影响真实用户) + ②账号级 DB 持久锁定 (store 内计数,
      重启不丢、跨浏览器有效); 管理员解锁同时清两层。
    - 管理员重置/新建的账号 (must_change_password=1) 登录后强制跳转
      系统设置页改密; deps 层对 API 做 403 拦截, 双端强制。

v2.3 忘记密码 (借鉴用户中心 B/E 能力):
    - 凭"用户名+登记邮箱"精确匹配发 6 位邮件码 (10 分钟/一次性/5 次作废/60s 冷却)
    - 防枚举: 匹配与否页面响应完全一致 (文案+状态码), 差异只进操作日志
    - SMTP 未配置: 页面明确提示"请联系管理员", 不发码

v0.1.0 正式版:
    - 涉及 bcrypt 哈希 / SMTP 阻塞收发 / SQLite 的处理器改为同步 def,
      由 FastAPI 放入线程池执行 —— workers=1 单进程下不再阻塞事件循环
      (旧实现登录高峰或 SMTP 慢时会卡住全部用户的所有请求)。
    - 会话过期友好提示: 401 跳转 /login?expired=1, 登录页显示过期说明。
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from ..deps import get_current_user, revoke_web_session, require_api_user, _APIException
from ..state import SESSION_COOKIE_TTL, get_state

logger = logging.getLogger("ose.web.auth")

router = APIRouter()

# ==================== 登录失败限速 (防在线爆破 / 用户名枚举喷洒) ====================

_LOGIN_MAX_FAILS = 5        # 连续失败 N 次后锁定
_LOGIN_LOCK_SECONDS = 600   # 锁定时长 10 分钟
_LOGIN_USERNAME_MAX = 64    # M-11: 与 store.create_user 的口令/用户名上限同口径
_LOGIN_FAILS_CAP = 4096     # M-11: LRU 上限, 防止超长用户名 + 分布式 IP 撑爆内存
_login_fails: "OrderedDict[str, dict]" = OrderedDict()  # {key: {fails, locked_until}}
_login_lock = threading.Lock()


def _throttle_key(username: str, ip: str) -> str:
    """限速记录的 key。

    M-11: username 来自表单、无长度上限, 原样拼进 key 会让每次失败
    登录都新增一条不可清理的大字符串记录 (锁定期 10 分钟内清不掉)。
    这里截断到 64 字符, 与账号体系的用户名上限一致。
    """
    return f"{username[:_LOGIN_USERNAME_MAX]}@{ip}"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_remaining_lock(username: str, ip: str) -> int:
    """返回剩余锁定秒数 (0 = 未锁定)"""
    with _login_lock:
        rec = _login_fails.get(_throttle_key(username, ip))
        if rec and rec["locked_until"] > time.time():
            return int(rec["locked_until"] - time.time()) + 1
    return 0


def _record_login_fail(username: str, ip: str) -> None:
    key = _throttle_key(username, ip)
    now = time.time()
    with _login_lock:
        # 只清理"曾锁定且已过期"的记录: locked_until == 0 表示还在累计失败
        # 次数, 清掉就等于给爆破者重置计数器 (旧实现只在 >1000 时清理,
        # 不会误伤; 这里加LRU后每笔都跑清理, 必须带上这个条件)。
        for k in [k for k, v in _login_fails.items()
                  if v["locked_until"] and v["locked_until"] < now]:
            _login_fails.pop(k, None)
        while len(_login_fails) >= _LOGIN_FAILS_CAP:
            _login_fails.popitem(last=False)   # 丢最旧的一条
        rec = _login_fails.setdefault(key, {"fails": 0, "locked_until": 0.0})
        _login_fails.move_to_end(key)
        rec["fails"] += 1
        if rec["fails"] >= _LOGIN_MAX_FAILS:
            rec["locked_until"] = now + _LOGIN_LOCK_SECONDS
            rec["fails"] = 0


def _clear_login_fails(username: str, ip: str) -> None:
    with _login_lock:
        _login_fails.pop(_throttle_key(username, ip), None)


def clear_login_throttle(username: str) -> None:
    """管理员解锁账号时同步清除该用户名的 IP 限速记录 (v2.1)。

    只按用户名前缀匹配清理, 不区分 IP —— 解锁是管理员显式动作,
    宁可多清不可漏清 (漏清会让用户拿着正确口令仍被 429 挡着)。
    """
    prefix = f"{username[:_LOGIN_USERNAME_MAX]}@"
    with _login_lock:
        for k in [k for k in _login_fails if k.startswith(prefix)]:
            _login_fails.pop(k, None)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/", status_code=303)
    state = get_state()
    # 会话过期/未登录跳转带 ?expired=1 时给出友好提示 (v0.1.0)
    notice = "登录已过期或未登录, 请重新登录" if request.query_params.get("expired") else ""
    return state.templates.TemplateResponse(
        request, "login.html", {"error": "", "notice": notice}
    )


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form("")):
    """同步 def: authenticate 内含 bcrypt 哈希 (CPU 密集), 放线程池执行"""
    state = get_state()
    ip = _client_ip(request)

    # 第 1 层 · IP 限速 (username@ip 维度): 覆盖"用户不存在"的枚举/密码喷洒,
    # 这类账号没有 DB 行可计数, 只能靠内存限速。达阈值返回 429。
    remaining = _login_remaining_lock(username, ip)
    if remaining > 0:
        state.config_manager.add_log(
            level="WARNING", operation="web_login", target=username,
            status="failure", message=f"登录被限速锁定 (还剩 {remaining}s)",
        )
        return state.templates.TemplateResponse(
            request, "login.html",
            {"error": f"失败次数过多, 请 {max(remaining // 60, 1)} 分钟后再试", "notice": ""},
            status_code=429,
        )

    # 第 2 层 · 账号级 DB 持久锁定 (真实账号): 重启不丢、跨浏览器有效。
    # 停用/锁定如实提示 (运维状态, 非枚举泄露)。
    blocked = state.store.login_block_reason(username)
    if blocked:
        state.config_manager.add_log(
            level="WARNING", operation="web_login", target=username,
            status="failure", message=f"登录被拒: {blocked} (ip={ip})",
        )
        return state.templates.TemplateResponse(
            request, "login.html",
            {"error": blocked, "notice": ""},
            status_code=200,
        )

    user = state.store.authenticate(username, password)
    if user is None:
        # 统一模糊提示, 不区分"用户不存在/密码错误" (防枚举);
        # 两层计数同时累加 (IP 层覆盖不存在账号, DB 层覆盖存在账号)
        _record_login_fail(username, ip)
        state.config_manager.add_log(
            level="WARNING", operation="web_login", target=username,
            status="failure", message="登录失败 (口令错误或账号不存在)",
        )
        return state.templates.TemplateResponse(
            request, "login.html",
            {"error": "用户名或口令错误", "notice": ""},
            status_code=200,
        )
    _clear_login_fails(username, ip)

    # 会话外置化: 服务端登记会话行 (web_sessions), 令牌只携带 uid/sid 引用。
    # sid 每次登录重新生成 —— 换账号登录时旧会话状态不复用。
    sid = uuid.uuid4().hex
    request.session["uid"] = user["username"]
    request.session["sid"] = sid
    try:
        state.persist.create_session(sid, user["username"], SESSION_COOKIE_TTL)
    except Exception:
        # 会话行登记失败 (库忙等极端情况): 照常发 cookie, 但首个请求会因
        # 服务端无行而要求重新登录 —— fail closed, 不放行无行会话
        logger.warning("会话行登记失败 (sid=%s)", sid, exc_info=True)

    state.config_manager.add_log(
        level="INFO", operation="web_login", target=user["username"],
        status="success", message=f"Web 登录成功 ({user['role']})",
    )
    if user.get("must_change"):
        return RedirectResponse("/settings?force=1", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    revoke_web_session(request)  # 服务端吊销 (全 worker 即时失效)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


@router.put("/api/web/password")
def change_own_password(request: Request, body: PasswordChangeIn):
    """任何登录用户修改自己的口令 (需验证旧口令; 强制改密模式跳过旧口令)

    同步 def: update_password 内含 bcrypt 哈希。
    强制改密标记改由 web_users.must_change_password 推导 (会话外置化):
    改密成功落库后自动解除, 无需回写令牌。
    """
    user = get_current_user(request)
    if user is None:
        return JSONResponse(status_code=401, content={"success": False, "message": "未登录"})
    state = get_state()
    forced = bool(int(user.get("must_change_password") or 0))
    if not forced:
        check = state.store.authenticate(user["username"], body.old_password)
        if check is None:
            return JSONResponse(status_code=400, content={"success": False, "message": "旧口令错误"})
    try:
        state.store.update_password(user["username"], body.new_password)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})
    state.config_manager.add_log(
        level="INFO", operation="web_password_change", target=user["username"],
        status="success",
        message=("强制改密完成 (初始口令失效)" if forced else "修改了自己的 Web 口令"),
    )
    return {"success": True, "message": "口令已修改" + ("，初始口令已失效" if forced else "")}


# ==================== v2.3 忘记密码 (邮件验证码自助重置) ====================

# 发码 IP 限速: 每 IP 每小时最多 10 次申请 (与登录限速同构, 独立桶)
_SEND_MAX_PER_IP = 10
_SEND_WINDOW = 3600
_send_fails: dict = {}
_send_lock = threading.Lock()


def _send_rate_ok(ip: str) -> bool:
    now = time.time()
    with _send_lock:
        arr = [t for t in _send_fails.get(ip, []) if now - t < _SEND_WINDOW]
        if len(arr) >= _SEND_MAX_PER_IP:
            _send_fails[ip] = arr
            return False
        arr.append(now)
        _send_fails[ip] = arr
        if len(_send_fails) > 5000:
            _send_fails.clear()
        return True


_GENERIC_SEND_MSG = "如果用户名与邮箱匹配, 重置验证码已发送至该邮箱 (10 分钟内有效), 请查收"


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/", status_code=303)
    from .. import mailer
    state = get_state()
    return state.templates.TemplateResponse(
        request, "forgot_password.html",
        {"error": "", "notice": "", "sent": "", "mail_ready": mailer.is_configured()},
    )


@router.post("/forgot-password")
def forgot_send(request: Request, username: str = Form(""), email: str = Form("")):
    """第一步: 申请重置验证码。防枚举 — 匹配与否响应完全一致。

    同步 def: 发码路径含 bcrypt(验证码哈希) 与 SMTP 阻塞收发 (最长 15s)"""
    from .. import mailer
    state = get_state()
    ip = _client_ip(request)

    def _render(error="", sent=""):
        return state.templates.TemplateResponse(
            request, "forgot_password.html",
            {"error": error, "notice": "", "sent": sent,
             "mail_ready": mailer.is_configured(),
             "username": username.strip(), "email": email.strip()},
        )

    if not _send_rate_ok(ip):
        state.config_manager.add_log(
            level="WARNING", operation="web_password_reset_send", target=username,
            status="failure", message=f"发码申请被 IP 限速 (ip={ip})")
        return _render(error="申请过于频繁, 请 1 小时后再试")

    if not mailer.is_configured():
        return _render(error="邮件服务未配置, 无法自助重置, 请联系管理员")

    user = state.store.find_for_password_reset(username, email)
    if user is None:
        # 防枚举: 不区分"用户不存在/邮箱不符/未登记", 与成功路径同文案同状态码
        state.config_manager.add_log(
            level="INFO", operation="web_password_reset_send", target=username,
            status="failure", message=f"发码申请未匹配到账号 (ip={ip})")
        return _render(sent=_GENERIC_SEND_MSG)

    key = (user["username"], user["email"])
    st = state.store.reset_code_status(*key)
    if st["exists"] and datetime.utcnow() < st["cooldown_until"]:
        state.config_manager.add_log(
            level="INFO", operation="web_password_reset_send", target=username,
            status="failure", message="重发冷却期内, 未发送")
        return _render(sent=_GENERIC_SEND_MSG)

    code = state.store.issue_reset_code(*key)
    sent = mailer.send_password_reset_code(user["email"], code)
    if not sent:
        # 发送失败 (SMTP 故障/收件人限流): 作废已签发的码, 对外仍统一文案
        state.store.clear_reset_codes(user["username"])
        state.config_manager.add_log(
            level="WARNING", operation="web_password_reset_send", target=username,
            status="failure", message=f"验证码邮件发送失败 (ip={ip})")
        return _render(sent=_GENERIC_SEND_MSG)
    state.config_manager.add_log(
        level="INFO", operation="web_password_reset_send", target=user["username"],
        status="success", message=f"密码重置验证码已发送 (ip={ip})")  # 不记码
    return _render(sent=_GENERIC_SEND_MSG)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_page(request: Request, username: str = "", email: str = ""):
    if get_current_user(request):
        return RedirectResponse("/", status_code=303)
    state = get_state()
    return state.templates.TemplateResponse(
        request, "reset_password.html",
        {"error": "", "notice": "", "username": username, "email": email},
    )


@router.post("/reset-password")
def reset_submit(request: Request, username: str = Form(""), email: str = Form(""),
                 code: str = Form(""), new_password: str = Form("")):
    """第二步: 凭验证码设置新口令。(同步 def: 含 bcrypt 校验与哈希)"""
    state = get_state()
    ip = _client_ip(request)

    def _render(error=""):
        return state.templates.TemplateResponse(
            request, "reset_password.html",
            {"error": error, "notice": "", "username": username, "email": email},
        )

    user = state.store.find_for_password_reset(username, email)
    ok = state.store.verify_reset_code(user["username"], user["email"], code) if user else False
    if not user or not ok:
        state.config_manager.add_log(
            level="WARNING", operation="web_password_reset", target=username,
            status="failure",
            message=f"重置校验失败: {'码无效或过期' if user else '账号不匹配'} (ip={ip})")
        return _render(error="验证码错误或已失效, 请重新获取")

    try:
        state.store.reset_password_self(user["username"], new_password)
    except ValueError as e:
        # 强度/历史校验失败: 码已被消费, 如实返回原因 (需重新申请)
        return _render(error=str(e))
    clear_login_throttle(user["username"])
    state.config_manager.add_log(
        level="INFO", operation="web_password_reset", target=user["username"],
        status="success", message=f"密码自助重置成功 (ip={ip})")
    return state.templates.TemplateResponse(
        request, "login.html",
        {"error": "", "notice": "密码已重置, 请使用新口令登录"},
    )


# ==================== v2.3 找回邮箱 API (登录用户自助 + 管理员代管) ====================


class EmailIn(BaseModel):
    email: str = ""


@router.get("/api/web/me")
def api_web_me(request: Request):
    """当前登录用户信息 (v2.3: 含找回邮箱, 设置页预填用)"""
    user = require_api_user(request)
    return {"success": True, "data": {
        "username": user["username"], "role": user["role"],
        "email": user.get("email") or "",
        "must_change_password": int(user.get("must_change_password") or 0),
    }}


@router.put("/api/web/email")
def set_own_email(request: Request, body: EmailIn):
    """当前登录用户设置/清除自己的找回邮箱 (同步 def: 含 SQLite 写)"""
    user = require_api_user(request)
    state = get_state()
    try:
        norm = state.store.set_email(user["username"], user["username"], body.email)
    except ValueError as e:
        raise _APIException(400, str(e))
    state.config_manager.add_log(
        level="INFO", operation="web_email_set", target=user["username"],
        status="success", message="绑定/修改找回邮箱" if norm else "清除找回邮箱")
    return {"success": True, "email": norm,
            "message": "邮箱已保存" if norm else "邮箱已清除"}
