# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""pytest 全局夹具

关键点: OSE_DATA_DIR / WEB_ADMIN_PASSWORD 必须在导入 objstoreexplorer
之前设置 —— settings.py 在模块导入期就解析 APP_DIR, Web 用户库也会在
AppState 初始化时创建。conftest 在测试模块导入前执行, 因此在这里落环境变量。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Test-Admin-Pass-123!"

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="ose_pytest_data_"))
os.environ["OSE_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["WEB_ADMIN_PASSWORD"] = ADMIN_PASSWORD
os.environ.setdefault("TZ", "Asia/Shanghai")


@pytest.fixture(scope="session")
def data_dir():
    yield _TEST_DATA_DIR
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    """整个测试会话共用一个 TestClient (lifespan 只启动/停止一次)"""
    from fastapi.testclient import TestClient

    from objstoreexplorer.webapp.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def anon(client):
    """无登录态的客户端: 每个测试前后清 cookie"""
    client.cookies.clear()
    yield client
    client.cookies.clear()


@pytest.fixture()
def admin_client(client):
    """已用 admin 登录的客户端"""
    client.cookies.clear()
    resp = client.post(
        "/login",
        data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"admin 登录失败: {resp.status_code} {resp.text[:200]}"
    yield client
    client.cookies.clear()
