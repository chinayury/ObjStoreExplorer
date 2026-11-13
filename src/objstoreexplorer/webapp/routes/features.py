# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""特性 API - 桶版本控制 / 生命周期规则"""
from __future__ import annotations


from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..deps import require_api_user, _APIException, get_web_session
from ..state import get_state
from ...utils import update_checker

router = APIRouter(prefix="/api")


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


def _track(sess, op: str, ok: bool, msg: str) -> None:
    """把操作结果过一遍能力追踪: 明确「服务端不支持」时记录,
    前端据此对相关导航入口做降级标记 (D21 能力感知)"""
    try:
        sess.s3_client.track_result(op, ok, msg)
    except Exception:
        pass


# ==================== 版本控制 ====================


class VersioningIn(BaseModel):
    status: str  # Enabled / Suspended


@router.get("/versioning/{bucket}")
def api_get_versioning(request: Request, bucket: str):
    require_api_user(request)
    sess = get_web_session(request)
    ok, status = sess.s3_client.get_bucket_versioning(bucket)
    _track(sess, "versioning", ok, "" if ok else str(status))
    return {"success": ok, "message": "" if ok else str(status),
            "data": {"status": status or "Off"}}


@router.put("/versioning/{bucket}")
def api_set_versioning(request: Request, bucket: str, body: VersioningIn):
    """写操作: admin only (viewer 在下方校验拦截)"""
    user = require_api_user(request)
    if user.get("role") != "admin":
        raise _APIException(403, "只读账号无权执行写操作")
    sess = get_web_session(request)
    if body.status not in ("Enabled", "Suspended"):
        raise _APIException(400, "状态只能是 Enabled / Suspended")
    ok, msg = sess.s3_client.set_bucket_versioning(bucket, body.status)
    _log(sess, "versioning", bucket, ok, msg)
    _track(sess, "versioning", ok, msg)
    return {"success": ok, "message": msg}


# ==================== 对象历史版本 (浏览 / 恢复 / 删除) ====================

class VersionQueryIn(BaseModel):
    prefix: str = ""


class VersionRestoreIn(BaseModel):
    key: str
    version_id: str
    dest_key: str = ""


class VersionDeleteIn(BaseModel):
    key: str
    version_id: str


def _validate_version_key(key: str) -> None:
    """版本操作的 key 校验: 空/越界/控制字符 key 不进 S3 层"""
    if not key or not key.strip():
        raise _APIException(400, "对象 key 不能为空")
    if len(key) > 1024:
        raise _APIException(400, "对象 key 过长")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in key):
        raise _APIException(400, "对象 key 含控制字符")


@router.post("/versions/{bucket}/list")
def api_list_versions(request: Request, bucket: str, body: VersionQueryIn):
    """列出桶内对象的历史版本 (含删除标记)

    v0.1.0 功能补齐: core 的 list_object_versions 早已实现, Web 侧一直没有
    路由与入口 —— 误覆盖/误删后用户无法在 Web 上自救, 只能找管理员敲 mc。
    上限 200 条 (与 MAX_LIST_ITEMS 同口径), 超限时 truncated=True。
    """
    require_api_user(request)
    sess = get_web_session(request)
    prefix = (body.prefix or "").strip()
    ok, rows = sess.s3_client.list_object_versions(bucket, prefix, 200)
    if not ok:
        return {"success": False, "message": str(rows), "data": []}
    return {"success": True,
            "truncated": len(rows) >= 200,
            "data": rows}


@router.post("/versions/{bucket}/restore")
def api_restore_version(request: Request, bucket: str, body: VersionRestoreIn):
    """把历史版本恢复为当前版本 (误覆盖后的回滚) — admin only"""
    user = require_api_user(request)
    if user.get("role") != "admin":
        raise _APIException(403, "只读账号无权执行写操作")
    _validate_version_key(body.key)
    if not body.version_id:
        raise _APIException(400, "version_id 不能为空")
    sess = get_web_session(request)
    dest = (body.dest_key or "").strip() or body.key
    _validate_version_key(dest)
    ok, msg = sess.s3_client.copy_object_version(
        bucket, body.key, body.version_id, dest)
    _log(sess, "version_restore", f"{bucket}/{body.key}", ok, msg)
    return {"success": ok, "message": msg}


