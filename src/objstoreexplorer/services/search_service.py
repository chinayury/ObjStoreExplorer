# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""services/search_service - 搜索服务

支持递归搜索、关键词过滤、结果高亮。

成本边界 (借鉴 brows3「深搜索三上限」, 按本栈架构折算):
    - 对象扫描上限 SEARCH_MAX_SCAN_OBJECTS = 50000:
      一次搜索最多物化 5 万个对象进内存 (minio-py 默认 1000/页,
      即内部 LIST 调用 ≤ 50 次);
    - 结果上限 SEARCH_MAX_RESULTS_CAP = 1000: 用户要 1 万条也只给 1000;
    - 截断如实回传: last_truncated / last_scan_limit 让 UI 明说
      「结果可能不完整」, 不假装列全了。

Unicode 归一化 (借鉴 flask-s3-viewer):
    关键词与对象名匹配前统一 NFC 归一化 —— macOS 上传的文件名是
    NFD, 浏览器 IME 输入是 NFC, 不归一化会出现「明明有却搜不到」。
"""
from __future__ import annotations
import unicodedata
from typing import List, Dict, Tuple, Any


# 一次搜索最多扫描的对象数 (硬上限): 百万对象的桶不能一次全量进内存
SEARCH_MAX_SCAN_OBJECTS = 50000
# 一次搜索最多返回的匹配数 (硬上限)
SEARCH_MAX_RESULTS_CAP = 1000


def _norm(s: str) -> str:
    """NFC 归一化 (大小写转换由调用方按需处理)"""
    try:
        return unicodedata.normalize("NFC", s or "")
    except Exception:  # noqa: BLE001 - 极端输入不阻断搜索
        return s or ""


class SearchService:
    """搜索服务"""

    def __init__(self, locator):
        self._locator = locator
        # 最近一次失败的描述 (返回值签名固定为 List, 错误原因放这里)
        self.last_error: str = ""
        # 最近一次搜索的列举是否被上限截断 (结果可能不完整)
        self.last_truncated: bool = False
        # 最近一次搜索实际生效的扫描上限 (UI 用于说明「已扫描前 N 个对象」)
        self.last_scan_limit: int = 0

    def search(
        self,
        bucket: str,
        keyword: str,
        prefix: str = "",
        case_sensitive: bool = False,
        max_results: int = 500,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """搜索对象

        Args:
            bucket: 桶名
            keyword: 关键词 (NFC 归一化后匹配)
            prefix: 搜索起始路径
            case_sensitive: 是否区分大小写
            max_results: 最大结果数 (内部封顶 SEARCH_MAX_RESULTS_CAP)

        Returns:
            (success, [{name, display_name, size, is_dir, matched}, ...])
            失败时第二项恒为 []; 失败原因见 self.last_error;
            截断状态见 self.last_truncated / self.last_scan_limit
        """
        self.last_error = ""
        self.last_truncated = False
        self.last_scan_limit = 0

        # ⚠ 要 strip: 搜索框里敲一串空格再回车, `if not keyword` 判不出来
        # (非空字符串), 于是继续往下走到 self._locator —— 而搜索可能是在
        # 还没连接时触发的, 直接 AttributeError。用户在界面上看到的是
        # "程序内部错误"弹窗, 而不是"关键词不能为空"。
        keyword = _norm((keyword or "").strip())
        if not keyword:
            self.last_error = "关键词不能为空"
            return False, []

        fm = self._locator.file_manager
        if fm is None:
            self.last_error = "文件管理器未初始化"
            return False, []

        # 结果数封顶: 用户要 1 万条也只给 SEARCH_MAX_RESULTS_CAP
        try:
            want = int(max_results or 0)
        except (TypeError, ValueError):
            want = 500
        want = max(1, min(want, SEARCH_MAX_RESULTS_CAP))

        # 扫描上限: 固定 SEARCH_MAX_SCAN_OBJECTS —— 既覆盖结果上限
        # (want ≤ 1000 << 50000, 不会「要 500 条却只扫 500 个对象」),
        # 又保证「搜索一个关键词」不会把百万对象的桶整个物化进内存。
        list_limit = SEARCH_MAX_SCAN_OBJECTS
        self.last_scan_limit = list_limit

        ok, objects = fm.list_objects(
            bucket, prefix=prefix, recursive=True, max_items=list_limit
        )
        if not ok:
            self.last_error = objects if isinstance(objects, str) else "列举对象失败"
            return False, []
        self.last_truncated = bool(fm.last_list_truncated())

        # 流式过滤 + 命中上限立刻中断:
        # 大桶不该全量过滤完再截断
        if case_sensitive:
            def hit(obj: Dict[str, Any]) -> bool:
                return keyword in _norm(obj.get("name", ""))
        else:
            kw = keyword.lower()

            def hit(obj: Dict[str, Any]) -> bool:
                return kw in _norm(obj.get("name", "")).lower()

        matches: List[Dict[str, Any]] = []
        for obj in objects:
            if hit(obj):
                obj["matched"] = True   # 前端用于高亮
                matches.append(obj)
                if len(matches) >= want:
                    break

        return True, matches

    def search_files(
        self,
        bucket: str,
        keyword: str,
        prefix: str = "",
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """仅搜索文件 (排除文件夹)"""
        ok, results = self.search(bucket, keyword, prefix)
        if not ok:
            return False, results
        return True, [r for r in results if not r.get("is_dir")]

    def cleanup(self) -> None:
        pass
