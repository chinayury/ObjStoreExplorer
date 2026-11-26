# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""全局配置 - 常量、路径、版本

集中管理所有路径、尺寸、阈值等常量,避免散落在各处的 magic number。
"""
import os
import sys
from pathlib import Path

# ==================== 应用元信息 ====================

APP_NAME = "ObjStoreExplorer"
APP_VERSION = "0.6.2"
# 窗口标题 — 故意不带版本号,版本号从关于页查
APP_DISPLAY_NAME = f"{APP_NAME} - MinIO/S3 管理工具"

# ==================== 路径配置 ====================

def _get_executable_dir() -> Path:
    """程序所在目录

    - 开发模式 (`python -m objstoreexplorer`): 返回项目根 (含 pyproject.toml 的目录)
    - PyInstaller 打包后: 返回 .exe 所在目录
    """
    if getattr(sys, "frozen", False):
        # 打包后 sys.executable 指向 .exe 自身
        return Path(sys.executable).parent.resolve()
    # 开发模式: 本文件是 <项目根>/src/objstoreexplorer/config/settings.py。
    # 向上回溯到含 pyproject.toml 的项目根 —— 直接用 parent.parent 会把 data/
    # 建进包目录 (src/objstoreexplorer/data), 污染源码树且不可预期。
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    # 兜底: src/<pkg>/config -> 项目根 (向上 4 级)
    return here.parents[3]


def _get_app_dir() -> Path:
    """获取应用数据目录

    一切数据放在程序所在目录的 `data/` 子目录下, 方便备份和迁移,
    不污染源码目录, 也不依赖系统约定 (Windows %APPDATA% / macOS / Linux XDG)。

    环境变量 `OSE_DATA_DIR` 可覆盖 (多实例 / 测试 / 便携模式),
    未设置时行为与历史版本完全一致。
    """
    env_dir = os.environ.get("OSE_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir).resolve()
    return _get_executable_dir() / "data"


APP_DIR = _get_app_dir()
DB_DIR = APP_DIR / "db"
CACHE_DIR = APP_DIR / "cache"
LOG_DIR = APP_DIR / "logs"
TEMP_DIR = APP_DIR / "temp"

DB_FILE_NAME = "config.db"
KEY_FILE_NAME = "explorer.key"
LOG_FILE_NAME = "app.log"


def ensure_dirs() -> None:
    """创建运行期目录 (第一次运行时)

    ⚠ 这里原本是模块级的 `for _dir in (...): _dir.mkdir(...)`, 也就是
    **只要有人 import 任何一个引用 settings 的模块, 就会产生文件系统副作用**
    (core/encryption.py 导入链就会触发)。后果是:
      - 程序装到 `C:\\Program Files\\` 这类只读位置时, import 期就抛
        PermissionError —— 早于任何 try/except, 用户看到的是双击无反应;
      - 测试脚本只想读个配置项也会顺手在源码目录里建出 data/;
      - 循环变量 `_dir` 泄漏成模块属性。

    改为显式函数, 由 main.py 启动流程调用一次; 调用方仍需自己处理
    "目录不可写"的情况 (main 已有 try/except 兜底并弹窗)。
    """
    for d in (APP_DIR, DB_DIR, CACHE_DIR, LOG_DIR, TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)

# ==================== 业务阈值 ====================

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB 单文件上传限制
MAX_LIST_ITEMS = 1000  # 单次列表最大显示数量
DEFAULT_CACHE_SIZE_MB = 100  # 缓存最大 100MB
DEFAULT_CACHE_EXPIRE_HOURS = 24  # 缓存过期时间 24h

# ==================== UI 尺寸 ====================

# 视觉重构: 侧栏分组 + Hero 页眉 + 4 张统计卡 + 5 列表格,
# 1200x750 装不下 (侧栏 220 + Hero 左右内边距 60 + 卡片栅格 + 表格列宽),
# 会导致内容横向溢出、侧栏被裁。放宽默认/最小尺寸。
WINDOW_DEFAULT_SIZE = "1440x900"
WINDOW_MIN_SIZE = (1100, 700)
SIDEBAR_WIDTH = 236
STATUS_BAR_HEIGHT = 26
DIALOG_DEFAULT_SIZE = (500, 400)

# ==================== 线程/进度 ====================

PROGRESS_POLL_INTERVAL = 100  # 进度刷新间隔 ms
THREAD_POOL_WORKERS = 4  # 后台线程池大小

# ==================== 第三方库版本 ====================

MINIO_V2_MIN_VERSION = "7.1.0"  # minio-py 7.1+ 才有稳定 admin API

# ==================== 反馈系统 ====================
# 接入 MultiFeedbackSystem (多租户反馈中转服务)
# 配置详情见 config/feedback.yaml, 接入手册 docs/08-集成手册/MultiFeedbackSystem-接入手册-v.html

FEEDBACK_CONFIG_FILE = "feedback.yaml"
FEEDBACK_OFFLINE_DIR_NAME = "feedback_bundles"  # 离线反馈包保存目录 (在 APP_DIR/data/ 下)
FEEDBACK_MAX_IMAGES = 9                          # 接入手册上限
FEEDBACK_MAX_IMAGE_BYTES = 5 * 1024 * 1024       # 5MB, 接入手册上限
FEEDBACK_TIMEOUT_SECONDS = 10                    # HTTP 请求超时
FEEDBACK_BUNDLE_MAX_BYTES = 50 * 1024 * 1024     # 50MB, 接入手册上限 (离线包)
