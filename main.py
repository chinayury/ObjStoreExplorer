# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ObjStoreExplorer 桌面版启动引导 (薄壳)

源码采用 src 布局, 真实入口逻辑位于 objstoreexplorer 包内。本文件是
PyInstaller 打包入口与 `python main.py` 源码直跑的引导壳:

    python main.py                 # 源码直跑 (自动把 src/ 加入搜索路径)
    python -m objstoreexplorer     # 标准模块入口 (需 pip install -e .)
    pyinstaller build.spec          # 打包 (入口即本文件)

推荐日常开发: `pip install -e .` 后 `python -m objstoreexplorer`。
"""
import os
import sys

# 源码直跑时把 src/ 加入搜索路径, 使 objstoreexplorer 可被导入 (无需先安装)
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from objstoreexplorer.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
