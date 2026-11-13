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
    """版本号唯一真源: 代码各处转发一致, compose 镜像标签不硬编码版本"""
    from objstoreexplorer import __version__ as pkg_version
    from objstoreexplorer.config.settings import APP_VERSION
    from objstoreexplorer.webapp import __version__ as web_version

    # 代码侧: 包级 / webapp 均为 settings.APP_VERSION 的转发
    assert APP_VERSION == web_version == pkg_version
    # compose 侧: 镜像标签参数化 (OSE_IMAGE_TAG 可覆盖), 不得再硬编码 vX.Y.Z
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "objstoreexplorer-web:${OSE_IMAGE_TAG:-latest}" in compose
    assert f"objstoreexplorer-web:v{APP_VERSION}" not in compose
    # webapp 包不得再回退为字面量声明 (防回归)
    web_init = (PROJECT_ROOT / "src" / "objstoreexplorer" / "webapp" / "__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{APP_VERSION}"' not in web_init


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


# ==================== 检查更新 (只查询, 不自更新) ====================


def test_update_checker_parse_version():
    from objstoreexplorer.utils.update_checker import parse_version

    assert parse_version("v0.2.1") == parse_version("0.2.1") == (0, 2, 1)
    assert parse_version("1.0.0") > parse_version("0.99.99")
    try:
        parse_version("not-a-version")
        raise AssertionError("非法版本号应当抛 ValueError")
    except ValueError:
        pass


def test_update_checker_offline_graceful(monkeypatch):
    """网络失败必须返回 ok=False 的统一结果, 不抛异常、不误报有更新"""
    import objstoreexplorer.utils.update_checker as uc

    def _boom(*args, **kwargs):
        raise TimeoutError("network unreachable")

    monkeypatch.setattr(uc.urllib.request, "urlopen", _boom)
    res = uc.check_update(current="0.1.0")
    assert res["ok"] is False
    assert res["update_available"] is False
    assert res["error"]
    assert res["current"] == "0.1.0"


def test_update_checker_found_newer(monkeypatch):
    """tag v9.9.9 且当前 0.1.0: 应判出 update_available 并带下载页"""
    import json as _json

    import objstoreexplorer.utils.update_checker as uc

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return _json.dumps(
                {"tag_name": "v9.9.9", "html_url": "https://example.test/rel"}
            ).encode("utf-8")

    monkeypatch.setattr(uc.urllib.request, "urlopen", lambda *a, **k: _Resp())
    res = uc.check_update(current="0.1.0")
    assert res["ok"] is True
    assert res["update_available"] is True
    assert res["latest"] == "9.9.9"
    assert res["release_url"] == "https://example.test/rel"


def test_update_check_endpoint(admin_client, monkeypatch):
    """登录后可调用; 未登录 (anon) 会被会话中间件拦截, 不测网络真调"""
    import objstoreexplorer.utils.update_checker as uc

    monkeypatch.setattr(
        uc, "check_update",
        lambda *a, **k: {"ok": True, "update_available": True,
                         "current": "0.1.0", "latest": "9.9.9",
                         "release_url": "https://example.test/rel",
                         "error": None})
    resp = admin_client.get("/api/update-check")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["update_available"] is True
    assert body["data"]["latest"] == "9.9.9"


def test_about_page_has_update_check(admin_client):
    """关于页渲染包含检查更新入口 (版本号由后端注入, 模板不硬编码)"""
    resp = admin_client.get("/about")
    assert resp.status_code == 200
    assert "btn-check-update" in resp.text
    assert "/api/update-check" in resp.text
