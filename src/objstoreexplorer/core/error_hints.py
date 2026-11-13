# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""core/error_hints - S3 错误码人话映射 (桌面 + Web 双形态共用)

借鉴 bucketdock / Evil_Pig-CloudStore 的「错误信息人话映射」实践:
    S3/MinIO 的原始错误码 (AccessDenied / SignatureDoesNotMatch /
    InvalidAccessKeyId / NoSuchBucket ...) 对运维用户不可操作。
    本模块把高频错误码翻译成「现象 → 可能原因 → 建议动作」三段式
    中文提示, 让 6.2 红线「异常须捕获并给出友好提示」落到实处。

用法:
    from .error_hints import hint_for_error
    text = hint_for_error("AccessDenied: ...")   # 无命中时原样返回
    detail = hint_for_error(exc)                 # 异常对象亦可
"""
from __future__ import annotations
import re
from typing import Optional


# 错误码 → (标题, 原因, 建议)。按特异性从高到低匹配。
_RULES = [
    (
        ("SignatureDoesNotMatch",),
        "签名校验失败",
        "Access Key / Secret Key 不匹配, 或系统时钟与服务器偏差过大",
        "核对 AK/SK 是否抄错 (注意首尾空格); 检查本机时间是否自动同步",
    ),
    (
        ("InvalidAccessKeyId",),
        "Access Key 不存在",
        "服务端不存在该 AK, 或密钥已被禁用 / 轮换",
        "确认 AK 属于当前环境 (测试 / 生产密钥常混淆); 到 MinIO 控制台核对用户状态",
    ),
    (
        ("AccessDenied",),
        "权限不足",
        "当前密钥没有执行该操作所需的权限 (如 ListBuckets / 桶策略读写)",
        "用具备该权限的账号重试; 或在「访问策略」中为当前用户附加对应策略",
    ),
    (
        ("NoSuchBucket",),
        "桶不存在",
        "该桶尚未创建, 或名称拼写不一致 (桶名区分大小写)",
        "到「存储桶空间」页确认桶名; 大小写与连字符需完全一致",
    ),
    (
        ("BucketNotEmpty",),
        "桶不为空",
        "桶内仍有对象 (含历史版本与未完成分片)",
        "勾选「强制清空后删除」, 或先清空对象与历史版本再删桶",
    ),
    (
        ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"),
        "桶已存在",
        "同名桶已存在 (桶名全局唯一)",
        "更换桶名, 或直接使用已有桶",
    ),
    (
        ("InvalidBucketName",),
        "桶名不合法",
        "不符合 S3 命名规则 (3-63 字符, 小写字母 / 数字 / 连字符, 不能以连字符开头结尾)",
        "按规则修改桶名; 含大写或下划线的名称会被服务端拒绝",
    ),
    (
        ("EntityTooLarge",),
        "文件超过单次上传上限",
        "单文件超出服务端或本工具上传限制",
        "到「系统设置」调整上传上限; 超大文件建议分卷后上传",
    ),
    (
        ("RequestTimeTooSkewed",),
        "请求时间偏差过大",
        "本机时钟与服务器时间不同步, 签名被判过期",
        "开启系统时间自动同步 (NTP), 与服务器时区保持一致",
    ),
    (
        ("SlowDown", "ServiceUnavailable", "InternalError"),
        "服务端繁忙",
        "MinIO 集群限流或内部繁忙 (SlowDown 即 503 限流)",
        "稍后重试; 频繁出现时检查服务端负载或并发设置",
    ),
    (
        ("Connection refused", "ConnectTimeout", "连接被拒绝", "无法连接"),
        "连不上服务器",
        "Endpoint 不可达、端口错误或服务未启动",
        "确认 Endpoint 为「主机:端口」 (不写端口且不写协议时按 MinIO 默认补 9000, 不是 80); 检查服务端是否放行端口",
    ),
    (
        ("getaddrinfo failed", "Name or service not known", "域名解析失败"),
        "域名解析失败",
        "Endpoint 主机名无法解析 (DNS 或拼写问题)",
        "检查主机名拼写; 内网地址确认 DNS 或 hosts 配置",
    ),
    (
        ("certificate verify failed", "SSL", "CERTIFICATE_VERIFY_FAILED"),
        "TLS 证书校验失败",
        "服务端使用自签名证书, 或证书链不完整",
        "内网自签名场景可取消勾选「使用 HTTPS」改用 http; 或为服务端配置受信任证书",
    ),
    (
        ("NoSuchKey",),
        "对象不存在",
        "指定 key 在桶中不存在 (可能已被删除或移动)",
        "返回上级目录刷新列表确认对象是否还在",
    ),
    (
        ("NoSuchLifecycleConfiguration",),
        "未配置生命周期规则",
        "该桶尚未设置任何生命周期规则",
        "在「生命周期」页新增规则; 无规则时此项为空属正常现象",
    ),
    (
        ("ObjectLockConfigurationNotFound",),
        "未开启对象锁定",
        "该桶创建时未启用对象锁定 (版本控制+保留策略)",
        "对象锁定只能在创建桶时开启, 无法事后追加; 新建桶时勾选即可",
    ),
]

_CODE_RE = re.compile(r"[A-Za-z]+")


def _match_code(text: str) -> Optional[str]:
    """从错误文本中提取可能的 S3 错误码 (大写蛇形词优先)"""
    for m in re.finditer(r"\b([A-Z][A-Za-z]*(?:[A-Z][A-Za-z]*)+)\b", text):
        return m.group(1)
    return None


def hint_for_error(err) -> str:
    """把错误对象 / 错误文本翻译成人话提示。

    命中规则时返回「标题 + 原因 + 建议」多行文本; 未命中时原样返回
    输入文本 (strip 后), 保证调用方无需分支处理。
    """
    if err is None:
        return ""
    text = err if isinstance(err, str) else (getattr(err, "message", None) or str(err))
    text = (text or "").strip()
    if not text:
        return "未知错误 (无错误详情)"

    code = _match_code(text) or ""
    haystack = f"{code} {text}"
    for codes, title, cause, action in _RULES:
        if any(c.lower() in haystack.lower() for c in codes):
            return f"{title}\n可能原因: {cause}\n建议: {action}"
    return text
