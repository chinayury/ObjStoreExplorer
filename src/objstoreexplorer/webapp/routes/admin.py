# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""Admin API - MinIO 用户/策略管理 + 一键创建 + 服务器信息 + Web 账号管理

MinIO 用户/策略依赖 Admin API (V2 客户端), 未具备权限时返回可读错误。
Web 账号管理: admin 增删 Web 登录账号、调整角色 (viewer 无权访问)。

v0.1.0: 全部处理器为同步 def —— 函数体是阻塞的 MinIO Admin 网络调用与
bcrypt 哈希, 由 FastAPI 放入线程池执行; 旧 async def 版本在 workers=1
单进程下会阻塞事件循环, 一台慢 MinIO 可卡住全部用户的所有请求。
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...core.admin_manager import generate_strong_password
from ..deps import require_admin, _APIException, get_web_session
from ..routes.auth import clear_login_throttle
from ..state import get_state

router = APIRouter(prefix="/api")


def _sess(request: Request):
    return get_web_session(request)


def _log(sess, operation: str, target: str, ok: bool, msg: str) -> None:
    try:
        get_state().config_manager.add_log(
            level="INFO" if ok else "ERROR",
            operation=operation, target=target,
            status="success" if ok else "failure",
            message=f"[web:{sess.username}] {msg}",
        )
    except Exception:
        pass


# ==================== MinIO 用户 ====================


class MinioUserIn(BaseModel):
    access_key: str
    secret_key: str = ""  # 留空自动生成 16 位强密码


@router.get("/admin/users")
def api_list_users(request: Request):
    require_admin(request)
    sess = _sess(request)
    ok, users = sess.admin_manager.list_users()
    return {"success": ok, "message": "" if ok else str(users),
            "data": users if ok else []}


@router.post("/admin/users")
def api_create_user(request: Request, body: MinioUserIn):
    require_admin(request)
    sess = _sess(request)
    sk = body.secret_key.strip() or generate_strong_password(16)
    ok, msg = sess.admin_manager.create_user(body.access_key.strip(), sk)
    _log(sess, "create_user", body.access_key, ok, msg)
    resp: dict = {"success": ok, "message": msg}
    if ok:
        resp["data"] = {"access_key": body.access_key, "secret_key": sk}
    return resp


@router.delete("/admin/users/{ak}")
def api_delete_user(request: Request, ak: str):
    require_admin(request)
    sess = _sess(request)
    ok, msg = sess.admin_manager.delete_user(ak)
    _log(sess, "delete_user", ak, ok, msg)
    return {"success": ok, "message": msg}


@router.post("/admin/users/{ak}/enable")
def api_enable_user(request: Request, ak: str):
    require_admin(request)
    sess = _sess(request)
    ok, msg = sess.admin_manager.enable_user(ak)
    _log(sess, "enable_user", ak, ok, msg)
    return {"success": ok, "message": msg}


@router.post("/admin/users/{ak}/disable")
def api_disable_user(request: Request, ak: str):
    require_admin(request)
    sess = _sess(request)
    ok, msg = sess.admin_manager.disable_user(ak)
    _log(sess, "disable_user", ak, ok, msg)
    return {"success": ok, "message": msg}


class ResetSecretIn(BaseModel):
    new_secret_key: str = ""  # 留空自动生成


@router.post("/admin/users/{ak}/reset-secret")
def api_reset_secret(request: Request, ak: str, body: ResetSecretIn):
    require_admin(request)
    sess = _sess(request)
    new_sk = body.new_secret_key.strip() or generate_strong_password(16)
    ok, msg = sess.admin_manager.reset_user_secret(ak, new_sk)
    _log(sess, "reset_user_secret", ak, ok, msg)
    resp: dict = {"success": ok, "message": msg}
    if ok:
        resp["data"] = {"secret_key": new_sk}
    return resp


# ==================== 策略 ====================


class PolicyIn(BaseModel):
    name: str
    content: dict  # 策略 JSON 内容


class PolicyAttachIn(BaseModel):
    policy: str
    access_key: str


class FullSetupIn(BaseModel):
    bucket_name: str = ""      # 新桶 (可空)
    access_key: str
    policy_type: str = "readwrite"  # readonly/readwrite/full
    auth_bucket: str = ""      # 授权已有桶 (bucket_name 为空时必填)


@router.get("/admin/policies")
def api_list_policies(request: Request):
    require_admin(request)
    sess = _sess(request)
    ok, policies = sess.admin_manager.list_policies()
    return {"success": ok, "message": "" if ok else str(policies),
            "data": policies if ok else []}


