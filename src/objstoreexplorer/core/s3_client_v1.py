# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""S3 客户端 V1 实现 - 兼容 minio-py 7.x

仅使用 minio 公共 API,所有方法返回 Tuple[bool, ...] 统一结果。
支持所有 S3 基础操作 + 简化 Admin API (通过 has_attr 探测)。
"""
from __future__ import annotations
import os
import io
import json
import re
import logging
import threading
from typing import List, Dict, Optional, Tuple, Any
from datetime import timedelta

from .s3_client_base import S3ClientBase, ProgressCallback
from ..config.exceptions import (
    map_s3_error,
    ServerUnavailableError,
    AuthenticationError,
)


class S3ClientV1(S3ClientBase):
    """S3 客户端 V1 - 适用于所有 minio-py 版本 (基础功能)

    Admin 操作通过 has_attr 探测,不支持时返回 False。
    """

    # ==================== 列表截断状态 (线程本地) ====================

    def _list_tls(self) -> threading.local:
        """列表状态的线程本地存储 (懒创建, 兼容 __new__ 出的裸实例)"""
        tls = self.__dict__.get("_list_tls_obj")
        if tls is None:
            tls = threading.local()
            self.__dict__["_list_tls_obj"] = tls
        return tls

    @property
    def _last_list_truncated(self) -> bool:
        """兼容旧属性: 当前线程最近一次 list_objects 是否被截断"""
        return bool(getattr(self._list_tls(), "truncated", False))

    @_last_list_truncated.setter
    def _last_list_truncated(self, value: bool) -> None:
        self._list_tls().truncated = bool(value)

    def last_list_truncated(self) -> bool:
        """公开查询接口: 当前线程最近一次 list_objects 是否达到 max_items 截断

        概览页会 4 线程并发对每个桶做 recursive 列表, 截断标志必须是
        **线程本地** 的 —— 早期版本写 `self._last_list_truncated` 实例属性,
        并发下互相覆盖, A 桶的截断状态会显示到 B 桶上 (而且根本没人读它)。
        """
        return bool(getattr(self._list_tls(), "truncated", False))

    def connect(self) -> Tuple[bool, str]:
        """建立连接"""
        try:
            from minio import Minio
        except ImportError as e:
            return False, f"缺少 minio 库: {e}"

        try:
            ep_clean = re.sub(r"^https?://", "", self.endpoint)
            self._client = Minio(
                ep_clean,
                access_key=self.ak,
                secret_key=self.sk,
                secure=self.ssl,
            )
            self._client.list_buckets()
            self._try_init_admin()
            self._detect_version()
            return True, "连接成功"
        except Exception as e:
            self._client = None
            mapped = map_s3_error(e)
            if isinstance(mapped, ServerUnavailableError):
                return False, f"服务不可用: {mapped.message}"
            if isinstance(mapped, AuthenticationError):
                return False, f"认证失败: {mapped.message}"
            return False, f"连接失败: {mapped.message}"

    def _try_init_admin(self) -> None:
        """尝试初始化 admin 客户端 (优雅降级)"""
        ep_clean = re.sub(r"^https?://", "", self.endpoint)
        try:
            from minio.credentials import StaticProvider
            MinioAdmin = None
            try:
                from minio.minioadmin import MinioAdmin
            except ImportError:
                try:
                    from minio import MinioAdmin
                except ImportError:
                    MinioAdmin = None

            if MinioAdmin is None:
                self._admin_client = None
                return

            try:
                self._admin_client = MinioAdmin(
                    endpoint=ep_clean,
                    credentials=StaticProvider(self.ak, self.sk),
                    secure=self.ssl,
                )
            except TypeError:
                # 旧签名: MinioAdmin(endpoint, access_key=..., secret_key=...)
                try:
                    self._admin_client = MinioAdmin(
                        ep_clean,
                        access_key=self.ak,
                        secret_key=self.sk,
                        secure=self.ssl,
                    )
                except Exception:
                    self._admin_client = None
        except Exception:
            self._admin_client = None

    def _detect_version(self) -> None:
        """探测服务器版本"""
        try:
            if hasattr(self._client, "info"):
                info = self._client.info()
                if isinstance(info, dict):
                    self._server_version = info.get("version", "unknown")
                elif hasattr(info, "server") and hasattr(info.server, "version"):
                    self._server_version = info.server.version
        except Exception:
            pass

    # ==================== 桶操作 ====================

    def list_buckets(self) -> Tuple[bool, List[str]]:
        if not self._client:
            return False, "客户端未连接"
        try:
            buckets = [b.name for b in self._client.list_buckets()]
            return True, buckets
        except Exception as e:
            return False, f"列出桶失败: {map_s3_error(e).message}"

    def bucket_exists(self, bucket: str) -> bool:
        if not self._client:
            return False
        try:
            return self._client.bucket_exists(bucket)
        except Exception:
            return False

    def create_bucket(self, bucket: str) -> Tuple[bool, str]:
        if not self._client:
            return False, "客户端未连接"
        try:
            if self._client.bucket_exists(bucket):
                return False, f"桶 {bucket} 已存在"
            self._client.make_bucket(bucket)
            return True, f"桶 {bucket} 创建成功"
        except Exception as e:
            return False, map_s3_error(e).message

    def delete_bucket(self, bucket: str, force: bool = False) -> Tuple[bool, str]:
        """删除桶

        修复: 不再做 `bucket_exists` 预检 (HEAD bucket 偶发 404,
        会让 UI 误报 "桶 X 不存在", 但 list_buckets 列表里能看到)。
        直接尝试 list_objects / remove_bucket, 由 S3 服务端的 404
        错误判断桶是否存在, 给出准确的错误消息。

        force=True 时: 先递归列对象逐个删, 再删桶; 任一对象删失败
        立即返回详细错误 (前 5 个失败对象 + 总数)。
        """
        if not self._client:
            return False, "客户端未连接"
        try:
            if force:
                # ⚠ 版本化桶必须先清历史版本。
                #   批量接口 remove_objects 不带 versionId 时【只删当前版本】,
                #   历史版本原地不动, 后面 remove_bucket 照样报 BucketNotEmpty ——
                #   用户看到的是"我明明清空了为什么还删不掉"。
                try:
                    ok_v, vstatus = self.get_bucket_versioning(bucket)
                except Exception:
                    ok_v, vstatus = False, None
                if ok_v and vstatus == "Enabled":
                    ok_dv, dv_msg = self.delete_all_versions(bucket)
                    if not ok_dv:
                        return False, f"清空历史版本失败: {dv_msg}"
                    # 历史版本清完后, 当前版本可能还需要再清一遍
                    # (remove_object 带 version_id 已覆盖, 这里兜底)
                    try:
                        for obj in self._client.list_objects(bucket, recursive=True):
                            if not getattr(obj, "is_delete_marker", False):
                                self._client.remove_object(bucket, obj.object_name)
                    except Exception:
                        pass
                    self._client.remove_bucket(bucket)
                    return True, f"桶 {bucket} 已删除 (含全部历史版本)"

                # 未启用版本控制: 流式列举 + 每 1000 条一批批量删除
                # (旧实现 `list(...)` 物化全桶会 OOM, 逐个 remove_object 要 N 次往返)
                failed: List[str] = []
                total = 0
                batch: List[str] = []
                try:
                    def _flush(names: List[str]) -> None:
                        if not names:
                            return
                        try:
                            for err in self._client.remove_objects(bucket, names):
                                # remove_objects 是生成器, 逐条 yield 错误
                                if err is not None:
                                    name = getattr(err, "object_name", "?")
                                    failed.append(f"{name}: {err}")
                        except Exception as e:  # noqa: BLE001
                            failed.append(f"批量删除异常: {e}")

                    for obj in self._client.list_objects(bucket, recursive=True):
                        total += 1
                        batch.append(obj.object_name)
                        if len(batch) >= 1000:
                            _flush(batch)
                            batch = []
                    _flush(batch)
                except Exception as e_list:  # noqa: BLE001
                    err = map_s3_error(e_list)
                    from ..config.exceptions import NotFoundError
                    if isinstance(err, NotFoundError):
                        return False, f"桶 {bucket} 不存在"
                    return False, f"列对象失败: {err.message}"
                if failed:
                    preview = "; ".join(failed[:5])
                    more = f" 等 {len(failed)} 个" if len(failed) > 5 else ""
                    return False, (
                        f"清空失败 {len(failed)} 个对象 (共扫描 {total} 个): "
                        f"{preview}{more}"
                    )
            self._client.remove_bucket(bucket)
            return True, f"桶 {bucket} 已删除"
        except Exception as e:
            err = map_s3_error(e)
            from ..config.exceptions import BucketNotEmptyError, NotFoundError
            if isinstance(err, NotFoundError):
                return False, f"桶 {bucket} 不存在"
            if isinstance(err, BucketNotEmptyError):
                return False, "桶不为空,请先清空或使用 force=True"
            return False, err.message

    # ==================== 对象操作 ====================

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
            max_items: 最多返回多少条; 0 = 不限制。达到上限会截断, 并把
                       **当前线程** 的截断标志置 True, 用
                       `last_list_truncated()` 查询 (线程本地, 并发安全)。

        ⚠ 无上限的物化曾导致概览页 OOM —— 4 线程并发对每个桶做
        recursive=True 全量拉取, 大桶直接把内存吃光。
        """
        if not self._client:
            return False, "客户端未连接"
        try:
            results = []
            # ⚠ 旧实现无上限地把整个桶/前缀的对象物化成 Python list。
            #   概览页对【每个桶】都调一次 list_objects(recursive=True) 并
            #   4 线程并发, 数十万对象的桶会把内存吃到 GB 级, 客户端
            #   无响应甚至崩溃。config/settings.py 里的 MAX_LIST_ITEMS
            #   定义了却从未被引用 —— 这里接上。
            truncated = False
            for obj in self._client.list_objects(
                bucket, prefix=prefix, recursive=recursive
            ):
                if max_items and len(results) >= max_items:
                    truncated = True
                    break
                is_dir = obj.object_name.endswith("/")
                results.append({
                    "name": obj.object_name,
                    "size": obj.size if not is_dir else 0,
                    "last_modified": obj.last_modified,
                    "is_dir": is_dir,
                    "etag": getattr(obj, "etag", None),
                })
            # 线程本地写入 (属性 setter 也走同一份存储, 旧读法不失效)
            self._last_list_truncated = truncated
            if truncated:
                # 明确告诉调用方"还有更多", 让 UI 能提示而不是假装列全了
                logging.getLogger("ose.core").info(
                    "list_objects(%s/%s) 达到上限 %d 条, 结果已截断",
                    bucket, prefix, max_items,
                )
            return True, results
        except Exception as e:
            return False, map_s3_error(e).message

    def upload(
        self,
        local_path: str,
        bucket: str,
        key: str,
        progress_callback: ProgressCallback = None,
    ) -> Tuple[bool, str]:
        if not self._client:
            return False, "客户端未连接"
        if not os.path.exists(local_path):
            return False, f"文件不存在: {local_path}"
        try:
            progress_obj = _ProgressAdapter(progress_callback) if progress_callback else None
            self._client.fput_object(
                bucket, key, local_path,
                progress=progress_obj,
            )
            if progress_callback:
                progress_callback(1.0)
            return True, "上传成功"
        except Exception as e:
            return False, f"上传失败: {map_s3_error(e).message}"

    def download(
        self,
        bucket: str,
        key: str,
        local_path: str,
        progress_callback: ProgressCallback = None,
    ) -> Tuple[bool, str]:
        if not self._client:
            return False, "客户端未连接"
        # 下载原子性 (借鉴 Pail「先下临时文件并校验, 通过后才替换目标」):
        # 直接写目标路径时, 网络中断/取消会在本地留下半截文件, 还会覆盖
        # 用户已有同名文件。改为同目录临时文件 + 完成后 os.replace
        # (同卷原子替换, Windows 同样成立), 失败/取消不留半截也不碰旧文件。
        tmp_path = local_path + ".ose-tmp"
        try:
            save_dir = os.path.dirname(local_path)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            progress_obj = _ProgressAdapter(progress_callback) if progress_callback else None
            # 优先 fget_object,失败回退到流式
            try:
                self._client.fget_object(
                    bucket, key, tmp_path,
                    progress=progress_obj,
                )
            except TypeError:
                # 老版本 fget_object 不支持 progress 参数
                self._client.fget_object(bucket, key, tmp_path)
            except Exception:
                response = self._client.get_object(bucket, key)
                try:
                    total = int(response.headers.get("content-length", "0") or 0)
                    if progress_obj:
                        progress_obj.set_meta(total, key)
                    with open(tmp_path, "wb") as f:
                        for chunk in response.stream(8192):
                            f.write(chunk)
                            if progress_obj:
                                progress_obj.update(len(chunk))
                finally:
                    response.close()
                    response.release_conn()

            # 临时文件完整落定才替换目标; 中途失败则旧文件原封不动
            os.replace(tmp_path, local_path)
            if progress_callback:
                progress_callback(1.0)
            return True, "下载成功"
        except Exception as e:
            # 清理半截临时文件: 不留垃圾, 也不覆盖目标
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            return False, f"下载失败: {map_s3_error(e).message}"

    def read_object_bytes(
        self,
        bucket: str,
        key: str,
        max_bytes: int,
    ) -> Tuple[bool, Any]:
        """读取对象前 max_bytes 字节 (在线预览用, 不落盘)。

        minio-py 的 get_object 支持 offset/length 定长读取, 单次网络往返
        拿到头部字节即可; 响应体读完后立即释放连接, 避免池占用。

        Returns:
            (True, bytes) / (False, 错误消息)
        """
        if not self._client:
            return False, "客户端未连接"
        if max_bytes <= 0:
            return False, "max_bytes 必须为正数"
        try:
            resp = self._client.get_object(bucket, key, offset=0, length=max_bytes)
            try:
                data = resp.read(max_bytes + 1)
            finally:
                resp.close()
                resp.release_conn()
            return True, data
        except Exception as e:
            return False, f"读取预览内容失败: {map_s3_error(e).message}"

    def delete(self, bucket: str, key: str) -> Tuple[bool, str]:
        if not self._client:
            return False, "客户端未连接"
        try:
            self._client.remove_object(bucket, key)
            return True, "删除成功"
        except Exception as e:
            return False, f"删除失败: {map_s3_error(e).message}"

    def copy(
        self,
        src_bucket: str,
        src_key: str,
        dst_bucket: str,
        dst_key: str,
    ) -> Tuple[bool, str]:
        if not self._client:
            return False, "客户端未连接"
        try:
            from minio.commonconfig import CopySource
            self._client.copy_object(
                dst_bucket,
                dst_key,
                CopySource(src_bucket, src_key),
            )
            return True, "复制成功"
        except Exception as e:
            return False, f"复制失败: {map_s3_error(e).message}"

    def move(
        self,
        bucket: str,
        old_key: str,
        new_key: str,
    ) -> Tuple[bool, str]:
        """同桶内移动 = 复制 + 删除原文件

        若复制成功但删除失败,**不会**返回 True — 因为原文件仍存在,
        视为移动未完成。调用方应处理这种情况(例如提示用户去手动删除原文件)。
        """
        if old_key == new_key:
            return True, "源与目标相同,无需移动"
        ok, msg = self.copy(bucket, old_key, bucket, new_key)
        if not ok:
            return False, msg
        del_ok, del_msg = self.delete(bucket, old_key)
        if not del_ok:
            return False, (
                f"复制成功但删除原对象失败,移动未完成 "
                f"(已创建 {new_key}, 原 {old_key} 仍存在): {del_msg}"
            )
        return True, "移动成功"

    def create_folder(self, bucket: str, prefix: str) -> Tuple[bool, str]:
        if not self._client:
            return False, "客户端未连接"
        try:
            folder_key = prefix if prefix.endswith("/") else prefix + "/"
            self._client.put_object(
                bucket,
                folder_key,
                io.BytesIO(b""),
                0,
            )
            return True, f"文件夹 {prefix} 创建成功"
        except Exception as e:
            return False, f"创建文件夹失败: {map_s3_error(e).message}"

    def stat_object(
        self,
        bucket: str,
        key: str,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        if not self._client:
            return False, "客户端未连接"
        try:
            stat = self._client.stat_object(bucket, key)
            # 顺带把 user metadata 与标签带出来 —— 之前只返回 6 个字段,
            # "按标签检索""查看自定义元数据"这类需求完全够不着数据。
            result: Dict[str, Any] = {
                "name": stat.object_name,
                "size": stat.size,
                "etag": stat.etag,
                "content_type": stat.content_type,
                "last_modified": stat.last_modified,
                "metadata": {},
                "tags": {},
            }
            meta = getattr(stat, "metadata", None)
            if isinstance(meta, dict):
                # S3 的 x-amz-meta-* 会被 SDK 剥掉前缀, 这里统一补回去
                result["metadata"] = {
                    (k if k.lower().startswith("x-amz-meta-")
                     else f"x-amz-meta-{k}"): v
                    for k, v in meta.items()
                }
            ok_tags, tags = self.get_object_tags(bucket, key)
            if ok_tags:
                result["tags"] = tags
            return True, result
        except Exception as e:
            from ..config.exceptions import NotFoundError
            err = map_s3_error(e)
            if isinstance(err, NotFoundError):
                return False, "对象不存在"
            return False, err.message

    # ==================== 桶策略 ====================

    def get_bucket_policy(self, bucket: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """读取桶策略 (JSON)

        Returns:
            (True, dict) 已配置 / (True, None) 未配置任何策略 (不是错误)
        """
        if not self._client:
            return False, "客户端未连接"
        try:
            raw = self._client.get_bucket_policy(bucket)
            if not raw:
                return True, None
            data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            return True, data if isinstance(data, dict) else None
        except Exception as e:
            err = map_s3_error(e)
            text = str(e).lower()
            # 未配置策略时 S3 返回 NoSuchBucketPolicy, 这不是错误
            if "nosuchbucketpolicy" in text or "no such bucket policy" in text:
                return True, None
            return False, f"读取桶策略失败: {err.message}"

    def set_bucket_policy(self, bucket: str, policy: Dict[str, Any]) -> Tuple[bool, str]:
        """设置桶策略"""
        if not self._client:
            return False, "客户端未连接"
        if not isinstance(policy, dict) or not policy:
            return False, "桶策略不能为空 (要清除请用「删除桶策略」)"
        # 策略里必须带 Bucket, 否则服务端会拒; 这里替用户补上, 少一类踩坑
        doc = dict(policy)
        doc.setdefault("Version", "2012-10-17")
        stmts = doc.get("Statement")
        if isinstance(stmts, list):
            for st in stmts:
                if isinstance(st, dict):
                    st.setdefault("Resource", f"arn:aws:s3:::{bucket}/*")
                    st.setdefault("Effect", "Allow")
        elif isinstance(stmts, dict):
            stmts.setdefault("Resource", f"arn:aws:s3:::{bucket}/*")
            stmts.setdefault("Effect", "Allow")
        else:
            return False, "策略缺少 Statement 字段"
        try:
            self._client.set_bucket_policy(bucket, json.dumps(doc, ensure_ascii=False))
            return True, f"桶 {bucket} 的策略已设置"
        except Exception as e:
            return False, f"设置桶策略失败: {map_s3_error(e).message}"

    def delete_bucket_policy(self, bucket: str) -> Tuple[bool, str]:
        """删除桶策略 (恢复为私有)"""
        if not self._client:
            return False, "客户端未连接"
        try:
            self._client.delete_bucket_policy(bucket)
            return True, f"桶 {bucket} 的策略已删除 (已恢复私有访问)"
        except Exception as e:
            return False, f"删除桶策略失败: {map_s3_error(e).message}"

    # ==================== 对象标签 ====================

    def get_object_tags(self, bucket: str, key: str) -> Tuple[bool, Dict[str, str]]:
        """读取对象标签"""
        if not self._client:
            return False, "客户端未连接"
        try:
            tags = self._client.get_object_tags(bucket, key)
            if tags is None:
                return True, {}
            # minio 返回的 Tags 支持 items() 与 dict()
            if hasattr(tags, "items"):
                return True, {str(k): str(v) for k, v in tags.items()}
            return True, {str(k): str(v) for k, v in dict(tags)}
        except Exception as e:
            err = str(e).lower()
            if "nosuchtagset" in err or "no such tag set" in err:
                return True, {}          # 没打标不是错误
            return False, map_s3_error(e).message

    def set_object_tags(self, bucket: str, key: str, tags: Dict[str, str]) -> Tuple[bool, str]:
        """设置对象标签 (整体替换)"""
        if not self._client:
            return False, "客户端未连接"
        if not tags:
            return self.delete_object_tags(bucket, key)
        # S3 标签的 key/value 有长度与字符集限制, 提前拦下给清晰提示
        for k, v in tags.items():
            if not k or len(k) > 128:
                return False, f"标签名非法或超长: {k!r} (限 128 字符)"
            if len(str(v)) > 256:
                return False, f"标签 {k!r} 的值超长 (限 256 字符)"
        try:
            # ⚠ Tags 的构造签名是 `__init__(self, for_object: bool = False)`,
            #   传 dict 会被当成那个布尔参数, 结果是个空标签集 ——
            #   "设了标签却读回来是空的"。必须用 new_object_tags() 再 update。
            from minio.commonconfig import Tags
            tags_obj = Tags.new_object_tags()
            tags_obj.update({str(k): str(v) for k, v in tags.items()})
            self._client.set_object_tags(bucket, key, tags_obj)
            return True, f"已设置 {len(tags)} 个标签"
        except Exception as e:
            return False, f"设置标签失败: {map_s3_error(e).message}"

    def delete_object_tags(self, bucket: str, key: str) -> Tuple[bool, str]:
        """清除对象标签"""
        if not self._client:
            return False, "客户端未连接"
        try:
            from minio.commonconfig import Tags
            self._client.delete_object_tags(bucket, key, Tags.new_object_tags())
            return True, "标签已清除"
        except Exception as e:
            return False, f"清除标签失败: {map_s3_error(e).message}"

    # ==================== 对象版本 ====================

    def list_object_versions(
        self,
        bucket: str,
        prefix: str = "",
        max_items: int = 0,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """列出对象历史版本

        用 minio 的 list_objects(include_version=True), 它同时返回当前版本
        和历史版本; 删除标记 (is_delete_marker=True) 也在其中 —— 那些是
        "这个 key 被删了"的记录, 界面上要单独标出来。
        """
        if not self._client:
            return False, "客户端未连接"
        try:
            out: List[Dict[str, Any]] = []
            for obj in self._client.list_objects(
                bucket, prefix=prefix, recursive=True, include_version=True
            ):
                if max_items and len(out) >= max_items:
                    break
                out.append({
                    "key": obj.object_name,
                    "version_id": getattr(obj, "version_id", None),
                    "is_latest": bool(getattr(obj, "is_latest", False)),
                    "is_delete_marker": bool(getattr(obj, "is_delete_marker", False)),
                    "size": 0 if getattr(obj, "is_delete_marker", False) else obj.size,
                    "last_modified": obj.last_modified,
                    "etag": getattr(obj, "etag", None),
                })
            return True, out
        except Exception as e:
            return False, f"列出对象版本失败: {map_s3_error(e).message}"

    def remove_object_version(self, bucket: str, key: str, version_id: str) -> Tuple[bool, str]:
        """删除指定版本"""
        if not self._client:
            return False, "客户端未连接"
        if not version_id:
            return False, "version_id 不能为空"
        try:
            self._client.remove_object(bucket, key, version_id=version_id)
            return True, f"版本 {version_id[:12]}… 已删除"
        except Exception as e:
            return False, f"删除版本失败: {map_s3_error(e).message}"

    def copy_object_version(
        self, bucket: str, key: str, version_id: str, dest_key: str
    ) -> Tuple[bool, str]:
        """把历史版本恢复为一个新的当前版本 (误覆盖后的回滚)"""
        if not self._client:
            return False, "客户端未连接"
        if not version_id:
            return False, "version_id 不能为空"
        dest_key = dest_key or key
        try:
            from minio.commonconfig import CopySource
            self._client.copy_object(
                bucket, dest_key,
                CopySource(bucket, key, version_id=version_id),
            )
            return True, f"版本 {version_id[:12]}… 已恢复为 {dest_key}"
        except Exception as e:
            return False, f"恢复版本失败: {map_s3_error(e).message}"

    def delete_all_versions(self, bucket: str) -> Tuple[bool, str]:
        """清空桶内全部版本 (含删除标记)

        强制删版本化桶时必须走这条: 只删当前版本的话, 桶里还留着历史版本,
        remove_bucket 会一直报 BucketNotEmpty。
        """
        if not self._client:
            return False, "客户端未连接"
        try:
            total = 0
            failed = 0
            for obj in self._client.list_objects(bucket, recursive=True, include_version=True):
                vid = getattr(obj, "version_id", None)
                if not vid:
                    continue      # 未启用版本控制的对象没有 version_id
                total += 1
                try:
                    self._client.remove_object(bucket, obj.object_name, version_id=vid)
                except Exception:
                    failed += 1
            if total == 0:
                return True, "桶内没有需要清理的版本"
            if failed:
                return False, f"清理 {total} 个版本, 其中 {failed} 个失败"
            return True, f"已清理 {total} 个版本"
        except Exception as e:
            return False, f"清理版本失败: {map_s3_error(e).message}"

    # ==================== 高级功能 ====================

    def get_presigned_url(
        self,
        bucket: str,
        key: str,
        expires: int = 3600,
    ) -> Tuple[bool, Optional[str]]:
        if not self._client:
            return False, "客户端未连接"
        try:
            # D9 外链 Host (借鉴 s3manager 的 PRESIGN_URL 与 ENDPOINT 分离):
            # 主机名是 SigV4 签名的一部分, 内网地址签出的链接外网不可用。
            # 用「指向外部主机名的孪生客户端」重新签名 (Minio 对象构造
            # 不发请求, 成本可忽略), 而不是改写 URL 字符串 (会破坏签名)。
            signer = self._client
            ext = (self.external_host or "").strip()
            if ext and ext != self.endpoint:
                try:
                    from minio import Minio
                    signer = Minio(
                        endpoint=ext,
                        access_key=self.ak,
                        secret_key=self.sk,
                        secure=self.ssl,
                    )
                except Exception:
                    signer = self._client  # 孪生客户端构造失败则退回内网签名
            url = signer.get_presigned_url(
                "GET",
                bucket,
                key,
                expires=timedelta(seconds=expires),
            )
            return True, url
        except Exception as e:
            return False, f"生成 URL 失败: {e}"

    def get_bucket_versioning(self, bucket: str) -> Tuple[bool, Optional[str]]:
        if not self._client:
            return False, "客户端未连接"
        try:
            config = self._client.get_bucket_versioning(bucket)
            if config is None:
                return True, None
            return True, getattr(config, "status", None)
        except Exception as e:
            return False, map_s3_error(e).message

    def set_bucket_versioning(self, bucket: str, status: str) -> Tuple[bool, str]:
        """设置桶版本控制状态

        S3 协议只接受两个值: "Enabled" / "Suspended" —— 没有 Off, 桶一旦
        创建过 versioning 就一直存在。

        ⚠ 旧实现用三元表达式把"不是 enabled 的一切"都折叠成 Suspended,
        于是 "on" / "enable" / "Enable" / 空串 / 拼错的枚举值都会静默变成
        Suspended, 而且返回的提示还回显**入参** —— 界面显示"已设置为 on",
        实际生效的是 Suspended, 状态与用户意图相反且提示成功。
        改成白名单校验 + 回显实际生效值。
        """
        if not self._client:
            return False, "客户端未连接"
        # 容忍 UI 可能传的大小写与别名, 但只认这两个语义
        normalized = (status or "").strip().lower()
        mapping = {
            "enabled": "Enabled",
            "enable": "Enabled",
            "on": "Enabled",
            "suspended": "Suspended",
            "suspend": "Suspended",
            "off": "Suspended",
        }
        status_value = mapping.get(normalized)
        if not status_value:
            return False, (
                f"版本控制状态只能是 Enabled 或 Suspended, 收到 {status!r}"
            )
        try:
            from minio.versioningconfig import VersioningConfig
            self._client.set_bucket_versioning(bucket, VersioningConfig(status_value))
            # 回显实际生效值, 而不是用户传进来的字符串
            return True, f"版本控制已设置为 {status_value}"
        except Exception as e:
            return False, f"设置版本控制失败: {e}"

    def get_bucket_lifecycle(self, bucket: str) -> Tuple[bool, Optional[object]]:
        """获取桶生命周期配置

        Returns:
            (True, None) - 未配置
            (True, LifecycleConfig) - 已配置,可通过 .rules 取规则列表
            (False, error_msg)
        """
        if not self._client:
            return False, "客户端未连接"
        try:
            config = self._client.get_bucket_lifecycle(bucket)
            if not config:
                return True, None
            return True, config  # 直接返回对象,别 str() (会丢 .rules 等属性)
        except Exception as e:
            return False, map_s3_error(e).message

    def set_bucket_lifecycle(self, bucket: str, config: Dict) -> Tuple[bool, str]:
        if not self._client:
            return False, "客户端未连接"
        try:
            from minio.lifecycleconfig import (
                LifecycleConfig, Rule, Expiration,
                NoncurrentVersionExpiration, Transition,
                AbortIncompleteMultipartUpload,
            )
            from minio.commonconfig import ENABLED, DISABLED, Filter
            rules = []
            no_action = []
            dropped_by_rule = []
            for idx, r in enumerate(config.get("Rules", [])):
                status_str = (r.get("Status") or "Enabled").lower()
                rule_status = ENABLED if status_str == "enabled" else DISABLED

                # ⚠ 每种动作都独立可选, 且 JSON 里可以显式写 null
                #   (例如 {"Expiration": null} 表示"这条规则不配过期")。
                #   旧代码用 `r.get("Expiration", {}).get("Days", 30)`, 默认值
                #   只在【键不存在】时生效, 键存在且为 null 时对 None 调 .get
                #   直接 AttributeError; 而且它【强制】给每条规则都加
                #   Expiration, 导致"仅非当前版本过期""存储层级转换""中止未完成
                #   分片"这类规则一律写不进去。
                #
                # ⚠ minio 的 Rule 每个动作字段只接受【单个对象】, 不是列表
                #   (transition / noncurrent_version_transition 均是单数)。
                #   这里取第一条, 多余的明确报出来而不是静默丢弃。
                kwargs: Dict[str, Any] = {}
                dropped: List[str] = []

                # 当前版本过期
                exp_days = (r.get("Expiration") or {}).get("Days")
                if exp_days is not None:
                    kwargs["expiration"] = Expiration(days=int(exp_days))

                # 非当前版本过期
                ncv = r.get("NoncurrentVersionExpiration") or {}
                ncv_days = ncv.get("NoncurrentDays")
                if ncv_days is not None:
                    kwargs["noncurrent_version_expiration"] = (
                        NoncurrentVersionExpiration(noncurrent_days=int(ncv_days))
                    )

                # 存储层级转换
                transitions = r.get("Transitions") or []
                for ti, tr in enumerate(transitions):
                    sc = tr.get("StorageClass")
                    if not sc:
                        continue
                    if ti > 0:
                        dropped.append(f"Transitions[{ti}]")
                        continue
                    cur_days = tr.get("Days")
                    noncur_days = tr.get("NoncurrentDays")
                    if cur_days is not None:
                        # 注意按关键字传: Transition 的第一个位置参数是
                        # date 不是 days, 写成 Transition(30, ...) 会把 30
                        # 当成日期, days 留空。
                        kwargs["transition"] = Transition(
                            days=int(cur_days), storage_class=sc
                        )
                    elif noncur_days is not None:
                        kwargs["noncurrent_version_transition"] = Transition(
                            storage_class=sc, noncurrent_days=int(noncur_days)
                        )
                    else:
                        dropped.append(f"Transitions[{ti}](无有效天数)")

                # 中止未完成分片上传
                abort_days = (r.get("AbortIncompleteMultipartUpload") or {}).get(
                    "DaysAfterInitiation"
                )
                if abort_days is not None:
                    kwargs["abort_incomplete_multipart_upload"] = (
                        AbortIncompleteMultipartUpload(
                            days_after_initiation=int(abort_days)
                        )
                    )

                rule_id = r.get("ID", f"rule-{idx + 1}")
                if not kwargs:
                    # S3 要求每条规则至少有一个动作, 提前拦下并给中文提示
                    no_action.append(rule_id)
                    continue
                if dropped:
                    dropped_by_rule.append((rule_id, dropped))

                rules.append(Rule(
                    rule_id=rule_id,
                    status=rule_status,
                    rule_filter=Filter(prefix=r.get("Prefix", "")),
                    **kwargs,
                ))

            if not rules:
                detail = ""
                if no_action:
                    detail = f" (这些规则没配任何动作: {', '.join(no_action)})"
                    detail += "。每条规则至少要有 过期/非当前版本过期/存储转换/中止分片 之一。"
                return False, f"没有可生效的生命周期规则{detail}"
            if dropped_by_rule:
                names = "; ".join(f"{rid}: {', '.join(d)}" for rid, d in dropped_by_rule)
                print(f"[提示] 以下生命周期配置项被忽略 (S3 每条规则每种动作只支持一个): {names}")

            self._client.set_bucket_lifecycle(bucket, LifecycleConfig(rules))
            return True, f"生命周期规则已设置 ({len(rules)} 条生效)"
        except Exception as e:
            return False, f"设置生命周期失败: {e}"

    def delete_bucket_lifecycle(self, bucket: str) -> Tuple[bool, str]:
        if not self._client:
            return False, "客户端未连接"
        try:
            self._client.delete_bucket_lifecycle(bucket)
            return True, "生命周期规则已删除"
        except Exception as e:
            return False, f"删除生命周期失败: {e}"

    # ==================== Admin 操作 (V1 简化) ====================

    def _admin_method(
        self,
        method_name: str,
        *args,
        **kwargs,
    ):
        """通过 has_attr 调用 admin 方法 (优雅降级)"""
        if not self._admin_client:
            return False, "Admin API 不可用"
        method = getattr(self._admin_client, method_name, None)
        if not method:
            return False, f"Admin API 不支持 {method_name}"
        try:
            result = method(*args, **kwargs)
            return True, result
        except Exception as e:
            return False, str(e)

    def admin_list_users(self) -> Tuple[bool, List[Dict[str, Any]]]:
        if not self._admin_client:
            return False, []
        try:
            method = getattr(self._admin_client, "user_list", None) or \
                     getattr(self._admin_client, "list_users", None)
            if not method:
                return False, []
            raw = method()
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
        except Exception:
            return False, []

    def admin_create_user(self, ak: str, sk: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("user_add", "add_user"):
            method = getattr(self._admin_client, method_name, None)
            if method:
                try:
                    method(ak, sk)
                    return True, f"用户 {ak} 创建成功"
                except Exception as e:
                    err = str(e)
                    if "exists" in err.lower() or "already" in err.lower():
                        return False, f"用户 {ak} 已存在"
                    return False, err
        return False, "Admin API 不支持创建用户"

    def admin_delete_user(self, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("user_remove", "remove_user"):
            method = getattr(self._admin_client, method_name, None)
            if method:
                try:
                    method(ak)
                    return True, f"用户 {ak} 已删除"
                except Exception as e:
                    err = str(e)
                    if "not found" in err.lower():
                        return False, f"用户 {ak} 不存在"
                    return False, err
        return False, "Admin API 不支持删除用户"

    def admin_enable_user(self, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("user_enable", "enable_user"):
            method = getattr(self._admin_client, method_name, None)
            if method:
                try:
                    method(ak)
                    return True, f"用户 {ak} 已启用"
                except Exception as e:
                    return False, str(e)
        return False, "Admin API 不支持启用用户"

    def admin_disable_user(self, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("user_disable", "disable_user"):
            method = getattr(self._admin_client, method_name, None)
            if method:
                try:
                    method(ak)
                    return True, f"用户 {ak} 已禁用"
                except Exception as e:
                    return False, str(e)
        return False, "Admin API 不支持禁用用户"

    def admin_get_user_info(self, ak: str) -> Tuple[bool, Dict[str, Any]]:
        """获取用户详细信息 (含 status, policyName 等)

        Returns:
            (success, {access_key, status, policyName, memberOf: [...]})
        """
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("user_info", "get_user"):
            method = getattr(self._admin_client, method_name, None)
            if not method:
                continue
            try:
                raw = method(ak)
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, dict):
                    return True, data
                return True, {"access_key": ak, "raw": data}
            except Exception as e:
                err = str(e)
                if "not found" in err.lower():
                    return False, f"用户 {ak} 不存在"
                return False, err
        return False, "Admin API 不支持获取用户详情"

    def admin_set_user_policies(self, ak: str, policies: List[str]) -> Tuple[bool, str]:
        """把用户的策略列表【整体设置】为 policies

        ⚠ 为什么需要这个方法:
        MinIO Admin API 的 attach_policy / detach_policy 底层都走 SetPolicy,
        语义是"把用户的完整策略列表替换成我传的东西", 而不是"增删一项"。
        所以对挂着 [A, B, C] 的用户调 detach_policy("B") 之后, 该用户会只剩
        B, A 和 C 一起消失 —— 历史上 admin_set_policy_content 就是这么把
        用户的其余权限抹掉的。

        正确做法: 想"摘掉 B", 就把 [A, C] 整体写回去。

        Args:
            ak: access key
            policies: 目标完整列表 (空列表 = 清空该用户全部策略)

        Returns:
            (success, message)
        """
        if not self._admin_client:
            return False, "Admin API 不可用"
        wanted = [p for p in (policies or []) if p]
        for method_name in ("attach_policy", "set_policy"):
            method = getattr(self._admin_client, method_name, None)
            if not method:
                continue
            attempts = (
                lambda: method(list(wanted), user=ak),
                lambda: method(list(wanted) or "", user=ak),
                lambda: method(list(wanted), ak),
            )
            for fn in attempts:
                try:
                    fn()
                    shown = ", ".join(wanted) if wanted else "(无)"
                    return True, f"用户 {ak} 的策略已设置为: {shown}"
                except TypeError:
                    # 签名不匹配, 换下一种调用形式
                    continue
                except Exception as e:
                    return False, str(e)
        return False, "Admin API 不支持设置用户策略"

    def _get_user_policies(self, ak: str) -> List[str]:
        """读用户当前策略列表 (读失败返回空列表; 调用方需自行判断)"""
        ok, info = self.admin_get_user_info(ak)
        if not ok or not isinstance(info, dict):
            return []
        raw = info.get("policyName", info.get("policy_name", ""))
        if isinstance(raw, str):
            return [raw] if raw else []
        if isinstance(raw, (list, tuple)):
            return [str(p) for p in raw if p]
        return []

    def _get_user_groups(self, ak: str) -> List[str]:
        """读用户当前所属组 (memberOf); 读失败返回空列表"""
        ok, info = self.admin_get_user_info(ak)
        if not ok or not isinstance(info, dict):
            return []
        raw = info.get("memberOf", info.get("member_of", ""))
        if isinstance(raw, str):
            return [raw] if raw else []
        if isinstance(raw, (list, tuple)):
            return [str(g) for g in raw if g]
        return []

    def admin_add_user_group(self, group: str, ak: str) -> Tuple[bool, str]:
        """把用户加入组 (恢复 memberOf 身份用)"""
        if not self._admin_client:
            return False, "Admin API 不可用"
        method = getattr(self._admin_client, "group_add", None)
        if not method:
            return False, "Admin API 不支持用户组操作"
        try:
            method(group, ak)
            return True, f"用户 {ak} 已加入组 {group}"
        except TypeError:
            try:
                method(group, user=ak)
                return True, f"用户 {ak} 已加入组 {group}"
            except Exception as e:
                return False, str(e)
        except Exception as e:
            return False, str(e)

    def admin_reset_user_secret(self, ak: str, new_secret: str) -> Tuple[bool, str]:
        """重置用户 Secret Key

        MinIO 没有原地改密钥的 API, 只能 remove + add 模拟。这条路径本身
        是"先删后建", 一旦 add 失败用户就永久消失, 因此这里做三件事降低风险:

        1. **建之前先校验新密钥** —— MinIO 要求 secret 至少 8 位, 不满足会
           在 add 阶段才报错, 而那时用户已经被删了。提前拦掉这一类失败。
        2. **快照完整权限** —— 旧实现只回填 policyName, 用户的组身份
           (memberOf) 会静默丢失, 权限实际被降级。现在 policy + group 都还原。
        3. **失败时明确告知损失** —— 不再只说"重建失败", 而是列出需要人工
           补救的具体内容。

        保留: 用户的策略列表与所属组, 自动重新附加/加回。
        """
        if not self._admin_client:
            return False, "Admin API 不可用"
        if not ak or not new_secret:
            return False, "用户和新 Secret Key 都不能为空"
        # MinIO 服务端硬性要求: secret 至少 8 位。提前校验, 避免"先删后建"
        # 中途失败导致用户永久消失。
        if len(new_secret) < 8:
            return False, "新 Secret Key 至少 8 位 (MinIO 服务端硬性要求)"

        # 快照权限 (重建会丢)
        old_policies = self._get_user_policies(ak)
        old_groups = self._get_user_groups(ak)

        # 删 + 建
        try:
            self._admin_client.user_remove(ak)
        except Exception as e:
            return False, f"删除旧用户失败: {e}"
        try:
            self._admin_client.user_add(ak, new_secret)
        except Exception as e:
            lost = []
            if old_policies:
                lost.append("策略 " + ", ".join(old_policies))
            if old_groups:
                lost.append("组 " + ", ".join(old_groups))
            tail = ("; 原权限 " + "; ".join(lost) + " 已丢失, 请手工重建该用户") if lost else ""
            return False, (
                f"重建用户失败, 用户 {ak} 已被删除且无法自动恢复: {e}{tail}"
            )

        # 还原策略 (整体写回, 不是逐个 attach —— 避免只挂上最后一条)
        warn: List[str] = []
        if old_policies:
            ok, msg = self.admin_set_user_policies(ak, old_policies)
            if not ok:
                warn.append(f"重新附加策略失败 ({msg})")
        # 还原组身份
        for g in old_groups:
            ok, msg = self.admin_add_user_group(g, ak)
            if not ok:
                warn.append(f"加回组 {g} 失败 ({msg})")

        if warn:
            return True, (
                f"用户 {ak} 密码已重置, 但权限未完全恢复: {'; '.join(warn)}。"
                f"请手工核对。"
            )
        return True, f"用户 {ak} 密码已重置 (已还原 {len(old_policies)} 个策略 / {len(old_groups)} 个组)"

    def admin_list_policies(self) -> Tuple[bool, List[str]]:
        if not self._admin_client:
            return False, []
        try:
            method = getattr(self._admin_client, "policy_list", None) or \
                     getattr(self._admin_client, "list_policies", None)
            if not method:
                return False, []
            raw = method()
            data = json.loads(raw) if isinstance(raw, str) else raw
            return True, list(data.keys()) if isinstance(data, dict) else list(data)
        except Exception:
            return False, []

    def admin_create_policy(self, name: str, content: Dict) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("policy_add", "add_policy"):
            method = getattr(self._admin_client, method_name, None)
            if method:
                # dict 内容必须走 policy= 关键字 (否则被当成 policy_file 路径)
                attempts = (
                    {"policy": content},          # 新版 MinioAdmin
                    {},                            # 退一步: 位置参数 (老版本)
                )
                last_err = None
                for kwargs in attempts:
                    try:
                        if kwargs:
                            method(name, **kwargs)
                        else:
                            method(name, content)
                        return True, f"策略 {name} 创建成功"
                    except TypeError as e:
                        last_err = e
                        continue
                    except Exception as e:
                        err = str(e)
                        if "exists" in err.lower():
                            return False, f"策略 {name} 已存在"
                        return False, err
                if last_err:
                    return False, str(last_err)
        return False, "Admin API 不支持创建策略"

    def admin_delete_policy(self, name: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("policy_remove", "remove_policy"):
            method = getattr(self._admin_client, method_name, None)
            if method:
                try:
                    method(name)
                    return True, f"策略 {name} 已删除"
                except Exception as e:
                    err = str(e)
                    if "not found" in err.lower():
                        return False, f"策略 {name} 不存在"
                    return False, err
        return False, "Admin API 不支持删除策略"

    def admin_attach_policy(self, policy: str, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("attach_policy", "set_policy"):
            method = getattr(self._admin_client, method_name, None)
            if not method:
                continue
            # 新版 attach_policy 期望 list[str] + user= 关键字;老版 set_policy 是 (policy, user)
            attempts = (
                lambda: method([policy], user=ak),
                lambda: method(policy, user=ak),
                lambda: method(policy, ak),
            )
            last_err = None
            for fn in attempts:
                try:
                    fn()
                    return True, f"策略 {policy} 已附加到 {ak}"
                except TypeError as e:
                    last_err = e
                    continue
                except Exception as e:
                    return False, str(e)
            if last_err:
                return False, str(last_err)
        return False, "Admin API 不支持附加策略"

    def admin_detach_policy(self, policy: str, ak: str) -> Tuple[bool, str]:
        if not self._admin_client:
            return False, "Admin API 不可用"
        for method_name in ("detach_policy",):
            method = getattr(self._admin_client, method_name, None)
            if not method:
                continue
            attempts = (
                lambda: method([policy], user=ak),
                lambda: method(policy, user=ak),
                lambda: method(policy, ak),
            )
            last_err = None
            for fn in attempts:
                try:
                    fn()
                    return True, f"策略 {policy} 已从 {ak} 分离"
                except TypeError as e:
                    last_err = e
                    continue
                except Exception as e:
                    return False, str(e)
            if last_err:
                return False, str(last_err)
        return False, "Admin API 不支持分离策略"

    def admin_get_server_info(self) -> Tuple[bool, Dict[str, Any]]:
        if not self._admin_client:
            return False, {}
        try:
            method = getattr(self._admin_client, "info", None)
            if not method:
                return False, {}
            raw = method()
            data = json.loads(raw) if isinstance(raw, str) else raw
            return True, data if isinstance(data, dict) else {}
        except Exception:
            return False, {}

    def admin_set_policy_content(self, name: str, content: Dict) -> Tuple[bool, str]:
        """修改策略内容 (MinIO 无 update API, 用 摘除 → 删 → 建 → 还原)

        保留: 附加到此策略的所有用户 (策略名不变), 且【这些用户的其他策略
        与组身份必须原样保留】。

        ⚠ 这段逻辑以前会把用户的权限抹干净, 根因是 MinIO 的 attach/detach
        语义: 两者底层都是 SetPolicy —— "把用户完整策略列表替换成我传的"。
        对挂着 [readonly, thisPolicy] 的用户 detach_policy("thisPolicy") 之后,
        该用户会只剩 thisPolicy, readonly 一起消失。旧实现没有快照,
        策略重建一失败就是不可逆的权限丢失。
        """
        if not self._admin_client:
            return False, "Admin API 不可用"
        if not name or not content:
            return False, "策略名和内容不能为空"

        def _attached_users() -> Tuple[Optional[List[str]], str]:
            """列出附加到此策略的所有用户。

            返回 (users, err): 读失败时 users 为 None —— 调用方必须据此中止,
            绝不能把"读不到"当成"没有用户"继续往下走 (那会漏掉 detach 目标)。
            """
            users: List[str] = []
            try:
                raw = self._admin_client.user_list()
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, dict):
                    for ak, info in data.items():
                        if not isinstance(info, dict):
                            continue
                        names = info.get("policyName", info.get("policy_name", ""))
                        if isinstance(names, str):
                            names = [names] if names else []
                        if name in (names or []):
                            users.append(ak)
                return users, ""
            except Exception as e:
                return None, str(e)

        # 1. 快照: 每个受影响用户的【完整】策略列表 (用于最后原样写回)
        attached, err = _attached_users()
        if attached is None:
            return False, (
                f"无法列出用户列表 ({err}), 已中止修改 —— "
                f"在无法确认受影响范围时继续操作会导致权限丢失"
            )
        snapshot: Dict[str, List[str]] = {}
        for ak in attached:
            snapshot[ak] = self._get_user_policies(ak)

        # 2. 摘除: 把每个用户的策略列表整体重写为"去掉 name 之后"的剩余项。
        #    写回剩余完整列表, 而不是 detach_policy(name) —— 后者会连带
        #    抹掉该用户的其他策略。
        detach_failed: List[str] = []
        for ak in attached:
            remaining = [p for p in snapshot[ak] if p != name]
            ok, _msg = self.admin_set_user_policies(ak, remaining)
            if not ok:
                detach_failed.append(ak)
        if detach_failed:
            # 摘除阶段就失败: 尽力把已摘的用户恢复回去, 再中止
            for ak in attached:
                if ak not in detach_failed and snapshot[ak]:
                    self.admin_set_user_policies(ak, snapshot[ak])
            return False, (
                f"策略 {name} 正被 {len(detach_failed)} 个用户使用且摘除失败 "
                f"({', '.join(detach_failed)}), 已中止修改, 原策略与权限未动"
            )

        # 3. 删 + 建
        try:
            self._admin_client.policy_remove(name)
        except Exception as e:
            err_text = str(e)
            if "in use" in err_text.lower() or "inuse" in err_text.replace(" ", "").lower():
                # 兜底: user_list 偶发漏用户 → 再收集-摘除-重删一次
                retry_users, retry_err = _attached_users()
                if retry_users is None:
                    for ak in attached:
                        if snapshot[ak]:
                            self.admin_set_user_policies(ak, snapshot[ak])
                    return False, f"删除旧策略失败且无法重新确认用户列表 ({retry_err})"
                for ak in retry_users:
                    remaining = [p for p in self._get_user_policies(ak) if p != name]
                    self.admin_set_user_policies(ak, remaining)
                    snapshot.setdefault(ak, self._get_user_policies(ak))
                try:
                    self._admin_client.policy_remove(name)
                except Exception as e2:
                    for ak, pols in snapshot.items():
                        if pols:
                            self.admin_set_user_policies(ak, pols)
                    return False, f"删除旧策略失败: {e2}"
            else:
                for ak, pols in snapshot.items():
                    if pols:
                        self.admin_set_user_policies(ak, pols)
                return False, f"删除旧策略失败: {err_text}"

        try:
            self._admin_client.policy_add(name, policy=content)
        except Exception as e:
            # 策略重建失败 → 原策略已不存在, 权限已摘除, 必须还原
            for ak, pols in snapshot.items():
                if pols:
                    self.admin_set_user_policies(ak, pols)
            return False, (
                f"重建策略失败 ({e})。已把 {len(snapshot)} 个用户的策略列表还原为修改前状态, "
                f"但策略 {name} 本身已不存在, 需要重建后重新附加。"
            )

        # 4. 还原: 用快照里的完整列表整体写回 (含新策略), 用户的其他策略一并回来
        restore_failed: List[str] = []
        for ak, pols in snapshot.items():
            if name not in pols:
                pols = pols + [name]
            ok, _msg = self.admin_set_user_policies(ak, pols)
            if not ok:
                restore_failed.append(ak)

        if restore_failed:
            return False, (
                f"策略 {name} 已重建, 但 {len(restore_failed)} 个用户的权限未能恢复: "
                f"{', '.join(restore_failed)}。请手工核对这些用户的策略列表。"
            )
        if attached:
            return True, f"策略 {name} 已更新 ({len(attached)} 个用户的权限已原样保留)"
        return True, f"策略 {name} 已更新"


class _ProgressAdapter:
    """适配 minio 的 progress 协议: set_meta(total_length, object_name) + update(length)

    把字节进度归一化为 0.0-1.0 转发给我们的 ProgressCallback。
    minio 在内部线程调用 update,这里只做简单算术,不持锁。
    """

    def __init__(self, callback):
        self._cb = callback
        self._total = 0
        self._sent = 0

    def set_meta(self, total_length: int, object_name: str) -> None:
        self._total = max(0, int(total_length or 0))
        self._sent = 0

    def update(self, length: int) -> None:
        if length <= 0:
            return
        self._sent += length
        if self._total <= 0 or self._cb is None:
            return
        try:
            self._cb(min(1.0, self._sent / self._total))
        except Exception:
            pass
