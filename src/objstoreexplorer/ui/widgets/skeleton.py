# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/skeleton - 加载骨架屏

灰色块 + after() 漂移动画,在数据加载时占位,体验比静态 "..." 强。

用法:
    s = SkeletonRow(parent, width=200, height=14)
    s.pack(pady=4)
    # 数据返回后:
    s.destroy()
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional

from ..styles import Neutral
from ..widgets._anim import lerp_color


# 呼吸动画的两个端点色 (收敛到 styles.py 的板岩灰阶, 不再硬编码)
_PULSE_FROM = Neutral.BG_SUBTLE
_PULSE_TO = Neutral.DIVIDER
_PULSE_COLORS = (_PULSE_FROM, _PULSE_TO, _PULSE_FROM)


class SkeletonRow(tk.Frame):
    """单行骨架,带呼吸动画

    动画间隔 100ms (原来 40ms): 4 张卡 = 每次 40ms 触发一轮 → 持续
    100Hz 以上的 configure 重绘, CPU 占用可观且没有任何视觉收益。
    骨架本来就是"看不清细节"的占位, 慢一点反而更自然。
    """

    TICK_MS = 100

    def __init__(
        self,
        parent: tk.Misc,
        width: int = 200,
        height: int = 14,
        **kw,
    ):
        super().__init__(parent, bg=parent.cget("bg") if hasattr(parent, "cget") else Neutral.BG_PANEL, **kw)
        self._block = tk.Frame(
            self, width=width, height=height,
            bg=Neutral.BG_SUBTLE,
            highlightthickness=0, bd=0,
        )
        self._block.pack()
        self._block.pack_propagate(False)

        self._t = 0
        self._steps = 30
        self._dir = 1
        self._after_token: Optional[str] = None
        self.bind("<Destroy>", self._cancel)
        self._tick()

    def _tick(self):
        self._t += self._dir
        if self._t >= self._steps:
            self._dir = -1
        elif self._t <= 0:
            self._dir = 1
        ratio = self._t / self._steps
        color = lerp_color(_PULSE_COLORS[0], _PULSE_COLORS[1], ratio)
        try:
            self._block.configure(bg=color)
        except tk.TclError:
            return
        self._after_token = self.after(self.TICK_MS, self._tick)

    def _cancel(self, _e=None):
        if self._after_token:
            try:
                self.after_cancel(self._after_token)
            except Exception:
                pass
            self._after_token = None
