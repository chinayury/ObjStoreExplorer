# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""services/clipboard_service - 剪贴板服务

管理文件/文件夹的剪切/复制/粘贴操作。
只存储引用,实际移动在粘贴时执行。
"""
from __future__ import annotations
import os
from typing import List, Dict, Any, Tuple

from ..config.exceptions import ValidationError


class ClipboardItem:
    """剪贴板中的单个对象"""

    def __init__(self, bucket: str, key: str, name: str, is_dir: bool):
        self.bucket = bucket
        self.key = key
        self.name = name
        self.is_dir = is_dir


class ClipboardService:
    """剪贴板服务"""

    OP_NONE = "none"
    OP_CUT = "cut"
    OP_COPY = "copy"

    # 剪贴板容量上限: 超出的从**最早**开始丢弃, 防止无界增长
    MAX_ITEMS = 10000

    # 粘贴覆盖冲突的错误码 (UI 拿它弹二次确认)
    CONFLICT_CODE = "PasteConflict"

    def __init__(self, locator=None, on_change=None):
        # locator 可选 — 注入后 paste() 才能真正执行 copy/move
        # on_change 可选 — 剪贴板变化回调 (Web 版据此写库实现跨 worker 保持;
        #                   桌面版不传, 行为不变)
        self._locator = locator
        self._on_change = on_change
        self._items: List[ClipboardItem] = []
        self._operation: str = self.OP_NONE

    def _notify_change(self) -> None:
        """变化通知 (回调异常不外抛, 落库失败不能影响剪贴板操作本身)"""
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass

    @property
    def operation(self) -> str:
        return self._operation

    @property
    def is_empty(self) -> bool:
        return len(self._items) == 0

    @property
    def count(self) -> int:
        return len(self._items)

    def _set_items(self, items: List[Dict[str, Any]]) -> None:
        """转换并截断到 MAX_ITEMS (保留最新的 MAX_ITEMS 条)

        注意: 这里不触发 on_change —— cut/copy 的 operation 在其后才赋值,
        提前通知会把旧 operation 写进持久层 (本轮实测踩过: 复制落库成 none)。
        通知由 cut/copy/clear 在自身状态完整后触发。
        """
        converted = [self._to_clipboard_item(i) for i in items]
        if len(converted) > self.MAX_ITEMS:
            converted = converted[-self.MAX_ITEMS:]
        self._items = converted

    def hydrate(self, state) -> None:
        """从持久化数据恢复 (Web 版会话重建专用; 不触发 on_change 回调)

        state: {"op": "cut"/"copy"/"none", "items": [{bucket, key, name, is_dir}]}
        结构异常时静默放弃 (剪贴板本就是易失状态, 恢复失败无副作用)。
        """
        if not isinstance(state, dict):
            return
        op = state.get("op") or self.OP_NONE
        items = state.get("items")
        if not isinstance(items, list):
            return
        try:
            converted = [self._to_clipboard_item(i) for i in items]
        except Exception:
            return
        self._items = converted[-self.MAX_ITEMS:]
        self._operation = op if op in (self.OP_CUT, self.OP_COPY, self.OP_NONE) else self.OP_NONE

    def cut(self, items: List[Dict[str, Any]]) -> None:
        """剪切

        Args:
            items: [{bucket, key, name, is_dir}, ...]
        """
        self._set_items(items)
        self._operation = self.OP_CUT
        self._notify_change()

    def copy(self, items: List[Dict[str, Any]]) -> None:
        """复制"""
        self._set_items(items)
        self._operation = self.OP_COPY
        self._notify_change()

    def clear(self) -> None:
        self._items.clear()
        self._operation = self.OP_NONE
        self._notify_change()

    def get_items(self) -> List[ClipboardItem]:
        return list(self._items)

    def _target_keys(self, target_bucket: str, target_prefix: str) -> List[str]:
        """算出每个剪贴板条目粘贴后的目标 key"""
        prefix = target_prefix
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"
        targets: List[str] = []
        for item in self._items:
            base_name = os.path.basename(item.key.rstrip("/"))
            if item.is_dir and not base_name.endswith("/"):
                base_name = base_name + "/"
            targets.append(f"{prefix}{base_name}")
        return targets

    def find_conflicts(self, target_bucket: str, target_prefix: str) -> List[str]:
        """预检: 返回粘贴后会覆盖的既有对象 key 列表

        UI 应在真正粘贴前用它弹二次确认 (覆盖不可逆)。
        """
        if not self._items or self._locator is None:
            return []
        fm = self._locator.file_manager
        conflicts: List[str] = []
        for new_key in self._target_keys(target_bucket, target_prefix):
            try:
                if fm.exists(target_bucket, new_key):
                    conflicts.append(new_key)
            except Exception:  # noqa: BLE001 - 探测失败不当冲突, 交给 paste 处理
                continue
        return conflicts

    def paste(self, target_bucket: str, target_prefix: str) -> List[Dict[str, Any]]:
        """粘贴到目标位置 (真正执行 copy/move)

        目标已存在同名 key 时**不会静默覆盖**, 该条目返回
        success=False + conflict=True, 由 UI 弹确认后走 overwrite 流程。

        H-03: 文件夹条目 (is_dir=True) 旧实现和文件一样走单 key 的
        move_object/copy_object, 只操作 `/` 结尾的占位对象 —— 剪切一个
        "文件夹"过去, 里面的文件全都留在原地。现在按 is_dir 分流到
        rename_folder / copy_folder (整棵子树)。

        Args:
            target_bucket: 目标桶
            target_prefix: 目标路径 (应当以 '/' 结尾,可为空表示桶根)

        Returns:
            [{key, new_key, success, message, conflict}, ...]

        Raises:
            ValidationError: 未连接时粘贴
        """
        if not self._items:
            return []

        if self._locator is None:
            raise ValidationError("剪贴板服务未绑定 locator,无法执行粘贴", code="NoLocator")

        # 确保 target_prefix 以 / 结尾 (除空字符串)
        if target_prefix and not target_prefix.endswith("/"):
            target_prefix = target_prefix + "/"

        fm = self._locator.file_manager
        results: List[Dict[str, Any]] = []

        for item, new_key in zip(self._items, self._target_keys(target_bucket, target_prefix)):
            # 覆盖保护: 同名目标已存在就停下, 交给 UI 确认
            try:
                exists = fm.exists(target_bucket, new_key)
            except Exception:  # noqa: BLE001 - 探测失败不阻断粘贴
                exists = False
            if exists:
                results.append({
                    "key": item.key, "new_key": new_key,
                    "success": False, "conflict": True,
                    "message": f"目标已存在, 已跳过: {new_key} [{self.CONFLICT_CODE}]",
                })
                continue

            if item.is_dir:
                ok, msg = self._paste_folder(fm, item, target_bucket, new_key)
            elif self._operation == self.OP_CUT:
                if item.bucket == target_bucket:
                    ok, msg = fm.move_object(item.bucket, item.key, new_key)
                else:
                    ok, msg = fm.move_object_cross_bucket(
                        item.bucket, item.key, target_bucket, new_key,
                    )
            elif self._operation == self.OP_COPY:
                ok, msg = fm.copy_object(
                    item.bucket, item.key, target_bucket, new_key,
                )
            else:
                ok, msg = False, f"未知剪贴板操作: {self._operation}"

            results.append({
                "key": item.key, "new_key": new_key,
                "success": ok, "message": msg, "conflict": False,
            })

        # 剪切全部成功才清空; 有任一项失败就保留剪贴板, 让用户可以重试
        # (文件夹整棵搬迁中途失败时, 部分子树可能已到位, 更不能悄悄清掉)
        if self._operation == self.OP_CUT and results and all(
            r["success"] for r in results
        ):
            self.clear()
        return results

    def _paste_folder(self, fm, item: "ClipboardItem",
                      target_bucket: str, new_key: str) -> Tuple[bool, str]:
        """剪贴板里的文件夹条目: 整棵子树复制/移动"""
        if self._operation == self.OP_CUT:
            if item.bucket == target_bucket:
                return fm.rename_folder(item.bucket, item.key, new_key)
            # 跨桶搬文件夹: 先整棵复制, 成功后再递归删源
            ok, msg = fm.copy_folder(
                item.bucket, item.key, target_bucket, new_key)
            if not ok:
                return False, msg
            ok_d, msg_d = fm.delete_folder(item.bucket, item.key)
            if not ok_d:
                return False, (
                    f"已复制到 {target_bucket}/{new_key}, 但删除源文件夹失败: "
                    f"{msg_d}。请手动删除 {item.key}"
                )
            return True, msg
        if self._operation == self.OP_COPY:
            return fm.copy_folder(item.bucket, item.key, target_bucket, new_key)
        return False, f"未知剪贴板操作: {self._operation}"

    def _to_clipboard_item(self, item: Dict[str, Any]) -> ClipboardItem:
        """转换为 ClipboardItem"""
        return ClipboardItem(
            bucket=item.get("bucket", ""),
            key=item.get("key", "") or item.get("name", ""),
            name=item.get("name", ""),
            is_dir=item.get("is_dir", False),
        )

    def cleanup(self) -> None:
        self.clear()
