# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""core/bucket_ext - 桶扩展治理操作 (CORS 配置 / 未完成分片清理)

背景 (借鉴 medical_equ/s3、cloudlena/s3manager、Pail):
    CORS 配置与「中止未完成的分段上传」是桶级治理闭环的两块常见缺口:
      - 浏览器直传 / 前端跨域访问必须配 CORS, 否则控制台只能敲 mc;
      - 中断的上传会在桶里留下 invisible 分片持续计费, 用户无从发现。
    minio-py 7.x 的高级 API 未暴露这两组操作 (实测 7.2.20 只有
    object_lock / notification / replication / encryption)。

实现选择:
    不引入 boto3 新依赖 (仅两组操作不值一个重依赖), 改用 minio-py
    内部 `_url_open` 直接发 S3 REST 请求 —— 签名 / 区域解析 / 错误
    类型仍由 minio-py 完成, 安全面不扩大; 内部 API 若随大版本变更,
    本模块所有入口统一降级返回「当前客户端版本不支持」, 由
    S3ClientBase.track_result 记入能力降级清单 (D21), 不会静默出错。

    XML 响应仅来自用户自己的 S3 服务端 (同一信任域), 解析前限制大小;
    ElementTree 不解析外部实体, 且响应体积有上限, 足矣。
