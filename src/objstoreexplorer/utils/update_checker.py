# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""检查更新 — 只查询、不自更新 (借鉴 Pail 的保守升级口径)

匿名查询 GitHub Releases 最新版本并与 APP_VERSION 比对:
- 只读公开 API, 不带任何凭据, 不上报本机任何信息;
- 不做静默自动下载/替换 (Windows 产物未签名, 静默替换二进制的供应链
  风险大于收益), 只提示新版本号、下载页与 SHA256SUMS.txt 校验指引。
"""
from __future__ import annotations

import json
import re
import urllib.request

from ..config.settings import APP_NAME, APP_VERSION

REPO_OWNER = "chinayury"
REPO_NAME = "ObjStoreExplorer"
RELEASES_LATEST_API = (
    f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
)
RELEASES_PAGE = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest"

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_UA = f"{APP_NAME}/{APP_VERSION} (update-check)"


def parse_version(s: str) -> tuple[int, int, int]:
    """'v0.2.1' / '0.2.1' -> (0, 2, 1); 解析失败抛 ValueError"""
    m = _VERSION_RE.match((s or "").strip())
    if not m:
        raise ValueError(f"无法解析版本号: {s!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def check_update(current: str = APP_VERSION, timeout: float = 5.0) -> dict:
    """查询 GitHub Releases 最新版本并与 current 比对。

    永不抛异常 —— 网络失败/解析失败都返回 ok=False 的统一结果:
        ok                是否成功取到 Release 信息
        update_available  latest > current 时 True
        current / latest  版本号字符串 (latest 去掉 v 前缀)
        release_url       最新 Release 页面
        error             失败原因 (ok=False 时)
    """
    result: dict = {
        "ok": False, "update_available": False, "current": current,
        "latest": None, "release_url": RELEASES_PAGE, "error": None,
    }
    try:
        req = urllib.request.Request(
            RELEASES_LATEST_API,
            headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        m = _VERSION_RE.match(str(data.get("tag_name") or ""))
        if not m:
            raise ValueError(f"Release tag 无法解析: {data.get('tag_name')!r}")
        latest = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        result.update(
            ok=True,
            latest=latest,
            update_available=parse_version(latest) > parse_version(current),
            release_url=str(data.get("html_url") or RELEASES_PAGE),
        )
    except Exception as e:  # noqa: BLE001 —— 统一降级为 ok=False, 不向上抛
        result["error"] = f"{type(e).__name__}: {e}"
    return result
