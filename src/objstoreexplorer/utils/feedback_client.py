# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""反馈提交客户端 - 接入 MultiFeedbackSystem (多租户反馈中转服务)

两种模式:
  1. 在线: HTTP POST 到 /api/submit.php (含 app_key + 截图)
  2. 离线: 打包 zip 到本地 (给管理员手动导入后台)

API (在线, 接入手册 § 4):
  POST /api/submit.php (Content-Type: application/json)
  POST /api/upload.php (multipart/form-data, 单图 ≤5MB, JPG/PNG/WebP/GIF)
  GET  /api/apps.php   (查应用信息, app_key 走请求头 X-App-Key)

  注: app_key 一律走 X-App-Key 请求头, 不拼在 URL query 上 —— query 会落进
  服务端 access log / 反代日志 / Referer, 泄露面远大于请求头。
  api_base 默认强制 https; 内网 http 需在 feedback.yaml 显式
  `allow_insecure_http: true` 才放行 (默认 false)。

API (离线, 接入手册 § 6):
  - 打包 zip (≤50MB) 含 screenshot/*.png + log/*.log + meta.json
  - 运营人员后台「离线导入」上传, 系统自动解压

占位符: config/feedback.yaml 里 app_key / api_base 用 PLACEHOLDER 时
全部走离线模式 (避免发到不存在的服务端).

接入手册: docs/08-集成手册/MultiFeedbackSystem-接入手册-v.html
"""
import json
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    import yaml
except ImportError:
    # 打包环境漏装 PyYAML 时 (早期版本 的 exe 即如此),
    # 不再让 "反馈" 按钮回调静默崩溃; feedback.yaml 解析跳过,
    # 配置退到 数据库覆盖 + 内置默认 (yaml 里本来就只有占位值)
    yaml = None

from ..config.settings import (
    APP_NAME, APP_VERSION, APP_DIR,
    FEEDBACK_MAX_IMAGES, FEEDBACK_MAX_IMAGE_BYTES,
    FEEDBACK_TIMEOUT_SECONDS, FEEDBACK_BUNDLE_MAX_BYTES,
    FEEDBACK_OFFLINE_DIR_NAME,
)
from .diagnostics import check_internet


PLACEHOLDER_APP_KEY = "PLACEHOLDER_APP_KEY"
PLACEHOLDER_API_BASE = "https://your-domain"


# ==================== 反馈数据 ====================

@dataclass
class FeedbackPayload:
    """用户提交的反馈原始数据 (待上传 / 打包).

    字段对应 API 规范 (接入手册 § 4):
      - title, content, category, contact, images
      - device_info 由 submitter 自动填
    """
    title: str
    content: str
    category: int = 1                 # 1=功能异常 2=体验问题 3=使用建议 4=应用授权 5=其他
    contact: str = ""
    images: List[bytes] = field(default_factory=list)   # PNG/JPG bytes 列表
    device_info: str = ""

    def validate(self, cfg: Optional[Dict[str, Any]] = None) -> List[str]:
        """校验, 返回错误信息列表. 空列表表示通过.

        Args:
            cfg: 反馈配置 (可选)。传了就用 config/feedback.yaml 里的
                 max_images / max_image_bytes, 否则退回 settings 常量 ——
                 之前硬编码常量, 用户改 yaml 的 max_images 完全不生效。
                 不传该参数时行为与原来一致 (UI 层可继续无参调用)。
        """
        cfg = cfg or {}
        try:
            max_images = int(cfg.get("max_images", FEEDBACK_MAX_IMAGES))
        except (TypeError, ValueError):
            max_images = FEEDBACK_MAX_IMAGES
        try:
            max_image_bytes = int(cfg.get("max_image_bytes", FEEDBACK_MAX_IMAGE_BYTES))
        except (TypeError, ValueError):
            max_image_bytes = FEEDBACK_MAX_IMAGE_BYTES
        errs = []
        if not (2 <= len(self.title) <= 100):
            errs.append(f"标题长度需 2-100 字 (当前 {len(self.title)})")
        if not (5 <= len(self.content) <= 5000):
            errs.append(f"内容长度需 5-5000 字 (当前 {len(self.content)})")
        if len(self.contact) > 50:
            errs.append(f"联系方式 ≤50 字 (当前 {len(self.contact)})")
        if not (1 <= self.category <= 5):
            errs.append(f"category 必须 1-5 (当前 {self.category})")
        if len(self.images) > max_images:
            errs.append(f"截图最多 {max_images} 张 (当前 {len(self.images)})")
        for i, img in enumerate(self.images):
            if len(img) > max_image_bytes:
                errs.append(f"第 {i+1} 张截图超 5MB ({len(img)} bytes)")
        return errs


# ==================== 配置加载 ====================

# 反馈平台对接参数存本地数据库 (config_manager.app_settings 表),
# 优先级: 数据库 > config/feedback.yaml > 内置占位。
# 首次点 "反馈" 按钮若无参数, UI 层弹 FeedbackSettingsDialog 让用户设置。
FEEDBACK_DB_KEYS = {
    "api_base": "feedback.api_base",
    "app_key": "feedback.app_key",
    "link": "feedback.link",
}


def load_feedback_overrides_from_db() -> Dict[str, Any]:
    """从本地数据库读反馈平台参数 (无/读失败返回空 dict, 不抛异常)"""
    out: Dict[str, Any] = {}
    try:
        from ..core.config_manager import ConfigManager
        cm = ConfigManager()
        for cfg_field, key in FEEDBACK_DB_KEYS.items():
            v = cm.get_setting(key)
            if v:
                out[cfg_field] = v
    except Exception:
        pass
    return out


def save_feedback_overrides_to_db(cfg: Dict[str, Any]) -> None:
    """把反馈平台参数写入本地数据库 (app_settings 表)"""
    from ..core.config_manager import ConfigManager
    cm = ConfigManager()
    for cfg_field, key in FEEDBACK_DB_KEYS.items():
        v = (cfg.get(cfg_field) or "").strip()
        if v:
            cm.set_setting(key, v)


def _resolve_config_path() -> Optional[Path]:
    """按优先级定位 feedback.yaml

    候选位置 (用户可编辑的优先):

    - 开发模式 (python -m objstoreexplorer):
        APP_DIR = <项目根>/data
        ① <项目根>/data/config/feedback.yaml      ← 用户可编辑 (推荐放这里)
    - PyInstaller onedir 模式:
        APP_DIR = <exe目录>/data
        ① <exe目录>/data/config/feedback.yaml     ← 用户可编辑 (推荐放这里)
        ② <exe目录>/_internal/config/feedback.yaml ← PyInstaller 把 datas 打的副本

    旧实现只看 ① 的旧位置 (<exe目录>/config/), 而 build.spec 把文件打进了 ②,
    于是发布出去的 exe 永远读不到自带的配置, 反馈功能静默退化成离线模式, 用户
    也无处可改。(v0.1.0 打包实测发现)

    现在用户可编辑的 ① 优先 (数据目录内, 不污染源码树) —— 覆盖内置副本不需要
    重打包。
    """
    from ..config.settings import FEEDBACK_CONFIG_FILE

    candidates = [APP_DIR / "config" / FEEDBACK_CONFIG_FILE]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "config" / FEEDBACK_CONFIG_FILE)
    for p in candidates:
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def load_feedback_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """读取反馈配置: 数据库 > config/feedback.yaml > 默认占位.

    不存在返回默认占位配置 (使客户端走离线模式)。
    """
    if config_path is None:
        config_path = _resolve_config_path()
    cfg: Dict[str, Any] = {}
    if config_path is not None and yaml is not None and config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = {}
    # 补默认值
    cfg.setdefault("app_key", PLACEHOLDER_APP_KEY)
    cfg.setdefault("api_base", PLACEHOLDER_API_BASE)
    cfg.setdefault("timeout", FEEDBACK_TIMEOUT_SECONDS)
    cfg.setdefault("offline_dir", FEEDBACK_OFFLINE_DIR_NAME)
    # 限额以 yaml 为准 (settings 常量只做兜底), 改动无需改代码
    cfg.setdefault("max_images", FEEDBACK_MAX_IMAGES)
    cfg.setdefault("max_image_bytes", FEEDBACK_MAX_IMAGE_BYTES)
    cfg.setdefault("bundle_max_bytes", FEEDBACK_BUNDLE_MAX_BYTES)
    # http 明文传输开关: 默认关闭 (安全默认), 见 _normalize_api_base
    cfg.setdefault("allow_insecure_http", False)
    # 数据库里保存的对接参数优先 (设置窗口写入)
    for cfg_field, v in load_feedback_overrides_from_db().items():
        cfg[cfg_field] = v
    return cfg


def is_placeholder_config(cfg: Dict[str, Any]) -> bool:
    """判断是否还是占位配置 (决定走离线模式)."""
    return (
        cfg.get("app_key", "").startswith("PLACEHOLDER")
        or cfg.get("api_base", "").startswith("https://your")
    )


def has_feedback_config() -> bool:
    """反馈平台参数是否已配置 (未配置时 UI 层应先弹设置窗口)"""
    try:
        return not is_placeholder_config(load_feedback_config())
    except Exception:
        return False


def check_app_key_online(
    api_base: str,
    app_key: str,
    timeout: int = 8,
    allow_insecure_http: bool = False,
) -> Tuple[bool, str]:
    """校验 app_key 是否有效 (接入手册 §4 ③ GET /api/apps.php).

    app_key 走请求头 X-App-Key, 不再拼在 URL query 上 —— query 会进服务端
    access log / 反代日志 / Referer, 泄露面比请求头大得多。
    upload.php 本来就是这个约定, 两处保持一致。

    Returns:
        (True, "应用名 <name>") 或 (False, "错误说明")
    """
    try:
        api_base = _normalize_api_base(api_base, allow_insecure_http)
    except ValueError as e:
        return False, str(e)
    url = f"{api_base}/api/apps.php"
    try:
        req = urllib.request.Request(
            url, method="GET", headers={"X-App-Key": app_key}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        hints = {403: "app_key 无效或已停用", 405: "请求方法不允许", 429: "请求过于频繁 (限流)"}
        return False, f"HTTP {e.code}: {hints.get(e.code, '服务端错误')}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"连不上反馈平台: {e}"
    except Exception as e:
        return False, f"响应异常: {e}"
    if result.get("code") != 0:
        return False, result.get("msg", "app_key 校验失败")
    name = (result.get("data", {}) or {}).get("app", {}).get("name", "")
    return True, f"应用 {name}" if name else "app_key 有效"


def _normalize_api_base(api_base: str, allow_insecure_http: bool = False) -> str:
    """校验反馈平台地址: 默认强制 https, 且必须带主机名.

    两层防护:
      1. scheme 只允许 http/https —— 防止 feedback.yaml 里被配成 file:// /
         ftp:// 之类, 让 urllib 以非预期协议发起请求。
      2. 默认拒绝 http:// —— app_key 和反馈正文会随请求体明文过网, 链路上
         任何一跳都能拿到。只有显式打开 allow_insecure_http (yaml 里
         `allow_insecure_http: true`) 才放行内网 http, 且调用方应给用户提示。
    """
    base = (api_base or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"api_base 不合法 (仅支持 http/https): {api_base!r}")
    if parsed.scheme == "http" and not allow_insecure_http:
        raise ValueError(
            "api_base 必须是 https (当前为 http): app_key 与反馈内容会明文传输。"
            "内网自建服务确需 http 时, 在 config/feedback.yaml 设 "
            "allow_insecure_http: true"
        )
    return base


def insecure_http_warning(cfg: Optional[Dict[str, Any]]) -> str:
    """http 明文接入时返回给 UI 层的警告文案 (https 返回空串)."""
    if not isinstance(cfg, dict):
        return ""
    base = str(cfg.get("api_base") or "").strip().lower()
    if base.startswith("http://") and cfg.get("allow_insecure_http"):
        return "警告: 反馈平台为 http 明文传输, app_key 与反馈内容可能被链路窃听"
    return ""


# ==================== 在线提交 ====================

def _upload_image(api_base: str, app_key: str, img_bytes: bytes, timeout: int) -> str:
    """单张图上传, 返回图片 URL (供 submit 的 images 字段引用)."""
    # 接入手册: multipart/form-data, 字段名 image
    boundary = "----OSEFeedbackBoundary" + str(int(time.time()))
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"image\"; filename=\"clip.png\"\r\n"
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{api_base}/api/upload.php",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-App-Key": app_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("code") != 0:
        raise RuntimeError(f"upload 失败: {result.get('msg', 'unknown')}")
    return result["data"]["url"]


def submit_online(
    payload: FeedbackPayload,
    cfg: Optional[Dict[str, Any]] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """在线提交反馈.

    Returns:
        {ok: bool, mode: "online", id?: int, msg: str, response?: dict}

    Raises:
        RuntimeError 上传图片 / 提交失败
    """
    cfg = cfg or load_feedback_config()
    timeout = timeout or cfg.get("timeout", FEEDBACK_TIMEOUT_SECONDS)
    try:
        api_base = _normalize_api_base(
            cfg["api_base"], bool(cfg.get("allow_insecure_http", False))
        )
    except ValueError as e:
        raise RuntimeError(str(e)) from None
    app_key = cfg["app_key"]

    # 先上传所有图, 拿到 URL 列表
    image_urls: List[str] = []
    for img in payload.images:
        url = _upload_image(api_base, app_key, img, timeout)
        image_urls.append(url)

    # 再提交主反馈
    body = {
        "app_key": app_key,
        "title": payload.title,
        "content": payload.content,
        "category": payload.category,
        "contact": payload.contact,
        "images": image_urls,
        "device_info": payload.device_info,
    }
    req = urllib.request.Request(
        f"{api_base}/api/submit.php",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    warn = insecure_http_warning(cfg)
    if result.get("code") != 0:
        msg = result.get("msg", "未知错误")
        return {"ok": False, "mode": "online", "msg": f"{warn}; {msg}" if warn else msg, "response": result}
    msg = result.get("msg", "提交成功")
    return {"ok": True, "mode": "online", "id": result.get("data", {}).get("id"), "msg": f"{warn}; {msg}" if warn else msg}


# ==================== 离线打包 ====================

# 日志脱敏: 反馈包会连同日志一起外发 (或交给运营后台), 打包前必须抹掉凭据。
# 覆盖: AWS AK、secret/access key、sk- 前缀 token、Bearer、密码类赋值。
_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Za-z]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)(\"?(?:secret_key|access_key|secretKey|accessKey|password|passwd|token)\"?\s*[:=]\s*\")[^\"]*(\")"),
    re.compile(r"(?i)(authorization\s*[:=]\s*\S+\s+)\S+"),
)


def desensitize_text(text: str) -> str:
    """把文本里的凭据替换成 *** (不改动其余内容)"""
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + "***" + (m.group(2) if m.lastindex and m.lastindex > 1 else ""), out)
        else:
            out = pat.sub("***", out)
    return out


def _safe_username() -> str:
    """当前系统用户名 (取不到返回 "unknown", 不抛异常)"""
    import getpass
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"

def export_offline(
    payload: FeedbackPayload,
    diagnostics: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """打包离线反馈包 (zip) 到本地 data/feedback_bundles/.

    目录结构 (接入手册 § 6):
      bundle-<timestamp>.zip
        ├─ meta.json         (反馈主信息 + 客户端元数据)
        ├─ content.txt       (反馈内容, 文本)
      └─ screenshots/        (截图, PNG)
          ├─ 01.png
          ├─ 02.png
          ...

    Returns:
        {ok: bool, mode: "offline", path: str, size: int, msg: str}
    """
    import platform, socket
    cfg = cfg or load_feedback_config()
    offline_dir = APP_DIR / cfg.get("offline_dir", FEEDBACK_OFFLINE_DIR_NAME)
    offline_dir.mkdir(parents=True, exist_ok=True)

    try:
        max_bundle_bytes = int(cfg.get("bundle_max_bytes", FEEDBACK_BUNDLE_MAX_BYTES))
    except (TypeError, ValueError):
        max_bundle_bytes = FEEDBACK_BUNDLE_MAX_BYTES
    if max_bundle_bytes <= 0:
        max_bundle_bytes = FEEDBACK_BUNDLE_MAX_BYTES

    ts = time.strftime("%Y%m%d-%H%M%S")
    bundle_name = f"feedback-{ts}.zip"
    bundle_path = offline_dir / bundle_name

    meta = {
        "title": payload.title,
        "content": payload.content,
        "category": payload.category,
        "contact": payload.contact,
        "device_info": payload.device_info,
        "app": {"name": APP_NAME, "version": APP_VERSION},
        "client": {
            # 直接调 getpass: 之前写的是
            # `getpass.getuser() if hasattr(__builtins__, "getpass") else "unknown"`,
            # 而模块导入下 __builtins__ 是 dict, hasattr 恒为 False,
            # 于是所有离线包里的 user 字段都是 "unknown"。
            "user": _safe_username(),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if diagnostics:
        meta["diagnostics"] = {
            "online": diagnostics.get("online"),
            "process": diagnostics.get("process"),
            "services": diagnostics.get("services", []),
            "eventlog_count": len(diagnostics.get("eventlog", [])),
            "app_log_lines": diagnostics.get("app_log", "").count("\n") if diagnostics.get("app_log") else 0,
        }
        # 日志和 eventlog 单独文件 (避免 JSON 太大)
        if diagnostics.get("app_log"):
            meta["diagnostics"]["app_log_file"] = "logs/app.log"
        if diagnostics.get("eventlog"):
            meta["diagnostics"]["eventlog_file"] = "logs/eventlog.json"

    # ==================== 先攒内容, 再算体积, 最后才落盘 ====================
    # 之前是 zf 全部写完再 stat() 检查 50MB: 超限时磁盘已经被写满一次,
    # 还得再 unlink 一次, 大包场景下等于白白占满一轮磁盘 IO。
    entries: List[Tuple[str, bytes]] = [
        ("meta.json", json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")),
        ("content.txt", f"标题: {payload.title}\n\n{payload.content}\n".encode("utf-8")),
    ]
    for i, img_bytes in enumerate(payload.images, 1):
        entries.append((f"screenshots/{i:02d}.png", img_bytes))
    if diagnostics:
        if diagnostics.get("app_log"):
            # 脱敏后再打包: 原始日志不进反馈包
            entries.append((
                "logs/app.log",
                desensitize_text(diagnostics["app_log"]).encode("utf-8", errors="replace"),
            ))
        if diagnostics.get("eventlog"):
            entries.append((
                "logs/eventlog.json",
                desensitize_text(
                    json.dumps(diagnostics["eventlog"], ensure_ascii=False, indent=2)
                ).encode("utf-8", errors="replace"),
            ))

    # 接入手册 § 6: ≤50MB。未压缩原始大小之和是上界 (DEFLATED 只会更小),
    # 偏保守但绝不会误判放行。
    total = sum(len(data) for _arc, data in entries)
    if total > max_bundle_bytes:
        over = total - max_bundle_bytes
        return {
            "ok": False,
            "mode": "offline",
            "path": "",
            "size": 0,
            "msg": (
                f"反馈包超 {max_bundle_bytes // 1024 // 1024}MB "
                f"(内容约 {total // 1024 // 1024}MB, 超出 {over} 字节), "
                "请减少截图张数或日志行数后重试"
            ),
        }

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in entries:
            zf.writestr(arcname, data)

    size = bundle_path.stat().st_size
    if size > max_bundle_bytes:
        # 接入手册 § 6: ≤50MB (压缩后仍超, 兜底删掉)
        bundle_path.unlink(missing_ok=True)
        return {"ok": False, "mode": "offline", "path": "", "size": 0, "msg": f"反馈包超 {max_bundle_bytes // 1024 // 1024}MB"}

    return {
        "ok": True,
        "mode": "offline",
        "path": str(bundle_path),
        "size": size,
        "msg": f"已打包到 {bundle_path}",
    }


# ==================== 智能提交 ====================

def submit_smart(
    payload: FeedbackPayload,
    diagnostics: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """根据联网状态和配置自动选择在线 / 离线模式.

    Returns:
        {ok, mode: "online"|"offline", id?, path?, msg, ...}
    """
    cfg = cfg or load_feedback_config()
    # 校验先 (传 cfg: 限额以 yaml 的 max_images / max_image_bytes 为准)
    errs = payload.validate(cfg)
    if errs:
        return {"ok": False, "mode": "none", "msg": " | ".join(errs)}

    if is_placeholder_config(cfg):
        # 占位配置 → 强制离线
        result = export_offline(payload, diagnostics, cfg)
        result["msg"] = "未配置 API (app_key/api_base 为占位符), " + result.get("msg", "")
        return result

    # 试连 API: 这里只探"网络可达性", 不带 app_key —— 之前拼在 URL 上,
    # 每点一次"反馈"就往服务端 access log / 反代日志里写一条凭据。
    # check_internet 拿到任何 HTTP 状态码都算通, 所以无 key 的端点足够判断。
    online = check_internet(cfg["api_base"].rstrip("/") + "/api/apps.php", timeout=5)
    if not online:
        result = export_offline(payload, diagnostics, cfg)
        result["msg"] = "检测到无网络或 API 不可达, " + result.get("msg", "")
        return result

    # 在线
    try:
        return submit_online(payload, cfg)
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        # 在线失败, 降级离线
        result = export_offline(payload, diagnostics, cfg)
        result["msg"] = f"在线提交失败 ({e}), " + result.get("msg", "")
        return result