@router.delete("/versions/{bucket}")
def api_delete_version(request: Request, bucket: str, body: VersionDeleteIn):
    """删除指定历史版本 — admin only"""
    user = require_api_user(request)
    if user.get("role") != "admin":
        raise _APIException(403, "只读账号无权执行写操作")
    _validate_version_key(body.key)
    if not body.version_id:
        raise _APIException(400, "version_id 不能为空")
    sess = get_web_session(request)
    ok, msg = sess.s3_client.remove_object_version(bucket, body.key, body.version_id)
    _log(sess, "version_delete", f"{bucket}/{body.key}", ok, msg)
    return {"success": ok, "message": msg}


# ==================== 生命周期 ====================


class LifecycleIn(BaseModel):
    rule_id: str
    prefix: str = ""
    days: int = 30
    enabled: bool = True


def _serialize_lifecycle(config) -> list:
    """minio LifecycleConfig → [{id, status, prefix, days}]"""
    rules = []
    for r in getattr(config, "rules", None) or []:
        try:
            rules.append({
                "id": getattr(r, "rule_id", "") or "",
                "status": str(getattr(r, "status", "") or ""),
                "prefix": getattr(getattr(r, "rule_filter", None), "prefix", "") or "",
                "days": getattr(getattr(r, "expiration", None), "days", None),
            })
        except Exception:
            continue
    return rules


@router.get("/lifecycle/{bucket}")
def api_get_lifecycle(request: Request, bucket: str):
    require_api_user(request)
    sess = get_web_session(request)
    ok, config = sess.s3_client.get_bucket_lifecycle(bucket)
    _track(sess, "lifecycle", ok, "" if ok else str(config))
    if not ok:
        return {"success": False, "message": str(config), "data": []}
    return {"success": True, "data": _serialize_lifecycle(config)}


@router.put("/lifecycle/{bucket}")
def api_set_lifecycle(request: Request, bucket: str, body: LifecycleIn):
    user = require_api_user(request)
    if user.get("role") != "admin":
        raise _APIException(403, "只读账号无权执行写操作")
    sess = get_web_session(request)
    if body.days < 1:
        raise _APIException(400, "过期天数至少 1 天")
    payload = {
        "Rules": [{
            "ID": body.rule_id.strip() or "rule",
            "Status": "Enabled" if body.enabled else "Disabled",
            "Prefix": body.prefix.strip(),
            "Expiration": {"Days": body.days},
        }]
    }
    ok, msg = sess.s3_client.set_bucket_lifecycle(bucket, payload)
    _log(sess, "lifecycle", bucket, ok, msg)
    _track(sess, "lifecycle", ok, msg)
    return {"success": ok, "message": msg}


@router.delete("/lifecycle/{bucket}")
def api_delete_lifecycle(request: Request, bucket: str):
    user = require_api_user(request)
    if user.get("role") != "admin":
        raise _APIException(403, "只读账号无权执行写操作")
    sess = get_web_session(request)
    ok, msg = sess.s3_client.delete_bucket_lifecycle(bucket)
    _log(sess, "lifecycle_delete", bucket, ok, msg)
    _track(sess, "lifecycle", ok, msg)
    return {"success": ok, "message": msg}


# ==================== 检查更新 (只查询, 不自更新) ====================


@router.get("/update-check")
def api_update_check(request: Request):
    """匿名查询 GitHub Releases 最新版本 (借鉴 Pail: 只提示, 不静默自更新)。

    不依赖 S3 连接, 登录用户即可调用; 查询走服务端而不是浏览器, 避免内网
    部署时直连 GitHub 失败。网络失败不抛 5xx —— 返回 success=False 与原因,
    前端如实展示, 不假装"已是最新"。
    """
    require_api_user(request)
    res = update_checker.check_update()
    if not res["ok"]:
        return {"success": False, "message": f"检查失败: {res['error']}", "data": None}
    if res["update_available"]:
        message = f"发现新版本 v{res['latest']}（当前 v{res['current']}）"
    else:
        message = f"已是最新版本（v{res['current']}）"
    return {"success": True, "message": message, "data": res}
