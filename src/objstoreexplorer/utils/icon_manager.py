# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""图标管理 - base64 内嵌 logo.ico

解决 PyInstaller 打包后图标丢失问题。
运行时解码到临时文件,退出时清理。

进程内只创建一次临时 ico(双检锁),避免反复 mkstemp 泄露。
"""
from __future__ import annotations
import os
import sys
import base64
import tempfile
import atexit
import threading
from pathlib import Path
from typing import List, Optional, Set
import tkinter as tk


# 默认空图标 (1x1 透明) - 占位,实际部署时替换
DEFAULT_ICO_BASE64 = (
    "AAABAAEAEBAAAAEAIABoBAAAFgAAACgAAAAQAAAAIAAAAAEAIAAAAAAAQAQAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAA////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A"
    "////AP///wD///8A////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///8A////AP///wD///8A////"
    "AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8AAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD/"
    "////wD///8A////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///8A////AP//"
    "/wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8AAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAA////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD/"
    "///8A////AP///wD///8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD/"
    "////wD///8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)


# 优先从 resources/icons/ 加载真实图标
def _resolve_ico_path() -> Optional[Path]:
    """按优先级查找 logo.ico:
        1. PyInstaller 解包目录 (sys._MEIPASS) - 打包后运行时
        2. 项目根/resources/icons/logo.ico - 源码运行时 (utils/ 上两级)
        3. 当前工作目录/resources/icons/logo.ico - 兼容从别处启动
        4. 项目根/resources/logo.ico - 兼容旧版位置
        5. 项目根/logo.ico - 兼容旧版位置
    """
    candidates: List[Path] = []

    # 1) PyInstaller 解包目录
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "resources" / "icons" / "logo.ico")
        candidates.append(Path(meipass) / "resources" / "logo.ico")
        candidates.append(Path(meipass) / "logo.ico")

    # 2) 项目根 (utils/icon_manager.py -> 项目根 是上两级)
    project_root = Path(__file__).resolve().parent.parent
    candidates.append(project_root / "resources" / "icons" / "logo.ico")
    candidates.append(project_root / "resources" / "logo.ico")
    candidates.append(project_root / "logo.ico")

    # 3) CWD
    candidates.append(Path.cwd() / "resources" / "icons" / "logo.ico")
    candidates.append(Path.cwd() / "resources" / "logo.ico")
    candidates.append(Path.cwd() / "logo.ico")

    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _load_real_icon() -> Optional[bytes]:
    """从 resources/logo.ico (或项目根/logo.ico) 加载真实图标字节"""
    ico_path = _resolve_ico_path()
    if ico_path is None:
        return None
    try:
        with open(ico_path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _get_icon_bytes() -> bytes:
    """获取图标字节"""
    real = _load_real_icon()
    if real:
        return real
    # 占位图标
    return base64.b64decode(DEFAULT_ICO_BASE64)


# 临时文件管理
# 用 set 而非 list: 临时文件被外部清掉后会重建, list.append 会让同一个/已失效的
# 路径无限堆积 (退出时清理要遍历的项越来越多)。重建时把旧路径踢出集合。
_temp_icon_files: Set[str] = set()
_cached_icon_path: Optional[str] = None
_icon_cache_lock = threading.Lock()


def _cleanup_temp_icons() -> None:
    """程序退出时清理临时图标"""
    for path in _temp_icon_files:
        try:
            if path and os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass


# 注册清理
atexit.register(_cleanup_temp_icons)


def get_window_icon() -> Optional[str]:
    """获取临时图标文件路径 (进程内缓存,只创建一次)

    Returns:
        临时 ico 文件路径,失败返回 None
    """
    global _cached_icon_path
    # 快速路径: 已经创建过,直接返回
    if _cached_icon_path and os.path.exists(_cached_icon_path):
        return _cached_icon_path
    # 慢路径: 加锁后再次检查 (避免并发首次调用创建多个)
    with _icon_cache_lock:
        if _cached_icon_path and os.path.exists(_cached_icon_path):
            return _cached_icon_path
        try:
            ico_data = _get_icon_bytes()
            fd, path = tempfile.mkstemp(suffix=".ico")
            os.write(fd, ico_data)
            os.close(fd)
            # 旧的失效路径不再需要清理 (文件可能已被系统清掉), 移出集合
            if _cached_icon_path:
                _temp_icon_files.discard(_cached_icon_path)
            _temp_icon_files.add(path)
            _cached_icon_path = path
            return path
        except Exception:
            return None


def set_root_icon(window: tk.Tk) -> bool:
    """为 Tk 窗口设置图标

    Args:
        window: 根窗口

    Returns:
        是否成功
    """
    try:
        icon_path = get_window_icon()
        if icon_path:
            window.iconbitmap(icon_path)
            return True
    except Exception:
        pass
    return False
