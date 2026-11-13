# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""对象 API - 列表/上传/下载/分享/删除/重命名/复制/移动/文件夹/剪贴板/搜索

权限模型 (两角色):
    - viewer: 只读 (列表/搜索/下载/分享/属性)
    - admin : 全部 (上传/删除/重命名/复制/移动/建文件夹/剪贴板粘贴)

传输模型:
    - 上传: multipart 落临时目录 → 后台任务 → 前端轮询 /api/tasks
    - 单文件下载: 临时文件 + 流式响应 (下载完即删临时目录)
    - 多选/文件夹下载: 后台任务下载+打包 zip → 轮询完成后取 /api/tasks/{id}/result
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from typing import List, Optional

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ...core.validators import sanitize_filename
from ...utils.text_codec import decode_best_effort
from ...config.settings import MAX_UPLOAD_SIZE
from ..deps import require_api_user, get_web_session, _APIException
from ..state import get_state
from ..tasks import WebTask

logger = logging.getLogger("ose.web.objects")

router = APIRouter(prefix="/api")

# ---------------- 请求模型 ----------------


class DeleteIn(BaseModel):
    bucket: str
    keys: List[str]


class RenameIn(BaseModel):
    bucket: str
    old_key: str
    new_key: str


class CopyMoveIn(BaseModel):
    src_bucket: str
    src_key: str
    dst_bucket: str
    dst_key: str


class FolderIn(BaseModel):
    bucket: str
    parent: str = ""
    name: str


class ClipboardOpIn(BaseModel):
    op: str  # cut / copy
    items: List[dict]  # [{bucket, key, name, is_dir}]


class ClipboardPasteIn(BaseModel):
    bucket: str
    prefix: str = ""


class DownloadZipIn(BaseModel):
    bucket: str
    keys: List[str]


class ShareIn(BaseModel):
    bucket: str
    key: str
    expires: int


# 预签名分享有效期白名单 (秒): 只接受预置三档, 上限对齐 S3 规范的 7 天
SHARE_EXPIRES_OPTIONS = {3600: "1 小时", 86400: "24 小时", 604800: "7 天"}
SHARE_EXPIRES_MAX = 604800


# ---------------- 权限 helper ----------------


def _require_writer(request: Request) -> None:
    """写操作权限: 两角色模型下 admin 即可写"""
    user = require_api_user(request)
    if user.get("role") != "admin":
        raise _APIException(403, "只读账号无权执行写操作")


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


def _upload_limit_bytes() -> int:
    """单文件上传大小限制 (字节)。0 = 不限制。

    与 FileManager._resolve_upload_limit 同口径: 未设置回退默认
    MAX_UPLOAD_SIZE(100MB), 显式 0 = 不限制, 负值视为非法回退默认。
    """
    try:
        mb = get_state().config_manager.get_setting_int("max_upload_size_mb", -1)
    except Exception:
        return MAX_UPLOAD_SIZE
    if mb < 0:
        return MAX_UPLOAD_SIZE
    if mb == 0:
        return 0
    return mb * 1024 * 1024


def _validate_key_arg(bucket: str, *keys: str) -> None:
    """路由层基础参数校验 (v0.1.0): 桶/对象 key 非空、去首部斜杠, 给友好中文提示"""
    if not bucket or not bucket.strip():
        raise _APIException(400, "桶名不能为空")
    for k in keys:
        if not k or not k.strip():
            raise _APIException(400, "对象 key 不能为空")
        if k.startswith("/"):
            raise _APIException(400, "对象 key 不能以 / 开头")


# ---------------- 列表/搜索/属性/预览 (viewer 可用) ----------------

# ---------------- 在线预览 (B1, viewer 可用) ----------------
# 只按「扩展名白名单」判型, 不信任 S3 返回的 Content-Type:
#   - 图片类按原类型回传 (svg 明确排除 —— svg 可内嵌脚本, 同源内联执行即存储型 XSS)
#   - 文本类一律降级 text/plain 输出, 即使桶里存的是 .html/.js 也只做纯文本展示
PREVIEW_MAX_BYTES = 2 * 1024 * 1024
PREVIEW_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}
PREVIEW_TEXT_EXT = {
    ".txt", ".log", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".ini",
    ".cfg", ".conf", ".toml", ".env", ".py", ".java", ".js", ".ts", ".css",
    ".html", ".htm", ".sh", ".sql", ".go", ".rs", ".php", ".rb", ".c", ".cpp",
    ".h", ".hpp", ".swift", ".kt", ".tsv", ".properties", ".plist",
}
PREVIEW_IMAGE_CT_OUT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".ico": "image/x-icon",
}


