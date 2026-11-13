# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""校验工具 - 桶名/AK/Endpoint 等

参考 AWS S3 桶命名规范:
    - 长度 3-63
    - 只能小写字母、数字、点、连字符
    - 必须以字母或数字开头和结尾
    - 不能包含连续的点
    - 不能是 IP 地址格式

参考 AWS AccessKey 规范:
    - 长度 3-64
    - 只能字母、数字、下划线
"""
from __future__ import annotations
import re
from typing import Tuple, Dict

from ..config.exceptions import ValidationError


# ==================== 桶名 ====================

_BUCKET_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9.-]*[a-z0-9]")
_IP_PATTERN = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")

# M-03: `re.match(r"^...$")` 的 `$` 在"字符串末尾前的一个换行"处也匹配,
# 于是 "abc\n" 能通过校验 —— 换行会进 HTTP Host 头 / XML 响应体, 属
# CRLF 注入面。统一入口先拒所有控制字符, 与 parse_endpoint 的口径一致。
def _has_control_chars(s: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in s)


def validate_bucket_name(name: str) -> Tuple[bool, str]:
    """校验桶名称

    Args:
        name: 桶名

    Returns:
        (is_valid, message) 元组
    """
    if not name:
        return False, "桶名称不能为空"
    if len(name) < 3:
        return False, "桶名称至少 3 个字符"
    if len(name) > 63:
        return False, "桶名称最多 63 个字符"
    if _has_control_chars(name):
        return False, "桶名称不能包含控制字符 (换行/回车/制表符)"
    if not _BUCKET_NAME_PATTERN.fullmatch(name):
        return False, (
            "桶名称只能包含小写字母、数字、点和连字符,"
            "且必须以字母或数字开头和结尾"
        )
    if ".." in name:
        return False, "桶名称不能包含连续的点"
    if _IP_PATTERN.fullmatch(name):
        return False, "桶名称不能是 IP 地址格式"
    if name.startswith("xn--"):
        return False, "桶名称不能以 xn-- 开头"
    if name.endswith("-s3alias"):
        return False, "桶名称不能以 -s3alias 结尾"
    return True, "合法"


def validate_bucket_name_or_raise(name: str) -> None:
    """校验桶名,失败时抛出 ValidationError"""
    ok, msg = validate_bucket_name(name)
    if not ok:
        raise ValidationError(msg, code="InvalidBucketName")


# ==================== AccessKey ====================

_AK_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


def validate_access_key(ak: str) -> Tuple[bool, str]:
    """校验 Access Key

    Args:
        ak: Access Key

    Returns:
        (is_valid, message) 元组
    """
    if not ak:
        return False, "Access Key 不能为空"
    if len(ak) < 3:
        return False, "Access Key 至少 3 个字符"
    if len(ak) > 64:
        return False, "Access Key 最多 64 个字符"
    if _has_control_chars(ak):
        return False, "Access Key 不能包含控制字符 (换行/回车/制表符)"
    if not _AK_PATTERN.fullmatch(ak):
        return False, "Access Key 只能包含字母、数字和下划线"
    return True, "合法"


def validate_access_key_or_raise(ak: str) -> None:
    """校验 AK,失败时抛出 ValidationError"""
    ok, msg = validate_access_key(ak)
    if not ok:
        raise ValidationError(msg, code="InvalidAccessKey")


# ==================== SecretKey ====================

def validate_secret_key(sk: str) -> Tuple[bool, str]:
    """校验 Secret Key"""
    if not sk:
        return False, "Secret Key 不能为空"
    if len(sk) < 8:
        return False, "Secret Key 至少 8 个字符 (建议 16+)"
    if len(sk) > 128:
        return False, "Secret Key 最多 128 个字符"
    return True, "合法"


# ==================== Endpoint ====================

# 主机名合法字符集 (RFC 1123 标签 + IPv6 十六进制/冒号 + 通配的连字符)。
# 只允许这些, 等于一次性挡掉: 换行/回车 (CRLF 注入 —— endpoint 会进 HTTP
# Host 头, 换行就能塞进额外的请求头)、空格、shell 元字符 ($ ` ; | & > <)、
# 引号、括号、分号、百分号编码等。
_HOSTNAME_RE = re.compile(
    r"^[A-Za-z0-9._\-]+$"          # 常规主机名 / IPv4
    r"|^\[[0-9A-Fa-f:.]+\]$"       # 带方括号的 IPv6
    r"|^[0-9A-Fa-f:]+$"            # 裸 IPv6
)


def _is_valid_hostname(host: str) -> bool:
    """主机名是否只含安全字符"""
    if not host or len(host) > 255:
        return False
    # 标签级检查: 允许点分, 但不允许空标签 / 连续点 / 首尾点 / 标签超长
    if "." in host and not host.startswith("["):
        labels = host.split(".")
        if any(not lb for lb in labels):
            return False
        if any(len(lb) > 63 for lb in labels):
            return False
    return bool(_HOSTNAME_RE.match(host))


def parse_endpoint(endpoint: str) -> Dict[str, str]:
    """解析 endpoint 字符串

    支持格式:
        - 192.168.1.247:9000
        - http://192.168.1.247:9000
        - https://minio.example.com
        - minio.example.com:9000

    Returns:
        {protocol, host, port}

    默认端口按协议走标准: HTTP=80, HTTPS=443。MinIO 自定义端口(9000)请显式写。

    ⚠ 未写端口且未写协议时, 旧实现回填 80 —— 但 MinIO 默认端口是 9000,
    于是 "minio.example.com" 这种最常见的填法会连到 80 端口上必然失败,
    而错误提示只会说"连接被拒绝", 用户根本想不到是端口填漏了。这里改回
    9000 并在校验时明确提示。
    """
    _HTTP_PREFIX = "http://"
    _HTTPS_PREFIX = "https://"
    _DEFAULT_HTTP_PORT = "80"
    _DEFAULT_HTTPS_PORT = "443"
    _DEFAULT_MINIO_PORT = "9000"

    result = {
        "protocol": "http",
        "host": "",
        "port": _DEFAULT_MINIO_PORT,
        "raw": endpoint,
        "port_inferred": True,   # 端口是补的, 不是用户写的
    }
    if not endpoint:
        return result

    # ⚠ 先掐掉控制字符。endpoint 会进 HTTP Host 头, 换行/回车就是 CRLF 注入;
    #   也会被 diagnostics 拼进 PowerShell 脚本, 控制字符同样危险。
    #   必须在任何解析之前处理。
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in endpoint):
        result["error"] = "服务地址含控制字符 (换行/制表符等), 已拒绝"
        return result

    endpoint = endpoint.strip()

    if endpoint.startswith(_HTTPS_PREFIX):
        result["protocol"] = "https"
        result["port"] = _DEFAULT_HTTPS_PORT
        endpoint = endpoint[len(_HTTPS_PREFIX):]
    elif endpoint.startswith(_HTTP_PREFIX):
        result["protocol"] = "http"
        result["port"] = _DEFAULT_HTTP_PORT
        endpoint = endpoint[len(_HTTP_PREFIX):]
    else:
        # 没写协议时按 MinIO 默认端口补 (而不是 HTTP 的 80)
        result["port"] = _DEFAULT_MINIO_PORT

    if "/" in endpoint:
        endpoint = endpoint.split("/", 1)[0]

    if ":" in endpoint:
        host, port = endpoint.rsplit(":", 1)
        result["host"] = host
        result["port"] = port
        result["port_inferred"] = False
    else:
        result["host"] = endpoint

    return result


def validate_endpoint(endpoint: str) -> Tuple[bool, str]:
    """校验 endpoint

    除基本的"主机名 + 数字端口 + 端口范围"外, 还要挡掉会影响下游的输入:
      - 控制字符 (CRLF 注入 / PowerShell 脚本注入)
      - shell 元字符与空格、引号
      - 非法 scheme (file:// / ftp:// / javascript: ...)
    """
    parsed = parse_endpoint(endpoint)
    if parsed.get("error"):
        return False, parsed["error"]
    host = parsed["host"]
    if not host:
        return False, "服务地址不能为空"

    # 方案必须是 http/https —— 否则可能被配成 file:// 让 urllib 用非预期
    # 协议发起请求, 或 javascript: 之类
    raw = (endpoint or "").strip().lower()
    for bad in ("file://", "ftp://", "gopher://", "javascript:", "data:"):
        if raw.startswith(bad):
            return False, f"服务地址协议不合法 (仅支持 http/https): {endpoint!r}"

    if not _is_valid_hostname(host):
        return False, (
            f"主机名含非法字符: {host!r}。"
            f"只允许字母/数字/点/连字符/下划线 (或方括号包裹的 IPv6)"
        )

    if not parsed["port"].isdigit():
        return False, "端口必须是数字"
    port = int(parsed["port"])
    if port < 1 or port > 65535:
        return False, "端口范围 1-65535"

    if parsed.get("port_inferred") and parsed["protocol"] == "http":
        return True, (
            "合法 (未写端口, 按 MinIO 默认补 9000; 若你的服务在 80 端口请显式写 :80)"
        )
    return True, "合法"


# ==================== 文件名 ====================

def validate_external_host(host: str) -> Tuple[bool, str]:
    """校验预签名外链 Host (D9, 可选字段, 空串 = 不启用)

    只接受「主机名[:端口]」: 不允许带协议前缀 / 路径 / 查询串 ——
    它是用来替换签名 Host 的, 多一个字符签名就对不上。
    """
    h = (host or "").strip()
    if not h:
        return True, "未启用 (留空)"
    if "://" in h:
        return False, "外链 Host 不要带协议前缀 (只填 主机:端口)"
    if any(c in h for c in "/?# "):
        return False, "外链 Host 只能填 主机[:端口], 不能带路径/查询串/空格"
    # 端口段 (若有) 必须是 1-65535 的数字; 主机名部分单独校验
    # (IPv6 字面量 [::1]:9000 整体放行, 交给下游 urllib 判)
    host_part = h
    if ":" in h and not h.startswith("["):
        host_part, port = h.rsplit(":", 1)
        if port and (not port.isdigit() or not (1 <= int(port) <= 65535)):
            return False, "外链 Host 端口必须是 1-65535 的数字"
    if not _is_valid_hostname(host_part):
        return False, f"外链 Host 含非法字符: {h!r}"
    return True, "合法"


_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# M-04: Windows 保留设备名。对象存储允许任意 key (别处上传的 `CON`/`NUL`
# 都能存在), 但下载落盘时 open("CON","wb") 会写到控制台设备而不是文件,
# 随后 FileResponse 找不到文件 → 500; 上传暂存同理会污染控制台。
# 命中即加 `_` 前缀 (COM1.txt → _COM1.txt), 保留可读性。
_WIN_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _is_win_reserved(stem: str) -> bool:
    return stem.upper() in _WIN_RESERVED_NAMES


def validate_filename(filename: str) -> Tuple[bool, str]:
    """校验本地文件名 (不含路径)"""
    if not filename:
        return False, "文件名不能为空"
    if len(filename) > 255:
        return False, "文件名超过 255 字符"
    if _ILLEGAL_FILENAME_CHARS.search(filename):
        return False, '文件名包含非法字符 (< > : " / \\ | ? *)'
    if filename in (".", ".."):
        return False, "文件名不能是 . 或 .."
    if _is_win_reserved(filename.rsplit(".", 1)[0]):
        return False, "文件名不能使用 Windows 保留设备名 (CON/PRN/AUX/NUL/COM1-9/LPT1-9)"
    return True, "合法"


def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """清洗文件名,替换非法字符

    Args:
        filename: 原始文件名
        replacement: 替换字符

    Returns:
        清洗后的安全文件名
    """
    if not filename:
        return "unnamed"
    cleaned = _ILLEGAL_FILENAME_CHARS.sub(replacement, filename)
    # Windows 会自动去掉尾随空格/点, 落盘名与实际 key 不一致, 一并清掉
    cleaned = cleaned.strip().rstrip(". ")
    if not cleaned or cleaned in (".", ".."):
        return "unnamed"
    # M-04: Windows 保留设备名加前缀, 否则 open() 落到设备上而不是文件
    if "." in cleaned:
        stem, ext = cleaned.rsplit(".", 1)
        if _is_win_reserved(stem):
            cleaned = "_" + cleaned
    elif _is_win_reserved(cleaned):
        cleaned = "_" + cleaned
    if len(cleaned) > 200:
        name, ext = cleaned.rsplit(".", 1) if "." in cleaned else (cleaned, "")
        max_name = 200 - len(ext) - 1 if ext else 200
        cleaned = name[:max_name] + ("." + ext if ext else "")
    return cleaned
