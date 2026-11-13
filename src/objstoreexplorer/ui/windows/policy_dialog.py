# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""策略管理对话框 - 创建/编辑 策略

minio-py 没有 update_policy, 改策略内容 = remove + add(同名)。
保留: 附加到此策略的所有用户, 自动重新附加。

修复: 同 create_user_dialog 一样, 改用顶层 grid 布局 (header / body / footer),
scrollable canvas 的 create_window 顺序修复 (先于 bind <Configure>)。
scrollable canvas 双 bind 模板 (经验证不够, 仍出现 width=0 问题)
"""
from __future__ import annotations
import json
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable, Dict

from ..widgets.scrollarea import bind_mousewheel
from ..styles import Brand, Neutral, Space, UIFont
from ..widgets.buttons import (
    create_primary_button, create_secondary_button
)
from ..widgets.notifications import notify
from ...utils.icon_manager import get_window_icon
from ...services.service_locator import ServiceLocator


# 策略模板 (从 admin_manager.POLICY_TEMPLATES 复用, 这里简化展示)
POLICY_TEMPLATES_SIMPLE = {
    "readonly": {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": ["arn:aws:s3:::BUCKET_NAME", "arn:aws:s3:::BUCKET_NAME/*"],
        }],
    },
    "readwrite": {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "s3:GetObject", "s3:PutObject",
                "s3:DeleteObject", "s3:ListBucket",
            ],
            "Resource": ["arn:aws:s3:::BUCKET_NAME", "arn:aws:s3:::BUCKET_NAME/*"],
        }],
    },
    "full": {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:*"],
            "Resource": ["arn:aws:s3:::BUCKET_NAME", "arn:aws:s3:::BUCKET_NAME/*"],
        }],
    },
    "readonly-all": {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": ["arn:aws:s3:::*"],
        }],
    },
    "readwrite-all": {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "s3:GetObject", "s3:PutObject",
                "s3:DeleteObject", "s3:ListBucket",
            ],
            "Resource": ["arn:aws:s3:::*"],
        }],
    },
}


class PolicyDialog:
    """创建或编辑策略 (mode='create' / 'edit')"""

    DEFAULT_SIZE = "820x720"   # 800x720 → 820x720 (适配 grid + scroll)
    MIN_SIZE = (700, 600)

    def __init__(
        self,
        parent: tk.Misc,
        locator: ServiceLocator,
        mode: str = "create",
        policy_name: str = "",
        policy_content: Optional[Dict] = None,
        on_success: Optional[Callable] = None,
    ):
        self.parent = parent
        self.locator = locator
        self.mode = mode
        self.policy_name = policy_name
        self.policy_content = policy_content or {}
        self._on_success = on_success

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("创建策略" if mode == "create" else f"编辑策略 - {policy_name}")
        self.dialog.geometry(self.DEFAULT_SIZE)
        self.dialog.minsize(*self.MIN_SIZE)
        self.dialog.resizable(True, True)
        self.dialog.transient(parent.winfo_toplevel() if isinstance(parent, tk.Widget) else parent)
        self.dialog.grab_set()

        # 顶层 3 行 grid
        # row 0: header (固定高)
        # row 1: body   (扩展, 滚动)
        # row 2: footer (固定高)
        self.dialog.columnconfigure(0, weight=1)
        # row 0: header (固定 64) / row 1: 发丝线 / row 2: body (扩)
        # row 3: 发丝线 / row 4: footer (固定)
        self.dialog.rowconfigure(0, minsize=64)   # header
        self.dialog.rowconfigure(1, minsize=1)    # 分隔线
        self.dialog.rowconfigure(2, weight=1)     # body (扩)
        self.dialog.rowconfigure(3, minsize=1)    # 分隔线
        self.dialog.rowconfigure(4, minsize=58)   # footer

        self._set_icon()
        self._create_header()
        self._create_body()
        self._create_footer()
        if mode == "edit":
            self._load_existing()

    def _set_icon(self) -> None:
        try:
            icon = get_window_icon()
            if icon:
                self.dialog.iconbitmap(icon)
        except Exception:
            pass

    def _create_header(self) -> None:
        from ...utils.icons import get as get_icon

        header = tk.Frame(self.dialog, bg=Neutral.BG_PANEL, height=64)
        header.grid(row=0, column=0, sticky="nsew")
        header.pack_propagate(False)

        chip = tk.Frame(header, bg=Brand.PRIMARY_50, width=36, height=36)
        chip.pack(side=tk.LEFT, padx=(Space.LG, Space.MD), pady=Space.MD)
        chip.pack_propagate(False)
        img = get_icon("shield-check", 24, tint=Brand.PRIMARY)
        if img is not None:
            lbl = tk.Label(chip, image=img, bg=Brand.PRIMARY_50)
            lbl.image = img
            lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        col = tk.Frame(header, bg=Neutral.BG_PANEL)
        col.pack(side=tk.LEFT, fill=tk.Y, pady=Space.MD)
        tk.Label(
            col, text="POLICY", font=UIFont.kicker(),
            bg=Neutral.BG_PANEL, fg=Brand.PRIMARY,
        ).pack(anchor=tk.W)
        tk.Label(
            col,
            text="创建策略" if self.mode == "create" else "编辑策略",
            font=UIFont.h2(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
        ).pack(anchor=tk.W)

        tk.Frame(self.dialog, bg=Neutral.BORDER, height=1).grid(row=1, column=0, sticky="ew")

    def _create_body(self) -> None:
        body_outer = tk.Frame(self.dialog, bg=Neutral.BG_PANEL)
        body_outer.grid(row=2, column=0, sticky="nsew")

        # 滚动 canvas
        canvas = tk.Canvas(body_outer, highlightthickness=0, bg=Neutral.BG_PANEL)
        vsb = ttk.Scrollbar(body_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        # 内部 frame
        self._scroll_frame = tk.Frame(canvas, bg=Neutral.BG_PANEL)

        # 关键修复: create_window 先于 bind <Configure> (bug)
        self._scroll_window_id = canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw",
        )
        self._scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._scroll_window_id, width=e.width),
        )
        # 改用控件级绑定。原来 Enter 时 bind_all / Leave 时 unbind_all,
        # 关闭弹窗时 <Leave> 不会触发, all 上会残留悬空 handler 引用已销毁的 canvas。
        bind_mousewheel(canvas, self._scroll_frame)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas = canvas

        content = self._scroll_frame

        # 策略名
        top = tk.Frame(content, bg=Neutral.BG_PANEL)
        top.pack(fill=tk.X, padx=20, pady=(16, 8))

        tk.Label(
            top, text="策略名:", font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W, width=10,
        ).pack(side=tk.LEFT)

        self.name_var = tk.StringVar(value=self.policy_name)
        self.name_entry = tk.Entry(
            top, textvariable=self.name_var, font=UIFont.body(),
            bg=Neutral.BG_APP, relief="solid", bd=1,
        )
        self.name_entry.pack(side=tk.LEFT, padx=(0, 12), fill=tk.X, expand=True)
        if self.mode == "edit":
            self.name_entry.config(state="readonly", bg=Neutral.BG_SUBTLE)

        # 模板选择 (仅 create 模式)
        if self.mode == "create":
            tk.Label(
                top, text="模板:", font=UIFont.body_sm(),
                bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2, anchor=tk.W,
            ).pack(side=tk.LEFT, padx=(8, 4))
            self.template_var = tk.StringVar(value="(自定义)")
            self.template_combo = ttk.Combobox(
                top, textvariable=self.template_var,
                state="readonly", width=18, font=UIFont.body_sm(),
                values=("(自定义)", "readonly", "readwrite", "full",
                        "readonly-all", "readwrite-all"),
            )
            self.template_combo.pack(side=tk.LEFT)
            self.template_combo.bind("<<ComboboxSelected>>", self._on_template_select)

        # 桶名提示 (用于模板替换 BUCKET_NAME 占位符)
        if self.mode == "create":
            bucket_frame = tk.Frame(content, bg=Neutral.BG_PANEL)
            bucket_frame.pack(fill=tk.X, padx=20, pady=(0, 4))
            tk.Label(
                bucket_frame, text="桶名 (替换 BUCKET_NAME):", font=UIFont.body_sm(),
                bg=Neutral.BG_PANEL, fg=Neutral.TEXT_2, anchor=tk.W,
            ).pack(side=tk.LEFT)
            self.bucket_var = tk.StringVar()
            self.bucket_combo = ttk.Combobox(
                bucket_frame, textvariable=self.bucket_var,
                font=UIFont.body_sm(),
            )
            self.bucket_combo.pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)
            self._load_buckets()
            self.bucket_var.trace_add("write", self._on_bucket_change)

        # JSON 编辑区
        tk.Label(
            content, text="策略内容 (JSON):", font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W,
        ).pack(anchor=tk.W, padx=20, pady=(12, 4))

        # ⚠ wrap=NONE 只有竖向滚动条: 长 ARN / 长 Resource 行看不到尾部,
        #   必须补横向滚动条 (xnscrollcommand)。
        text_outer = tk.Frame(content, bg=Neutral.BG_PANEL)
        text_outer.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 16))
        text_outer.rowconfigure(0, weight=1)
        text_outer.columnconfigure(0, weight=1)

        self.json_text = tk.Text(
            text_outer, wrap=tk.NONE, font=UIFont.mono(10),
            bg=Neutral.BG_APP, fg=Neutral.TEXT_1,
            relief="solid", bd=1, height=16,
        )
        self.json_text.grid(row=0, column=0, sticky="nsew")
        text_sb_y = ttk.Scrollbar(
            text_outer, orient=tk.VERTICAL, command=self.json_text.yview,
        )
        text_sb_y.grid(row=0, column=1, sticky="ns")
        text_sb_x = ttk.Scrollbar(
            text_outer, orient=tk.HORIZONTAL, command=self.json_text.xview,
        )
        text_sb_x.grid(row=1, column=0, sticky="ew")
        self.json_text.configure(
            yscrollcommand=text_sb_y.set, xscrollcommand=text_sb_x.set,
        )

    def _create_footer(self) -> None:
        tk.Frame(self.dialog, bg=Neutral.BORDER, height=1).grid(row=3, column=0, sticky="ew")
        footer = tk.Frame(self.dialog, bg=Neutral.BG_SUBTLE)
        footer.grid(row=4, column=0, sticky="nsew")
        footer.pack_propagate(False)
        btn_frame = tk.Frame(footer, bg=Neutral.BG_SUBTLE)
        btn_frame.pack(padx=Space.LG, pady=Space.MD, side=tk.RIGHT)
        create_secondary_button(
            btn_frame, "取消", self.dialog.destroy, width=10,
        ).pack(side=tk.LEFT, padx=4)
        if self.mode == "create":
            create_primary_button(
                btn_frame, "创建", self._on_create, width=10,
            ).pack(side=tk.LEFT, padx=4)
        else:
            create_primary_button(
                btn_frame, "保存", self._on_save, width=10,
            ).pack(side=tk.LEFT, padx=4)

    def _load_buckets(self) -> None:
        try:
            ok, buckets = self.locator.bucket_manager.list_buckets()
            if ok:
                self.bucket_combo["values"] = buckets
        except Exception:
            pass

    def _on_bucket_change(self, *args) -> None:
        """桶名变更时, 替换 JSON 中的 BUCKET_NAME 占位符"""
        bucket = self.bucket_var.get().strip()
        if not bucket:
            return
        # 只在未手动编辑时替换 (避免覆盖用户编辑)
        content = self.json_text.get("1.0", tk.END)
        if "BUCKET_NAME" in content:
            new_content = content.replace("BUCKET_NAME", bucket)
            self.json_text.delete("1.0", tk.END)
            self.json_text.insert("1.0", new_content)

    def _on_template_select(self, event) -> None:
        """应用模板时, 填充 JSON 并设置桶名"""
        sel = self.template_var.get()
        if sel == "(自定义)":
            return
        template = POLICY_TEMPLATES_SIMPLE.get(sel)
        if not template:
            return
        # 应用模板前, 替换 BUCKET_NAME 为当前桶名
        bucket = self.bucket_var.get().strip() or "BUCKET_NAME"
        # 深拷贝模板
        import copy
        content = copy.deepcopy(template)
        # 替换资源 ARN 中的 BUCKET_NAME
        for stmt in content.get("Statement", []):
            for i, res in enumerate(stmt.get("Resource", [])):
                stmt["Resource"][i] = res.replace("BUCKET_NAME", bucket)
        # 写入 JSON 编辑区
        text = json.dumps(content, indent=2, ensure_ascii=False)
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert("1.0", text)

    def _load_existing(self) -> None:
        """编辑模式: 加载现有策略内容"""
        ok, data = self.locator.admin_manager.get_policy(self.policy_name)
        if ok and isinstance(data, dict):
            text = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            text = f"# 无法加载策略 {self.policy_name} 详情\n# {data}"
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert("1.0", text)

    def _validate(self) -> tuple[bool, str, Optional[Dict]]:
        """校验: 返回 (ok, error_msg, parsed_dict)"""
        name = self.name_var.get().strip()
        if not name:
            return False, "策略名不能为空", None
        if not name.replace("-", "").replace("_", "").isalnum():
            return False, "策略名只能包含字母数字、- 和 _", None
        if len(name) > 64:
            return False, "策略名不能超过 64 字符", None
        text = self.json_text.get("1.0", tk.END).strip()
        if not text:
            return False, "策略内容不能为空", None
        try:
            content = json.loads(text)
        except json.JSONDecodeError as e:
            return False, f"JSON 格式错误: {e}", None
        if not isinstance(content, dict):
            return False, "策略内容必须是 JSON 对象", None
        if "Version" not in content or "Statement" not in content:
            return False, "策略必须包含 Version 和 Statement 字段", None
        return True, "", content

    def _on_create(self) -> None:
        ok, err, content = self._validate()
        if not ok:
            messagebox.showerror("参数错误", err, parent=self.dialog)
            return
        name = self.name_var.get().strip()
        try:
            ok, msg = self.locator.admin_manager.create_policy(name, content)
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self.dialog)
            return
        if ok:
            self.locator.logger.success("create_policy", name, msg)
            notify(self.dialog, "success", f"策略 {name} 创建成功")
            if self._on_success:
                self._on_success()
            self.dialog.destroy()
        else:
            messagebox.showerror("失败", msg, parent=self.dialog)
            self.locator.logger.error("create_policy", name, msg)

    def _on_save(self) -> None:
        ok, err, content = self._validate()
        if not ok:
            messagebox.showerror("参数错误", err, parent=self.dialog)
            return
        if not messagebox.askyesno(
            "确认保存",
            f"确定要保存策略 {self.policy_name} 的修改吗?\n\n"
            f"(会删除旧策略并重新创建, 附加到此策略的用户会自动重新附加)",
            parent=self.dialog,
        ):
            return
        try:
            ok, msg = self.locator.admin_manager.update_policy_content(
                self.policy_name, content,
            )
        except Exception as e:
            messagebox.showerror("失败", str(e), parent=self.dialog)
            return
        if ok:
            self.locator.logger.success("update_policy", self.policy_name, msg)
            notify(self.dialog, "success", msg)
            if self._on_success:
                self._on_success()
            self.dialog.destroy()
        else:
            messagebox.showerror("失败", msg, parent=self.dialog)
            self.locator.logger.error("update_policy", self.policy_name, msg)
