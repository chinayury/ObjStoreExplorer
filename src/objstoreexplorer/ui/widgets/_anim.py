# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/widgets/_anim - 颜色插值与简易过渡动画

Tk 没有 CSS transition,这里手写一个 RGB 线性插值,
用于按钮 hover / sidebar 选中切换等场景。
"""
from __future__ import annotations
import tkinter as tk
from typing import Callable, Optional


# Tk 在某些 widget (尤其首次构造时) cget("background") 会返回命名颜色而非 hex。
# 这里给常见命名颜色建一张表,动画启动时把 current 归一化到 hex 再插值。
_NAMED_COLORS = {
    "white": "#FFFFFF",
    "black": "#000000",
    "red": "#FF0000",
    "green": "#008000",
    "blue": "#0000FF",
    "gray": "#808080",
    "grey": "#808080",
    "lightgray": "#D3D3D3",
    "lightgrey": "#D3D3D3",
    "darkgray": "#A9A9A9",
    "darkgrey": "#A9A9A9",
    "yellow": "#FFFF00",
    "cyan": "#00FFFF",
    "magenta": "#FF00FF",
    "pink": "#FFC0CB",
    "orange": "#FFA500",
    "purple": "#800080",
    "brown": "#A52A2A",
    # Tk 系统色 (Win/macOS/Linux 都有)
    # 注意: "systembuttonface" 之前被写了两遍 (同一 dict 里重复键),
    # 后一个只是覆盖前一个, 属于明显的复制粘贴残留。
    "systembuttonface": "#F0F0F0",
    "systemwindow": "#FFFFFF",
    "systemhighlight": "#0078D7",
    "systemmenu": "#F0F0F0",
    "systemmenutext": "#000000",
}


def _normalize_to_hex(c: str, fallback: str = "#000000") -> str:
    """把任意颜色字符串 (hex / 命名色 / 空格分隔 RGB) 归一化成 #RRGGBB"""
    if not c:
        return fallback
    c = c.strip().lower()
    if c.startswith("#"):
        return c
    if c in _NAMED_COLORS:
        return _NAMED_COLORS[c]
    # Tk 还有 "rgb N1 N2 N3" 形式 (百分数)
    parts = c.split()
    if len(parts) == 4 and parts[0] == "rgb":
        try:
            vals = [max(0, min(255, int(round(float(p) * 2.55)))) for p in parts[1:]]
            return f"#{vals[0]:02X}{vals[1]:02X}{vals[2]:02X}"
        except Exception:
            pass
    if len(parts) == 3:
        try:
            vals = [max(0, min(255, int(p))) for p in parts]
            return f"#{vals[0]:02X}{vals[1]:02X}{vals[2]:02X}"
        except Exception:
            pass
    return fallback


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"invalid hex color: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def lerp_color(c1: str, c2: str, t: float) -> str:
    """在 c1 ~ c2 之间按 t (0..1) 插值。命名色 / 异常值会安全降级。"""
    t = max(0.0, min(1.0, t))
    try:
        h1 = _normalize_to_hex(c1)
        h2 = _normalize_to_hex(c2)
        r1, g1, b1 = _hex_to_rgb(h1)
        r2, g2, b2 = _hex_to_rgb(h2)
    except Exception:
        # 极端异常: 直接返回 target 让动画立刻完成
        return _normalize_to_hex(c2)
    return _rgb_to_hex(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )


def animate_bg(
    widget: tk.Widget,
    target: str,
    duration_ms: int = 160,
    steps: int = 5,
    on_done: Optional[Callable[[], None]] = None,
) -> None:
    """把 widget 的 bg 从当前色平滑过渡到 target。

    - duration_ms < steps * 16 时会自动减帧
    - widget 销毁时 after 调度自动失效 (after_cancel 由 widget._anim_token 管理)
    - 与同一 widget 上的前一次动画自动互斥 (后启动的覆盖前者)
    """
    try:
        current_raw = widget.cget("background") or widget.cget("bg")
    except Exception:
        return
    target_hex = _normalize_to_hex(target)
    current = _normalize_to_hex(current_raw, fallback=target_hex)
    if not current or current == target_hex:
        try:
            widget.configure(bg=target_hex)
        except Exception:
            pass
        if on_done:
            on_done()
        return

    # 取消上一个动画
    prev = getattr(widget, "_anim_token", None)
    if prev:
        try:
            widget.after_cancel(prev)
        except Exception:
            pass

    interval = max(16, duration_ms // max(1, steps))
    state = {"i": 0}

    def step():
        state["i"] += 1
        t = state["i"] / steps
        try:
            widget.configure(bg=lerp_color(current, target_hex, t))
        except tk.TclError:
            # widget 已销毁
            return
        if state["i"] < steps:
            token = widget.after(interval, step)
            setattr(widget, "_anim_token", token)
        else:
            setattr(widget, "_anim_token", None)
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    token = widget.after(interval, step)
    setattr(widget, "_anim_token", token)


def cancel_animation(widget: tk.Widget) -> None:
    """主动取消 widget 上的进行中动画 (Destroy 钩子可调用)"""
    token = getattr(widget, "_anim_token", None)
    if token:
        try:
            widget.after_cancel(token)
        except Exception:
            pass
        setattr(widget, "_anim_token", None)
