# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""生命周期规则配置页面 — 桶级过期策略 (「暮橙 Emberline」)"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox

from ..pages.base_page import BasePage
from ..styles import Brand, Neutral, Space, UIFont
from ..widgets.page_header import PageHeader
from ..widgets.card import Card
from ..widgets.buttons import (
    create_primary_button, create_secondary_button, create_danger_ghost_button,
)
from ..widgets.notifications import notify


class LifecyclePage(BasePage):
    """桶生命周期配置页面"""

    def _build_ui(self) -> None:
        header = PageHeader(
            self.frame,
            kicker="Lifecycle",
            title="生命周期规则",
            subtitle="按前缀设置对象自动过期天数，MinIO 后台扫描器会定期清理到期对象以回收空间；规则即时生效。",
            icon="timer",
        )
        header.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(Space.HERO_PAD_Y, Space.LG))
        create_secondary_button(
            header.actions, "重新加载", self.refresh, icon="refresh-cw",
        ).pack(side=tk.LEFT)

        # ---------- 卡 1: 查看现有规则 ----------
        view_card = Card(self.frame, title="已生效规则", icon="list")
        view_card.pack(fill=tk.BOTH, expand=True,
                       padx=Space.HERO_PAD_X, pady=(0, Space.MD))

        inner = view_card.body

        self._label(inner, "存储桶").grid(
            row=0, column=0, sticky=tk.W, padx=(0, Space.MD), pady=(0, Space.SM))
        self.bucket_var = tk.StringVar()
        self.bucket_combo = ttk.Combobox(
            inner, textvariable=self.bucket_var,
            state="readonly", font=UIFont.body(), width=36,
        )
        self.bucket_combo.grid(row=0, column=1, sticky=tk.EW, pady=(0, Space.SM))
        self.bucket_combo.bind("<<ComboboxSelected>>", self._on_bucket_select)

        rules_frame = tk.Frame(
            inner, bg=Neutral.BG_SUBTLE,
            highlightbackground=Neutral.BORDER,
            highlightthickness=1,
        )
        rules_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW,
                         pady=(Space.SM, 0))
        rules_frame.rowconfigure(0, weight=1)
        rules_frame.columnconfigure(0, weight=1)
        self.rules_text = tk.Text(
            rules_frame, font=UIFont.mono(10), height=7,
            bg=Neutral.BG_SUBTLE, fg=Neutral.TEXT_1,
            relief="flat", wrap=tk.NONE, state="disabled",
            highlightthickness=0, padx=Space.MD, pady=Space.SM,
        )
        # ⚠ wrap=NONE 必配双向滚动条, 否则长前缀行看不到尾部
        self.rules_text.grid(row=0, column=0, sticky="nsew")
        rules_sb_y = ttk.Scrollbar(
            rules_frame, orient=tk.VERTICAL, command=self.rules_text.yview,
        )
        rules_sb_y.grid(row=0, column=1, sticky="ns")
        rules_sb_x = ttk.Scrollbar(
            rules_frame, orient=tk.HORIZONTAL, command=self.rules_text.xview,
        )
        rules_sb_x.grid(row=1, column=0, sticky="ew")
        self.rules_text.configure(
            yscrollcommand=rules_sb_y.set, xscrollcommand=rules_sb_x.set,
        )

        inner.columnconfigure(1, weight=1)

        # ---------- 卡 2: 下发单条规则 ----------
        self._build_apply_card()

    def _build_apply_card(self) -> None:
        card = Card(self.frame, title="下发单条规则", icon="calendar")
        card.pack(fill=tk.X, padx=Space.HERO_PAD_X, pady=(0, Space.HERO_PAD_Y))

        inner = card.body
        form = tk.Frame(inner, bg=Neutral.BG_PANEL)
        form.pack(fill=tk.X)

        self._label(form, "规则 ID").grid(
            row=0, column=0, sticky=tk.W, padx=(0, Space.MD), pady=Space.XS)
        self.rule_id_var = tk.StringVar(value="expire-30d")
        tk.Entry(
            form, textvariable=self.rule_id_var, font=UIFont.mono(10),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, relief="flat", bd=0,
            highlightbackground=Neutral.BORDER_HI, highlightthickness=1,
        ).grid(row=0, column=1, sticky=tk.EW, padx=(0, Space.MD), pady=Space.XS, ipady=5)

        self._label(form, "过期天数").grid(
            row=1, column=0, sticky=tk.W, padx=(0, Space.MD), pady=Space.XS)
        self.days_var = tk.StringVar(value="30")
        tk.Entry(
            form, textvariable=self.days_var, font=UIFont.body(), width=10,
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, relief="flat", bd=0,
            highlightbackground=Neutral.BORDER_HI, highlightthickness=1,
        ).grid(row=1, column=1, sticky=tk.W, pady=Space.XS, ipady=5)

        self.enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            inner, text="启用此规则", variable=self.enabled_var,
            font=UIFont.body(), bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1,
            activebackground=Neutral.BG_PANEL, activeforeground=Brand.PRIMARY_800,
            highlightthickness=0, bd=0,
        ).pack(anchor=tk.W, pady=(Space.SM, 0))

        tk.Label(
            inner,
            text="MinIO 每个桶仅支持一条生命周期配置，应用新规则会覆盖原有配置。",
            font=UIFont.caption(), bg=Neutral.BG_PANEL,
            fg=Neutral.TEXT_3, wraplength=620, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(Space.XS, 0))

        btn = tk.Frame(inner, bg=Neutral.BG_PANEL)
        btn.pack(anchor=tk.W, pady=(Space.MD, 0))
        create_primary_button(
            btn, "应用规则", self._on_apply, icon="check",
        ).pack(side=tk.LEFT, padx=(0, Space.SM))
        create_danger_ghost_button(
            btn, "清除所有规则", self._on_delete, icon="trash-2",
        ).pack(side=tk.LEFT)

        form.columnconfigure(1, weight=1)

    @staticmethod
    def _label(parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(
            parent, text=text, font=UIFont.body(),
            bg=Neutral.BG_PANEL, fg=Neutral.TEXT_1, anchor=tk.W,
        )

    # ==================== 数据 ====================

    def refresh(self) -> None:
        if self.frame is None:
            return
        self._load_buckets()

    def _load_buckets(self) -> None:
        try:
            ok, buckets = self.locator.bucket_manager.list_buckets()
            if ok and buckets:
                self.bucket_combo["values"] = buckets
                if not self.bucket_var.get():
                    self.bucket_var.set(buckets[0])
            else:
                self._set_rules("(未连接或没有可访问的存储桶)")
                return
        except Exception:
            self._set_rules("(未连接或没有可访问的存储桶)")
            return
        # ⚠ 无条件刷新当前选中桶: 旧版只在 bucket_var 为空时才调
        #   _on_bucket_select, 于是点「重新加载」时已选桶的状态纹丝不动
        #   (用户改完配置回来刷新, 看到的还是旧值 → 以为没生效)。
        self._on_bucket_select(None)

    def _set_rules(self, text: str) -> None:
        self.rules_text.configure(state="normal")
        self.rules_text.delete("1.0", tk.END)
        self.rules_text.insert("1.0", text)
        self.rules_text.configure(state="disabled")

    def _on_bucket_select(self, event) -> None:
        bucket = self.bucket_var.get()
        if not bucket:
            self._set_rules("(选择桶后查看)")
            return
        # try/except: get_bucket_lifecycle 跨 minio-py 版本可能抛
        # AttributeError / 各种 S3Error, 没有兜底时整个刷新直接中断
        try:
            ok, lc = self.locator.s3_client.get_bucket_lifecycle(bucket)
        except Exception as e:
            self._set_rules(f"获取失败: {e}")
            return
        if not ok:
            self._set_rules(f"获取失败: {lc}")
            return
        rules = getattr(lc, "rules", None) or [] if lc is not None else []
        if not rules:
            self._set_rules("(该桶未配置生命周期规则)")
            return
        lines = []
        for r in rules:
            exp = getattr(r, "expiration", None)
            days = getattr(exp, "days", None) if exp else None
            # ⚠ 旧版 `r.rule_filter` 是属性访问: 某些 minio-py 版本把字段叫
            #    `filter`, 没有 rule_filter → AttributeError 打断整个列表渲染。
            prefix = self._rule_prefix(r)
            lines.append(
                f"ID         {getattr(r, 'rule_id', '?')}\n"
                f"状态       {getattr(r, 'status', '?')}\n"
                f"前缀       {prefix or '(整桶)'}\n"
                f"过期天数   {days if days is not None else '-'}\n"
            )
        self._set_rules("\n".join(lines))

    @staticmethod
    def _rule_prefix(r) -> str:
        """跨 minio-py 版本安全地取规则前缀 (rule_filter / filter)"""
        flt = getattr(r, "rule_filter", None)
        if flt is None:
            flt = getattr(r, "filter", None)
        if flt is None:
            return ""
        return getattr(flt, "prefix", "") or ""

    # ==================== 操作 ====================

    def _on_apply(self) -> None:
        bucket = self.bucket_var.get()
        if not bucket:
            messagebox.showwarning("提示", "请先选择桶", parent=self.frame)
            return
        try:
            days = int(self.days_var.get())
            if days <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "过期天数必须是正整数", parent=self.frame)
            return

        rule_id = self.rule_id_var.get().strip() or "default-rule"
        config = {
            "Rules": [{
                "ID": rule_id,
                "Status": "Enabled" if self.enabled_var.get() else "Disabled",
                "Expiration": {"Days": days},
            }]
        }

        # ⚠ MinIO 每桶只存一份生命周期配置, set_bucket_lifecycle 是**整体覆盖**。
        #   旧版点"应用规则"直接下发, 桶里原有的规则被无声抹掉; 而同一页的
        #   "清除所有规则"却有确认框 —— 逻辑不一致, 用户以为只是加一条。
        existing = self._existing_rules(bucket)
        if existing:
            if not messagebox.askyesno(
                "确认覆盖",
                f"桶「{bucket}」已存在 {len(existing)} 条生命周期规则。\n\n"
                f"MinIO 每个桶只支持一份生命周期配置, 下发新配置会"
                f"**整体覆盖**下面这些规则:\n\n"
                + "\n".join(f"  • {r}" for r in existing[:8])
                + ("\n  …" if len(existing) > 8 else "")
                + f"\n\n新配置 (将替换上面全部):\n"
                f"  • ID: {rule_id}\n"
                f"  • 状态: {'启用' if self.enabled_var.get() else '禁用'}\n"
                f"  • 过期天数: {days}\n\n确定继续吗?",
                parent=self.frame,
            ):
                return

        ok, msg = self.locator.s3_client.set_bucket_lifecycle(bucket, config)
        if ok:
            notify(self.frame, "success", f"生命周期规则已设置: {msg}")
            self.locator.logger.success("set_lifecycle", bucket, f"规则 {rule_id} {days}天")
            self._on_bucket_select(None)
        else:
            messagebox.showerror("失败", msg, parent=self.frame)
            self.locator.logger.error("set_lifecycle", bucket, msg)

    def _existing_rules(self, bucket: str) -> list:
        """读回当前桶已有的规则摘要 (供覆盖确认展示新旧对比)"""
        try:
            ok, lc = self.locator.s3_client.get_bucket_lifecycle(bucket)
        except Exception:
            return []
        if not ok or lc is None:
            return []
        out = []
        for r in (getattr(lc, "rules", None) or []):
            exp = getattr(r, "expiration", None)
            d = getattr(exp, "days", None) if exp else None
            prefix = self._rule_prefix(r)
            out.append(
                f"{getattr(r, 'rule_id', '?')} "
                f"(状态 {getattr(r, 'status', '?')}, "
                f"前缀 {prefix or '整桶'}, 过期 {d if d is not None else '-'})"
            )
        return out

    def _on_delete(self) -> None:
        bucket = self.bucket_var.get()
        if not bucket:
            return
        if not messagebox.askyesno("确认", f"确定要清除桶 {bucket} 的所有生命周期规则吗?", parent=self.frame):
            return
        ok, msg = self.locator.s3_client.delete_bucket_lifecycle(bucket)
        if ok:
            notify(self.frame, "success", msg)
            self.locator.logger.success("delete_lifecycle", bucket, msg)
            self._on_bucket_select(None)
        else:
            messagebox.showerror("失败", msg, parent=self.frame)
            self.locator.logger.error("delete_lifecycle", bucket, msg)