@router.get("/admin/policies/{name}")
def api_get_policy(request: Request, name: str):
    require_admin(request)
    sess = _sess(request)
    ok, content = sess.admin_manager.get_policy(name)
    if ok and content is not None and not isinstance(content, str):
        try:
            content = json.dumps(content, ensure_ascii=False, indent=2)
        except Exception:
            content = str(content)
    return {"success": ok, "message": "" if ok else str(content),
            "data": content if ok else None}


@router.post("/admin/policies")
def api_create_policy(request: Request, body: PolicyIn):
    require_admin(request)
    sess = _sess(request)
    ok, msg = sess.admin_manager.create_policy(body.name.strip(), body.content)
    _log(sess, "create_policy", body.name, ok, msg)
    return {"success": ok, "message": msg}


class PolicyContentIn(BaseModel):
    content: dict  # 新策略 JSON 内容


@router.put("/admin/policies/{name}")
def api_update_policy(request: Request, name: str, body: PolicyContentIn):
    """编辑策略内容 (MinIO 无 update API, 底层为 摘除附加用户→删→建→还原)。

    先确认策略存在再动手: update_policy_content 走"删+建", 若策略本不存在,
    删除会失败 (虽有回滚但白折腾一轮); 存在性预检让"改不存在的策略"直接报错。
    """
    require_admin(request)
    sess = _sess(request)
    name = name.strip()
    if not name:
        return {"success": False, "message": "策略名不能为空"}
    if not body.content:
        return {"success": False, "message": "策略内容不能为空"}
    ok, res = sess.admin_manager.get_policy(name)
    if not ok:
        err = str(res).lower()
        if "not found" in err or "does not exist" in err or "no such" in err:
            _log(sess, "update_policy", name, False, "策略不存在")
            return {"success": False, "message": f"策略 {name} 不存在, 无法编辑"}
        # 读取失败时不盲改: update_policy_content 走"删+建", 在无法确认现状时
        # 继续操作等于蒙眼拆桥 —— 中止并如实报错
        _log(sess, "update_policy", name, False, f"预检读取失败: {res}")
        return {"success": False, "message": f"无法读取现有策略 (已中止修改): {res}"}
    ok, msg = sess.admin_manager.update_policy_content(name, body.content)
    _log(sess, "update_policy", name, ok, msg)
    return {"success": ok, "message": msg}


@router.delete("/admin/policies/{name}")
def api_delete_policy(request: Request, name: str):
    require_admin(request)
    sess = _sess(request)
    ok, msg = sess.admin_manager.delete_policy(name)
    _log(sess, "delete_policy", name, ok, msg)
    return {"success": ok, "message": msg}


@router.post("/admin/policies/attach")
def api_attach_policy(request: Request, body: PolicyAttachIn):
    require_admin(request)
    sess = _sess(request)
    ok, msg = sess.admin_manager.attach_policy(body.policy, body.access_key)
    _log(sess, "attach_policy", f"{body.policy} -> {body.access_key}", ok, msg)
    return {"success": ok, "message": msg}


@router.post("/admin/policies/detach")
def api_detach_policy(request: Request, body: PolicyAttachIn):
    require_admin(request)
    sess = _sess(request)
    ok, msg = sess.admin_manager.detach_policy(body.policy, body.access_key)
    _log(sess, "detach_policy", f"{body.policy} -x {body.access_key}", ok, msg)
    return {"success": ok, "message": msg}


@router.post("/admin/create-full-setup")
def api_create_full_setup(request: Request, body: FullSetupIn):
    """一键创建 (可选)新桶 + 用户 + 策略 + 附加, 失败自动回滚"""
    require_admin(request)
    sess = _sess(request)
    result = sess.admin_manager.create_full_setup(
        bucket_name=body.bucket_name.strip(),
        access_key=body.access_key.strip(),
        policy_type=body.policy_type,
        auth_bucket=body.auth_bucket.strip(),
    )
    _log(sess, "create_full_setup",
         result.get("access_key", ""), result.get("success", False),
         str(result.get("error", "一键创建完成")))
    return {"success": result.get("success", False), "data": result}


@router.get("/admin/server-info")
def api_server_info(request: Request):
    require_admin(request)
    sess = _sess(request)
    return {"success": True, "data": sess.admin_manager.get_server_info()}


# ==================== Web 账号管理 (admin) ====================


class WebUserIn(BaseModel):
    username: str
    password: str = ""   # 留空 = 系统生成一次性临时口令 + 强制首登改密 (v2.1)
    role: str = "viewer"
    email: str = ""      # v2.3 选填: 找回邮箱 (忘记密码自助重置凭据)


