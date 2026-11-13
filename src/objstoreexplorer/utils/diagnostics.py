# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""自检模块 - 收集诊断信息 (网络 / 服务 / 日志)

用于反馈系统自动收集问题现场 (因为有些错误一闪就没)。
跨平台实现:
  - Windows: Get-WinEvent (系统日志) + Get-Service (服务状态)
  - macOS / Linux: log show (macOS) / journalctl (systemd)
  - 不支持的平台: 返回空, 不报错

API:
  collect_diagnostics() -> dict - 主入口, 返回所有诊断信息
  check_internet(url, timeout) -> bool - 联网检测
  collect_windows_event_log(hours, max_events) -> list[dict]
  collect_service_status(names) -> list[dict]
  collect_app_log(tail_lines) -> str
  collect_process_snapshot() -> dict
"""
import json
import platform
import subprocess
import sys
import time
from collections import deque
from typing import List, Dict, Any, Optional
import socket
import ssl
import urllib.request
import urllib.error

from ..config.settings import LOG_DIR, LOG_FILE_NAME, APP_VERSION, APP_NAME


# ==================== 参数清洗 (PowerShell 拼接安全) ====================

def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    r"""把外部传入的数值参数强转 int 并夹到 [lo, hi]。

    这些值会被 f-string 直接拼进 PowerShell 脚本, 配置文件被篡改成
    `1; Remove-Item C:\ -Recurse` 之类就是任意命令执行, 所以只信 int。
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _ps_quote(s: str) -> str:
    """把字符串安全地嵌进 PowerShell 单引号串。

    PowerShell 单引号串内没有反斜杠转义, 唯一的转义是 ' -> ''。
    换行 / 控制字符会直接截断脚本, 一并剔除。
    """
    s = str(s).replace("\x00", "")
    s = "".join(ch for ch in s if ch >= " " and ch != "\x7f")
    return "'" + s.replace("'", "''") + "'"


# ==================== 联网检测 ====================

def check_internet(url: str = "https://www.baidu.com", timeout: int = 5) -> bool:
    """检测能否访问指定 URL —— 判定的是**网络可达性**, 不是业务是否成功。

    关键语义 (修复「明明有网却提示无网络」):
        拿到任何 HTTP 状态码, 就说明 DNS 解析 + TCP 连接 + TLS 握手**全都成功了**,
        网络显然是通的。所以 `HTTPError` (4xx / 5xx) 必须算作「有网」。

    之前把 `HTTPError` 连同 `URLError` 一起 except 掉返回 False, 而实测
    `https://feedback.itmsky.com/api/apps.php` 对 HEAD 请求返回
    **405 Method Not Allowed** (PHP 接口不实现 HEAD), 于是每次都被误判成无网络。

    策略: 先用 HEAD 探; 若服务端不接受 HEAD (405 / 501), 退回 GET 重试一次。
    不抛异常, 总是返回 bool。
    """
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except urllib.error.HTTPError:
            # 收到 HTTP 响应 = 网络通 (哪怕是 4xx/5xx/405)
            return True
        except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError):
            # 连 DNS/TCP/TLS 都没成功 —— 真的不通
            if method == "GET":
                return False
            continue          # HEAD 失败但可能是方法不被支持, 用 GET 再试
        except Exception:
            if method == "GET":
                return False
            continue
    return False


# ==================== 应用自身日志 ====================

def collect_app_log(tail_lines: int = 200) -> str:
    """读取应用日志尾部 N 行.

    LOG_DIR / LOG_FILE_NAME 由 config.settings 决定.
    文件不存在返回空串.
    """
    log_file = LOG_DIR / LOG_FILE_NAME
    if not log_file.exists():
        return ""
    try:
        tail_lines = _clamp_int(tail_lines, 1, 100000, 200)
        # deque(maxlen=N) 增量读, 只保留最后 N 行 —— 之前 readlines() 把整个
        # 日志读进内存再切片, 几十 MB 的日志会直接把进程内存顶上去。
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=tail_lines)
        return "".join(lines)
    except Exception as e:
        return f"[读取日志失败: {e}]"


# ==================== Windows Event Log ====================

