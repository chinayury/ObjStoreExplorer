# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""一键打包脚本 - 把 ObjStoreExplorer 打成 onedir 目录 (+)

用法:
    python build.py
    # 或: pyinstaller build.spec --clean

前置:
    pip install pyinstaller

产物 (+ onedir 模式):
    dist/ObjStoreExplorer/                        ← 整个目录, 双击里面的 ObjStoreExplorer.exe
    dist/ObjStoreExplorer-v<version>-win-x64.zip  ← 自动打包, 方便分发
    dist/SHA256SUMS.txt                           ← 校验和

变更历史:
    及更早: 单文件 dist/ObjStoreExplorer.exe (PyInstaller onefile)
      → 360/火绒/Defender 报"银狐木马" (自解压特征触发启发式)
    改 onedir, 目录式分发, 误报率大幅下降
"""
import os
import re
import sys
import shutil
import subprocess
import zipfile
import hashlib
from pathlib import Path

# Windows runner 控制台默认 GBK 编码, 输出 Unicode 字符 (\u2713 等) 会 UnicodeEncodeError
# 强制 stdout/stderr 用 utf-8 (Python 3.7+ reconfigure)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

PROJECT_ROOT = Path(__file__).resolve().parent


def _detect_version() -> str:
    """读取版本号 —— 唯一真源是 config/settings.py 的 APP_VERSION

    v0.1.0 起移除了 OSE_VERSION 环境变量覆盖机制。原先的逻辑是
    "OSE_VERSION > settings.py > 硬编码 0.1.0", 存在两个问题:

    1. **版本漂移**: CI 在 tag 流水线里设 OSE_VERSION, 于是打出来的 zip
       名跟代码里的 APP_VERSION 不一致, 同一个 commit 可能产出两个版本号;
    2. **静默兜底**: settings.py 读不到时直接 return "0.1.0", 一旦有人
       改名或挪动该文件, 打包会"成功"但版本号是错的, 没有任何报错。

    现在: 只认 settings.py; 读不到就明确失败, 让人来改, 而不是猜一个。
    """
    settings_file = PROJECT_ROOT / "src" / "objstoreexplorer" / "config" / "settings.py"
    if not settings_file.exists():
        raise FileNotFoundError(
            f"找不到版本号定义文件: {settings_file}\n"
            "版本号唯一真源是 src/objstoreexplorer/config/settings.py 里的 APP_VERSION。"
        )
    text = settings_file.read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not m:
        raise ValueError(
            f"{settings_file} 里读不到 APP_VERSION 定义。\n"
            "请确认该文件里有形如 APP_VERSION = \"0.1.0\" 的赋值。"
        )
    return m.group(1)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    # 1. 校验
    icon = PROJECT_ROOT / "src" / "objstoreexplorer" / "resources" / "icons" / "logo.ico"
    if not icon.is_file():
        print(f"ERROR: 找不到 {icon},请确认 logo.ico 在 src/objstoreexplorer/resources/icons/ 目录")
        return 1

    # 2. 校验 PyInstaller
    try:
        import importlib.util
        if importlib.util.find_spec("PyInstaller") is None:
            raise ImportError("PyInstaller 未安装")
    except ImportError:
        print("ERROR: 未安装 pyinstaller,先跑 `pip install pyinstaller`")
        return 1

    # 3. 清旧
    for d in ("build", "dist"):
        p = PROJECT_ROOT / d
        if p.exists():
            print(f"清理 {p}/ ...")
            shutil.rmtree(p, ignore_errors=True)

    # 4. 打包 (onedir 模式, 见 build.spec)
    spec = PROJECT_ROOT / "build.spec"
    print(f"运行: pyinstaller {spec} --clean")
    rc = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(spec), "--clean", "--noconfirm"],
        cwd=str(PROJECT_ROOT),
    )
    if rc.returncode != 0:
        print("ERROR: pyinstaller 失败")
        return rc.returncode

    # 5. 校验产物: dist/ObjStoreExplorer/ 目录
    app_dir = PROJECT_ROOT / "dist" / "ObjStoreExplorer"
    exe = app_dir / "ObjStoreExplorer.exe"
    if not exe.exists():
        print(f"WARN: 没找到 {exe},检查上面日志")
        return 1

    # 6. 生成 SHA256SUMS.txt (含目录里 ObjStoreExplorer.exe + zip 之后的 zip)
    version = _detect_version()
    zip_name = f"ObjStoreExplorer-v{version}-win-x64.zip"
    zip_path = PROJECT_ROOT / "dist" / zip_name

    # 6.1 先把整个目录打包成 zip
    print(f"\n打包目录成 zip: {zip_name}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(app_dir.rglob("*")):
            if f.is_file():
                # zip 内路径用正斜杠 (Windows 兼容)
                arcname = str(f.relative_to(app_dir.parent)).replace(os.sep, "/")
                zf.write(f, arcname)
    zip_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"  zip 大小: {zip_mb:.1f} MB")

    # 6.2 生成 SHA256SUMS.txt (主要条目)
    sums = []
    sums.append(f"{_sha256_file(exe)}  ObjStoreExplorer/ObjStoreExplorer.exe")
    sums.append(f"{_sha256_file(zip_path)}  {zip_name}")
    sums_path = PROJECT_ROOT / "dist" / "SHA256SUMS.txt"
    sums_path.write_text("\n".join(sums) + "\n", encoding="ascii")
    print(f"  SHA256SUMS.txt: {len(sums)} 条")

    # 7. 总结
    app_size_mb = sum(f.stat().st_size for f in app_dir.rglob("*") if f.is_file()) / 1024 / 1024
    print("\n[OK] 打包完成 (onedir 模式):")
    print(f"  目录:  {app_dir}/  ({app_size_mb:.1f} MB 总, 含 ObjStoreExplorer.exe + .dll + .pyd)")
    print(f"  zip:   {zip_path}  ({zip_mb:.1f} MB, 推荐分发)")
    print(f"  校验:  {sums_path}")
    print(f"  图标:  {icon}")
    print("\n[INFO] 分发提示:")
    print(f"  用户需解压 {zip_name}, 进入 ObjStoreExplorer/ 目录, 双击 ObjStoreExplorer.exe")
    print("  (整个目录必须保持完整, 不能只复制 .exe)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
