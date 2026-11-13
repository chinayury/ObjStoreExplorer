# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ObjStoreExplorer 模块入口

支持: python -m objstoreexplorer
"""
import sys
from .main import main

if __name__ == "__main__":
    sys.exit(main())