class WebUserPatchIn(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = None
    active: Optional[bool] = None
    email: Optional[str] = None   # v2.3 管理员代管找回邮箱 (留空串=清除)


def _wlog(request: Request, operation: str, target: str, ok: bool, msg: str) -> None:
    """Web 账号管理操作日志 (操作人取当前会话, 与 _log 的 S3 会话版区分)"""
    try:
        actor = request.session.get("uid") or "?"
        get_state().config_manager.add_log(
            level="INFO" if ok else "ERROR",
            operation=operation, target=target,
            status="success" if ok else "failure",
            message=f"[web:{actor}] {msg}",
        )
    except Exception:
        pass


@router.get("/web/users")
def api_web_users(request: Request):
    require_admin(request)
    return {"success": True, "data": get_state().store.list_users()}


@router.post("/web/users")
def api_web_create_user(request: Request, body: WebUserIn):
    require_admin(request)
    state = get_state()
    try:
        res = state.store.create_user(body.username.strip(), body.password, body.role, body.email)
    except ValueError as e:
        _wlog(request, "web_user_create", body.username, False, str(e))
        raise _APIException(400, str(e))
    temp = res.get("temp_password")
    _wlog(request, "web_user_create", body.username, True,
          f"创建 Web 账号 ({body.role}{', 系统生成临时口令' if temp else ''})")
    # 临时口令仅此一次随响应返回, 不落日志 (v2.1)
    return {"success": True,
            "message": f"已创建 {body.role} 账号: {body.username}",
            "temp_password": temp}


@router.patch("/web/users/{username}")
def api_web_patch_user(request: Request, username: str, body: WebUserPatchIn):
    require_admin(request)
    state = get_state()
    revoked_sessions = 0
    try:
        if body.role:
            state.store.update_role(username, body.role)
        if body.password:
            # 管理员代设口令 → 强制该用户下次登录改密 (v2.1)
            state.store.set_password_by_admin(username, body.password)
        if body.active is not None:
            state.store.set_active(username, body.active)
            if not body.active:
                # 会话外置化: 停用即吊销其全部会话 (跨 worker 即时失效)
                try:
                    revoked_sessions = state.persist.revoke_user_sessions(username)
                except Exception:
                    pass
        if body.email is not None:
            # v2.3 代管找回邮箱 (set_email 内部拦"改其他管理员", 与隔离规则一致)
            state.store.set_email(request.session.get("uid") or "?", username, body.email)
    except ValueError as e:
        _wlog(request, "web_user_patch", username, False, str(e))
        raise _APIException(400, str(e))
    _wlog(request, "web_user_patch", username, True,
          "更新 Web 账号" + (f" (已吊销 {revoked_sessions} 个会话)" if revoked_sessions else ""))
    return {"success": True, "message": "已更新"}


@router.post("/web/users/{username}/reset-password")
def api_web_reset_password(request: Request, username: str):
    """重置口令: 生成一次性随机临时口令 + 强制改密 + 清除锁定 (v2.1)。

    临时口令仅此一次随响应返回, 管理员需通过安全渠道转交。
    """
    require_admin(request)
    state = get_state()
    try:
        temp = state.store.reset_password(username)
    except ValueError as e:
        _wlog(request, "web_user_reset", username, False, str(e))
        raise _APIException(400, str(e))
    _wlog(request, "web_user_reset", username, True, "重置 Web 账号口令 (一次性临时口令)")
    # 重置后清除 IP 限速, 否则用户拿着新临时口令仍可能被 429 挡在门外
    clear_login_throttle(username)
    return {"success": True, "message": f"已重置 {username} 的口令", "temp_password": temp}


@router.post("/web/users/{username}/unlock")
def api_web_unlock(request: Request, username: str):
    """管理员手动解锁 (清除 DB 账号锁定 + 内存 IP 限速) (v2.1)"""
    require_admin(request)
    state = get_state()
    try:
        state.store.unlock(username)
    except ValueError as e:
        raise _APIException(400, str(e))
    clear_login_throttle(username)
    _wlog(request, "web_user_unlock", username, True, "解锁 Web 账号")
    return {"success": True, "message": f"已解锁账号: {username}"}


@router.delete("/web/users/{username}")
def api_web_delete_user(request: Request, username: str):
    require_admin(request)
    state = get_state()
    try:
        state.store.delete_user(username)
    except ValueError as e:
        _wlog(request, "web_user_delete", username, False, str(e))
        raise _APIException(400, str(e))
    # 会话外置化: 删除即吊销其全部会话 (软删账号 get_user 返回 None 同样失效,
    # 这里显式吊销让其他 worker 的活跃会话立即 401)
    try:
        state.persist.revoke_user_sessions(username)
    except Exception:
        pass
    _wlog(request, "web_user_delete", username, True, "删除 Web 账号 (软删, 数据保留)")
    return {"success": True, "message": f"已删除账号: {username} (数据保留供审计)"}
