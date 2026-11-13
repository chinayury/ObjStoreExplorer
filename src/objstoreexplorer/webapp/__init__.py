# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ObjStoreExplorer Web 容器版

FastAPI + Jinja2 + HTMX 的浏览器访问版, 复用桌面版 core/ 与 config/ 层,
与 Tkinter 桌面版并存 (桌面版零改动)。

版本口径: 版本号唯一真源是 config.settings.APP_VERSION。本模块与包级
__init__ 一样只做转发, 不再另存字面量 —— 历史上 Web 版曾独立维护字面量
(桌面版 0.1.0 → Web 内部迭代 2.0~2.4 → v0.1.0 归一, 完整线索见
CHANGELOG.md), 归一后两处字面量仍有漂移隐患, 现已彻底收敛为单一来源。

用法:
    uvicorn objstoreexplorer.webapp.main:app --host 0.0.0.0 --port 8000
"""

from ..config.settings import APP_VERSION as __version__

__all__ = ["__version__"]
