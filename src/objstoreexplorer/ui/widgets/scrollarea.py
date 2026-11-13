# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/widgets/scrollarea — Canvas 滚轮绑定的安全封装

背景 (修复「关闭子对话框后滚轮必崩」):
    老代码到处用 `canvas.bind_all("<MouseWheel>", ..., add="+")`。
    `bind_all` 挂的是**应用级** bindtag `all`, 生命周期跟整个进程走:
      1. 任何鼠标位置滚动, 都会触发所有历史绑定;
      2. 用 `add="+"` 叠加后, 关闭任一对话框都不会解绑;
      3. 残留 handler 仍引用已销毁的 canvas -> 下一��滚轮事件直接
         `TclError: invalid command name ".!toplevel2.toplevel2.frame.canvas"`。

正确做法: 绑到**具体控件**上。Tk 在控件销毁时自动清掉它的绑定,
不会留悬空引用。Windows 上滚轮事件发给光标下的控件, 所以要同时绑
canvas 和 canvas 内嵌的可滚动内容容器。

注意: 只绑直接子控件不够 —— 容器里再嵌一层 (Label 列表、Card、表单)
时, 光标落在孙控件上滚轮就失效。本模块用 bindtags 把 handler 挂到
后代控件上, 但**不递归拷贝子控件** (后者会让每次重排都重复叠加绑定)。
"""
from __future__ import annotations
import tkinter as tk
from typing import List, Optional


def _make_handler(canvas: tk.Canvas, step: int):
    """生成带存活校验的滚轮 handler。"""
    def _on_wheel(event) -> str:
        # canvas 可能已被销毁 (对话框关闭后事件仍可能投递过来)
        try:
            if not canvas.winfo_exists():
                return "break"
            delta = getattr(event, "delta", 0)
            if not delta:
                return "break"
            # 触控板会给出很小的 delta, 累积到 120 再翻一格, 手感更跟手
            if abs(delta) < 120:
                canvas.yview_scroll(-1 if delta > 0 else 1, "units")
            else:
                canvas.yview_scroll(int(-step * (delta / 120)), "units")
        except tk.TclError:
            return "break"
        return "break"
    return _on_wheel


def bind_mousewheel(
    canvas: tk.Canvas,
    *also_on: Optional[tk.Misc],
    step: int = 3,
    recursive: bool = True,
) -> None:
    """给 Canvas + 其内嵌内容绑定滚轮 (替代危险的 bind_all)。

    Args:
        canvas:    目标 Canvas
        also_on:   还需要绑定的控件 (通常是 create_window 进去的 Frame)
        step:      每格滚动单位数
        recursive: 是否递归到所有后代控件。容器里全是 Label 时必须开,
                   否则光标停在 Label 上滚轮完全没反应。
    """
    handler = _make_handler(canvas, step)
    targets = [canvas, *[x for x in also_on if x is not None]]

    if recursive:
        for root in targets:
            targets.extend(_descendants(root))

    for w in targets:
        try:
            # 不用 add="+": 重复调用 bind_mousewheel 会把同一个 handler
            # 在同一控件上叠加多份, 一次滚轮滚 3 格的步长 —— 越滚越快。
            w.bind("<MouseWheel>", handler)
            # Linux / macOS(X11) 的滚轮事件名不同, 一并绑上
            w.bind("<Button-4>", lambda e: _on_wheel_by(e, canvas, step))
            w.bind("<Button-5>", lambda e: _on_wheel_by(e, canvas, -step))
        except tk.TclError:
            continue


def _descendants(widget: tk.Misc) -> List[tk.Misc]:
    """广度优先收集全部后代控件 (含自己), 供滚轮绑定使用"""
    out: List[tk.Misc] = []
    queue_: List[tk.Misc] = [widget]
    while queue_:
        cur = queue_.pop(0)
        try:
            kids = cur.winfo_children()
        except tk.TclError:
            continue
        for k in kids:
            out.append(k)
            queue_.append(k)
    return out


def _on_wheel_by(event, canvas: tk.Canvas, amount: int) -> str:
    try:
        if canvas.winfo_exists():
            canvas.yview_scroll(amount, "units")
    except tk.TclError:
        pass
    return "break"


def unbind_mousewheel(*widgets: Optional[tk.Misc]) -> None:
    """手动解绑 (一般不需要 —— 控件销毁时 Tk 会自动清理)。"""
    for w in widgets:
        if w is None:
            continue
        try:
            w.unbind("<MouseWheel>")
            w.unbind("<Button-4>")
            w.unbind("<Button-5>")
        except tk.TclError:
            continue
