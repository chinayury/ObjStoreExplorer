# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

# -*- mode: python ; coding: utf-8 -*-
"""
ObjStoreExplorer PyInstaller 打包配置 (onedir 模式)

早期用单文件 (onefile): dist/ObjStoreExplorer.exe
  → 360 / 火绒 / Windows Defender 报"银狐木马" (高误报, 自解压特征)
现用 onedir 模式: dist/ObjStoreExplorer/ 目录 (含 .exe + .dll + .pyd)
  → 误报率大幅下降, 但分发时需分发整个目录
  → CI 在 build 完成后压缩成 zip 上传 artifact

用法:
    pip install pyinstaller
    pyinstaller build.spec --clean
    # 或: python build.py

产物:
    dist/ObjStoreExplorer/                      ← 整个目录, 双击里面的 ObjStoreExplorer.exe
    dist/ObjStoreExplorer-v<版本>-win-x64.zip  ← (仅 build.py 自动打包, 手动跑 pyinstaller 没有)

注意: 所有路径都锚在 SPECPATH (本文件所在目录) 上, 因此
      从仓库根执行 `pyinstaller objstoreexplorer-local/build.spec` 也能正确工作。
"""
import os
import tempfile
from pathlib import Path

block_cipher = None

PROJECT_ROOT = Path(os.path.abspath(SPECPATH))   # SPECPATH 由 PyInstaller 注入
ENTRY_SCRIPT = str(PROJECT_ROOT / "main.py")     # 绝对路径: 不依赖调用时的 CWD
LOGO_ICO = PROJECT_ROOT / "src" / "objstoreexplorer" / "resources" / "icons" / "logo.ico"
ICONS_DIR = PROJECT_ROOT / "src" / "objstoreexplorer" / "resources" / "icons"
# ⚠ 打进包的是 feedback.yaml.example（全占位符）的内容，落位名 feedback.yaml。
#   三个独立原因，缺一不可：
#   1) 可构建性：config/feedback.yaml 被 .gitignore 排除（里面有真实 app_key），
#      CI 全新 checkout 根本没有这个文件。直接打会在 PyInstaller 阶段报
#      "Unable to find ... config\feedback.yaml" —— 本地能构建不代表 CI 能。
#   2) 安全（更要紧）：就算本地存在，把开发者本机的 feedback.yaml 打进分发包，
#      等于把真实 app_key 烘进要发给用户的 exe。那串 key 能代表用户向反馈平台
#      提交数据，属于凭据随产物外泄。
#   3) 文件名：PyInstaller 的 datas 保留**源文件基名**。直接把
#      feedback.yaml.example 丢进去，产物里就叫 feedback.yaml.example，
#      而 utils/feedback_client.py 找的是 feedback.yaml —— 兜底配置等于没打进去。
#      （本项目真踩过：打包成功、产物 32MB、唯独反馈配置缺失）
#      所以先复制成 staging 目录下的 feedback.yaml 再交给 datas。
#   运行时 _resolve_config_path() 优先读 <exe目录>/config/feedback.yaml
#   （用户可编辑），打进去的这份只是兜底默认值，所以用 example 完全够用。
FEEDBACK_YAML_EXAMPLE = PROJECT_ROOT / "src" / "objstoreexplorer" / "config" / "feedback.yaml.example"
if not FEEDBACK_YAML_EXAMPLE.exists():
    raise SystemExit(
        "Missing src/objstoreexplorer/config/feedback.yaml.example: the fallback "
        "feedback config template is required for packaging and must stay in VCS.")

_STAGE = Path(tempfile.mkdtemp(prefix="ose_feedback_stage_"))
STAGED_FEEDBACK_YAML = _STAGE / "feedback.yaml"
STAGED_FEEDBACK_YAML.write_bytes(FEEDBACK_YAML_EXAMPLE.read_bytes())
print("[build.spec] staged feedback fallback: %s -> %s (as feedback.yaml)"
      % (FEEDBACK_YAML_EXAMPLE.name, STAGED_FEEDBACK_YAML))

