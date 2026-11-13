# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""
ObjStoreExplorer - MinIO/S3 对象存储管理工具 (v0.1.0 正式版)

架构 (均位于 objstoreexplorer 包内):
    config/    配置与异常定义
    core/      S3 客户端、凭据加密、本地存储、业务管理器
    services/  传输/同步/缓存/剪贴板等后台服务
    ui/        tkinter 界面 (pages / widgets / windows)
    utils/     工具层 (图标/截图/线程池/反馈客户端)
    webapp/    Web 容器版 (FastAPI 路由/模板/静态资源)
    resources/ 图标资源

关键设计:
    - 工厂模式自动适配 minio-py V1/V2
    - Fernet 加密本地存储所有敏感信息 (AK/SK/反馈平台 app_key)
    - 统一异常体系 (ConfigError/AccessPermissionError/NotFoundError 等)
    - 统一返回结果 (Tuple[bool, str]) 模式
    - 设计 token 集中管理 (ui/styles.py), 组件不硬编码色值
    - 后台线程 + 主线程桥接 (ui/threading_bridge.py), 不卡 UI 且不跨线程碰 Tk

依赖:
    pip install -r requirements.txt

用法:
    python -m objstoreexplorer
"""

# 版本号的唯一真源是 config/settings.py:APP_VERSION。
# 这里做转发而不是再写一份字面量 —— 之前两处各写一个 "0.1.0", 是版本漂移的隐患点。
# 用惰性导入避免在包初始化期就拉起 config -> core -> services 整条依赖链。
def __getattr__(name):
    if name in ("__version__", "APP_VERSION"):
        from .config.settings import APP_VERSION
        return APP_VERSION
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__author__ = "智维ITMSKY <41469858@qq.com>"
__all__ = ["__version__", "APP_VERSION", "__author__"]
