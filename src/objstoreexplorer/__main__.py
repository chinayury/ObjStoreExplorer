# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ObjStoreExplorer 模块入口

支持: python -m objstoreexplorer
"""
import sys
from .main import main

if __name__ == "__main__":
    sys.exit(main())