# 入口
a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=[
        # 把整个 resources/icons/ 目录打进 exe (含所有 PNG/ICO)
        # 运行时从 sys._MEIPASS/resources/icons/ 读取
        # 注意: 必须是目录,源 PyInstaller 会递归扫描所有文件
        (str(ICONS_DIR), 'resources/icons'),
        # ⚠ feedback.yaml 必须显式打包, 否则发布的 exe 自带反馈功能会静默退化
        #   成离线模式, 用户还无处可改 (与"requirements 漏写 PyYAML → 点反馈没反应"
        #   是同一类事故)。
        #
        #   注意它会落在 <exe目录>/_internal/config/feedback.yaml —— PyInstaller
        #   onedir 把所有 datas 收进 _internal/。所以 utils/feedback_client.py
        #   的 _resolve_config_path() 同时认两个位置:
        #     ① <exe目录>/data/config/feedback.yaml          用户可编辑, 优先级高
        #     ② <exe目录>/_internal/config/feedback.yaml 这里, 即本条打进去的
        #   这样用户想改配置不必重打包, 放 ① 即可覆盖 ②。
        #   ② 打的是 .example 的内容、落位名 feedback.yaml(见上方
        #   FEEDBACK_YAML_EXAMPLE 的注释): CI 能构建 + 不泄露真实 app_key +
        #   文件名对得上, 三个目标同时满足。
        (str(STAGED_FEEDBACK_YAML), 'config'),
    ],
    hiddenimports=[
        # tkinter 显式声明, 避免漏打包
        'tkinter', 'tkinter.ttk', 'tkinter.filedialog',
        'tkinter.messagebox', 'tkinter.simpledialog',
        # Pillow 在 PyInstaller 打包时需要这个 finder
        'PIL._tkinter_finder',
        # cryptography / minio 是隐式依赖
        'cryptography', 'minio',
        # yaml 显式声明双保险 (feedback_client 读 feedback.yaml;
        # 之前 requirements 漏写 PyYAML, 打包缺 yaml 点反馈直接没反应)
        'yaml',
        # ⚠ pywin32 全部补齐。core/encryption.py 与 utils/screenshot.py 里的
        #   win32security/win32api/win32gui/win32ui/win32con 全是【函数体内的
        #   延迟 import】, PyInstaller 的静态分析最容易漏掉这种形态;
        #   win32ui 还额外依赖 pywintypes 与 pywin32_system32 的 DLL 加载
        #   机制, 是打包翻车重灾区。漏了的表现是"源码能跑, exe 一截图/一
        #   收紧密钥权限就 ImportError"。
        'win32api', 'win32con', 'win32gui', 'win32ui',
        'win32security', 'win32event', 'win32file', 'win32pipe',
        'pywintypes', 'win32service', 'win32ts',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除大体积无关模块, 显著缩小目录
        'matplotlib', 'numpy', 'pandas', 'scipy', 'sympy',
        'pytest', 'IPython', 'jupyter', 'notebook',
        'PyQt5', 'PyQt6', 'wx', 'gtk',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ===== 关键: 程序图标 =====
# Windows 资源管理器 .exe 图标 / Alt-Tab / 任务栏 都用这个
icon_path = str(LOGO_ICO) if LOGO_ICO.exists() else None

# ===== onedir 模式 =====
# exclude_binaries=True: exe 不嵌入二进制, 留给 COLLECT 收集到目录
# 这样产物是 dist/ObjStoreExplorer/ 目录 (而非单文件), 大幅降低杀软误报
exe = EXE(
    pyz,
    a.scripts,
    [],                                     # 关键: onedir 模式不放 binaries
    exclude_binaries=True,                  # 关键: onedir 模式
    name='ObjStoreExplorer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # ⚠ 关掉 UPX。UPX 压缩壳是杀软启发式扫描的高触发特征, 而本项目从
    #   onefile 改 onedir 的目的正是降低误报 (见文件头说明)。开着 UPX
    #   等于把刚解决的问题又请回来。真要压缩体积应该改用安装包工具,
    #   而不是给 exe 套壳。
    upx=False,
    upx_exclude=[                           # 保留列表, 即使将来重开 UPX 也不压系统 dll
        'vcruntime140.dll',
        'msvcp140.dll',
        'concrt140.dll',
        'ucrtbase.dll',
    ],
    runtime_tmpdir=None,
    console=False,                         # GUI 程序, 不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,                      # None = 自动
    codesign_identity=None,                 # TODO: 配代码签名 (暂未配, 靠 onedir 降低误报)
    entitlements_file=None,
    icon=icon_path,
)

# 把所有二进制 + 数据 + zip 收集到 dist/ObjStoreExplorer/ 目录
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,                            # 与 EXE 保持一致, 理由见上
    upx_exclude=[
        'vcruntime140.dll',
        'msvcp140.dll',
        'concrt140.dll',
        'ucrtbase.dll',
    ],
    name='ObjStoreExplorer',                # 产物目录名: dist/ObjStoreExplorer/
)

