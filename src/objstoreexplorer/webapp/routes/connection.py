# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""连接 API - 建立/断开 S3 连接、连接历史

连接历史与桌面版共享 (data/config.db), SK 由服务端解密使用, 不回传前端。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...core.error_hints import hint_for_error
from ..deps import require_api_user, get_web_session
from ..state import get_state

router = APIRouter(prefix="/api")


class ConnectIn(BaseModel):
    endpoint: str
    access_key: str
    secret_key: str
    ssl: bool = False
    save: bool = True
    external_host: str = ""


class HistoryConnectIn(BaseModel):
    name: str


@router.post("/connect")
def api_connect(request: Request, body: ConnectIn):
    require_api_user(request)
    sess = get_web_session(request)
    ok, msg = sess.connect(
        endpoint=body.endpoint,
        access_key=body.access_key,
        secret_key=body.secret_key,
        ssl=body.ssl,
        save=body.save,
        external_host=body.external_host,
    )
    # 失败信息过人话映射 (未命中规则时原样返回, 调用方无感)
    resp: dict = {"success": ok, "message": msg if ok else hint_for_error(msg)}
    if ok:
        resp["data"] = {
            "endpoint": sess.current_endpoint,
            "admin_available": bool(sess.s3_client and sess.s3_client.admin_available),
            "server_version": sess.s3_client.server_version,
        }
    return resp


@router.post("/disconnect")
def api_disconnect(request: Request):
    require_api_user(request)
    sess = get_web_session(request)
    # 先取 endpoint 再断开: 断开后 current_endpoint 为 None, 日志目标会变空串
    endpoint = sess.current_endpoint or ""
    sess.disconnect()
    get_state().config_manager.add_log(
        level="INFO", operation="disconnect", target=endpoint,
        status="info", message=f"[web:{sess.username}] 已断开连接",
    )
    return {"success": True, "message": "已断开连接"}


@router.get("/status")
def api_status(request: Request):
    require_api_user(request)
    sess = get_web_session(request)
    # D21: 能力感知 — 把「服务端明确不支持的操作」透出, 前端对相关
    # 导航入口做降级标记 (而不是等用户点了才报错)
    unsupported = []
    try:
        if sess.s3_client is not None:
            unsupported = list(sess.s3_client.unsupported_ops)
    except Exception:
        unsupported = []
    return {
        "success": True,
        "data": {
            "connected": sess.is_connected,
            "endpoint": sess.current_endpoint or "",
            "admin_available": bool(
                sess.is_connected and sess.s3_client and sess.s3_client.admin_available
            ),
            "unsupported": unsupported,
        },
    }


@router.get("/history")
def api_history(request: Request):
    require_api_user(request)
    sess = get_web_session(request)
    return {"success": True, "data": sess.list_history()}


@router.post("/history/connect")
def api_history_connect(request: Request, body: HistoryConnectIn):
    require_api_user(request)
    sess = get_web_session(request)
    ok, msg = sess.connect_from_history(body.name)
    resp: dict = {"success": ok, "message": msg if ok else hint_for_error(msg)}
    if ok:
        resp["data"] = {
            "endpoint": sess.current_endpoint,
            "admin_available": bool(sess.s3_client and sess.s3_client.admin_available),
        }
    return resp


@router.delete("/history/{name:path}")
def api_history_delete(request: Request, name: str):
    require_api_user(request)
    sess = get_web_session(request)
    ok = sess.delete_history(name)
    return {"success": ok, "message": "已删除" if ok else "未找到该历史配置"}
