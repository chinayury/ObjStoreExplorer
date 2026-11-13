# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""services/connection_service - 连接管理服务

封装连接逻辑:
    - 保存当前连接到历史
    - 自动加载最近一次连接
    - 列出可用历史配置
"""
from __future__ import annotations
from typing import List, Dict, Optional, Tuple, Any


class ConnectionService:
    """连接管理服务"""

    def __init__(self, locator):
        self._locator = locator

    @property
    def is_connected(self) -> bool:
        return self._locator.is_connected

    @property
    def current_endpoint(self) -> Optional[str]:
        if self._locator.s3_client:
            return self._locator.s3_client.endpoint
        return None

    def connect(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        ssl: bool = False,
        save: bool = True,
    ) -> Tuple[bool, str]:
        """建立连接 (并可选保存到历史)"""
        ok, msg = self._locator.connect(endpoint, access_key, secret_key, ssl)
        if not ok:
            return False, msg

        if save:
            # name = endpoint + ":" + access_key,避免同 endpoint 不同 AK 互相覆盖
            ep_short = endpoint.replace("http://", "").replace("https://", "")
            name = f"{ep_short}@{access_key}" if access_key else ep_short
            warnings: List[str] = []
            try:
                # 实际探测是否为管理员账号 (取代旧的命名后缀判断)
                is_admin = False
                client = self._locator.s3_client
                if client is not None:
                    try:
                        is_admin = client.probe_admin()
                    except Exception:
                        is_admin = False

                self._locator.config_manager.add_server(
                    name=name,
                    endpoint=endpoint,
                    access_key=access_key,
                    secret_key=secret_key,
                    ssl=ssl,
                    is_admin=is_admin,
                )
                self._locator.config_manager.mark_used(name)
            except Exception as e:
                # 保存失败不影响连接, 但必须让用户知道 (之前完全静默)
                warnings.append(f"已连接, 但保存到历史失败: {e}")

            if warnings:
                return True, f"{msg} ({'; '.join(warnings)})"

        return True, msg

    def disconnect(self) -> None:
        self._locator.disconnect()

    def list_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """列出历史连接配置"""
        return self._locator.config_manager.list_servers()[:limit]

    def connect_from_history(self, name: str) -> Tuple[bool, str]:
        """从历史配置连接"""
        cfg = self._locator.config_manager.get_server(name)
        if not cfg:
            return False, f"未找到配置: {name}"

        # 用 get 取默认值: 老版本记录可能缺字段 (如 ssl), 直接下标会 KeyError 崩掉
        ok, msg = self.connect(
            endpoint=cfg.get("endpoint", ""),
            access_key=cfg.get("access_key", ""),
            secret_key=cfg.get("secret_key", ""),
            ssl=bool(cfg.get("ssl", False)),
            save=False,
        )
        if ok:
            self._locator.config_manager.mark_used(name)
        return ok, msg

    def try_last_connection(self) -> Tuple[bool, str]:
        """尝试最近一次连接"""
        history = self.list_history(limit=1)
        if not history:
            return False, "无历史连接"
        last = history[0]
        return self.connect(
            endpoint=last.get("endpoint", ""),
            access_key=last.get("access_key", ""),
            secret_key=last.get("secret_key", ""),
            ssl=bool(last.get("ssl", False)),
            save=False,
        )

    def delete_history(self, name: str) -> bool:
        return self._locator.config_manager.delete_server(name)

    def cleanup(self) -> None:
        pass
