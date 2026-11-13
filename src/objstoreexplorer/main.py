# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""程序入口 - ObjStoreExplorer v0.1

启动流程:
    1. 创建 Tk 根窗口
    2. 初始化服务容器
    3. 加载主窗口
    4. 进入事件循环
"""
import sys
import tkinter as tk
import threading
import traceback
from tkinter import messagebox

from .config.settings import (
    APP_DISPLAY_NAME,
    WINDOW_DEFAULT_SIZE,
    WINDOW_MIN_SIZE,
)
from .services.service_locator import ServiceLocator
from .utils.icon_manager import set_root_icon


def install_callback_error_dialog(root: tk.Tk) -> None:
    """UI 回调异常弹窗可见化 ().

    打包后的 exe 没有控制台, 事件回调里的异常原本静默死掉 —— 用户视角
    就是 "点了没反应" (反馈按钮缺 yaml 一案即如此)。
    装上本处理器后, 任何回调异常都会弹窗展示 (用户可截图反馈)。
    """
    def _on_callback_exception(exc_type, exc_value, exc_tb):
        try:
            detail = "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)
            )
            messagebox.showerror(
                "程序内部错误",
                "发生了一个未处理的错误, 请截图通过 \"反馈\" 提交:\n\n"
                + (detail if len(detail) <= 1500 else detail[:1500] + " ...(已截断)"),
            )
        except Exception:
            pass

    root.report_callback_exception = _on_callback_exception


def install_thread_hooks() -> None:
    """给非 Tk 回调路径装兜底 (打包后无控制台, 否则完全静默)

    两类"点了没反应"的来源都靠这里变可见:

    - `threading.excepthook`: 全项目有 8 处 `threading.Thread(..., daemon=True)`
      (上传/下载/删除/建用户/提交反馈/连接...), 线程里抛异常线程直接死掉,
      UI 永远停在"处理中"。旧代码没装这个钩子, 用户只看到界面卡住。
    - `sys.excepthook`: 非 Tk 回调路径的主线程未捕获异常。

    注意 report_callback_exception 只兜 Tk 事件循环, 替代不了这两个。
    """
    def _on_thread_exc(args):
        detail = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        line = (f"[thread] {getattr(args.thread, 'name', '?')} 未捕获异常:\n{detail}")
        print(line, file=sys.stderr)
        _try_notify("后台任务异常", line)

    def _on_sys_exc(exc_type, exc_value, exc_tb):
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        line = f"[main] 未捕获异常:\n{detail}"
        print(line, file=sys.stderr)
        _try_notify("程序内部错误", line)

    threading.excepthook = _on_thread_exc
    sys.excepthook = _on_sys_exc


def _try_notify(title: str, detail: str) -> None:
    """尽可能弹窗告知; 没有 Tk 环境时只落 stderr (不能在这里再抛)"""
    try:
        if detail and len(detail) > 1500:
            detail = detail[:1500] + " ...(已截断)"
        messagebox.showerror(title, "请截图通过 \"反馈\" 提交:\n\n" + detail)
    except Exception:
        pass


def main() -> int:
    """应用主入口

    Returns:
        退出码
    """
    install_thread_hooks()

    # 建运行期目录。⚠ 以前这一步藏在 config/settings.py 的模块级 for 循环里,
    #   意味着"import 任意模块就会碰文件系统"; 装到只读目录 (Program Files)
    #   时 import 期就 PermissionError, 早于任何 try/except, 用户只看到
    #   "双击图标没反应"。现在改成显式调用, 失败会被下面的 try 捕获并弹窗。
    try:
        from .config.settings import ensure_dirs
        ensure_dirs()
    except OSError as e:
        print(f"[fatal] 无法创建数据目录: {e}", file=sys.stderr)
        messagebox.showerror(
            "启动失败",
            f"无法创建数据目录。\n\n"
            f"请把程序放到有写入权限的位置 (例如 D:\\Tools), 或设置环境变量 "
            f"OSE_DATA_DIR 指向一个可写目录。\n\n技术细节: {e}",
        )
        return 1

    # 创建根窗口
    root = tk.Tk()
    root.title(APP_DISPLAY_NAME)
    root.geometry(WINDOW_DEFAULT_SIZE)
    root.minsize(*WINDOW_MIN_SIZE)

    # 设置窗口图标
    set_root_icon(root)

    # UI 回调异常弹窗可见化 (, 修 "点了没反应" 类静默崩溃)
    install_callback_error_dialog(root)

    locator = None
    try:
        # ⚠ 旧代码把 ServiceLocator() 放在 try 外面, 这行抛异常就没有任何
        #   捕获 —— 打包成 console=False 后 stderr 也看不到, 用户视角就是
        #   "双击图标没反应"。放进 try 才有兜底提示。
        # 初始化服务容器
        locator = ServiceLocator()

        # 显示主窗口
        from .ui.windows.main_window import MainWindow
        app = MainWindow(root, locator)
        app.show()
    except ImportError as e:
        messagebox.showerror("启动失败", f"缺失模块: {e}")
        return 1
    except Exception as e:
        messagebox.showerror("启动失败", f"未知错误: {e}")
        return 1
    finally:
        # 退出时清理
        try:
            if locator is not None:
                locator.shutdown()
        except Exception:
            pass

        # 显式关闭全局线程池 —— 否则仍在跑的后台线程会让进程挂住不退
        try:
            from .utils.thread_pool import shutdown_pool
            shutdown_pool()
        except Exception:
            pass

        # 缺图汇总: 提示哪些图标资源没找到, 便于判断 resources/icons 是否完整
        try:
            from .utils.icons import missing
            mlist = missing()
            if mlist:
                print(
                    f"[icons] {len(mlist)} icons missing under resources/icons: "
                    f"{', '.join(mlist[:8])}",
                    file=sys.stderr,
                )
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