"""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

from xml.sax.saxutils import escape

# REST 响应体上限 (1MB): ListMultipartUploads 页面本就小, 防御性截断
_MAX_RESP_BYTES = 1024 * 1024


class _Unsupported(Exception):
    """内部 API 不可用 / 服务端不支持的内部信号"""


def _region(client: Any, bucket: str) -> str:
    """解析桶区域 (内部 API, 失败即视为不支持)"""
    getter = getattr(client, "_get_region", None)
    if not callable(getter):
        raise _Unsupported("当前 minio 客户端版本不支持桶区域解析")
    return getter(bucket)


def _call(client: Any, method: str, bucket: str, *,
          query_params: Dict[str, str] | None = None,
          body: bytes | None = None,
          headers: Dict[str, str] | None = None) -> Tuple[int, bytes]:
    """发一次已签名的 S3 REST 请求, 返回 (status, body_bytes)"""
    url_open = getattr(client, "_url_open", None)
    if not callable(url_open):
        raise _Unsupported("当前 minio 客户端版本不支持底层请求")
    region = _region(client, bucket)
    resp = url_open(
        method, region, bucket_name=bucket,
        body=body, headers=headers or {}, query_params=query_params or {},
        preload_content=True,
    )
    try:
        status = int(getattr(resp, "status", 0) or 0)
        raw = resp.read() if hasattr(resp, "read") else b""
        data = raw[:_MAX_RESP_BYTES] if raw else b""
    finally:
        try:
            resp.close()
            resp.release_conn()
        except Exception:
            pass
    return status, data


def _err_from_body(status: int, data: bytes) -> str:
    """从 S3 错误响应 XML 里提取 Code + Message"""
    try:
        root = ET.fromstring(data)
        code = (root.findtext("Code") or "").strip()
        msg = (root.findtext("Message") or "").strip()
        return f"{code}: {msg}" if code else (msg or f"HTTP {status}")
    except ET.ParseError:
        return f"HTTP {status}"


# ==================== CORS ====================

def _cors_xml(rules: List[Dict[str, Any]]) -> bytes:
    """[{origin, methods, headers, max_age}] → CORSConfiguration XML"""
    parts = ["<CORSConfiguration>"]
    for r in rules:
        origin = str(r.get("origin", "*")).strip() or "*"
        methods = [str(m).strip().upper() for m in (r.get("methods") or []) if str(m).strip()]
        if not methods:
            methods = ["GET"]
        headers = [str(h).strip() for h in (r.get("headers") or []) if str(h).strip()]
        max_age = r.get("max_age")
        parts.append("<CORSRule>")
        parts.append(f"<AllowedOrigin>{escape(origin)}</AllowedOrigin>")
        for m in methods:
            parts.append(f"<AllowedMethod>{escape(m)}</AllowedMethod>")
        for h in headers or ["*"]:
            parts.append(f"<AllowedHeader>{escape(h)}</AllowedHeader>")
        if max_age is not None:
            try:
                parts.append(f"<MaxAgeSeconds>{int(max_age)}</MaxAgeSeconds>")
            except (TypeError, ValueError):
                pass
        parts.append("</CORSRule>")
    parts.append("</CORSConfiguration>")
    return "".join(parts).encode("utf-8")


def _parse_cors_xml(data: bytes) -> List[Dict[str, Any]]:
    """CORSConfiguration XML → [{origin, methods, headers, max_age}]"""
    if not data.strip():
        return []
    root = ET.fromstring(data)
    rules: List[Dict[str, Any]] = []
    for rule in root.findall("CORSRule"):
        rules.append({
            "origin": ",".join(e.text or "" for e in rule.findall("AllowedOrigin")),
            "methods": [e.text or "" for e in rule.findall("AllowedMethod")],
            "headers": [e.text or "" for e in rule.findall("AllowedHeader")],
            "max_age": rule.findtext("MaxAgeSeconds"),
        })
    return rules


def get_bucket_cors(client: Any, bucket: str) -> Tuple[bool, Any]:
    """读取桶 CORS 配置 (无配置时返回空列表)"""
    try:
        status, data = _call(client, "GET", bucket, query_params={"cors": ""})
    except _Unsupported as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001 - S3Error 等统一转文本
        return False, str(e)
    if status == 404:
        # MinIO 对未配置 CORS 的桶返回 NoSuchCORSConfiguration
        return True, []
    if status >= 300:
        return False, _err_from_body(status, data)
    try:
        return True, _parse_cors_xml(data)
    except ET.ParseError:
        return False, "CORS 配置解析失败 (响应不是合法 XML)"


def set_bucket_cors(client: Any, bucket: str,
                    rules: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """写入桶 CORS 配置 (整体覆盖)"""
    if not rules:
        return False, "至少需要一条 CORS 规则"
    body = _cors_xml(rules)
    try:
        status, data = _call(
            client, "PUT", bucket,
            query_params={"cors": ""}, body=body,
            headers={"Content-Type": "application/xml"},
        )
    except _Unsupported as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if status >= 300:
        return False, _err_from_body(status, data)
    return True, "CORS 配置已保存"


def delete_bucket_cors(client: Any, bucket: str) -> Tuple[bool, str]:
    """删除桶 CORS 配置"""
    try:
        status, data = _call(client, "DELETE", bucket, query_params={"cors": ""})
    except _Unsupported as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if status >= 300 and status != 404:
        return False, _err_from_body(status, data)
    return True, "CORS 配置已删除"


# ==================== 未完成分片清理 ====================

def list_multipart_uploads(client: Any, bucket: str) -> Tuple[bool, Any]:
    """列出桶内未完成的分段上传 (Upload 列表)

    Returns:
        (True, [{key, upload_id, initiated}]) / (False, 错误消息)
    """
    try:
        status, data = _call(client, "GET", bucket, query_params={"uploads": ""})
    except _Unsupported as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if status >= 300:
        return False, _err_from_body(status, data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return False, "分片列表解析失败 (响应不是合法 XML)"
    uploads: List[Dict[str, Any]] = []
    for up in root.findall("Upload"):
        uploads.append({
            "key": up.findtext("Key") or "",
            "upload_id": up.findtext("UploadId") or "",
            "initiated": up.findtext("Initiated") or "",
        })
    return True, uploads


def abort_multipart_upload(client: Any, bucket: str, key: str,
                           upload_id: str) -> Tuple[bool, str]:
    """中止一个未完成的分段上传 (DELETE /{bucket}/{key}?uploadId=)"""
    if not key or not upload_id:
        return False, "对象 key 与 upload_id 不能为空"
    try:
        status, data = _call(
            client, "DELETE", bucket, object_name=key,
            query_params={"uploadId": upload_id},
        )
    except _Unsupported as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if status >= 300 and status != 404:
        return False, _err_from_body(status, data)
    return True, f"已中止 {key} 的未完成上传"


# ==================== 对象公开性检查 (D8) ====================

def check_object_public(client: Any, bucket: str, key: str) -> Dict[str, Any]:
    """匿名 HEAD 探测对象是否公共可读 (借鉴 s3manager「公开性检查」)

    把「误公开」变成可见信号: 查询对象属性时附带一次不带任何凭据的
    HEAD 请求, 200 = 任何人可下载 (公共读), 403/401 = 需凭据。

    只探测不修改; 网络失败不影响主流程 (public 字段省略)。
    """
    import urllib.request
    import urllib.error
    from urllib.parse import quote

    result: Dict[str, Any] = {}
    try:
        endpoint = (getattr(client, "endpoint", "") or "").strip()
        if not endpoint:
            return result
        endpoint = re.sub(r"^https?://", "", endpoint).rstrip("/")
        scheme = "https" if getattr(client, "ssl", False) else "http"
        url = f"{scheme}://{endpoint}/{quote(bucket)}/{quote(key)}"
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            result["public"] = 200 <= resp.status < 300
            result["status"] = resp.status
    except urllib.error.HTTPError as e:
        # 403/401 = 需凭据 (非公开); 404 = 不存在或列表被禁 (不判公开)
        result["public"] = False
        result["status"] = e.code
    except Exception:
        # 超时 / 连接失败等: 不判公开, 由调用方决定是否展示
        pass
    return result
