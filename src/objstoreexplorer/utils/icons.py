# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""utils/icons - 图标加载/缓存层

设计:
    - 加载 resources/icons/<name>@<size>.png 为 PIL.ImageTk.PhotoImage
    - 进程级缓存 (name, size) -> PhotoImage,引用与进程同生命周期
    - 缺图返回 None + 一次性 log warning,调用方降级到 emoji/文字
    - 不抛异常 (UI 健壮性优先)

为什么用 PIL.ImageTk 而不是 tk.PhotoImage:
    - Pillow 已是项目依赖 (requirements.txt 声明)
    - PIL 支持更多 PNG 编码方式 / 透明通道
    - 后续可加 tint 着色 (hover/active 蓝/红变体)
"""
from __future__ import annotations
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Tuple, Set, Union

from PIL import Image

logger = logging.getLogger(__name__)


_ICON_DIR: Optional[Path] = None


def _icon_dir() -> Path:
    """resources/icons 目录路径"""
    global _ICON_DIR
    if _ICON_DIR is not None:
        return _ICON_DIR
    # 优先 PyInstaller 解包目录: 打包后 datas 把图标落位 _MEIPASS/resources/icons
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        _ICON_DIR = Path(meipass) / "resources" / "icons"
        return _ICON_DIR
    # 开发模式: utils/icons.py -> 包内 resources/icons (utils 的上一级即包根)
    here = Path(__file__).resolve().parent
    _ICON_DIR = here.parent / "resources" / "icons"
    return _ICON_DIR


class IconRegistry:
    """进程级图标缓存

    用法:
        from .icons import get
        img = get("upload", 16)
        if img:
            btn.configure(image=img, compound="left")

    ⚠ PhotoImage 绑定到**创建它的那个 Tk 解释器**。测试或嵌入场景里
    同一个进程可能先后创建多个 tk.Tk() (前一个已 destroy), 此时旧的
    PhotoImage 会变成 "pyimage1 doesn't exist"。所以缓存必须按解释器
    隔离 —— 检测到解释器换了就整体清空。
    """

    _cache: Dict[Tuple[str, int, object], object] = {}
    # key -> 重试到期时刻 (monotonic)。缺图带 TTL, 资源后解压出来能自动恢复,
    # 之前是永久写死, 首次调用撞上"资源还没就位"就整个运行期都降级。
    _missing: Dict[Tuple[str, int, object], float] = {}
    _warned: Set[Tuple[str, int, object]] = set()
    _tk_inited: bool = False
    _interp: object = None

    # 缓存容量上限: 侧栏 hover/选中会按 tint 生成 (name,size,tint) 组合,
    # 基数随调用方传的动态颜色无界增长, 必须限量。
    _CACHE_MAX: int = 512
    # 缺图重试冷却 (秒)
    _MISSING_TTL: float = 60.0

    @classmethod
    def _evict(cls) -> None:
        """超出容量时丢最早的一批 (dict/set 按插入序迭代)。

        丢掉的 PhotoImage 会在下次 get() 时重建, 代价只是多一次磁盘读。
        """
        while len(cls._cache) > cls._CACHE_MAX:
            cls._cache.pop(next(iter(cls._cache)), None)
        while len(cls._missing) > cls._CACHE_MAX:
            cls._missing.pop(next(iter(cls._missing)), None)
        while len(cls._warned) > cls._CACHE_MAX:
            cls._warned.discard(next(iter(cls._warned)))

    @classmethod
    def _sync_interpreter(cls) -> None:
        """检测 Tk 解释器是否换了; 换了就丢弃全部缓存"""
        import tkinter as _tk
        interp = getattr(_tk, "_default_root", None)
        if interp is not cls._interp:
            cls._cache.clear()
            cls._missing.clear()
            cls._interp = interp

    @classmethod
    def get(
        cls,
        name: str,
        size: int = 16,
        tint: Optional[Union[str, Tuple[int, int, int]]] = None,
    ):
        """加载图标,返回 PhotoImage 或 None。

        Args:
            name: 图标名 (kebab-case,如 "trash-2", "folder-plus")
            size: 像素尺寸 (推荐 16 或 24)
            tint: 可选颜色 ('#RRGGBB' / 'white' / (r,g,b))。
                  仅对带 alpha 通道的源图生效:把所有不透明像素的 RGB
                  替换为目标色,保留 alpha 蒙版,适合深色背景上的图标
                  重新着色。默认 None 保持原色。
        """
        if not name:
            return None
        cls._sync_interpreter()
        # ⚠ tint 必须进 key: 同一图标不同颜色是不同 PhotoImage,
        #   否则侧栏 hover/选中换色会拿到首次缓存的那个颜色。
        key = (name, size, tint if tint is None else str(tint))
        cached = cls._cache.get(key)
        if cached is not None:
            return cached
        # 缺图只在 TTL 内直接降级; 冷却期过允许重试 (资源可能刚解压完)
        retry_at = cls._missing.get(key)
        if retry_at is not None:
            if time.monotonic() < retry_at:
                return None
            cls._missing.pop(key, None)

        path = cls._resolve_path(name, size)
        if path is None or not path.exists():
            cls._missing[key] = time.monotonic() + cls._MISSING_TTL
            cls._evict()
            if key not in cls._warned:
                cls._warned.add(key)
                logger.warning("Icon not found: %s@%d (looked under %s)", name, size, _icon_dir())
            return None

        try:
            from PIL import ImageTk
            # with: Image.open 只在首次 load 时读文件句柄, 不关的话 Windows 上
            # 会一直占着文件, 资源更新/覆盖时容易踩到 PermissionError。
            with Image.open(str(path)) as im:
                img = im.copy()
            if img.size != (size, size):
                img = img.resize((size, size), Image.LANCZOS)
            if tint is not None:
                img = _apply_tint(img, tint)
            photo = ImageTk.PhotoImage(img)
            cls._cache[key] = photo
            cls._evict()
            return photo
        except Exception as e:
            cls._missing[key] = time.monotonic() + cls._MISSING_TTL
            cls._evict()
            if key not in cls._warned:
                cls._warned.add(key)
                logger.warning("Failed loading icon %s@%d: %s", name, size, e)
            return None

    @classmethod
    def _resolve_path(cls, name: str, size: int) -> Optional[Path]:
        """按优先级解析图标文件路径:
        1. resources/icons/<name>@<size>.png  (推荐)
        2. resources/icons/<name>.png         (单尺寸兜底)
        """
        d = _icon_dir()
        sized = d / f"{name}@{size}.png"
        if sized.exists():
            return sized
        fallback = d / f"{name}.png"
        if fallback.exists():
            return fallback
        return None

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()
        cls._missing.clear()
        cls._warned.clear()
        cls._interp = None

    @classmethod
    def missing(cls) -> list:
        """返回所有运行期间记录到的缺图 (调试用)"""
        return sorted(f"{n}@{s}" for n, s, _tint in cls._missing)


def _apply_tint(img, tint: Union[str, Tuple[int, int, int]]):
    """对图标按 alpha 蒙版重新着色。

    只替换不透明像素的 RGB, 透明像素保持透明; 接收 'white' / '#RRGGBB' /
    (r, g, b) 三种形式。

    非 RGBA 源图 (P 调色板 / L 灰度 / RGB 无 alpha) 统一先转 RGBA 再着色:
    之前直接原样返回, tint 被静默忽略, 侧栏 hover 换色看起来"没生效"。
    """
    rgb = _parse_color(tint)
    if rgb is None:
        return img
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    _r, _g, _b, alpha = img.split()
    solid = Image.new("RGBA", img.size, rgb + (255,))
    solid.putalpha(alpha)
    return solid


# 极简颜色解析,只支持 "#RRGGBB" / "#RGB" / 命名色 / (r,g,b) 元组,
# 不引入整个 PIL.ImageColor 以保持轻量。
_NAMED_COLORS = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
}


def _parse_color(c):
    if isinstance(c, tuple) and len(c) == 3:
        return tuple(max(0, min(255, int(v))) for v in c)
    if isinstance(c, str):
        if c in _NAMED_COLORS:
            return _NAMED_COLORS[c]
        s = c.strip()
        if s.startswith("#"):
            s = s[1:]
            if len(s) == 3:
                s = "".join(ch * 2 for ch in s)
            if len(s) == 6:
                try:
                    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
                except ValueError:
                    return None
    return None


# ==================== 顶层便利函数 ====================

def get(name: str, size: int = 16, tint=None):
    """加载图标 (顶层快捷方式)"""
    return IconRegistry.get(name, size, tint=tint)


def missing() -> list:
    return IconRegistry.missing()
