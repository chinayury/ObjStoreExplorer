# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""按钮组件工厂 —「暮橙 Emberline」

Tk 原生 Button 描边是"内嵌/浮雕"观感, 这里统一走 flat + 1px 冷灰描边,
hover 用 120ms 背景色过渡。几何圆角由 Surface.BTN_RADIUS (6) 表达
(Tk 原生 Button 不支持圆角, 以 token 声明 + 锐利直角呈现)。
"""
from __future__ import annotations
import tkinter as tk
from typing import Callable, Optional

from ..styles import Brand, Neutral, Status, Space, UIFont
from ..widgets._anim import animate_bg, cancel_animation
from ...utils.icons import get as get_icon


def _bind_hover(btn: tk.Widget, bg_idle: str, bg_hover: str,
                duration: int = 120) -> None:
    """统一 hover/leave 颜色过渡 (禁用态不高亮)"""
    def _animate(target: str) -> None:
        try:
            if str(btn.cget("state")) == tk.DISABLED:
                return
        except tk.TclError:
            return
        animate_bg(btn, target, duration_ms=duration, steps=4)

    btn.bind("<Enter>", lambda _e: _animate(bg_hover))
    btn.bind("<Leave>", lambda _e: _animate(bg_idle))
    btn.bind("<Destroy>", lambda _e: cancel_animation(btn))


def _icon_for(icon: Optional[str], tint: str) -> Optional[object]:
    return get_icon(icon, 16, tint=tint) if icon else None


def _apply_width(btn: tk.Button, width: Optional[int],
                 has_image: bool = False) -> None:
    """把 width 传给 tk.Button —— 仅限**没有图标**的按钮。

    旧版 5 个工厂函数全都声明了 width 参数却从不使用 (10+ 处调用方传了
    width=10/12/14), 结果对话框底部"取消"和"创建"宽度差一大截, 参差不齐。

    ⚠⚠ 但它**不能**用在带图标的按钮上 —— tk.Button 的 -width 是双语义:

        没有 -image : -width = 文本区宽度, 单位是**字体字符宽**
                      (本项目 UIFont.body 的字符宽 = 8px, 所以 width=12 → 96px)

        有   -image : -width = **图片区宽度, 单位是像素**, 跟字符数毫无关系

    工厂默认 width=12 而图标是 16px, 于是每个带图标的按钮图标都被裁掉 4px
    (顶栏"连接/断开/刷新/一键创建/反馈"五个全中, 共 45 处、16 个文件)。
    表现是「按钮上的图标看不全」, 而且很容易被当成图标本身画歪了。

    实测 (同一个图标 + 同一个文字, Microsoft YaHei UI 10pt, 字符宽 8px):

        带图标:  width=None → 90px 图标完整
                 width=12   → 44px 图标被裁 4px   ← 当前的 bug
                 width=8    → 40px 图标被裁 8px
                 width=16   → 48px 图标完整(但比自然宽度还窄, 挤)
        不带图标: width=None → 62px 自然宽度
                  width=12  → 130px (文本区 96px)  ← 正是"等宽对话框按钮"要的效果

    所以: 带图标的按钮**按内容自适应**(等于 width=None), 等宽需求只由
    纯文字按钮承担。Tk 没有"带图标时让文本区等于 N 字符"的表达方式。
    """
    if width is None or width <= 0:
        return
    if has_image:
        return          # 见上方说明: 带图标时 width 会被当成图片像素宽, 会裁图标
    try:
        btn.configure(width=width)
    except tk.TclError:
        pass


def _bind_disabled_style(
    btn: tk.Button,
    bg_disabled: str = Neutral.BG_SUBTLE,
    fg_disabled: str = Neutral.TEXT_3,
) -> None:
    """禁用态外观: 旧版 disable 后底色/字色完全不变, 看起来仍可点"""
    try:
        btn.configure(
            disabledbackground=bg_disabled,
            disabledforeground=fg_disabled,
        )
    except tk.TclError:
        pass


def create_primary_button(
    parent: tk.Misc,
    text: str,
    command: Optional[Callable] = None,
    width: int = 12,
    icon: Optional[str] = None,
) -> tk.Button:
    """主操作按钮 (陶土橙填充)"""
    img = _icon_for(icon, Neutral.TEXT_INV)
    btn = tk.Button(
        parent, text=text, command=command,
        image=img, compound=tk.LEFT if img is not None else tk.NONE,
        font=UIFont.body(),
        bg=Brand.PRIMARY, fg=Neutral.TEXT_INV,
        activebackground=Brand.PRIMARY_700, activeforeground=Neutral.TEXT_INV,
        relief="flat", cursor="hand2", bd=0,
        highlightthickness=0,
        padx=Space.LG, pady=Space.XS + 2,
    )
    if img is not None:
        btn.image = img
    _apply_width(btn, width, has_image=img is not None)
    _bind_disabled_style(btn, Brand.PRIMARY_50, Brand.PRIMARY_300)
    _bind_hover(btn, Brand.PRIMARY, Brand.PRIMARY_600)
    return btn


def create_secondary_button(
    parent: tk.Misc,
    text: str,
    command: Optional[Callable] = None,
    width: int = 12,
    icon: Optional[str] = None,
) -> tk.Button:
    """次要按钮 (白底 + 暖色描边, hover 转陶土橙浅底)"""
    img = _icon_for(icon, Neutral.TEXT_2)
    btn = tk.Button(
        parent, text=text, command=command,
        image=img, compound=tk.LEFT if img is not None else tk.NONE,
        font=UIFont.body(),
        bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
        activebackground=Brand.PRIMARY_50, activeforeground=Brand.PRIMARY_800,
        relief="flat", cursor="hand2", bd=0,
        highlightbackground=Neutral.BORDER_HI, highlightthickness=1,
        padx=Space.LG, pady=Space.XS + 1,
    )
    if img is not None:
        btn.image = img
    _apply_width(btn, width, has_image=img is not None)
    _bind_disabled_style(btn)
    _bind_hover(btn, Neutral.BG_PANEL, Brand.PRIMARY_50)
    return btn


def create_ghost_button(
    parent: tk.Misc,
    text: str,
    command: Optional[Callable] = None,
    width: int = 12,
    icon: Optional[str] = None,
) -> tk.Button:
    """幽灵按钮 (无描边, 仅文字, hover 浅底)"""
    img = _icon_for(icon, Neutral.TEXT_2)
    btn = tk.Button(
        parent, text=text, command=command,
        image=img, compound=tk.LEFT if img is not None else tk.NONE,
        font=UIFont.body(),
        bg=Neutral.BG_APP, fg=Neutral.TEXT_2,
        activebackground=Neutral.BG_HOVER, activeforeground=Neutral.TEXT_1,
        relief="flat", cursor="hand2", bd=0, highlightthickness=0,
        padx=Space.MD, pady=Space.XS + 1,
    )
    if img is not None:
        btn.image = img
    _apply_width(btn, width, has_image=img is not None)
    _bind_disabled_style(btn, Neutral.BG_APP, Neutral.TEXT_3)
    _bind_hover(btn, Neutral.BG_APP, Neutral.BG_HOVER)
    return btn


def create_danger_button(
    parent: tk.Misc,
    text: str,
    command: Optional[Callable] = None,
    width: int = 10,
    icon: Optional[str] = None,
) -> tk.Button:
    """危险按钮 (红填充)"""
    img = _icon_for(icon, Neutral.TEXT_INV)
    btn = tk.Button(
        parent, text=text, command=command,
        image=img, compound=tk.LEFT if img is not None else tk.NONE,
        font=UIFont.body(),
        bg=Status.DANGER, fg=Neutral.TEXT_INV,
        activebackground=Status.DANGER_HOVER,
        activeforeground=Neutral.TEXT_INV,
        relief="flat", cursor="hand2", bd=0, highlightthickness=0,
        padx=Space.LG, pady=Space.XS + 2,
    )
    if img is not None:
        btn.image = img
    _apply_width(btn, width, has_image=img is not None)
    _bind_disabled_style(btn, Status.DANGER_BG, Status.DANGER_FG)
    _bind_hover(btn, Status.DANGER, Status.DANGER_HOVER)
    return btn


def create_danger_ghost_button(
    parent: tk.Misc,
    text: str,
    command: Optional[Callable] = None,
    width: int = 10,
    icon: Optional[str] = None,
) -> tk.Button:
    """危险幽灵按钮 (仅红色文字, hover 浅红底)"""
    img = _icon_for(icon, Status.DANGER)
    btn = tk.Button(
        parent, text=text, command=command,
        image=img, compound=tk.LEFT if img is not None else tk.NONE,
        font=UIFont.body(),
        bg=Neutral.BG_PANEL, fg=Status.DANGER,
        activebackground=Status.DANGER_BG, activeforeground=Status.DANGER_FG,
        relief="flat", cursor="hand2", bd=0, highlightthickness=0,
        padx=Space.MD, pady=Space.XS + 1,
    )
    if img is not None:
        btn.image = img
    _apply_width(btn, width, has_image=img is not None)
    _bind_disabled_style(btn)
    _bind_hover(btn, Neutral.BG_PANEL, Status.DANGER_BG)
    return btn


def create_success_button(
    parent: tk.Misc,
    text: str,
    command: Optional[Callable] = None,
    icon: Optional[str] = None,
) -> tk.Button:
    """成功按钮 (绿填充)"""
    img = _icon_for(icon, Neutral.TEXT_INV)
    btn = tk.Button(
        parent, text=text, command=command,
        image=img, compound=tk.LEFT if img is not None else tk.NONE,
        font=UIFont.body(),
        bg=Status.SUCCESS, fg=Neutral.TEXT_INV,
        activebackground=Status.SUCCESS_HOVER, activeforeground=Neutral.TEXT_INV,
        relief="flat", cursor="hand2", bd=0, highlightthickness=0,
        padx=Space.LG, pady=Space.XS + 2,
    )
    if img is not None:
        btn.image = img
    _bind_hover(btn, Status.SUCCESS, Status.SUCCESS_HOVER)
    return btn