@router.get("/objects/preview")
def api_preview_object(request: Request, bucket: str, key: str):
    """在线预览: 按扩展名白名单读对象头部字节 (上限 2MB) 直接回传。

    安全设计:
        - 响应统一 X-Content-Type-Options: nosniff, 禁止浏览器嗅探改判类型;
        - 文本类强制 text/plain, 堵死 "桶里存 .html → 同源内联执行" 的存储型 XSS;
        - 大小上限防止把大对象整块读进内存。
    """
    require_api_user(request)
    _validate_key_arg(bucket, key)
    sess = get_web_session(request)
    if key.endswith("/"):
        raise _APIException(400, "请指定具体文件 (文件夹不支持预览)")

    ext = os.path.splitext(key)[1].lower()
    is_image = ext in PREVIEW_IMAGE_EXT
    is_text = ext in PREVIEW_TEXT_EXT
    if not (is_image or is_text):
        raise _APIException(400, "该类型暂不支持在线预览, 请下载后查看")

    ok, info = sess.file_manager.preview_object(bucket, key, max_bytes=PREVIEW_MAX_BYTES)
    if not ok:
        raise _APIException(404, f"读取对象失败: {info}")

    data = info.get("preview_bytes") or b""
    size = info.get("size") or 0

    if is_image:
        if size > PREVIEW_MAX_BYTES:
            raise _APIException(400, "图片超过 2MB 预览上限, 请下载后查看")
        return Response(
            content=data,
            media_type=PREVIEW_IMAGE_CT_OUT.get(ext, "application/octet-stream"),
            headers={"X-Content-Type-Options": "nosniff"},
        )

    # 文本类: 编码自动识别 (借鉴 CloudStore): 桶里的日志/配置可能是
    # GB18030/Big5/Shift-JIS, 无脑 UTF-8 会满屏乱码。识别失败兜底
    # latin-1 + replace, 绝不 500。
    text, encoding = decode_best_effort(data)
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Preview-Truncated": "1" if info.get("truncated") else "0",
        "X-Preview-Encoding": encoding,
    }
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers=headers,
    )


@router.get("/objects")
def api_list_objects(request: Request, bucket: str, prefix: str = "",
                           recursive: bool = False):
    require_api_user(request)
    if not bucket:
        raise _APIException(400, "桶名不能为空")
    sess = get_web_session(request)
    ok, items = sess.file_manager.list_objects(bucket, prefix=prefix, recursive=recursive)
    # H-04: 列表有上限 (MAX_LIST_ITEMS), 达到上限时如实告知"还有更多",
    # 而不是假装列全了 (旧实现无上限, 大桶直接把概览页 OOM)。
    truncated = bool(sess.file_manager.last_list_truncated()) if ok else False
    return {"success": ok, "message": "" if ok else str(items),
            "truncated": truncated,
            "data": items if ok else []}


@router.get("/search")
def api_search(request: Request, bucket: str, kw: str, prefix: str = ""):
    require_api_user(request)
    if not bucket:
        raise _APIException(400, "桶名不能为空")
    if not kw or not kw.strip():
        raise _APIException(400, "搜索关键词不能为空")
    sess = get_web_session(request)
    ok, results = sess.search.search(bucket, kw, prefix=prefix)
    # D4: 截断状态如实回传 —— 扫描达上限时前端明示「结果可能不完整」
    return {"success": ok, "message": "" if ok else str(results),
            "data": results if ok else [],
            "truncated": bool(sess.search.last_truncated) if ok else False,
            "scan_limit": int(sess.search.last_scan_limit) if ok else 0}


