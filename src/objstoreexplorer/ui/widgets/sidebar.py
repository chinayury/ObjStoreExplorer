# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/sidebar — 暮橙 Emberline 侧边栏菜单项

走浅底方案:
    - 常态: 透明底 + 二级板岩文字 + 冷灰图标
    - hover: BG_HOVER 浅底
    - 选中: PRIMARY_50 陶土橙浅底 + PRIMARY_800 文字 + 3px 陶土橙左指示条
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional, Callable

from ..styles import Brand, Neutral, Space, Surface, UIFont
from ..widgets._anim import animate_bg, cancel_animation
from ...utils.icons import get as get_icon


def _self_label(item: "SidebarItem") -> str:
    """取菜单项文案 (异常日志用)"""
    try:
        return str(item._label)
    except Exception:
        return "?"


class SidebarItem(tk.Frame):
    """单条侧边栏菜单项"""

    HEIGHT = 36
    def __init__(
        self,
        parent: tk.Misc,
        label: str,
        icon: Optional[str] = None,
        emoji_fallback: str = "",
        on_click: Optional[Callable] = None,
        bg_idle: str = Neutral.BG_PANEL,
        bg_hover: str = Neutral.BG_HOVER,
        bg_active: str = Brand.PRIMARY_50,
        fg_idle: str = Neutral.TEXT_2,
        fg_active: str = Brand.PRIMARY_800,
        **kw,
    ):
        super().__init__(parent, bg=bg_idle, cursor="hand2", **kw)
        self._bg_idle = bg_idle
        self._bg_hover = bg_hover
        self._bg_active = bg_active
        self._fg_idle = fg_idle
        self._fg_active = fg_active
        self._icon_tint_idle = Neutral.TEXT_3
        self._icon_tint_active = Brand.PRIMARY
        self._on_click = on_click
        self._selected = False
        self._icon_name = icon
        self._label = label

        # 3px 陶土橙左指示条 (选中时显示)
        self._indicator = tk.Frame(self, bg=Brand.PRIMARY, width=Surface.ACCENT_W)

        content = tk.Frame(self, bg=bg_idle)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                     padx=(Space.MD, Space.SM), pady=Space.XS + 1)
        self._content = content

        # 图标 (线性 PNG, 缺图才回退到文字符号)
        self._icon_lbl = None
        if icon:
            img = get_icon(icon, 16, tint=self._icon_tint_idle)
            if img is not None:
                self._icon_lbl = tk.Label(content, image=img, bg=bg_idle)
                self._icon_lbl.image = img
                self._icon_lbl.pack(side=tk.LEFT, padx=(0, Space.SM))
            elif emoji_fallback:
                self._icon_lbl = tk.Label(
                    content, text=emoji_fallback, font=("Segoe UI Symbol", 11),
                    bg=bg_idle, fg=fg_idle,
                )
                self._icon_lbl.pack(side=tk.LEFT, padx=(0, Space.SM))
        elif emoji_fallback:
            self._icon_lbl = tk.Label(
                content, text=emoji_fallback, font=("Segoe UI Symbol", 11),
                bg=bg_idle, fg=fg_idle,
            )
            self._icon_lbl.pack(side=tk.LEFT, padx=(0, Space.SM))

        self._text_lbl = tk.Label(
            content, text=label, font=UIFont.body(),
            bg=bg_idle, fg=fg_idle, anchor=tk.W,
        )
        self._text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        targets = [self, content, self._text_lbl]
        for w in targets:
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._fire_click)
        if self._icon_lbl is not None:
            self._icon_lbl.bind("<Enter>", self._on_enter)
            self._icon_lbl.bind("<Leave>", self._on_leave)
            self._icon_lbl.bind("<Button-1>", self._fire_click)

        self.bind("<Destroy>", lambda _e: cancel_animation(self))

    # ---------------- 配色同步 ----------------

    def _set_bg(self, color: str) -> None:
        try:
            self.configure(bg=color)
            self._content.configure(bg=color)
            self._text_lbl.configure(bg=color)
            if self._icon_lbl is not None:
                self._icon_lbl.configure(bg=color)
        except Exception:
            pass

    def _set_icon(self, icon_name: Optional[str], tint: str) -> None:
        if not icon_name or self._icon_lbl is None:
            return
        img = get_icon(icon_name, 16, tint=tint)
        if img is not None:
            self._icon_lbl.configure(image=img)
            self._icon_lbl.image = img

    # ---------------- 事件 ----------------

    def _on_enter(self, _e=None):
        if self._selected:
            return
        # ⚠ 先同步子控件底色再动画: 旧版只让 animate_bg 改**自己**的 bg,
        #   子控件 (content/文字/图标) 要等 on_done 才同步 —— 110ms 内
        #   父底色已变而子控件还是旧色, 出现一块可见的异色矩形。
        self._set_bg(self._bg_hover)
        animate_bg(self, self._bg_hover, duration_ms=110, steps=4)

    def _on_leave(self, _e=None):
        if self._selected:
            return
        self._set_bg(self._bg_idle)
        animate_bg(self, self._bg_idle, duration_ms=110, steps=4)

    def _fire_click(self, _e=None):
        if self._on_click:
            try:
                self._on_click()
            except tk.TclError:
                # 控件已销毁 (切页/退出时) —— 静默即可
                pass
            except Exception as e:
                # ⚠ 旧版所有异常都 pass 掉: 页面切换出错时侧栏"点了没反应",
                #   控制台也无从查起。至少留一条可检索的痕迹。
                print(f"[sidebar] 菜单项 {_self_label(self)} 点击失败: {e}")

    def set_selected(self, selected: bool) -> None:
        """主窗口侧控制选中态"""
        self._selected = selected
        if selected:
            if not self._indicator.winfo_ismapped():
                self._indicator.pack(side=tk.LEFT, fill=tk.Y,
                                     before=self._content)
            self._set_bg(self._bg_active)
            self._text_lbl.configure(fg=self._fg_active)
            self._set_icon(self._icon_name, self._icon_tint_active)
        else:
            self._indicator.pack_forget()
            self._set_bg(self._bg_idle)
            self._text_lbl.configure(fg=self._fg_idle)
            self._set_icon(self._icon_name, self._icon_tint_idle)
