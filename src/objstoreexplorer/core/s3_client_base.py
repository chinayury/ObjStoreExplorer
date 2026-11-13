# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""S3 客户端抽象基类

定义统一的 S3 客户端接口,供 V1/V2 实现。
所有方法返回 Tuple[bool, Any] 统一结果模式,调用方明确处理成功/失败。

能力感知 (借鉴 cagnard「能力感知的提供者契约」):
    异构 S3 兼容后端并非都支持版本控制 / 生命周期 / CORS。客户端在
    运行时把「明确不被支持的操作」记入 _unsupported_ops, UI 通过
    unsupported_ops 属性读取并对相关入口做降级提示, 而不是对每个
    后端做统一假设、等用户点了才报错。
"""
from __future__ import annotations
import inspect
import threading
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple, Callable, Any


ProgressCallback = Optional[Callable[[float], None]]
"""进度回调函数: callback(progress: 0.0-1.0)"""


# 操作名 → 前端导航页 (Web 侧降级标记用; 桌面侧同名入口同理)
OP_NAV_MAP: Dict[str, str] = {
    "versioning": "versioning",
    "lifecycle": "lifecycle",
    "cors": "policies",
    "policy": "policies",
    "users": "users",
    "object_lock": "versioning",
    "multipart": "buckets",
}


def is_unsupported_message(msg: str) -> bool:
    """判断错误信息是否表示「服务端不支持该操作」

    覆盖: 中文本地化文案 ("Admin API 不支持 X")、S3 标准错误码
    (NotImplemented / NotSupported / UnsupportedOperation)、
    以及 minio-py 侧的表达 ("不支持" 子串兜底)。
    """
    if not msg:
        return False
    low = msg.lower()
    return any(k in low for k in (
        "不支持", "notimplemented", "not supported", "unsupported",
    ))


def client_supports_max_items(client: Any) -> bool:
    """探测客户端的 list_objects 是否接受 max_items 关键字

    历史包袱: 早期实现的 list_objects 只有 (bucket, prefix, recursive) 三个
    参数 (测试里的 Mock 客户端、以及第三方自建客户端仍是这样)。统一给
    list_objects 加上限时必须**探测**而不是硬传, 否则一调用就 TypeError。
    探测不到签名时 (C 扩展 / MagicMock) 默认按"支持"处理, 由调用方兜底。
    """
    fn = getattr(client, "list_objects", None)
    if fn is None:
        return False
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    if "max_items" in sig.parameters:
        return True
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )


def list_objects_with_limit(
    client: Any,
    bucket: str,
    prefix: str = "",
    recursive: bool = False,
    max_items: int = 0,
) -> Tuple[bool, Any]:
    """带条数上限地调用客户端 list_objects

    max_items <= 0 = 不限制 (保持旧行为)。
    客户端不接受 max_items 时退回不带上限的调用 —— 宁可多列, 不可崩。
    """
    if max_items and max_items > 0 and client_supports_max_items(client):
        return client.list_objects(bucket, prefix, recursive, max_items=max_items)
    return client.list_objects(bucket, prefix, recursive)


class S3ClientBase(ABC):
    """S3/MinIO 客户端抽象基类

    所有方法返回 (success, result) 元组:
        - success=True, result=实际数据
        - success=False, result=错误消息

    子类必须实现所有 @abstractmethod。
    """

    def __init__(self, endpoint: str, ak: str, sk: str, ssl: bool = False):
        """初始化客户端 (不连接)

        Args:
            endpoint: 服务器地址 (不含协议)
            ak: Access Key
            sk: Secret Key
            ssl: 是否使用 HTTPS
        """
        self.endpoint = endpoint
        self.ak = ak
        self.sk = sk
        self.ssl = ssl
        self._client = None
        self._admin_client = None
        self._server_version: Optional[str] = None
        # 预签名外链 Host (D9): 容器内网部署时, 连接用内网地址 (如
        # minio:9000) 而分享链接要能被外网访问 —— 主机名是 SigV4 签名
        # 的一部分, 只能按外部主机名重新签名, 不能字符串改写。
        self.external_host: str = ""
        # 运行时记录的「服务端不支持的操作」集合 (能力降级追踪)
        self._unsupported_ops: set = set()
        self._unsupported_lock = threading.Lock()

    # ==================== 能力感知 ====================

    def note_unsupported(self, op: str) -> None:
        """记录一个服务端明确不支持的操作 (幂等, 线程安全)"""
        if not op:
            return
        with self._unsupported_lock:
            self._unsupported_ops.add(op)

    @property
    def unsupported_ops(self) -> Tuple[str, ...]:
        """已确认不被当前服务端支持的操作名 (排序稳定, UI 用)"""
        with self._unsupported_lock:
            return tuple(sorted(self._unsupported_ops))

    def track_result(self, op: str, ok: bool, msg: str) -> None:
        """把一次操作的结果过一遍能力追踪: 失败且是「不支持」类错误时记录

        在 Web 路由 / 桌面页面的操作出口调用, 一行接线:
            self._client.track_result("versioning", ok, msg)
        """
        if not ok and is_unsupported_message(msg or ""):
            self.note_unsupported(op)

    # ==================== 连接管理 ====================

    @abstractmethod
    def connect(self) -> Tuple[bool, str]:
        """建立连接 (验证可用性)"""
        pass

    def close(self) -> None:
        """关闭连接 (子类可重写)"""
        self._client = None
        self._admin_client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    @property
    def admin_available(self) -> bool:
        return self._admin_client is not None

    def probe_admin(self) -> bool:
        """实际探测当前凭证是否具备 admin 权限。

        默认实现:试调用一次 admin_list_users,不抛异常且首元素不为空即视为有权限。
        子类可重写以提供更便宜的判断。
        """
        if not self.admin_available:
            return False
        try:
            ok, _ = self.admin_list_users()
            return bool(ok)
        except Exception:
            return False

    @property
    def server_version(self) -> Optional[str]:
        return self._server_version

    # ==================== 桶操作 ====================

    @abstractmethod
    def list_buckets(self) -> Tuple[bool, List[str]]:
        """列出所有桶"""
        pass

    @abstractmethod
    def bucket_exists(self, bucket: str) -> bool:
        """检查桶是否存在"""
        pass

    @abstractmethod
    def create_bucket(self, bucket: str) -> Tuple[bool, str]:
        """创建桶"""
        pass

    @abstractmethod
    def delete_bucket(self, bucket: str, force: bool = False) -> Tuple[bool, str]:
        """删除桶 (force=True 时先清空所有对象)"""
        pass

    # ==================== 对象操作 ====================

    @abstractmethod
    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        recursive: bool = False,
        max_items: int = 0,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """列出对象

        Args:
            bucket: 桶名
            prefix: 前缀
            recursive: 是否递归
            max_items: 最多返回多少条; 0 = 不限制。达到上限即截断,
                       截断状态用 last_list_truncated() 查询 (线程本地)。

        Returns:
            (success, [{name, size, last_modified, is_dir, etag}, ...])
        """
        pass

    def last_list_truncated(self) -> bool:
        """当前线程最近一次 list_objects 是否被 max_items 截断"""
        return False

    @abstractmethod
    def upload(
        self,
        local_path: str,
        bucket: str,
        key: str,
        progress_callback: ProgressCallback = None,
    ) -> Tuple[bool, str]:
        """上传文件"""
        pass

    @abstractmethod
    def download(
        self,
        bucket: str,
        key: str,
        local_path: str,
        progress_callback: ProgressCallback = None,
    ) -> Tuple[bool, str]:
        """下载文件"""
        pass

    @abstractmethod
    def delete(self, bucket: str, key: str) -> Tuple[bool, str]:
        """删除对象"""
        pass

    @abstractmethod
    def copy(
        self,
        src_bucket: str,
        src_key: str,
        dst_bucket: str,
        dst_key: str,
    ) -> Tuple[bool, str]:
        """复制对象"""
        pass

    @abstractmethod
    def move(
        self,
        bucket: str,
        old_key: str,
        new_key: str,
    ) -> Tuple[bool, str]:
        """移动/重命名 (同桶内)"""
        pass

    @abstractmethod
    def create_folder(self, bucket: str, prefix: str) -> Tuple[bool, str]:
        """创建文件夹 (在桶内放一个空对象以 / 结尾)"""
        pass

    @abstractmethod
    def stat_object(self, bucket: str, key: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """获取对象元数据"""
        pass

    # ==================== 高级功能 (可选) ====================

    def get_presigned_url(
        self,
        bucket: str,
        key: str,
        expires: int = 3600,
    ) -> Tuple[bool, Optional[str]]:
        """获取预签名下载 URL"""
        return False, "当前客户端不支持预签名 URL"

    def get_bucket_versioning(self, bucket: str) -> Tuple[bool, Optional[str]]:
        """获取桶版本控制状态 (Enabled/Suspended)"""
        return False, "当前客户端不支持版本控制"

    def set_bucket_versioning(self, bucket: str, status: str) -> Tuple[bool, str]:
        """设置桶版本控制"""
        return False, "当前客户端不支持版本控制"

    def get_bucket_lifecycle(self, bucket: str) -> Tuple[bool, Optional[object]]:
        """获取桶生命周期配置
        Returns: (True, None)=未配置, (True, LifecycleConfig)=已配置"""
        return False, "当前客户端不支持生命周期"

    def set_bucket_lifecycle(self, bucket: str, config: Dict) -> Tuple[bool, str]:
        """设置桶生命周期配置"""
        return False, "当前客户端不支持生命周期"

    def delete_bucket_lifecycle(self, bucket: str) -> Tuple[bool, str]:
        return False, "当前客户端不支持生命周期"

    # ==================== 桶策略 (匿名访问 / 防盗链) ====================
    # 对象存储控制台的常规能力: 设置"公共读"、限制来源 IP、跨域等。
    # 之前只能改 IAM 用户策略, 桶本身的访问策略完全够不着。

    def get_bucket_policy(self, bucket: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """读取桶策略 (JSON)

        Returns:
            (True, dict)   已配置
            (True, None)   未配置任何策略 (不是错误)
        """
        return False, "当前客户端不支持桶策略"

    def set_bucket_policy(self, bucket: str, policy: Dict[str, Any]) -> Tuple[bool, str]:
        """设置桶策略 (JSON 字符串)"""
        return False, "当前客户端不支持桶策略"

    def delete_bucket_policy(self, bucket: str) -> Tuple[bool, str]:
        """删除桶策略 (恢复私有)"""
        return False, "当前客户端不支持桶策略"

    # ==================== 对象元数据与标签 ====================
    # 之前 stat_object 只返回 6 个字段, 拿不到 user metadata 与 tag,
    # 导致"按标签检索""批量改元数据"这类需求完全做不到。

    def get_object_tags(self, bucket: str, key: str) -> Tuple[bool, Dict[str, str]]:
        """读取对象标签 (S3 Tagging)"""
        return False, "当前客户端不支持对象标签"

    def set_object_tags(self, bucket: str, key: str, tags: Dict[str, str]) -> Tuple[bool, str]:
        """设置对象标签 (整体替换)"""
        return False, "当前客户端不支持对象标签"

    def delete_object_tags(self, bucket: str, key: str) -> Tuple[bool, str]:
        """清除对象标签"""
        return False, "当前客户端不支持对象标签"

    # ==================== 对象版本 ====================
    # 能开关版本控制, 但看不到历史版本 —— S3 误覆盖/误删之后用户无法自救。
    # 而且 delete_bucket(force=True) 在版本化桶上只删当前版本, 桶仍非空。

    def list_object_versions(
        self,
        bucket: str,
        prefix: str = "",
        max_items: int = 0,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """列出对象的历史版本

        Returns:
            (True, [{key, version_id, is_latest, size, last_modified, is_delete_marker}, ...])
        """
        return False, "当前客户端不支持版本浏览"

    def remove_object_version(
        self,
        bucket: str,
        key: str,
        version_id: str,
    ) -> Tuple[bool, str]:
        """删除指定版本"""
        return False, "当前客户端不支持版本浏览"

    def copy_object_version(
        self,
        bucket: str,
        key: str,
        version_id: str,
        dest_key: str,
    ) -> Tuple[bool, str]:
        """把某个历史版本恢复为一个新的当前版本 (误覆盖后的回滚)"""
        return False, "当前客户端不支持版本浏览"

    def delete_all_versions(self, bucket: str) -> Tuple[bool, str]:
        """清空桶内全部版本 (含删除标记), 供强制删桶使用"""
        return False, "当前客户端不支持版本浏览"

    # ==================== Admin 操作 (V2 默认不支持) ====================

    def admin_list_users(self) -> Tuple[bool, List[Dict[str, Any]]]:
        return False, []

    def admin_create_user(self, ak: str, sk: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_delete_user(self, ak: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_enable_user(self, ak: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_disable_user(self, ak: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_list_policies(self) -> Tuple[bool, List[str]]:
        return False, []

    def admin_create_policy(self, name: str, content: Dict) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_delete_policy(self, name: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_attach_policy(self, policy: str, ak: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_detach_policy(self, policy: str, ak: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_create_group(self, name: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_list_groups(self) -> Tuple[bool, List[str]]:
        return False, []

    def admin_delete_group(self, name: str) -> Tuple[bool, str]:
        return False, "Admin API 不可用"

    def admin_get_server_info(self) -> Tuple[bool, Dict[str, Any]]:
        return False, {}
