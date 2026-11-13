# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""截屏模块 - 全屏 / 当前窗口 / 错误弹窗

Windows 优先实现 (pywin32 + Pillow ImageGrab).
macOS 退到 screencapture 命令, Linux 退到 scrot/import.

API:
  capture_screen() -> bytes                  - 全屏 PNG
  capture_active_window() -> bytes           - 当前激活窗口
  capture_clipboard_image() -> Optional[bytes] - 从剪贴板读图 (Ctrl+V 粘贴用)
"""
import contextlib
import io
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator, Optional

try:
    from PIL import ImageGrab, Image
    _PIL_OK = True
except ImportError:  # pragma: no cover
    _PIL_OK = False


_SYSTEM = platform.system()


# ==================== 内部工具 ====================

@contextlib.contextmanager
def _temp_capture_dir() -> Iterator[Path]:
    """本次截屏独占一个临时目录, 退出时整目录删除。

    之前硬编码 /tmp/_ose_screenshot.png: 并发截屏会互相覆盖同一个文件,
    文件权限默认 0644 (其它用户可读), 而且失败路径下文件留在磁盘上。
    mkdtemp 建的是 0700 私有目录, 名字唯一, finally 保证清掉。
    """
    d = Path(tempfile.mkdtemp(prefix="ose_shot_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _load_png(path: Path) -> "Image.Image":
    """读 PNG 为独立的内存 Image (及时关掉文件句柄, 否则临时目录删不掉)"""
    with Image.open(path) as im:
        return im.copy()


def _release_gdi(bmp, save_dc, mfc_dc, hwnd, hwnd_dc) -> None:
    """按创建的逆序释放 GDI 对象: bitmap -> save_dc -> mfc_dc -> hwnd_dc。

    每一步各自 try/except: 释放本身就是清理动作, 一处失败不能挡住后面的释放。
    每进程 GDI 句柄上限约 10000, 反复截屏失败而不释放会让**其它窗口开始变白 /
    绘制异常**, 排查时完全看不出跟截屏有关。
    """
    import win32gui
    try:
        if bmp is not None:
            win32gui.DeleteObject(bmp.GetHandle())
    except Exception:
        pass
    try:
        if save_dc is not None:
            save_dc.DeleteDC()
    except Exception:
        pass
    try:
        if mfc_dc is not None:
            mfc_dc.DeleteDC()
    except Exception:
        pass
    try:
        if hwnd_dc is not None and hwnd:
            win32gui.ReleaseDC(hwnd, hwnd_dc)
    except Exception:
        pass


# ==================== 全屏 ====================

def capture_screen() -> bytes:
    """全屏截图, 返回 PNG bytes.

    失败时抛 RuntimeError.
    """
    if not _PIL_OK:
        raise RuntimeError("Pillow 未安装, 无法截屏")
    if _SYSTEM == "Windows":
        # Windows 上 ImageGrab.grab() 工作良好
        img = ImageGrab.grab(all_screens=True)
    elif _SYSTEM == "Darwin":
        # macOS 需要 screencapture -x (无声音), 截到独占临时目录再读
        with _temp_capture_dir() as tmpdir:
            tmp = tmpdir / "screenshot.png"
            subprocess.run(["screencapture", "-x", str(tmp)], check=True, timeout=10)
            img = _load_png(tmp)
    else:
        # Linux: 尝试 scrot / import
        with _temp_capture_dir() as tmpdir:
            tmp = tmpdir / "screenshot.png"
            for cmd in (["scrot", str(tmp)], ["import", str(tmp)]):
                try:
                    subprocess.run(cmd, check=True, timeout=10, capture_output=True)
                    img = _load_png(tmp)
                    break
                except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    continue
            else:
                raise RuntimeError("Linux 截屏需 scrot 或 ImageMagick (import)")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ==================== 当前激活窗口 ====================

def capture_active_window() -> bytes:
    """截取当前激活窗口 (Windows 用 pywin32, 其它平台回退全屏).

    失败回退 capture_screen().
    """
    if _SYSTEM == "Windows":
        try:
            import ctypes
            import win32gui
            import win32ui

            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                raise RuntimeError("GetForegroundWindow 返回 0")
            # 取窗口客户区尺寸 (不含标题栏)
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w = right - left
            h = bottom - top
            if w <= 0 or h <= 0:
                raise RuntimeError(f"窗口尺寸异常: {w}x{h}")

            # ⚠ 四个 GDI 对象的释放必须放在 finally: 中间任一步抛异常
            #   (PrintWindow / GetBitmapBits 失败) 都会跳过原来的清理代码,
            #   句柄一路泄漏, 反复失败就把 GDI 配额耗尽。
            hwnd_dc = mfc_dc = save_dc = bmp = None
            try:
                hwnd_dc = win32gui.GetWindowDC(hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()
                bmp = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(mfc_dc, w, h)
                save_dc.SelectObject(bmp)

                # PW_RENDERFULLCONTENT = 0x00000002 (Win 8.1+ 含 DWM 合成)
                ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0x2)

                bmp_info = bmp.GetInfo()
                bmp_str = bmp.GetBitmapBits(True)
                img = Image.frombuffer(
                    "RGB",
                    (bmp_info["bmWidth"], bmp_info["bmHeight"]),
                    bmp_str, "raw", "BGRX", 0, 1,
                )
            finally:
                _release_gdi(bmp, save_dc, mfc_dc, hwnd, hwnd_dc)

            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
        except Exception:
            # 回退全屏
            return capture_screen()
    else:
        return capture_screen()


# ==================== 剪贴板 ====================

def capture_clipboard_image() -> Optional[bytes]:
    """从系统剪贴板读取图片 (用户 Ctrl+V 粘贴时调用).

    返回 PNG bytes, 剪贴板无图返回 None.
    """
    if not _PIL_OK:
        return None
    try:
        img = ImageGrab.grabclipboard()
        if img is None:
            return None
        if isinstance(img, list):
            # PIL 在某些平台返回文件路径列表
            if not img:
                return None
            img = _load_png(Path(img[0]))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None