@router.get("/objects/stat")
def api_stat_object(request: Request, bucket: str, key: str):
    require_api_user(request)
    _validate_key_arg(bucket, key)
    sess = get_web_session(request)
    ok, info = sess.file_manager.stat_object(bucket, key)
    if ok and isinstance(info, dict):
        # D8 公开性检查: 匿名 HEAD 探测对象是否公共可读, 把「误公开」
        # 变成可见信号 (探测失败不影响主流程, public 字段省略)
        try:
            from ...core import bucket_ext
            info.update(bucket_ext.check_object_public(
                sess.s3_client, bucket, key))
        except Exception:
            pass
    return {"success": ok, "message": "" if ok else str(info),
            "data": info if ok else None}


# ---------------- 下载 (viewer 可用) ----------------


@router.get("/objects/download")
def api_download_object(request: Request, bucket: str, key: str):
    """单文件下载: S3 → 临时文件 → 流式响应 (响应完成删临时目录)"""
    require_api_user(request)
    _validate_key_arg(bucket, key)
    sess = get_web_session(request)
    if not key or key.endswith("/"):
        raise _APIException(400, "请指定具体文件 (文件夹请使用批量下载)")

    state = get_state()
    workdir = state.tasks.new_workdir(request.session.get("sid", "anon"))
    dest = workdir / sanitize_filename(os.path.basename(key.rstrip("/")))

    ok, msg = sess.file_manager.download_file(bucket, key, str(dest))
    _log(sess, "download", f"{bucket}/{key}", ok, msg)
    if not ok:
        shutil.rmtree(workdir, ignore_errors=True)
        raise _APIException(502, f"下载失败: {msg}")

    return FileResponse(
        path=str(dest),
        filename=dest.name,
        background=BackgroundTask(shutil.rmtree, workdir, True),
    )


@router.post("/objects/download-zip")
def api_download_zip(request: Request, body: DownloadZipIn):
    """多选/文件夹下载: 后台任务下载 + 打包 zip"""
    require_api_user(request)
    # M-08: keys 也要逐个校验 (非空/不带前导斜杠), 否则非法 key 会一路
    # 带进后台任务, 在临时目录里拼出穿越路径
    _validate_key_arg(body.bucket, *body.keys)
    sess = get_web_session(request)
    if not body.keys:
        raise _APIException(400, "未选择任何对象")

    state = get_state()
    workdir = state.tasks.new_workdir(request.session.get("sid", "anon"))
    task = WebTask("download_zip", f"下载 {len(body.keys)} 项", total=len(body.keys),
                   owner=request.session.get("sid", ""))
    state.tasks.register(task, workdir)
    state.tasks.run_download_zip(task, sess, body.bucket, body.keys)
    _log(sess, "download_zip", f"{body.bucket} x{len(body.keys)}", True, "已提交打包任务")
    return {"success": True, "message": "打包任务已提交", "data": {"task_id": task.id}}


# ---------------- 预签名分享 (viewer 可用, 权限对齐下载) ----------------


@router.post("/objects/share")
def api_share_object(request: Request, body: ShareIn):
    """预签名分享: 生成带签名的对象 GET 下载 URL (复用当前会话连接)"""
    require_api_user(request)
    _validate_key_arg(body.bucket, body.key)
    sess = get_web_session(request)
    if body.key.endswith("/"):
        raise _APIException(400, "请指定具体文件 (文件夹不支持分享)")
    label = SHARE_EXPIRES_OPTIONS.get(body.expires)
    if label is None:
        raise _APIException(400, f"有效期仅支持 1 小时 / 24 小时 / 7 天 (上限 {SHARE_EXPIRES_MAX} 秒)")

    # 先确认对象存在: 比"签名成功但下载 404"提前给出友好提示
    ok, info = sess.file_manager.stat_object(body.bucket, body.key)
    if not ok:
        raise _APIException(404, f"无法分享: {info}")

    ok, url = sess.s3_client.get_presigned_url(body.bucket, body.key, expires=body.expires)
    _log(sess, "share", f"{body.bucket}/{body.key}", ok,
         f"生成预签名分享链接 (有效期 {label})" if ok else f"生成分享链接失败: {url}")
    if not ok:
        raise _APIException(502, f"生成分享链接失败: {url}")
    return {"success": True, "message": f"已生成分享链接 (有效期 {label})",
            "data": {"url": url, "expires": body.expires, "expires_label": label}}


