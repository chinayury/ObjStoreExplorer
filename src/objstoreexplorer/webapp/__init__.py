# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ObjStoreExplorer Web 容器版

FastAPI + Jinja2 + HTMX 的浏览器访问版, 复用桌面版 core/ 与 config/ 层,
与 Tkinter 桌面版并存 (桌面版零改动)。

版本口径 (v0.1.0 正式稳定版): 本模块 __version__ 是 Web 版版本唯一真源,
与桌面版 config.settings.APP_VERSION、docker-compose 镜像标签统一为 0.1.0。
(桌面版 0.1.0 → Web 内部迭代 2.0~2.4 → 归一 v0.1.0 的完整线索见
CHANGELOG.md 与 docs/版本迭代说明-v0.1.0.md)

用法:
    uvicorn webapp.main:app --host 0.0.0.0 --port 8000
"""

__version__ = "0.1.0"
