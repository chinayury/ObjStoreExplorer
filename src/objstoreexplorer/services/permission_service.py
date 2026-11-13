# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""services/permission_service - 权限判断服务

授权一律 **fail-closed**: 只有实际探测 (s3_client.probe_admin) 成功返回 True
才认为有管理员权限。探测失败/不可用一律按 False 处理 ——
之前会降级到 AK 命名约定 (xxxadmin 判为管理员), UI 于是显示管理入口,
用户点进去才吃 403。

AK 命名约定只作为**提示文案**, 见 admin_hint(), 不参与授权。
"""
from __future__ import annotations


class PermissionService:
    """权限判断服务"""

    def __init__(self, locator=None):
        self._locator = locator

    def is_admin(self, access_key: str = "") -> bool:
        """判断当前连接是否具备管理员权限 (fail-closed)

        只有 probe_admin() 明确返回 True 才为 True; 探测失败/无客户端/未连接
        一律返回 False。access_key 参数只用于兼容旧调用签名, **不参与授权判定**。
        """
        if self._locator is None:
            return False
        client = getattr(self._locator, "s3_client", None)
        if client is None or not getattr(client, "is_connected", False):
            return False
        try:
            return bool(client.probe_admin())
        except Exception:
            # 探测不了就当没有权限, 不能让 UI 显示出必然 403 的入口
            return False

    def admin_hint(self, access_key: str = "") -> str:
        """给 UI 用的文案提示 (不参与授权)

        Returns:
            形如 "AK 命名看起来像管理员账号 (需实际权限确认)" 的提示; 不像则空串
        """
        if not access_key:
            return ""
        ak = access_key.lower()
        if ak.endswith("admin") or ak.endswith("minio"):
            return "AK 命名看起来像管理员账号, 但仍需实际权限确认"
        return ""

    def can_manage_users(self, access_key: str = "") -> bool:
        return self.is_admin(access_key)

    def can_view_stats(self, access_key: str = "") -> bool:
        return self.is_admin(access_key)

    def can_modify_buckets(self, access_key: str = "") -> bool:
        return self.is_admin(access_key)

    def cleanup(self) -> None:
        pass
