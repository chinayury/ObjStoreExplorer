# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""桶 API - 列表/创建/删除/统计/概览"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..deps import require_api_user, require_writer, get_web_session
from ..state import get_state

router = APIRouter(prefix="/api")


class BucketIn(BaseModel):
    name: str


class BucketDeleteIn(BaseModel):
    force: bool = False


@router.get("/buckets")
def api_list_buckets(request: Request):
    require_api_user(request)
    sess = get_web_session(request)
    ok, buckets = sess.bucket_manager.list_buckets()
    return {"success": ok, "message": "" if ok else str(buckets),
            "data": buckets if ok else []}


@router.post("/buckets")
def api_create_bucket(request: Request, body: BucketIn):
    require_writer(request)
    sess = get_web_session(request)
    ok, msg = sess.bucket_manager.create_bucket(body.name.strip())
    _log(request, sess, "create_bucket", body.name, ok, msg)
    return {"success": ok, "message": msg}


@router.delete("/buckets/{bucket}")
def api_delete_bucket(request: Request, bucket: str, force: bool = False):
    require_writer(request)
    sess = get_web_session(request)
    ok, msg = sess.bucket_manager.delete_bucket(bucket, force=force)
    _log(request, sess, "delete_bucket", bucket, ok, msg)
    return {"success": ok, "message": msg}


@router.get("/buckets/{bucket}/stats")
def api_bucket_stats(request: Request, bucket: str):
    require_api_user(request)
    sess = get_web_session(request)
    stats = sess.stats_manager.get_bucket_stats(bucket)
    # QUA-07: 旧写法 `"error" not in stats or not stats.get("error")` 是双重
    # 否定 —— "error" 不在 stats 里时第一项已为 True, 第二项的 not 永真,
    # 整个表达式退化成恒真, 等于没判断。直接判"有错误信息"即可。
    return {"success": not stats.get("error"), "data": stats}


@router.get("/overview")
def api_overview(request: Request):
    """概览页数据 (并发统计全部桶)"""
    require_api_user(request)
    sess = get_web_session(request)
    overview = sess.stats_manager.get_overview()
    if "error" in overview:
        return {"success": False, "message": overview["error"]}
    return {"success": True, "data": overview}


# ==================== CORS 配置 (D6) ====================

class CorsIn(BaseModel):
    origin: str = "*"
    methods: List[str] = ["GET"]
    headers: List[str] = ["*"]
    max_age: Optional[int] = None


@router.get("/buckets/{bucket}/cors")
def api_get_cors(request: Request, bucket: str):
    """读取桶 CORS 配置 (无配置返回空列表)"""
    require_api_user(request)
    sess = get_web_session(request)
    ok, rules = sess.bucket_manager.get_bucket_cors(bucket)
    if not ok:
        sess.s3_client.track_result("cors", False, str(rules))
        return {"success": False, "message": str(rules), "data": []}
    return {"success": True, "data": rules}


@router.put("/buckets/{bucket}/cors")
def api_set_cors(request: Request, bucket: str, body: List[CorsIn]):
    """写入桶 CORS 配置 (整体覆盖; admin only)"""
    require_writer(request)
    sess = get_web_session(request)
    if not body:
        return {"success": False, "message": "至少需要一条 CORS 规则"}
    rules = [r.model_dump() for r in body]
    ok, msg = sess.bucket_manager.set_bucket_cors(bucket, rules)
    _log(request, sess, "set_cors", bucket, ok, msg)
    if not ok:
        sess.s3_client.track_result("cors", False, msg)
    return {"success": ok, "message": msg}


@router.delete("/buckets/{bucket}/cors")
def api_delete_cors(request: Request, bucket: str):
    """删除桶 CORS 配置 (admin only)"""
    require_writer(request)
    sess = get_web_session(request)
    ok, msg = sess.bucket_manager.delete_bucket_cors(bucket)
    _log(request, sess, "delete_cors", bucket, ok, msg)
    if not ok:
        sess.s3_client.track_result("cors", False, msg)
    return {"success": ok, "message": msg}


# ==================== 未完成分片清理 (D7) ====================

@router.get("/buckets/{bucket}/multipart")
def api_list_multipart(request: Request, bucket: str):
    """列出桶内未完成的分段上传"""
    require_api_user(request)
    sess = get_web_session(request)
    ok, uploads = sess.bucket_manager.list_multipart_uploads(bucket)
    if not ok:
        sess.s3_client.track_result("multipart", False, str(uploads))
        return {"success": False, "message": str(uploads), "data": []}
    return {"success": True, "data": uploads}


class MultipartAbortIn(BaseModel):
    key: str
    upload_id: str


@router.delete("/buckets/{bucket}/multipart")
def api_abort_multipart(request: Request, bucket: str, body: MultipartAbortIn):
    """中止一个未完成的分段上传 (admin only)"""
    require_writer(request)
    sess = get_web_session(request)
    ok, msg = sess.bucket_manager.abort_multipart_upload(
        bucket, body.key, body.upload_id)
    _log(request, sess, "abort_multipart", f"{bucket}/{body.key}", ok, msg)
    return {"success": ok, "message": msg}


def _log(request: Request, sess, operation: str, target: str, ok: bool, msg: str) -> None:
    """写操作日志 (失败不打断主流程)"""
    try:
        get_state().config_manager.add_log(
            level="INFO" if ok else "ERROR",
            operation=operation, target=target,
            status="success" if ok else "failure",
            message=f"[web:{sess.username}] {msg}",
        )
    except Exception:
        pass
