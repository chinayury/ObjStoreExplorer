# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""ui/windows/bucket_policy_dialog — 桶访问策略编辑器

对象存储控制台的常规能力: 把桶设为公共读、限制来源 IP、限定请求方式等。
之前只能改 IAM 用户策略, 桶本身的访问策略完全够不着。

⚠ 这是高危操作 —— 一个 Principal 为 "*" 的 GetObject 策略等于把整个桶
   公开。所以:
     - 每次下发前必须展示新旧对比, 让用户看清差别;
     - 预设里"公共读"这类危险项额外加红字警告;
     - JSON 语法错当场拦下, 不把错误发给服务端。
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk

from ..styles import Fonts, Neutral, Space, Status
from ..threading_bridge import run_async
from ..widgets.buttons import create_primary_button, create_secondary_button
from ..widgets.notifications import notify
from ..widgets.text_viewer import show_text_viewer


# 常用预设。public-read 风险最高, 单独标出来
PRESETS: dict = {
    "私有 (推荐)": {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Deny",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:*"],
            "Resource": [f"arn:aws:s3:::{bucket}" for bucket in ["BUCKET"]],
        }],
    },
    "公共读 (匿名可下载)": {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{bucket}/" for bucket in ["BUCKET"]],
        }],
    },
    "公共读写 (极危险)": {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:PutObject", "s3:DeleteObject"],
            "Resource": [f"arn:aws:s3:::{bucket}/" for bucket in ["BUCKET"]],
        }],
    },
}

DANGER_PRESETS = {"公共读 (匿名可下载)", "公共读写 (极危险)"}


