# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""S3 客户端 V2 实现 - 使用 minio-py 新的 admin API

V2 是 V1 的子类,在 V1 基础上扩展:
    - 使用 minio.admin.MinioAdmin (新 API)
    - 支持服务账号、组、桶配额等高级功能
    - 修复 V1 中 has_attr 探测的脆弱性

V2 在以下情况生效:
    - minio-py >= 7.1 且 minio.admin 模块可导入
    - 服务端支持 admin API
"""
from __future__ import annotations
import json
from typing import List, Dict, Tuple, Any

from .s3_client_v1 import S3ClientV1


class S3ClientV2(S3ClientV1):
    """S3 客户端 V2 - 完整 Admin API 支持"""

    def _try_init_admin(self) -> None:
        """V2: 优先使用 minio.admin.MinioAdmin (兼容 minio.minioadmin)"""
        import re

        try:
            from minio.credentials import StaticProvider
        except ImportError:
            super()._try_init_admin()
            return

        MinioAdmin = None
        try:
            from minio.admin import MinioAdmin
        except ImportError:
            try:
                from minio.minioadmin import MinioAdmin
            except ImportError:
                MinioAdmin = None

        if MinioAdmin is None:
            super()._try_init_admin()
            return

        ep_clean = re.sub(r"^https?://", "", self.endpoint)
        try:
            self._admin_client = MinioAdmin(
                endpoint=ep_clean,
                credentials=StaticProvider(self.ak, self.sk),
                secure=self.ssl,
            )
        except Exception:
            self._admin_client = None

    # V2 重写 Admin 方法,使用稳定的 MinioAdmin API

    def admin_list_users(self) -> Tuple[bool, List[Dict[str, Any]]]:
        if not self._admin_client:
            return False, []
        try:
            raw = self._admin_client.user_list()
            data = json.loads(raw) if isinstance(raw, str) else raw
            users = []
            for ak, info in (data or {}).items():
                if isinstance(info, dict):
                    users.append({
                        "access_key": ak,
                        "status": info.get("status", "enabled"),
                        "policy": info.get("policyName", "-"),
                    })
            return True, users
        except Exception as e:
            return False, f"获取用户列表失败: {e}"

    def admin_create_user(self, ak: str, sk: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.user_add(ak, sk)
            return True, f"用户 {ak} 创建成功"
        except Exception as e:
            err = str(e)
            if "exists" in err.lower() or "already" in err.lower():
                return False, f"用户 {ak} 已存在"
            return False, err

    def admin_delete_user(self, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.user_remove(ak)
            return True, f"用户 {ak} 已删除"
        except Exception as e:
            err = str(e)
            if "not found" in err.lower():
                return False, f"用户 {ak} 不存在"
            return False, err

    def admin_enable_user(self, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.user_enable(ak)
            return True, f"用户 {ak} 已启用"
        except Exception as e:
            return False, str(e)

    def admin_disable_user(self, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.user_disable(ak)
            return True, f"用户 {ak} 已禁用"
        except Exception as e:
            return False, str(e)

    def admin_list_policies(self) -> Tuple[bool, List[str]]:
        if not self._admin_client:
            return False, []
        try:
            raw = self._admin_client.policy_list()
            data = json.loads(raw) if isinstance(raw, str) else raw
            return True, list(data.keys()) if isinstance(data, dict) else list(data)
        except Exception as e:
            return False, f"获取策略失败: {e}"

    def admin_get_policy(self, name: str) -> Tuple[bool, Any]:
        """获取单个策略的 JSON 内容 (dict)"""
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            raw = self._admin_client.policy_info(name)
            if isinstance(raw, str):
                return True, json.loads(raw)
            return True, raw
        except Exception as e:
            return False, str(e)

    def admin_create_policy(self, name: str, content: Dict) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            # MinioAdmin.policy_add(name, policy_file=..., policy=...) - dict 必须走 policy= 关键字
            self._admin_client.policy_add(name, policy=content)
            return True, f"策略 {name} 创建成功"
        except Exception as e:
            err = str(e)
            if "exists" in err.lower() or "already" in err.lower():
                return False, f"策略 {name} 已存在"
            return False, err

    def admin_delete_policy(self, name: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.policy_remove(name)
            return True, f"策略 {name} 已删除"
        except Exception as e:
            err = str(e)
            if "not found" in err.lower():
                return False, f"策略 {name} 不存在"
            return False, err

    def admin_attach_policy(self, policy: str, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            # MinioAdmin.attach_policy(policies: list[str], user=...) - 必须传列表
            self._admin_client.attach_policy([policy], user=ak)
            return True, f"策略 {policy} 已附加到 {ak}"
        except Exception as e:
            return False, str(e)

    def admin_detach_policy(self, policy: str, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.detach_policy([policy], user=ak)
            return True, f"策略 {policy} 已从 {ak} 分离"
        except Exception as e:
            return False, str(e)

    def admin_get_server_info(self) -> Tuple[bool, Dict[str, Any]]:
        if not self._admin_client:
            return False, {}
        try:
            raw = self._admin_client.info()
            data = json.loads(raw) if isinstance(raw, str) else raw
            return True, data if isinstance(data, dict) else {}
        except Exception:
            return False, {}

    # ==================== V2 扩展: 组/服务账号/桶配额 ====================

    def admin_create_group(self, name: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.group_add(name)
            return True, f"组 {name} 创建成功"
        except Exception as e:
            return False, str(e)

    def admin_list_groups(self) -> Tuple[bool, List[str]]:
        if not self._admin_client:
            return False, []
        try:
            raw = self._admin_client.group_list()
            data = json.loads(raw) if isinstance(raw, str) else raw
            return True, list(data) if isinstance(data, list) else list(data.keys())
        except Exception:
            return False, []

    def admin_delete_group(self, name: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.group_remove(name)
            return True, f"组 {name} 已删除"
        except Exception as e:
            return False, str(e)

    def set_bucket_quota(self, bucket: str, quota_mb: int) -> Tuple[bool, str]:
        """设置桶配额 (MB)"""
        if not self._admin_client:
            return False, "Admin API 不可用"
        try:
            self._admin_client.bucket_quota_set(bucket, quota_mb)
            return True, f"桶 {bucket} 配额已设置为 {quota_mb}MB"
        except Exception as e:
            return False, str(e)
