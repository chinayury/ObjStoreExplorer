# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""utils/text_codec - 文本字节流编码自动识别 (桌面 + Web 双形态共用)

借鉴 Evil_Pig/CloudStore 的「文本按编码自动识别」实践 (中文场景刚需):
    桶里的日志 / 配置文件可能是 Windows 记事本存的 GBK, 也可能是
    GB18030 / Big5 / Shift-JIS, 甚至带 BOM 的 UTF-8。无脑按 UTF-8 解
    会满屏乱码或直接 UnicodeDecodeError。

识别顺序 (按本项目用户域从常见到罕见):
    1. UTF-8 (含 BOM 的 utf-8-sig)
    2. GB18030 (中文 Windows 记事本默认, 且是 GBK 超集)
    3. Big5 (繁体中文)
    4. Shift-JIS (日文)
    5. UTF-16 (带 BOM 时)
    6. latin-1 (兜底: 单字节不会失败, 配合 errors=replace)

GB18030 覆盖全部 Unicode 码位, 对任意字节序列大多可解 —— 因此排在
Big5/Shift-JIS 之前是以「中文用户域优先」的取舍: GBK 文件能正确解码,
Big5 文件会得到可读但可能非预期的汉字 (用户可从 UI 上的编码标注察觉)。

用法:
    from .text_codec import decode_best_effort
    text, encoding = decode_best_effort(raw_bytes)
"""
from __future__ import annotations
from typing import Tuple


# 候选编码顺序 = 优先级 (中文用户域)
# ⚠ UTF-16 不在候选链: 无 BOM 的 UTF-16 与任意双字节序列不可区分
#   (测试实测: 16 个 0x80-0x8F 字节会被 "utf-16" 解成汉字), 误判为
#   乱码比不解更糟。UTF-16 只认 BOM (调用方先行判定)。
_CANDIDATES = ("utf-8", "gb18030", "big5", "shift_jis")
# UI 展示名映射
_DISPLAY = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 (带 BOM)",
    "gb18030": "GB18030",
    "big5": "Big5",
    "shift_jis": "Shift-JIS",
    "utf-16": "UTF-16",
    "latin-1": "Latin-1 (兜底)",
}


def _try_decode(data: bytes, encoding: str) -> Tuple[bool, str]:
    """严格模式尝试解码 (不允许替换字符蒙混过关)"""
    try:
        return True, data.decode(encoding, errors="strict")
    except (UnicodeDecodeError, LookupError, ValueError):
        return False, ""


def decode_best_effort(data: bytes) -> Tuple[str, str]:
    """把字节流解码成文本, 返回 (text, encoding)。

    encoding 为实际使用的编码展示名 (UI 可标注「已按 GB18030 解码」);
    全部候选失败时兜底 latin-1 + errors=replace, 绝不抛异常。
    """
    if data is None:
        return "", "UTF-8"
    if isinstance(data, str):  # 防御: 调用方已解过码
        return data, "UTF-8"

    # 空内容: 直接按 UTF-8 解 (空串), 不走候选链
    if not data:
        return "", "UTF-8"

    # BOM 优先判定 (带 BOM 的 UTF-8/UTF-16 不会误判)
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig"), _DISPLAY["utf-8-sig"]
        except UnicodeDecodeError:
            pass
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), _DISPLAY["utf-16"]
        except (UnicodeDecodeError, ValueError):
            pass

    for enc in _CANDIDATES:
        ok, text = _try_decode(data, enc)
        if ok:
            return text, _DISPLAY.get(enc, enc.upper())

    # 兜底: latin-1 单字节解码不会失败; 替换字符让用户看出「这里有非文本字节」
    return data.decode("latin-1", errors="replace"), _DISPLAY["latin-1"]


def sniff_encoding(data: bytes) -> str:
    """只返回识别出的编码名 (不解码全文, 供 UI 预标注)"""
    return decode_best_effort(data)[1]
