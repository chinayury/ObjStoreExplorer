# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

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