def collect_windows_event_log(hours: int = 1, max_events: int = 200) -> List[Dict[str, Any]]:
    """收集最近 N 小时 Windows 应用程序 / 系统日志 (Warning + Error 级别).

    用 PowerShell Get-WinEvent (Win10+ / Server 2012+).
    非 Windows 平台返回空 list.
    """
    if platform.system() != "Windows":
        return []
    # 数值参数强转 + 夹范围: 下面直接 f-string 拼进 PS 脚本, 不能让调用方
    # (含被篡改的配置文件) 拼进任意命令片段。
    hours = _clamp_int(hours, 1, 24 * 30, 1)
    max_events = _clamp_int(max_events, 1, 5000, 200)
    # PowerShell 脚本: 查 Application + System 日志最近 N 小时, Level=2(Error) 或 3(Warning)
    ps_script = f"""
$start = (Get-Date).AddHours(-{hours})
$logs = @('Application', 'System')
$events = Get-WinEvent -FilterHashtable @{{LogName=$logs; StartTime=$start; Level=1,2,3}} -ErrorAction SilentlyContinue |
    Select-Object -First {max_events} |
    ForEach-Object {{
        [PSCustomObject]@{{
            time_created = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss')
            log_name     = $_.LogName
            level        = $_.LevelDisplayName
            source       = $_.ProviderName
            event_id     = $_.Id
            message      = ($_.Message -replace '\\s+', ' ').Substring(0, [Math]::Min(300, $_.Message.Length))
        }}
    }}
$events | ConvertTo-Json -Depth 2 -Compress
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        data = json.loads(result.stdout)
        # 单个事件时 PS 返回 object 而非 array
        if isinstance(data, dict):
            data = [data]
        return data
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError) as e:
        return [{"error": f"Get-WinEvent 失败: {e}"}]


# ==================== 服务状态 (Windows / systemd) ====================

def collect_service_status(names: List[str]) -> List[Dict[str, Any]]:
    """查询指定服务运行状态.

    Windows: Get-Service (Status: Running / Stopped / ...)
    Linux:   systemctl is-active <name>
    macOS:   launchctl list | grep <name>
    """
    if not names:
        return []
    system = platform.system()
    results = []
    if system == "Windows":
        ps_script = f"""
$names = @({','.join(_ps_quote(n) for n in names)})
$names | ForEach-Object {{
    $svc = Get-Service -Name $_ -ErrorAction SilentlyContinue
    if ($svc) {{
        [PSCustomObject]@{{
            name    = $svc.Name
            display = $svc.DisplayName
            status  = $svc.Status.ToString()
        }}
    }} else {{
        [PSCustomObject]@{{
            name    = $_
            display = "(未找到)"
            status  = "NotFound"
        }}
    }}
}} | ConvertTo-Json -Compress
"""
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            )
            if r.stdout.strip():
                data = json.loads(r.stdout)
                if isinstance(data, dict):
                    data = [data]
                return data
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError) as e:
            return [{"error": f"Get-Service 失败: {e}"}]
    elif system == "Linux":
        for name in names:
            try:
                r = subprocess.run(
                    ["systemctl", "is-active", name],
                    capture_output=True, text=True, timeout=5,
                )
                status = r.stdout.strip() or "unknown"
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                status = "unknown"
            results.append({"name": name, "status": status})
    elif system == "Darwin":
        for name in names:
            try:
                r = subprocess.run(
                    ["launchctl", "list"],
                    capture_output=True, text=True, timeout=5,
                )
                found = any(name in line for line in r.stdout.splitlines())
                results.append({"name": name, "status": "Running" if found else "NotFound"})
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                results.append({"name": name, "status": "unknown"})
    return results


# ==================== 进程快照 ====================

def collect_process_snapshot() -> Dict[str, Any]:
    """当前 Python 进程的运行时快照 (版本 / 平台 / 内存)."""
    import os
    try:
        import psutil  # type: ignore
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        snap = {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "pid": os.getpid(),
            "cwd": os.getcwd(),
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
        }
    except ImportError:
        # 没 psutil 时给最少信息
        snap = {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "pid": os.getpid(),
            "cwd": os.getcwd(),
        }
    return snap


# ==================== 主入口 ====================

def collect_diagnostics(
    ping_target: str = "https://www.baidu.com",
    eventlog_hours: int = 1,
    app_log_tail: int = 200,
    service_names: Optional[List[str]] = None,
    include_eventlog: bool = True,
) -> Dict[str, Any]:
    """主入口: 一次性收集所有诊断信息.

    Args:
        ping_target: 网络检测目标 URL
        eventlog_hours: Windows Event Log 查询时间窗
        app_log_tail: 应用日志尾部行数
        service_names: 要查的服务名列表
        include_eventlog: 是否收集 Windows Event Log (非 Windows 平台无效)

    Returns:
        dict 包含:
          - online: bool
          - process: dict (Python 进程快照)
          - services: list[dict] (服务状态)
          - eventlog: list[dict] (Windows Event Log, 非 Windows 平台为空)
          - app_log: str (应用日志尾部)
          - collected_at: str (ISO 时间)
    """
    service_names = service_names or []
    online = check_internet(ping_target, timeout=5)
    process = collect_process_snapshot()
    services = collect_service_status(service_names)
    eventlog = collect_windows_event_log(eventlog_hours) if include_eventlog else []
    app_log = collect_app_log(app_log_tail)
    return {
        "online": online,
        "process": process,
        "services": services,
        "eventlog": eventlog,
        "app_log": app_log,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