class BucketPolicyDialog(tk.Toplevel):
    """桶策略编辑器

    Args:
        parent: 父窗口
        locator: ServiceLocator
        bucket: 桶名
    """

    def __init__(self, parent, locator, bucket: str):
        super().__init__(parent)
        self.locator = locator
        self.bucket = bucket
        self._closed = False
        self._original: str = ""

        self.title(f"桶访问策略 — {bucket}")
        self.geometry("860x640")
        self.minsize(700, 520)
        try:
            self.transient(parent)
        except tk.TclError:
            pass

        self._build_ui()
        self._load()

    # ==================== UI ====================

    def _build_ui(self) -> None:
        body = ttk.Frame(self, style="Modern.TFrame")
        body.pack(fill="both", expand=True, padx=Space.LG, pady=Space.LG)

        top = ttk.Frame(body, style="Modern.TFrame")
        top.pack(fill="x")

        ttk.Label(
            top,
            text=f"桶 {self.bucket} 的访问策略",
            style="Modern.TLabel",
        ).pack(side="left")

        self.status = ttk.Label(top, text="", style="Modern.TLabel")
        self.status.pack(side="right")

        warn = tk.Label(
            body,
            text=("注意: 策略里的 Principal 为 \"*\" 表示任何人都能访问。设为公共读之后，"
                  "任何拿到链接的人都能下载桶里的文件，且无法通过本程序收回日志。"),
            font=Fonts.BODY,
            fg=Status.DANGER_FG,
            bg=Status.DANGER_BG,
            justify="left",
            wraplength=800,
            padx=Space.SM,
            pady=Space.XS,
        )
        warn.pack(fill="x", pady=(Space.SM, Space.SM))

        # 预设
        preset_row = ttk.Frame(body, style="Modern.TFrame")
        preset_row.pack(fill="x", pady=(0, Space.SM))
        ttk.Label(preset_row, text="预设:", style="Modern.TLabel").pack(side="left")
        for name in PRESETS:
            b = ttk.Button(preset_row, text=name, style="Modern.TButton",
                           command=lambda n=name: self._apply_preset(n))
            b.pack(side="left", padx=Space.XS)

        # 编辑区
        edit_frame = ttk.Frame(body, style="Modern.TFrame")
        edit_frame.pack(fill="both", expand=True)

        self.text = tk.Text(
            edit_frame,
            wrap="none",                    # JSON 不自动换行, 横向滚动看完整行
            font=Fonts.MONO,
            bg=Neutral.BG_SUBTLE,
            fg=Neutral.TEXT_1,
            insertbackground=Neutral.TEXT_1,
            relief="flat",
            borderwidth=0,
            padx=Space.SM,
            pady=Space.SM,
            highlightthickness=0,
            undo=True,
        )
        self.text.pack(side="left", fill="both", expand=True)

        vs = ttk.Scrollbar(edit_frame, orient="vertical", command=self.text.yview)
        vs.pack(side="right", fill="y")
        hs = ttk.Scrollbar(edit_frame, orient="horizontal", command=self.text.xview)
        hs.pack(side="bottom", fill="x")
        self.text.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        # 底部按钮
        footer = ttk.Frame(self, style="Modern.TFrame")
        footer.pack(fill="x", padx=Space.LG, pady=(0, Space.LG))

        create_secondary_button(
            footer, "格式化", command=self._format_json, width=10
        ).pack(side="left", padx=(0, Space.SM))
        create_secondary_button(
            footer, "查看当前", command=self._show_current, width=10
        ).pack(side="left", padx=(0, Space.SM))

        create_primary_button(footer, "下发策略", command=self._apply, width=12).pack(side="right")
        create_secondary_button(
            footer, "删除策略 (恢复私有)", command=self._delete, width=20
        ).pack(side="right", padx=(0, Space.SM))
        create_secondary_button(footer, "关闭", command=self._close, width=8).pack(side="right")

        self.bind("<Escape>", lambda e: self._close())

    # ==================== 数据 ====================

    def _valid(self) -> bool:
        return not self._closed and bool(self.winfo_exists())

    def _load(self) -> None:
        def on_ok(result):
            if not self._valid():
                return
            if result is None:
                self._show_unset()
                return
            txt = json.dumps(result, indent=2, ensure_ascii=False)
            self._original = txt
            self.text.delete("1.0", "end")
            self.text.insert("1.0", txt)
            self.status.configure(text="当前: 已设置策略")

        def on_err(msg):
            if not self._valid():
                return
            # ⚠ "桶上没有策略" 是 S3 的正常状态, 不是错误。
            #   新建桶默认就是私有的, 所以这是用户最常遇到的情况 ——
            #   弹错误框会让人以为程序坏了。core 的 get_bucket_policy
            #   正常时返回 (True, None), 但个别 MinIO 兼容实现会直接抛
            #   NoSuchBucketPolicy, 这里一并兜住。
            text = str(msg)
            if "nosuchbucketpolicy" in text.lower() or "no such bucket policy" in text.lower():
                self._show_unset()
                return
            self.status.configure(text=f"读取失败: {msg}")
            messagebox.showerror("读取失败", msg, parent=self)
            self.locator.logger.error("get_bucket_policy", self.bucket, msg)

        def work():
            return self.locator.s3_client.get_bucket_policy(self.bucket)

        run_async(self, work, on_ok, on_err, "读取桶策略")

    def _show_unset(self) -> None:
        """桶上没有策略 —— 展示为"私有"而不是错误"""
        self._original = ""
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self._preset_text("私有 (推荐)"))
        self.status.configure(text="当前: 未设置策略 (桶是私有的)")

    def _current(self) -> str:
        return self.text.get("1.0", "end-1c").strip()

    def _preset_text(self, name: str) -> str:
        import copy
        doc = copy.deepcopy(PRESETS[name])
        for st in doc.get("Statement", []):
            res = st.get("Resource")
            if isinstance(res, list):
                st["Resource"] = [r.replace("BUCKET", self.bucket) for r in res]
        return json.dumps(doc, indent=2, ensure_ascii=False)

    def _apply_preset(self, name: str) -> None:
        if name in DANGER_PRESETS and not messagebox.askyesno(
            "确认套用危险预设",
            f"「{name}」会让【任何拿到链接的人】都能访问这个桶。\n\n确定继续?",
            parent=self,
        ):
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self._preset_text(name))

    def _format_json(self) -> None:
        try:
            doc = json.loads(self._current())
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON 语法错误", f"第 {e.lineno} 行第 {e.colno} 列: {e.msg}",
                                 parent=self)
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", json.dumps(doc, indent=2, ensure_ascii=False))
        self.status.configure(text="已格式化")

    def _show_current(self) -> None:
        show_text_viewer(self, f"{self.bucket} 当前的桶策略",
                         self._original or "(未设置策略, 桶是私有的)")

    def _diff_hint(self, new_txt: str) -> str:
        if not self._original:
            return "当前桶没有策略 (私有)。下发后将变成上面这份。"
        if new_txt.strip() == self._original.strip():
            return "内容与当前策略完全相同, 下发不会有变化。"
        return "注意: 下面要下发的策略与当前【不同】, 请确认这是你要的。"

    def _apply(self) -> None:
        txt = self._current()
        if not txt:
            messagebox.showwarning("提示", "策略内容为空", parent=self)
            return
        try:
            doc = json.loads(txt)
        except json.JSONDecodeError as e:
            messagebox.showerror(
                "JSON 语法错误",
                f"第 {e.lineno} 行第 {e.colno} 列: {e.msg}\n\n策略未下发。",
                parent=self,
            )
            return
        if not isinstance(doc, dict) or "Statement" not in doc:
            messagebox.showerror("策略无效", "策略必须包含 Statement 字段", parent=self)
            return

        # 公开性检测 —— 拦住最危险的一类
        warn = ""
        for st in (doc.get("Statement") or []):
            if not isinstance(st, dict):
                continue
            princ = st.get("Principal") or {}
            aws = princ.get("AWS") if isinstance(princ, dict) else None
            if isinstance(aws, list) and "*" in aws:
                warn = "\n\n注意: 该策略对匿名用户开放, 等同于把桶公开在互联网上。"
        if not messagebox.askyesno(
            "确认下发",
            f"把下面的策略下发到桶 {self.bucket}?\n\n{self._diff_hint(txt)}{warn}",
            parent=self,
        ):
            return

        new_txt = txt

        def on_ok(msg):
            if not self._valid():
                return
            self._original = new_txt
            self.status.configure(text="已下发")
            notify(self, "success", msg)
            self.locator.logger.success("set_bucket_policy", self.bucket, msg)

        def on_err(msg):
            if not self._valid():
                return
            self.status.configure(text="下发失败")
            messagebox.showerror("下发失败", msg, parent=self)
            self.locator.logger.error("set_bucket_policy", self.bucket, msg)

        def work():
            return self.locator.s3_client.set_bucket_policy(self.bucket, json.loads(new_txt))

        run_async(self, work, on_ok, on_err, "下发桶策略")

    def _delete(self) -> None:
        if not messagebox.askyesno(
            "删除桶策略",
            f"确定删除桶 {self.bucket} 的访问策略?\n\n"
            f"删除后该桶将恢复为【私有】, 匿名访问全部失效。",
            parent=self,
        ):
            return
        def on_ok(msg):
            if not self._valid():
                return
            self._original = ""
            self.status.configure(text="已删除策略")
            notify(self, "success", msg)
            self.locator.logger.success("delete_bucket_policy", self.bucket, msg)

        def on_err(msg):
            if not self._valid():
                return
            messagebox.showerror("删除失败", msg, parent=self)

        def work():
            return self.locator.s3_client.delete_bucket_policy(self.bucket)

        run_async(self, work, on_ok, on_err, "删除桶策略")

    def _close(self) -> None:
        if self._current() and self._current() != self._original.strip():
            if not messagebox.askyesno(
                "放弃修改",
                "策略内容已被修改但没有下发, 确定放弃?",
                parent=self,
            ):
                return
        self._closed = True
        try:
            self.destroy()
        except tk.TclError:
            pass
