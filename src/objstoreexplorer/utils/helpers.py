# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""utils/helpers - 通用工具函数

历史说明: sanitize_filename 之前在这也有个简陋版,与 core/validators 重复,
且不带长名截断,统一收敛到 core/validators.sanitize_filename。
"""
from __future__ import annotations
import re
from datetime import datetime


def format_bytes(size: int) -> str:
    """格式化字节数为可读字符串

    Examples:
        1024 -> "1.00 KB"
        1048576 -> "1.00 MB"
    """
    if size < 0:
        return "-"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.2f} MB"
    if size < 1024 * 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024 / 1024:.2f} GB"
    return f"{size / 1024 / 1024 / 1024 / 1024:.2f} TB"


def format_timestamp(ts) -> str:
    """格式化时间戳为 YYYY-MM-DD HH:MM:SS

    无法解析的字符串返回 "-": 之前原样返回该串, 列表里会出现一整条
    不可读的原始值, 看起来像"没格式化成功但没人管"。
    """
    if ts is None:
        return "-"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return "-"
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return str(ts)


def truncate_path(path: str, max_len: int = 50) -> str:
    """截断过长的路径 (中段省略, 保留首段与尾部目录)"""
    if len(path) <= max_len:
        return path
    # Windows 路径分隔符是 \, 只按 "/" 切会得到长度 1 的列表,
    # 于是退化成字符级硬砍 (C:\a\b\c -> C:\a\bbb...)。两种分隔符都要认。
    parts = [p for p in re.split(r"[/\\]", path) if p]
    if len(parts) <= 2:
        return path[:max_len - 3] + "..."

    result = parts[0] + "/..."
    # 正序追加。旧代码写的是 `reversed(parts[1:])`, 于是路径段是倒着拼的:
    # C:/home/user/data 会显示成 C:/.../data/user/home —— 层级完全颠倒,
    # 用户根本认不出那是哪个目录。
    for part in parts[1:]:
        test = result + "/" + part
        if len(test) > max_len:
            break
        result = test
    return result
