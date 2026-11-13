# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""关于页面 — 版本 / 功能 / 技术栈 (「暮橙 Emberline」)"""
from __future__ import annotations
import tkinter as tk

from ..pages.base_page import BasePage
from ..styles import Brand, Neutral, Space, UIFont
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ...config.settings import APP_VERSION


class AboutPage(BasePage):
    """关于本软件"""

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="About",
            title="关于本工具",
            subtitle="跨平台 Tkinter 桌面客户端，用于浏览和管理 MinIO / Amazon S3 兼容的对象存储。",
            icon="info",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))

        card = Card(self.frame, title="版本与说明", icon="file-text")
        card.pack(fill=tk.BOTH, expand=True,
                  padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))

        scroll = tk.Scrollbar(card.body, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._text = tk.Text(
            card.body, bg=Neutral.BG_PANEL, relief="flat", bd=0,
            highlightthickness=0, wrap="word", font=UIFont.body(),
            yscrollcommand=scroll.set, padx=Space.MD, pady=Space.SM,
            spacing1=2, spacing3=2,
        )
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self._text.yview)

        # 文本样式
        self._text.tag_configure("title", font=UIFont.h1(),
                                 foreground=Neutral.TEXT_1, spacing1=6, spacing3=2)
        self._text.tag_configure("kicker", font=UIFont.kicker(),
                                 foreground=Brand.PRIMARY, spacing1=6, spacing3=2)
        self._text.tag_configure("h2", font=UIFont.h2(),
                                 foreground=Brand.PRIMARY_800, spacing1=14, spacing3=6)
        self._text.tag_configure("h3", font=UIFont.h3(),
                                 foreground=Neutral.TEXT_1, spacing1=4, spacing3=4)
        self._text.tag_configure("body", font=UIFont.body(),
                                 foreground=Neutral.TEXT_2, spacing3=2)
        self._text.tag_configure("caption", font=UIFont.caption(),
                                 foreground=Neutral.TEXT_3, spacing3=2)

        t = self._text
        t.insert("end", "OBJESTOREEXPLORER\n", "kicker")
        t.insert("end", "对象存储管理工具\n", "title")
        t.insert("end", f"v{APP_VERSION} — MinIO / S3 桌面客户端\n", "caption")
        t.insert("end", "Copyright (c) 2026 智维工作室 All Rights Reserved.\n", "caption")

        t.insert("end", "简介\n", "h2")
        t.insert("end",
                 "一个跨平台 (Windows / macOS / Linux) 的 Tkinter 桌面客户端，"
                 "用于浏览和管理 MinIO / Amazon S3 兼容的对象存储。\n"
                 "支持桶与对象管理、上传/下载、用户/策略、版本控制、"
                 "生命周期规则、搜索、剪贴板等。\n", "body")

        t.insert("end", "主要功能\n", "h2")
        for line in [
            "•  桶管理：列出、创建、强制删除、统计（大小/对象数）、版本控制、生命周期",
            "•  对象管理：浏览、面包屑导航、按名称过滤、分页加载、批量上传/下载、复制/剪切/粘贴、重命名、删除、属性",
            "•  搜索：对象管理页工具栏的过滤框，对当前目录按名称模糊匹配（本地过滤，不重新请求远端）",
            "•  预览：双击文件下载到本地缓存，用系统默认程序打开（大文件/非文本类型会先询问）",
            "•  用户/策略：创建/启用/禁用用户，重置密码，策略可附加/分离到指定用户（需 Admin API）",
            "•  版本控制 / 生命周期：桶级配置管理（侧边栏快捷入口）",
            "•  操作日志：记录所有用户操作，支持筛选",
            "•  加密存储：AK/SK/密码用 Fernet 加密落盘",
        ]:
            t.insert("end", line + "\n", "body")

        t.insert("end", "技术栈\n", "h2")
        t.insert("end",
                 "•  Python 3.13+  /  Tkinter (UI)  /  ThreadPoolExecutor（后台异步）\n"
                 "•  minio-py 7.x（S3 客户端）  /  cryptography（Fernet 加密）"
                 "  /  Pillow（图标）\n"
                 "•  4 层架构：config / core / services / ui\n", "body")

        t.insert("end", "致谢\n", "h2")
        t.insert("end",
                 "图标来自 Lucide（ISC License）— https://lucide.dev\n"
                 "S3 客户端来自 minio-py（Apache 2.0）"
                 "— https://github.com/minio/minio-py\n", "caption")

        t.config(state="disabled")

    def refresh(self) -> None:
        """关于页是纯静态，无需刷新"""
        pass
