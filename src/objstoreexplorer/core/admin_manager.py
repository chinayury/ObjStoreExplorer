# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""AdminManager - 管理员业务 (用户/策略/组)

封装管理员相关操作:
    - 用户 CRUD + 启用/禁用
    - 策略 CRUD + 附加/分离
    - 组 CRUD (V2)
    - 一键创建用户+策略 (含回滚)
    - 强密码生成
"""
from __future__ import annotations
import secrets
import string
from typing import List, Dict, Optional, Tuple, Any

from .s3_client_base import S3ClientBase
from ..config.exceptions import (
    ConnectionError,
)


# 策略类型模板
POLICY_TEMPLATES = {
    # readonly/readwrite 补 s3:GetBucketLocation —
    # 几乎所有 S3 SDK (minio-py 未显式给 region 时 / 图床等客户端) 上传前会先
    # 调 GetBucketLocation 探测桶区域, 缺这个动作直接 AccessDenied (resource: /桶名),
    # 实测于 2026-09-11 图床上传 itmsky 全军覆没一案。
    "readonly": lambda bucket: {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:GetBucketLocation", "s3:GetObject", "s3:ListBucket"],
            "Resource": [
                f"arn:aws:s3:::{bucket}",
                f"arn:aws:s3:::{bucket}/*",
            ],
        }],
    },
    "readwrite": lambda bucket: {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "s3:GetBucketLocation", "s3:ListBucket",
                "s3:GetObject", "s3:PutObject",
                "s3:DeleteObject",
            ],
            "Resource": [
                f"arn:aws:s3:::{bucket}",
                f"arn:aws:s3:::{bucket}/*",
            ],
        }],
    },
    "full": lambda bucket: {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:*"],
            "Resource": [
                f"arn:aws:s3:::{bucket}",
                f"arn:aws:s3:::{bucket}/*",
            ],
        }],
    },
}


def generate_strong_password(length: int = 16) -> str:
    """生成强密码

    包含大小写字母、数字、特殊字符,长度 >= 8
    """
    if length < 8:
        length = 8

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"

    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%^&*" for c in password)):
            return password


class AdminManager:
    """管理员管理器"""

    def __init__(self, s3_client: S3ClientBase):
        if s3_client is None or not s3_client.is_connected:
            raise ConnectionError("S3 客户端未连接", code="NotConnected")
        self._client = s3_client

    @property
    def admin_available(self) -> bool:
        return self._client.admin_available

    # ==================== 用户管理 ====================

    def list_users(self) -> Tuple[bool, List[Dict[str, Any]]]:
        """列出所有用户

        Returns:
            (success, [{access_key, status, policy}, ...])
        """
        if not self.admin_available:
            return False, "Admin API 不可用 (当前客户端或服务不支持)"
        return self._client.admin_list_users()

    def list_users_with_detail(self) -> Tuple[bool, List[Dict[str, Any]]]:
        """列出用户 (含每个用户的 policyName/memberOf 详情, 略慢)"""
        if not self.admin_available:
            return False, "Admin API 不可用"
        ok, users = self._client.admin_list_users()
        if not ok:
            return False, users
        # 增强: 逐个查 user_info 拿 policyName
        for u in users:
            ak = u.get("access_key", "")
            if not ak:
                continue
            ok_info, info = self._client.admin_get_user_info(ak)
            if ok_info and isinstance(info, dict):
                u["status"] = info.get("status", u.get("status", "enabled"))
                u["policy"] = info.get("policyName", u.get("policy", "-"))
                u["member_of"] = info.get("memberOf", [])
        return True, users

    def create_user(self, access_key: str, secret_key: str) -> Tuple[bool, str]:
        """创建用户"""
        if not access_key or not secret_key:
            return False, "Access Key 和 Secret Key 不能为空"
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_create_user(access_key, secret_key)

    def delete_user(self, access_key: str) -> Tuple[bool, str]:
        """删除用户"""
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_delete_user(access_key)

    def enable_user(self, access_key: str) -> Tuple[bool, str]:
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_enable_user(access_key)

    def disable_user(self, access_key: str) -> Tuple[bool, str]:
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_disable_user(access_key)

    def reset_user_secret(self, access_key: str, new_secret_key: str) -> Tuple[bool, str]:
        """重置用户 Secret Key (minio 限制: 无法显示当前 SK, 只能 reset)

        保留: 用户附加的策略, 自动重新附加。
        """
        if not access_key or not new_secret_key:
            return False, "用户名和新 Secret Key 不能为空"
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_reset_user_secret(access_key, new_secret_key)

    # ==================== 策略管理 ====================

    def list_policies(self) -> Tuple[bool, List[str]]:
        """列出所有策略"""
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_list_policies()

    def get_policy(self, name: str) -> Tuple[bool, Any]:
        """获取单个策略的 JSON 内容"""
        if not self.admin_available:
            return False, "Admin API 不可用"
        getter = getattr(self._client, "admin_get_policy", None)
        if getter is None:
            return False, "当前客户端不支持获取策略详情"
        return getter(name)

    def create_policy(self, name: str, content: Dict) -> Tuple[bool, str]:
        """创建策略

        Args:
            name: 策略名
            content: 策略内容 (dict, 将转为 JSON)
        """
        if not name:
            return False, "策略名不能为空"
        if not content:
            return False, "策略内容不能为空"
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_create_policy(name, content)

    def delete_policy(self, name: str) -> Tuple[bool, str]:
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_delete_policy(name)

    def update_policy_content(self, name: str, content: Dict) -> Tuple[bool, str]:
        """修改策略内容 (minio 限制: 删+建, 保留附加用户)"""
        if not name or not content:
            return False, "策略名和内容不能为空"
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_set_policy_content(name, content)

    def attach_policy(self, policy: str, access_key: str) -> Tuple[bool, str]:
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_attach_policy(policy, access_key)

    def detach_policy(self, policy: str, access_key: str) -> Tuple[bool, str]:
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_detach_policy(policy, access_key)

    # ==================== 策略模板 ====================

    def get_bucket_policy(self, bucket: str, policy_type: str = "readwrite") -> Dict:
        """根据模板生成桶策略定义

        Args:
            bucket: 桶名
            policy_type: readonly / readwrite / full

        Returns:
            策略 dict
        """
        if policy_type not in POLICY_TEMPLATES:
            policy_type = "readwrite"
        return POLICY_TEMPLATES[policy_type](bucket)

    def get_policy_types(self) -> Dict[str, str]:
        """获取策略类型说明"""
        return {
            "readonly": "只读 - 仅能查看和下载文件",
            "readwrite": "读写 - 可上传、下载、删除文件",
            "full": "完全控制 - 包含所有权限",
        }

    # ==================== 一键创建 桶 + 用户 + 策略 ====================

    def create_full_setup(
        self,
        bucket_name: str = "",
        access_key: str = "",
        policy_type: str = "readwrite",
        secret_key: Optional[str] = None,
        auth_bucket: Optional[str] = None,
    ) -> Dict[str, Any]:
        """一键创建: (可选)建桶 → 建用户 → 建策略 → 附加

        失败回滚: 任何一步失败, 撤销之前已创建的.

        Args:
            bucket_name: 新桶名 (可空; 空则不建桶, 只对 auth_bucket 建用户+策略)
            access_key: 用户名
            policy_type: readonly / readwrite / full
            secret_key: 留空则自动生成
            auth_bucket: 授权桶 (策略授予的桶)。新桶名非空时策略授予新桶,
                否则必须提供 auth_bucket。

        Returns:
            {
                success: bool,
                bucket_name, access_key, secret_key, policy_name, policy_type,
                steps: [{step, ok, message}, ...],
                error: str (仅失败)
            }
        """
        bucket_name = (bucket_name or "").strip()
        auth_bucket = (auth_bucket or "").strip()
        # 策略授予的桶: 新桶优先 (建新桶就是给它授权), 没填新桶则授权已有桶
        target_bucket = bucket_name or auth_bucket

        result: Dict[str, Any] = {
            "success": False,
            "bucket_name": target_bucket,
            "access_key": access_key,
            "secret_key": "",
            "policy_name": "",
            "policy_type": policy_type,
            "steps": [],
        }
        if not self.admin_available:
            result["error"] = "Admin API 不可用"
            return result
        if not access_key:
            result["error"] = "Access Key 不能为空"
            return result
        if not target_bucket:
            result["error"] = "新桶名和授权桶至少填一个"
            return result

        if not secret_key:
            secret_key = generate_strong_password(16)
        # ⚠ secret_key 只在"确实会用这个密码新建用户"时才对调用方有意义。
        #   旧实现在这里就把生成/传入的密码写进 result, 而用户存在性检查在
        #   下面第 2 步 —— 目标用户已存在时会走"跳过创建"分支, 那个密码
        #   从未提交给服务端, UI 却照样弹出来让用户复制, 拿去连接必然失败。
        #   这里先不写入, 等确认要新建用户时再赋值。
        policy_name = f"{target_bucket}-{policy_type}-policy"
        result["policy_name"] = policy_name

        bucket_created = False
        user_created = False
        user_existed = False
        policy_created = False

        # === 步骤 1: 创建桶 (填了新桶名才建; 没填则跳过) ===
        if bucket_name:
            from .bucket_manager import BucketManager  # 避免循环
            try:
                bm = BucketManager(self._client)
                ok, msg = bm.create_bucket(bucket_name)
                if ok:
                    bucket_created = True
                    result["steps"].append({"step": f"创建桶 {bucket_name}", "ok": True, "message": msg})
                elif "已存在" in msg or "exists" in msg.lower():
                    result["steps"].append({"step": f"桶 {bucket_name} 已存在, 跳过", "ok": True, "message": msg})
                else:
                    result["steps"].append({"step": f"创建桶 {bucket_name}", "ok": False, "message": msg})
                    result["error"] = f"创建桶失败: {msg}"
                    return result
            except Exception as e:
                result["steps"].append({"step": f"创建桶 {bucket_name}", "ok": False, "message": str(e)})
                result["error"] = f"创建桶异常: {e}"
                return result
        else:
            result["steps"].append({"step": f"跳过创建桶 (授权已有桶 {auth_bucket})", "ok": True, "message": ""})

        # === 步骤 2: 创建用户 ===
        # 检查用户是否已存在
        try:
            ok_info, info = self._client.admin_get_user_info(access_key)
            if ok_info and isinstance(info, dict):
                user_existed = True
        except Exception:
            pass

        if not user_existed:
            ok, msg = self._client.admin_create_user(access_key, secret_key)
            if ok:
                user_created = True
                # 确认真的用这个密码建了号, 这时才把密码交给调用方
                result["secret_key"] = secret_key
                result["steps"].append({"step": f"创建用户 {access_key}", "ok": True, "message": msg})
            elif "已存在" in msg:
                user_existed = True
                result["steps"].append({"step": f"用户 {access_key} 已存在, 跳过", "ok": True, "message": msg})
            else:
                # 回滚桶
                if bucket_created:
                    try:
                        self._client.delete_bucket(bucket_name)
                    except Exception:
                        pass
                result["steps"].append({"step": f"创建用户 {access_key}", "ok": False, "message": msg})
                result["error"] = f"创建用户失败: {msg}"
                return result
        else:
            # 用户已存在 → 我们没有它的密码, 更不能凭空造一个显示给用户。
            # 明确写成占位说明, 与同文件 create_user_with_policy 的处理保持一致。
            result["secret_key"] = "(用户已存在, 密码不可查询; 如需重置请用「重置密码」)"
            result["steps"].append({"step": f"用户 {access_key} 已存在, 跳过创建", "ok": True, "message": ""})

        # === 步骤 3: 创建策略 (如果不存在) ===
        ok, policies = self._client.admin_list_policies()
        if not ok:
            policies = []
        if policy_name not in policies:
            policy_def = self.get_bucket_policy(target_bucket, policy_type)
            ok, msg = self._client.admin_create_policy(policy_name, policy_def)
            if ok:
                policy_created = True
                result["steps"].append({"step": f"创建策略 {policy_name}", "ok": True, "message": msg})
            else:
                # 回滚: 用户 + 桶
                if user_created:
                    try:
                        self._client.admin_delete_user(access_key)
                    except Exception:
                        pass
                if bucket_created:
                    try:
                        self._client.delete_bucket(bucket_name)
                    except Exception:
                        pass
                result["steps"].append({"step": f"创建策略 {policy_name}", "ok": False, "message": msg})
                result["error"] = f"创建策略失败: {msg}"
                return result
        else:
            result["steps"].append({"step": f"策略 {policy_name} 已存在, 跳过创建", "ok": True, "message": ""})

        # === 步骤 4: 附加策略到用户 ===
        ok, msg = self._client.admin_attach_policy(policy_name, access_key)
        if ok or "already" in msg.lower() or "no net effect" in msg.lower():
            result["steps"].append({"step": f"附加策略到 {access_key}", "ok": True, "message": msg})
        else:
            # 回滚: 策略(新建) + 用户(新建) + 桶
            if policy_created:
                try:
                    self._client.admin_delete_policy(policy_name)
                except Exception:
                    pass
            if user_created:
                try:
                    self._client.admin_delete_user(access_key)
                except Exception:
                    pass
            if bucket_created:
                try:
                    self._client.delete_bucket(bucket_name)
                except Exception:
                    pass
            result["steps"].append({"step": f"附加策略到 {access_key}", "ok": False, "message": msg})
            result["error"] = f"附加策略失败: {msg}"
            return result

        result["success"] = True
        result["existing_user"] = user_existed
        return result

    # ==================== 一键创建用户+策略 ====================

    def create_user_with_policy(
        self,
        access_key: str,
        bucket_name: str,
        policy_type: str = "readwrite",
    ) -> Dict[str, Any]:
        """一键创建用户并自动创建+附加策略

        Args:
            access_key: 新的用户名
            bucket_name: 要授权的桶
            policy_type: readonly/readwrite/full

        Returns:
            {
                success: bool,
                access_key, secret_key, policy_name, bucket_name, policy_type,
                error: str (仅失败时)
            }
        """
        result = {
            "success": False,
            "access_key": access_key,
            "secret_key": "",
            "policy_name": "",
            "bucket_name": bucket_name,
            "policy_type": policy_type,
        }

        if not self.admin_available:
            result["error"] = "Admin API 不可用"
            return result

        if not access_key or not bucket_name:
            result["error"] = "Access Key 和桶名不能为空"
            return result

        secret_key = generate_strong_password()
        policy_name = f"{bucket_name}-{policy_type}-policy"

        # 1. 检查用户是否已存在
        existing_user = None
        ok, users = self._client.admin_list_users()
        if ok and isinstance(users, list):
            existing_map = {u.get("access_key"): u for u in users}
            existing_user = existing_map.get(access_key)

        user_existed = existing_user is not None
        # M-10: secret_key 只在创建成功后才写入 result —— 失败分支若带着
        # 这把从未提交给服务端的随机口令返回, 调用方会拿到一个连不上的假密码。
        result["policy_name"] = policy_name

        # 2. 创建用户 (新用户)
        if not user_existed:
            ok, msg = self._client.admin_create_user(access_key, secret_key)
            if not ok:
                result["error"] = f"创建用户失败: {msg}"
                result["secret_key"] = ""      # 失败不得回传未提交的口令
                return result
            result["secret_key"] = secret_key
        else:
            # 已存在用户,使用占位密码 (无法查回, 这是 MinIO 的限制)
            result["secret_key"] = "(用户已存在,密码不可查询)"
            # 摘除旧策略前先快照【完整】策略列表。
            # 旧实现只 detach old_policy 一个名字, 而 MinIO 的 detach 语义是
            # "把用户策略列表替换成我传的" —— 挂多策略的用户会被抹成只剩
            # old_policy, 其余全丢。这里改成把"去掉旧策略后的完整列表"
            # 整体写回, 并且失败时用它还原。
            snapshotter = getattr(self._client, "_get_user_policies", None)
            old_policies = snapshotter(access_key) if snapshotter else []
            if not old_policies:
                info = existing_user.get("policy", "")
                old_policies = [info] if info else []
            setter = getattr(self._client, "admin_set_user_policies", None)
            if old_policies and setter and old_policies != [policy_name]:
                # 目标策略本来就在挂着, 什么都不用摘
                if policy_name not in old_policies:
                    remaining = [p for p in old_policies if p != policy_name or not p]
                    if not setter(access_key, remaining)[0]:
                        result["error"] = "已存在用户, 调整策略列表失败, 操作中止。"
                        return result
            result["_policy_snapshot"] = old_policies

        # 3. 检查策略是否存在 (只调一次,拿到结果直接用)
        ok, policies = self._client.admin_list_policies()
        if not ok:
            policies = []
        if policy_name not in policies:
            policy_def = self.get_bucket_policy(bucket_name, policy_type)
            ok, msg = self._client.admin_create_policy(policy_name, policy_def)
            if not ok:
                # 回滚: 删除刚创建的用户 / 还原已有用户的策略列表
                if not user_existed:
                    self._client.admin_delete_user(access_key)
                else:
                    snap = result.pop("_policy_snapshot", None)
                    setter = getattr(self._client, "admin_set_user_policies", None)
                    if snap and setter:
                        setter(access_key, snap)
                        result["error"] = (
                            f"创建策略失败: {msg}。已把用户 {access_key} 的策略列表"
                            f"还原为修改前状态。"
                        )
                        return result
                result["error"] = f"创建策略失败: {msg}"
                return result

        # 4. 附加策略 (整体设置, 不是增量附加 —— 保住用户的其他策略)
        setter = getattr(self._client, "admin_set_user_policies", None)
        if setter:
            snap = result.pop("_policy_snapshot", None) or []
            wanted = [p for p in snap if p != policy_name]
            wanted.append(policy_name)
            ok, msg = setter(access_key, wanted)
        else:
            ok, msg = self._client.admin_attach_policy(policy_name, access_key)
        if not ok and "already" not in msg.lower() and "no net effect" not in msg.lower():
            if not user_existed:
                self._client.admin_delete_user(access_key)
            else:
                snap = result.pop("_policy_snapshot", None) or []
                setter2 = getattr(self._client, "admin_set_user_policies", None)
                if snap and setter2:
                    setter2(access_key, snap)
                    result["error"] = f"附加策略失败: {msg}。已还原用户原有策略列表。"
                    return result
            result["error"] = f"附加策略失败: {msg}"
            return result

        result.pop("_policy_snapshot", None)
        result["success"] = True
        result["existing_user"] = user_existed
        return result

    # ==================== 组管理 (V2) ====================

    def list_groups(self) -> Tuple[bool, List[str]]:
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_list_groups()

    def create_group(self, name: str) -> Tuple[bool, str]:
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_create_group(name)

    def delete_group(self, name: str) -> Tuple[bool, str]:
        if not self.admin_available:
            return False, "Admin API 不可用"
        return self._client.admin_delete_group(name)

    # ==================== 服务信息 ====================

    def get_server_info(self) -> Dict[str, Any]:
        """获取服务信息"""
        info = {
            "version": "unknown",
            "uptime": "unknown",
            "status": "connected" if self._client.is_connected else "disconnected",
            "admin_available": self.admin_available,
        }
        if self._client.server_version:
            info["version"] = self._client.server_version
        if self.admin_available:
            ok, srv_info = self._client.admin_get_server_info()
            if ok and srv_info:
                info.update(srv_info)
        return info