# ---------------- 写操作 (admin) ----------------


@router.post("/objects/upload")
def api_upload(request: Request,
                     bucket: str = Form(...),
                     prefix: str = Form(""),
                     paths: Optional[List[str]] = Form(None),
                     files: List[UploadFile] = File(...)):
    """批量上传: multipart 落盘 → 后台任务 → 返回 task_id

    v0.1.0: 落盘前按 max_upload_size_mb 预检 (UploadFile.size), 超限文件
    直接拒绝 —— 旧实现只按文件名平铺上传; 新增可选 `paths` 表单字段,
    支持文件夹结构上传 (前端目录选择/拖拽传入相对路径)。

    v0.1.0: 落盘前按 max_upload_size_mb 预检 (UploadFile.size), 超限文件
    直接拒绝 —— 旧实现先完整落盘再由后台任务拒绝, 大文件白耗磁盘与带宽。
    """
    _require_writer(request)
    _validate_key_arg(bucket)
    sess = get_web_session(request)
    if not files:
        raise _APIException(400, "未选择文件")

    # 文件夹结构上传: 前端按 files 顺序传同名 index 的相对路径, 可选
    rel_paths: Optional[List[str]] = None
    if paths is not None:
        if len(paths) != len(files):
            raise _APIException(400, "文件与相对路径数量不匹配")
        rel_paths = []
        for raw in paths:
            segs = [s for s in re.split(r"[\\/]+", raw or "") if s]
            if not segs:
                raise _APIException(400, "相对路径不能为空")
            if any(s in (".", "..") for s in segs):
                raise _APIException(400, "相对路径不允许包含 . / .. 段")
            cleaned = "/".join(sanitize_filename(s) for s in segs)
            rel_paths.append(cleaned)

    state = get_state()
    limit = _upload_limit_bytes()
    if limit > 0:
        for f in files:
            size = getattr(f, "size", None)
            if size is not None and size > limit:
                _log(sess, "upload", f"{bucket}/{prefix}", False,
                     f"拒绝上传 (预检超限): {f.filename} 为 {size} 字节, "
                     f"超过 {limit // 1024 // 1024}MB 限制")
                raise _APIException(
                    400, f"文件 {f.filename} 超过 {limit // 1024 // 1024}MB 上传限制")

    sid = request.session.get("sid", "")
    workdir = state.tasks.new_workdir(sid or "anon")
    dest_files: List = []
    used_names: set = set()
    try:
        for i, f in enumerate(files):
            if rel_paths is not None:
                # 结构化上传: 按清洗后的相对路径暂存, 后台任务按同一相对路径入桶
                name = rel_paths[i]
                dest = workdir.joinpath(*name.split("/"))
                # 双重防线: 清洗后仍确保解析结果不逃出暂存目录
                if not dest.resolve().is_relative_to(workdir.resolve()):
                    raise _APIException(400, f"非法相对路径: {name}")
                dest.parent.mkdir(parents=True, exist_ok=True)
            else:
                name = sanitize_filename(os.path.basename(f.filename or "unnamed"))
                # 同批同名文件自动去重 (a.png → a(1).png), 避免临时目录相互覆盖丢数据
                base, n = name, 1
                while name in used_names:
                    stem, dot, ext = base.rpartition(".")
                    name = f"{stem}({n}){dot}{ext}" if dot else f"{base}({n})"
                    n += 1
                used_names.add(name)
                dest = workdir / name
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)
            dest_files.append(dest)
            # v0.1.0 修复: UploadFile.close() 在新版 Starlette 是协程, 同步
            # 调用只是产生 never-awaited 警告并不真正关闭; 关底层 spooled
            # 文件句柄 (Windows 下句柄不关会妨碍临时目录清理)
            try:
                f.file.close()
            except Exception:
                pass
    except _APIException:
        # M-12: 参数校验的 400 分支原本也在 try 里, 直接上抛会把已建的
        # 暂存目录漏在 temp/ 下 (每个失败请求泄漏一个目录, 直到 lifespan
        # 兜底清理才回收)。这里先清再抛。
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except OSError as e:
        # 磁盘写满/权限等: 清掉半成品目录再友好报错, 不留残留
        shutil.rmtree(workdir, ignore_errors=True)
        # M-13: 对外只给通用文案 + errno, 服务器绝对路径/盘符等细节只进日志
        errno = getattr(e, "errno", None)
        logger.warning(
            "上传暂存失败 (user=%s bucket=%s): %s", sess.username, bucket, e,
            exc_info=True,
        )
        detail = f" (错误码 {errno})" if errno else ""
        _log(sess, "upload", f"{bucket}/{prefix}", False, f"暂存上传文件失败: {e}")
        raise _APIException(
            507, f"暂存上传文件失败 (磁盘满或权限不足){detail}, 请稍后重试或联系管理员")

    task = WebTask("upload", f"上传 {len(dest_files)} 个文件 → {bucket}", total=len(dest_files),
                   owner=sid)
    state.tasks.register(task, workdir)
    state.tasks.run_upload(task, sess, bucket, prefix, dest_files, rel_paths=rel_paths)
    _log(sess, "upload", f"{bucket}/{prefix} x{len(dest_files)}", True, "已提交上传任务")
    return {"success": True, "message": "上传任务已提交", "data": {"task_id": task.id}}


