# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源代码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""任务 API - 上传/删除/打包下载任务的轮询、取消、结果获取

任务归属: 每个任务记录创建会话 ID (owner)。非本人会话的任务一律 403
(仅 admin 可跨会话查看/操作), 防止跨用户读取任务明细或下载他人打包结果。

v0.1.0 第二轮 (会话外置化): 任务落库后, manager.get() 可能返回本 worker
的 WebTask 执行副本或跨 worker 的 TaskView 只读视图 (webapp/tasks.py);
两者对路由暴露同一套属性, 取消统一走 manager.cancel (本地事件或 DB 标志)。

H-05: 4 个处理器原本是 `async def` 却做同步 SQLite 查询/文件响应 —— 阻塞
调用霸占事件循环, 一个慢查询卡住全部用户的全部请求。全部改同步 `def`,
由 FastAPI 放线程池执行。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from ..deps import require_api_user, _APIException
from ..state import get_state

router = APIRouter(prefix="/api")


def _sid(request: Request) -> str:
    return request.session.get("sid", "")


def _can_access(task, request: Request, user) -> bool:
    """任务归属校验: 创建会话本人或 admin"""
    return task.owner == _sid(request) or user.get("role") == "admin"


@router.get("/tasks")
def api_list_tasks(request: Request):
    user = require_api_user(request)
    tasks = get_state().tasks.list_for_session()
    if user.get("role") != "admin":
        tasks = [t for t in tasks if t.owner == _sid(request)]
    # 只回传最近 24h 的任务, 旧的已被 expire_results 清理
    return {"success": True, "data": [t.to_dict() for t in tasks[:50]]}


@router.get("/tasks/{task_id}")
def api_get_task(request: Request, task_id: str):
    user = require_api_user(request)
    task = get_state().tasks.get(task_id)
    if task is None:
        raise _APIException(404, "任务不存在或已过期")
    if not _can_access(task, request, user):
        raise _APIException(403, "无权访问其他会话的任务")
    return {"success": True, "data": task.to_dict()}


@router.post("/tasks/{task_id}/cancel")
def api_cancel_task(request: Request, task_id: str):
    user = require_api_user(request)
    task = get_state().tasks.get(task_id)
    if task is None:
        return {"success": False, "message": "任务不存在"}
    if not _can_access(task, request, user):
        raise _APIException(403, "无权操作其他会话的任务")
    # 统一经 manager: 本 worker 置取消事件, 跨 worker 置 DB 取消标志
    get_state().tasks.cancel(task_id)
    return {"success": True, "message": "已请求取消"}


@router.get("/tasks/{task_id}/result")
def api_task_result(request: Request, task_id: str):
    """取打包下载结果 (zip) — 仅任务归属会话或 admin 可取"""
    user = require_api_user(request)
    task = get_state().tasks.get(task_id)
    if task is None:
        raise _APIException(404, "任务不存在或已过期")
    if not _can_access(task, request, user):
        raise _APIException(403, "无权下载其他会话的任务结果")
    if task.kind != "download_zip" or task.status != "done" or not task.result_file:
        raise _APIException(409, "结果尚未就绪或任务未成功")
    if not task.result_file.exists():
        raise _APIException(410, "结果文件已被清理, 请重新打包")
    return FileResponse(path=str(task.result_file), filename=task.result_name)
