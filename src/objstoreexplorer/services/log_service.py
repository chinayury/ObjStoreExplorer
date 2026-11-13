# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""services/log_service - 日志服务

将 UI 层的日志消息统一写入数据库 + 推送给订阅者。

=== 线程契约 (调用方必读) ===

`_emit()` **在调用线程**同步执行, 订阅者回调也在调用线程被调用。
若日志是从后台线程发出的 (传输/同步线程), 订阅者若要更新 tkinter 控件,
必须自己切回主线程 —— 推荐直接用 `emit_on_main(root.after, ...)` 包一层。
"""
from __future__ import annotations
import sys
from datetime import datetime
from typing import List, Dict, Any, Callable, Optional


class LogService:
    """日志服务

    用法:
        logger = locator.logger
        logger.subscribe(callback)
        logger.info("connect", "192.168.1.1", "success", "连接成功")
    """

    def __init__(self, config_manager):
        self._config = config_manager
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """订阅日志事件

        回调在**发日志的那个线程**被调用, 不保证是主线程。
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def info(self, operation: str, target: str = "", message: str = "") -> None:
        self._emit("INFO", operation, target, "info", message)

    def warning(self, operation: str, target: str = "", message: str = "") -> None:
        self._emit("WARNING", operation, target, "warning", message)

    def error(self, operation: str, target: str = "", message: str = "") -> None:
        self._emit("ERROR", operation, target, "failure", message)

    def success(self, operation: str, target: str = "", message: str = "") -> None:
        self._emit("INFO", operation, target, "success", message)

    def _emit(self, level: str, operation: str, target: str,
              status: str, message: str) -> None:
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "operation": operation,
            "target": target,
            "status": status,
            "message": message,
        }

        # 写入数据库 (失败不影响推送, 但不能无声无息 —— 之前 except: pass
        # 会让"日志功能坏了"完全无痕)
        try:
            self._config.add_log(
                level=level, operation=operation, target=target,
                status=status, message=message,
            )
        except Exception as e:  # noqa: BLE001
            self._report_internal(
                f"日志写库失败 [{operation}]: {e}", exc=e,
            )

        # 推送给订阅者
        for cb in list(self._subscribers):
            try:
                cb(entry)
            except Exception as e:  # noqa: BLE001
                self._report_internal(
                    f"日志订阅者回调失败 [{operation}]: {e}", exc=e,
                )

    @staticmethod
    def _report_internal(text: str, exc: Optional[BaseException] = None) -> None:
        """服务自身的故障兜底: 写 stderr, 保证至少留下痕迹"""
        try:
            print(f"[LogService] {text}", file=sys.stderr)
            if exc is not None:
                import traceback
                traceback.print_exception(type(exc), exc, exc.__traceback__,
                                          file=sys.stderr)
            sys.stderr.flush()
        except Exception:  # noqa: BLE001 - 连 stderr 都失败就只能放弃
            pass

    def emit_on_main(
        self,
        schedule: Callable[[int, Callable[[], None]], str],
        level: str,
        operation: str,
        target: str = "",
        message: str = "",
    ) -> None:
        """把日志推给订阅者时, 强制切到主线程

        Args:
            schedule: 调度函数, tkinter 里传 `root.after`
            level: INFO / WARNING / ERROR
            operation / target / message: 同 info()/warning()/error()

        本方法自身线程安全: 可以从任意后台线程调用。
        """
        status = {"INFO": "info", "WARNING": "warning",
                  "ERROR": "failure"}.get(level, "info")

        def _dispatch() -> None:
            entry = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": level,
                "operation": operation,
                "target": target,
                "status": status,
                "message": message,
            }
            for cb in list(self._subscribers):
                try:
                    cb(entry)
                except Exception as e:  # noqa: BLE001
                    self._report_internal(
                        f"日志订阅者回调失败 [{operation}]: {e}", exc=e,
                    )

        # 数据库写入仍在当前线程做 (不碰 UI), 只有推送切主线程
        try:
            self._config.add_log(
                level=level, operation=operation, target=target,
                status=status, message=message,
            )
        except Exception as e:  # noqa: BLE001
            self._report_internal(
                f"日志写库失败 [{operation}]: {e}", exc=e,
            )

        try:
            schedule(0, _dispatch)
        except Exception as e:  # noqa: BLE001 - root 已销毁等情况
            self._report_internal(
                f"日志切主线程调度失败 [{operation}]: {e}", exc=e,
            )

    def get_history(self, limit: int = 100, level: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取历史日志"""
        return self._config.get_logs(limit=limit, level=level)

    def cleanup(self) -> None:
        self._subscribers.clear()