@router.post("/objects/delete")
def api_delete_objects(request: Request, body: DeleteIn):
    _require_writer(request)
    # M-08: keys 逐个校验 (与 download-zip 同口径)
    _validate_key_arg(body.bucket, *body.keys)
    sess = get_web_session(request)
    if not body.keys:
        raise _APIException(400, "未选择对象")

    state = get_state()
    task = WebTask("delete", f"删除 {len(body.keys)} 项", total=len(body.keys),
                   owner=request.session.get("sid", ""))
    state.tasks.register(task)
    state.tasks.run_delete(task, sess, body.bucket, body.keys)
    _log(sess, "delete", f"{body.bucket} x{len(body.keys)}", True, "已提交删除任务")
    return {"success": True, "message": "删除任务已提交", "data": {"task_id": task.id}}


@router.post("/objects/rename")
def api_rename(request: Request, body: RenameIn):
    _require_writer(request)
    _validate_key_arg(body.bucket, body.old_key, body.new_key)
    sess = get_web_session(request)
    if body.old_key.endswith("/") or body.new_key.endswith("/"):
        # C-02: 文件夹重命名必须整棵子树一起搬。旧实现走单 key 的
        # move_object, 只挪走了 `/` 结尾的占位对象, 里面的文件原封不动
        # —— 界面显示"重命名成功", 实际内容全没了。
        ok, msg = sess.file_manager.rename_folder(
            body.bucket, body.old_key, body.new_key)
    else:
        ok, msg = sess.file_manager.move_object(body.bucket, body.old_key, body.new_key)
    _log(sess, "rename", f"{body.bucket}: {body.old_key} -> {body.new_key}", ok, msg)
    return {"success": ok, "message": msg}


@router.post("/objects/copy")
def api_copy(request: Request, body: CopyMoveIn):
    _require_writer(request)
    _validate_key_arg(body.src_bucket, body.src_key, body.dst_key, body.dst_bucket)
    sess = get_web_session(request)
    if body.src_key.endswith("/") or body.dst_key.endswith("/"):
        ok, msg = sess.file_manager.copy_folder(
            body.src_bucket, body.src_key, body.dst_bucket, body.dst_key)
    else:
        ok, msg = sess.file_manager.copy_object(
            body.src_bucket, body.src_key, body.dst_bucket, body.dst_key)
    _log(sess, "copy", f"{body.src_bucket}/{body.src_key} -> {body.dst_bucket}/{body.dst_key}", ok, msg)
    return {"success": ok, "message": msg}


