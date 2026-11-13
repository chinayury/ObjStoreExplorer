# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (C) 2026 智维ITMSKY
# SPDX-License-Identifier: AGPL-3.0-or-later
# 开发者：智维ITMSKY  |  官网：http://www.itmsky.com
# 许可证：GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

"""v0.1.0 冒烟测试

覆盖: 版本一致性 / 健康检查 / 登录与未登录拦截 / 安全响应头 /
静态资源 / OpenAPI / Fernet 加密往返。不依赖真实 MinIO 服务。
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_version_consistency():
    """版本号三个声明位置 + compose 镜像标签必须同号"""
    from objstoreexplorer import __version__ as pkg_version
    from objstoreexplorer.config.settings import APP_VERSION
    from objstoreexplorer.webapp import __version__ as web_version

    assert APP_VERSION == web_version == pkg_version
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert f"objstoreexplorer-web:v{APP_VERSION}" in compose


def test_health_endpoint(anon):
    from objstoreexplorer.config.settings import APP_VERSION
    from objstoreexplorer.webapp import __version__ as web_version

    resp = anon.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["status"] == "ok"
    assert body["version"] == web_version == APP_VERSION
    assert body["core_version"] == APP_VERSION


def test_security_headers(anon):
    resp = anon.get("/api/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "same-origin"
    assert "frame-ancestors 'none'" in resp.headers.get("Content-Security-Policy", "")


def test_root_redirects_to_login(anon):
    resp = anon.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_page_renders(anon):
    resp = anon.get("/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "login" in resp.text.lower()


def test_login_wrong_password_stays_anonymous(anon):
    resp = anon.post(
        "/login",
        data={"username": "admin", "password": "definitely-wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert anon.get("/", follow_redirects=False).status_code == 303


def test_admin_login_success(admin_client):
    resp = admin_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_api_requires_auth(anon):
    resp = anon.get("/api/admin/users")
    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False


def test_static_asset_served(anon):
    resp = anon.get("/static/css/app.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_openapi_version(anon):
    from objstoreexplorer.webapp import __version__ as web_version

    resp = anon.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["version"] == web_version


def test_encryptor_roundtrip(tmp_path):
    from objstoreexplorer.core.encryption import Encryptor

    enc = Encryptor(key_path=tmp_path / "test.key")
    ciphertext = enc.encrypt("minio-secret-key")
    assert ciphertext != "minio-secret-key"
    assert enc.decrypt(ciphertext) == "minio-secret-key"
