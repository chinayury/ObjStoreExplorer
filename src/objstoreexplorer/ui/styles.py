# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""ui/styles — 「暮橙 Emberline」设计 tokens (Color/Font/Spacing)

暮橙设计体系 (v0.1.0 第五轮视觉重构, 与 Web 端同值归一)。所有颜色 /
间距 / 圆角 token 集中在此, 各 widget 组件只从这里取色, 不允许硬编码
色值 —— 改一处即可全局换肤:
    奶油暖白画布 + 陶土暖橙主色 + 圆润几何 + 1px 暖色描边 + 3px 主色
    accent 条。

配色分层:
    - 画布 BG_APP 奶油暖白 (#FAF7F2), 卡片 BG_PANEL 纯白, 二级面 BG_SUBTLE
    - 主色陶土梯度 PRIMARY_50 ~ PRIMARY_900, 深色描边表达"橙→赭渐变意象"
      (Tk 无真渐变, 品牌块/主按钮一律 主色底 + 深色内描边)
    - 中性文字 TEXT_1 ~ TEXT_4 (暖褐灰阶), 边框 BORDER / BORDER_HI
    - 状态色 success / warning / danger / info 各自带浅底 (_BG) 与深字 (_FG)

强调手段 (替代旧版纯描边):
    - 卡片: 1px BORDER 描边 + 左侧 3px PRIMARY accent 条
    - 侧栏选中: PRIMARY_50 浅底 + 3px PRIMARY 左指示条
    - 统计卡: 左侧 3px accent 竖条 (颜色按指标语义取)

几何 (比上一代 6/6/10 更圆润):
    - 按钮 BTN_RADIUS 8 / 输入框 INPUT_RADIUS 8 / 卡片 CARD_RADIUS 14

约定:
    - 旧的 `Colors/Fonts/Spacing` 保留(值已同步到新体系), 确保老代码零回归。
    - 新代码请用 `Brand/Neutral/Status/Surface/Space/UIFont` 这一套语义 token。
    - 仅亮色主题。
"""
from __future__ import annotations
import tkinter
import tkinter as tk
from tkinter import ttk, font as tkfont
from typing import Optional


# ==================== Brand (陶土暖橙 / ember) ====================

class Brand:
    """品牌陶土橙阶 (暮橙 Emberline)"""

    PRIMARY       = "#C2410C"   # 主品牌陶土橙
    PRIMARY_50    = "#FFF1E7"   # 选中底 / Tag 浅底
    PRIMARY_100   = "#FFE3D0"
    PRIMARY_200   = "#FBCFB0"
    PRIMARY_300   = "#F5B58A"
    PRIMARY_400   = "#EA580C"
    PRIMARY_500   = "#C2410C"
    PRIMARY_600   = "#9A3412"   # hover
    PRIMARY_700   = "#7C2D12"   # active / pressed
    PRIMARY_800   = "#65200E"
    PRIMARY_900   = "#431407"
    PRIMARY_LIGHT = "#FFF1E7"

    # 品牌标识渐变意象 (Tk 无渐变, 用"亮主色 + 深主色"两层表达层次)
    MARK_FROM = "#EA580C"
    MARK_TO   = "#9A3412"


# ==================== Neutral (暖褐灰 / 表面) ====================

class Neutral:
    """中性色系统 (暖调)"""

    TEXT_1     = "#292018"   # 一级文字 (主标题 / 数值)
    TEXT_2     = "#6B5D4F"   # 二级文字 (描述 / 次级)
    TEXT_3     = "#A39A8C"   # 辅助 / 禁用
    TEXT_4     = "#D6CDBF"   # 占位符
    TEXT_INV   = "#FFFFFF"
    BG_APP     = "#FAF7F2"   # 整体画布 (奶油暖白)
    BG_PANEL   = "#FFFFFF"   # 卡片
    BG_SUBTLE  = "#FBF8F3"   # 二级面板 / 表头
    BG_HOVER   = "#F5EFE6"   # 行 hover
    BORDER     = "#EAE2D6"
    BORDER_HI  = "#D9CDBB"
    DIVIDER    = "#F0E9DD"


# ==================== Status (状态) ====================

class Status:
    """状态色 + 浅背景 + 深字"""

    SUCCESS      = "#047857"
    SUCCESS_BG   = "#D1FAE5"
    SUCCESS_FG   = "#065F46"
    SUCCESS_HOVER = "#065F46"
    WARNING      = "#B45309"
    WARNING_BG   = "#FEF3C7"
    WARNING_FG   = "#92400E"
    WARNING_HOVER = "#92400E"
    DANGER       = "#B91C1C"
    DANGER_BG    = "#FEE2E2"
    DANGER_FG    = "#991B1B"
    DANGER_HOVER = "#991B1B"
    INFO         = "#C2410C"
    INFO_BG      = "#FFE3D0"
    INFO_FG      = "#9A3412"
    INFO_HOVER   = "#7C2D12"

    # 连接指示
    CONNECTED    = "#047857"
    DISCONNECTED = "#A39A8C"


# ==================== Surface (圆角 / 描边 / accent) ====================

class Surface:
    """Tk 无真阴影, 用 1px 描边 + 3px accent 条模拟层次"""

    # 几何 (暮橙: 比上一代 6/6/10 更圆润)
    CARD_RADIUS   = 14
    BTN_RADIUS    = 8
    INPUT_RADIUS  = 8
    SHADOW_COLOR  = "#292018"

    # 1px 描边色 (卡片 / 输入框 / 按钮)
    SHADOW_LIGHT  = "#EAE2D6"   # 卡片描边
    SHADOW_MEDIUM = "#D9CDBB"   # 输入框 / 按钮描边

    # 左侧 accent 条宽度 (卡片 / 侧栏 / 统计卡强调手段)
    ACCENT_W = 3


# ==================== 兼容层 (旧名, 值已同步) ====================

class Colors:
    """企业级运维工具色彩系统 (兼容旧调用方)"""

    PRIMARY = Brand.PRIMARY
    PRIMARY_HOVER = Brand.PRIMARY_600
    PRIMARY_ACTIVE = Brand.PRIMARY_700
    PRIMARY_LIGHT = Brand.PRIMARY_50

    SUCCESS = Status.SUCCESS
    SUCCESS_HOVER = Status.SUCCESS_HOVER
    SUCCESS_LIGHT = Status.SUCCESS_BG

    WARNING = Status.WARNING
    WARNING_HOVER = Status.WARNING_HOVER
    WARNING_LIGHT = Status.WARNING_BG

    DANGER = Status.DANGER
    DANGER_HOVER = Status.DANGER_HOVER
    DANGER_LIGHT = Status.DANGER_BG

    TEXT_PRIMARY = Neutral.TEXT_1
    TEXT_SECONDARY = Neutral.TEXT_2
    TEXT_DISABLED = Neutral.TEXT_3

    BG_PRIMARY = Neutral.BG_PANEL
    BG_SECONDARY = Neutral.BG_APP
    BG_HOVER = Neutral.BG_HOVER

    BORDER = Neutral.BORDER
    BORDER_HOVER = Neutral.BORDER_HI

    CONNECTED = Status.CONNECTED
    DISCONNECTED = Status.DISCONNECTED

    SIDEBAR_BG = Neutral.BG_PANEL
    SIDEBAR_ACTIVE = Brand.PRIMARY_50

    TABLE_HEADER_BG = Neutral.BG_SUBTLE


class Fonts:
    """字体规范 (兼容旧调用方)"""

    TITLE   = ("Microsoft YaHei UI", 20, "bold")
    HEADING = ("Microsoft YaHei UI", 12, "bold")
    BODY    = ("Microsoft YaHei UI", 11)
    CAPTION = ("Microsoft YaHei UI", 10)
    SMALL   = ("Microsoft YaHei UI", 9)
    MONO    = ("Consolas", 10)


class Spacing:
    """间距规范 (8px 基础单位)"""

    UNIT = 8
    SMALL = 4
    MEDIUM = 12
    LARGE = 16
    XLARGE = 24


# ==================== 字体 (系统兜底链) ====================

_font_family_primary: str | None = None
_font_family_mono: str | None = None


def _resolve_font_family() -> tuple[str, str]:
    """按系统已装字体选主字体 + 等宽字体。

    主字体: Microsoft YaHei UI > Microsoft YaHei > Segoe UI > TkDefaultFont
    等宽:   Cascadia Mono > Consolas > Courier New > TkFixedFont
    """
    global _font_family_primary, _font_family_mono
    if _font_family_primary and _font_family_mono:
        return _font_family_primary, _font_family_mono

    try:
        available = set(tkfont.families())
    except Exception:
        available = set()

    primary_chain = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
    mono_chain = ("Cascadia Mono", "Consolas", "Courier New")

    _font_family_primary = next((f for f in primary_chain if f in available), "TkDefaultFont")
    _font_family_mono = next((f for f in mono_chain if f in available), "TkFixedFont")
    return _font_family_primary, _font_family_mono


class UIFont:
    """字体语义 token (值在首次访问时按系统字体决定)"""

    SIZE_DISPLAY = 22   # 页面标题
    SIZE_H1      = 19   # 区块主标题
    SIZE_H2      = 14   # 卡片标题
    SIZE_H3      = 11   # 小标题 / 表头
    SIZE_BODY    = 10   # 正文
    SIZE_BODY_SM = 9
    SIZE_CAPTION = 9

    @classmethod
    def family(cls) -> str:
        return _resolve_font_family()[0]

    @classmethod
    def display(cls):
        f, _ = _resolve_font_family()
        return (f, cls.SIZE_DISPLAY, "bold")

    @classmethod
    def h1(cls):
        f, _ = _resolve_font_family()
        return (f, cls.SIZE_H1, "bold")

    @classmethod
    def h2(cls):
        f, _ = _resolve_font_family()
        return (f, cls.SIZE_H2, "bold")

    @classmethod
    def h3(cls):
        f, _ = _resolve_font_family()
        return (f, cls.SIZE_H3, "bold")

    @classmethod
    def body(cls):
        f, _ = _resolve_font_family()
        return (f, cls.SIZE_BODY)

    @classmethod
    def body_sm(cls):
        f, _ = _resolve_font_family()
        return (f, cls.SIZE_BODY_SM)

    @classmethod
    def caption(cls):
        f, _ = _resolve_font_family()
        return (f, cls.SIZE_CAPTION)

    @classmethod
    def kicker(cls):
        """页眉上方的英文小标 (加宽字距靠 tk 无法实现, 用大写 + 粗体近似)"""
        f, _ = _resolve_font_family()
        return (f, 8, "bold")

    @classmethod
    def metric(cls, size: int | None = None):
        """统计卡大数字 (等宽, 数字不跳动)"""
        f, m = _resolve_font_family()
        return (m, size or 20, "bold")

    @classmethod
    def mono(cls, size: int = 10):
        _, m = _resolve_font_family()
        return (m, size)


# ==================== 间距 (8pt grid) ====================

class Space:
    XS   = 4
    SM   = 8
    MD   = 12
    LG   = 16
    XL   = 20
    XXL  = 24
    XXXL = 32

    BTN_H      = 34
    INPUT_H    = 34
    CARD_PAD   = 20
    TOOLBAR_H  = 62
    ROW_H      = 40
    HEADER_H   = 40

    SIDEBAR_W   = 236
    HERO_PAD_X  = 30
    HERO_PAD_Y  = 26


# ==================== ttk 样式注册 ====================

_initialized = False


def init_global_styles(root: Optional[tk.Misc] = None) -> None:
    """初始化全局 Tk 样式 (进程内只需调用一次)

    Args:
        root: Tk 根窗口。**强烈建议显式传入。**

    必须在 Tk 根窗口【之后】调用, 最好把 root 显式传进来。

    原因: `ttk.Style()` 不带 master 时会去取 (或创建) tkinter 的默认根窗口。
    如果此刻还没有任何根窗口, 它会创建一个**隐藏的临时 root** 并把它设成
    默认根。之后业务代码再 `tk.Tk()` 建真正的 root, 两个 Tk 解释器就并存了。
    后果是 ImageTk.PhotoImage 会绑定到先创建的那个解释器上, 而控件建在
    另一个上 —— 表现为一连串莫名其妙的:

        tk.TclError: image "pyimage2" doesn't exist

    而且那个临时 root 永远不会被销毁(泄漏一个解释器)。

    之前是"看运气": main.py 先建 root 再进 MainWindow, 顺序恰好是对的;
    但任何先调本函数、后建 root 的路径(测试脚本、嵌入式调用)都会踩中。
    现在改成显式要求 root, 顺序错了立刻抛清晰错误, 而不是留下半个坏掉的进程。

    Raises:
        RuntimeError: 未传 root 且当前没有默认根窗口
    """
    global _initialized
    if _initialized:
        return

    if root is None:
        # 不用 ttk.Style() 的隐式兜底: _get_default_root 在没有根窗口时直接抛,
        # 正好把"顺序错了"这件事在初始化阶段就暴露出来。
        root = tkinter._get_default_root(
            "init_global_styles 需要 Tk 根窗口, 请先 tk.Tk() 或显式传入 root="
        )

    _initialized = True
    style = ttk.Style(master=root)
    _init_treeview(style)
    _init_scrollbar(style)
    _init_combobox(style)
    _init_frame_label(style)


def _init_treeview(style: ttk.Style) -> None:
    """表格: 白底 / 浅表头 / 陶土橙选中 / 冷灰网格线"""
    for name, header_bg, row_h, sel_bg, sel_fg in (
        ("Modern.Treeview",   Neutral.BG_SUBTLE, 36, Brand.PRIMARY, "#FFFFFF"),
        ("ModernV2.Treeview", Neutral.BG_SUBTLE, Space.ROW_H, Brand.PRIMARY_50, Brand.PRIMARY_800),
    ):
        try:
            style.configure(
                name,
                background=Neutral.BG_PANEL,
                fieldbackground=Neutral.BG_PANEL,
                foreground=Neutral.TEXT_1,
                rowheight=row_h,
                font=UIFont.body(),
                borderwidth=0,
                relief="flat",
            )
            style.configure(
                f"{name}.Heading",
                background=header_bg,
                foreground=Neutral.TEXT_2,
                font=UIFont.h3(),
                relief="flat",
                borderwidth=0,
                padding=(8, 8),
            )
            style.map(
                name,
                background=[("selected", sel_bg)],
                foreground=[("selected", sel_fg)],
            )
            style.map(
                f"{name}.Heading",
                background=[("active", header_bg)],
            )
        except Exception:
            # 字体未就绪等极端情况, 降级
            pass


def _init_scrollbar(style: ttk.Style) -> None:
    """细滚动条 (与卡片描边同色系)

    横向与竖向使用同一套配色 (trough/箭头/边框在两个方向上本就一致),
    但 orient 必须分别传 —— 旧版循环体里两处 configure 参数完全相同,
    第二个其实是横向样式名配了竖向语义, 分支形同虚设。
    """
    for name, orient in (
        ("Modern.Vertical.TScrollbar", "vertical"),
        ("Modern.Horizontal.TScrollbar", "horizontal"),
    ):
        try:
            style.configure(
                name,
                orientation=orient,
                background=Neutral.BORDER_HI,
                troughcolor=Neutral.BG_SUBTLE,
                bordercolor=Neutral.BG_SUBTLE,
                arrowcolor=Neutral.TEXT_3,
                borderwidth=0,
                relief="flat",
                arrowsize=12,
            )
        except Exception:
            pass
    try:
        style.configure(
            "TCombobox",
            fieldbackground=Neutral.BG_PANEL,
            background=Neutral.BG_PANEL,
            foreground=Neutral.TEXT_1,
            arrowcolor=Neutral.TEXT_3,
            bordercolor=Neutral.BORDER_HI,
            lightcolor=Neutral.BORDER_HI,
            darkcolor=Neutral.BORDER_HI,
            borderwidth=1,
            relief="solid",
            padding=(8, 6),
            font=UIFont.body(),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", Neutral.BG_PANEL)],
            bordercolor=[("focus", Brand.PRIMARY)],
        )
    except Exception:
        pass


def _init_combobox(style: ttk.Style) -> None:
    """Combobox 下拉列表底色 (部分平台需单独设置 root option)"""
    try:
        style.layout("TCombobox", style.layout("TCombobox"))
    except Exception:
        pass


def _init_frame_label(style: ttk.Style) -> None:
    """Modern.TFrame / Modern.TLabel / Modern.TButton 基础容器样式

    这些样式名在 text_viewer / bucket_policy_dialog 等处被显式引用,
    但 TFrame/TLabel 从未注册过 (TButton 亦同) —— ttk 对未知样式名静默
    回落到默认 TFrame/TLabel/TButton, 表现为"对话框里的 ttk 容器是系统
    灰底、预设按钮是 Windows 原生立体按钮", 与曜蓝体系明显割裂。
    这里补上注册, 让它们与曜蓝的画布 / 卡片底色 / 按钮观感一致。
    """
    try:
        style.configure("Modern.TFrame", background=Neutral.BG_PANEL, borderwidth=0)
        style.configure(
            "Modern.TLabel",
            background=Neutral.BG_PANEL,
            foreground=Neutral.TEXT_1,
            font=UIFont.body(),
        )
    except Exception:
        pass
    try:
        # 桶策略预设按钮 (bucket_policy_dialog 的 ttk.Button) 专用:
        # 白底 + 1px 冷灰描边 + flat, hover 转陶土橙浅底, 与 create_secondary_button 对齐
        style.configure(
            "Modern.TButton",
            background=Neutral.BG_PANEL,
            foreground=Neutral.TEXT_1,
            font=UIFont.body(),
            borderwidth=1,
            relief="solid",
            padding=(10, 5),
            focuscolor=Neutral.BG_PANEL,
        )
        style.map(
            "Modern.TButton",
            background=[("active", Brand.PRIMARY_50), ("pressed", Brand.PRIMARY_100)],
            foreground=[("active", Brand.PRIMARY_800), ("pressed", Brand.PRIMARY_800)],
            bordercolor=[("focus", Brand.PRIMARY)],
        )
    except Exception:
        pass


def ttk_scrollbar(parent, orient: str = "vertical"):
    """统一外观的滚动条工厂

    从 settings_page.py 移到此处: 它属于样式层而不是某个页面, 放在页面
    文件末尾会让其它页面无法复用 (此前只有设置页在用)。
    """
    from tkinter import ttk

    orient = "horizontal" if orient == "horizontal" else "vertical"
    style = "Modern.Horizontal.TScrollbar" if orient == "horizontal" \
        else "Modern.Vertical.TScrollbar"
    return ttk.Scrollbar(parent, orient=orient, style=style)