@router.post("/objects/move")
def api_move(request: Request, body: CopyMoveIn):
    _require_writer(request)
    _validate_key_arg(body.src_bucket, body.src_key, body.dst_key, body.dst_bucket)
    sess = get_web_session(request)
    if body.src_key.endswith("/") or body.dst_key.endswith("/"):
        if body.src_bucket != body.dst_bucket:
            # 跨桶搬文件夹: 先整棵复制过去, 成功后再递归删源 (与单文件
            # move_object_cross_bucket 同口径, 失败时源数据不动)
            ok, msg = sess.file_manager.copy_folder(
                body.src_bucket, body.src_key, body.dst_bucket, body.dst_key)
            if ok:
                ok_d, msg_d = sess.file_manager.delete_folder(body.src_bucket, body.src_key)
                if not ok_d:
                    return {"success": False,
                            "message": f"已复制到 {body.dst_bucket}, 但删除源文件夹失败: {msg_d}。"
                                       f"请手动删除 {body.src_key}"}
        else:
            ok, msg = sess.file_manager.rename_folder(
                body.src_bucket, body.src_key, body.dst_key)
    elif body.src_bucket == body.dst_bucket:
        ok, msg = sess.file_manager.move_object(
            body.src_bucket, body.src_key, body.dst_key)
    else:
        ok, msg = sess.file_manager.move_object_cross_bucket(
            body.src_bucket, body.src_key, body.dst_bucket, body.dst_key)
    _log(sess, "move", f"{body.src_bucket}/{body.src_key} -> {body.dst_bucket}/{body.dst_key}", ok, msg)
    return {"success": ok, "message": msg}


@router.post("/objects/folder")
def api_create_folder(request: Request, body: FolderIn):
    _require_writer(request)
    _validate_key_arg(body.bucket)
    sess = get_web_session(request)
    if not body.name or not body.name.strip():
        raise _APIException(400, "文件夹名称不能为空")
    ok, msg = sess.file_manager.create_folder(body.bucket, body.name.strip(), parent=body.parent)
    _log(sess, "create_folder", f"{body.bucket}/{body.parent}{body.name}", ok, msg)
    return {"success": ok, "message": msg}


# ---------------- 剪贴板 ----------------


@router.get("/clipboard")
def api_clipboard_state(request: Request):
    require_api_user(request)
    sess = get_web_session(request)
    cb = sess.clipboard
    return {
        "success": True,
        "data": {
            "operation": cb.operation,
            "count": cb.count,
            "items": [{"bucket": i.bucket, "key": i.key, "name": i.name, "is_dir": i.is_dir}
                      for i in cb.get_items()],
        },
    }


@router.post("/clipboard")
def api_clipboard_op(request: Request, body: ClipboardOpIn):
    _require_writer(request)
    sess = get_web_session(request)
    if body.op not in ("cut", "copy"):
        raise _APIException(400, "操作必须是 cut 或 copy")
    for item in body.items:
        if not isinstance(item, dict) or not item.get("bucket") or not item.get("key"):
            raise _APIException(400, "剪贴板项缺少 bucket/key 字段")
    if body.op == "cut":
        sess.clipboard.cut(body.items)
    else:  # copy (op 已在上文校验)
        sess.clipboard.copy(body.items)
    return {"success": True, "message": f"已{'剪切' if body.op == 'cut' else '复制'} {len(body.items)} 项"}


@router.post("/clipboard/paste")
def api_clipboard_paste(request: Request, body: ClipboardPasteIn):
    _require_writer(request)
    _validate_key_arg(body.bucket)
    sess = get_web_session(request)
    try:
        results = sess.clipboard.paste(body.bucket, body.prefix)
    except Exception as e:
        raise _APIException(409, str(e))
    ok = all(r.get("success") for r in results) if results else True
    _log(sess, "paste", f"{body.bucket}/{body.prefix} x{len(results)}", ok,
         "粘贴完成" if ok else "部分粘贴失败")
    return {"success": ok, "message": "粘贴完成" if ok else "部分粘贴失败, 详情查看日志",
            "data": results}


@router.delete("/clipboard")
def api_clipboard_clear(request: Request):
    """清空自己的剪贴板 (登录即可, 与 GET /api/clipboard 对称;

    viewer 的剪贴板恒为空, 清空无越权面 —— 旧实现误用 writer 权限)"""
    require_api_user(request)
    sess = get_web_session(request)
    sess.clipboard.clear()
    return {"success": True, "message": "剪贴板已清空"}
