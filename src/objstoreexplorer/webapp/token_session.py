# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""无状态签名会话令牌 (HMAC-SHA256, 纯标准库)

v0.1.0 第二轮迭代 (会话外置化): 取代 starlette SessionMiddleware。

为什么自实现而不是继续用 SessionMiddleware:
    - SessionMiddleware 底层 itsdangerous 默认 HMAC-SHA1 摘要, 且不暴露
      算法选择; 本模块显式使用 HMAC-SHA256 (stdlib hmac + hashlib)。
    - 令牌格式自控: header 段不可省略的显式 exp 过期时间 + 常数时间签名
      比较 (hmac.compare_digest), 校验失败一律视为未登录 (fail closed)。
    - 零新依赖: requirements-web.txt 保持不变 (itsdangerous 仍是声明依赖,
      只是本路径不再使用)。

令牌格式 (两段, base64url 去填充):
    body = base64url(json({"uid","sid","iat","exp"}))
    sig  = base64url(hmac_sha256(secret, body))
    token = body + "." + sig

安全要点:
    - 签名常数时间比较, 防时序侧信道 (竞品 Mikochi 用明文 == 是反面教材);
    - exp 过期由令牌自身携带, 多 worker 无需共享任何内存态;
    - cookie 属性: HttpOnly (JS 不可读) + SameSite=Lax + 可选 Secure;
    - 令牌只携带 uid/sid 引用, 绝不含 AK/SK (连接凭证落 SQLite 加密存储);
    - 服务端吊销由 web_sessions 表负责 (webapp/persist.py), 令牌本身吊销
      不了 —— 依赖注入层每请求校验会话行, 行被吊销/删除即失效。

兼容性: 旧 SessionMiddleware 签发的 itsdangerous cookie 无法通过本校验,
升级后所有用户需重新登录一次 (一次性代价)。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

# ==================== 编解码工具 ====================


def _b64encode(data: bytes) -> str:
    """base64url 编码 (去填充, cookie 安全字符集)"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    """base64url 解码 (补齐填充); 非法输入抛 binascii.Error 由调用方兜住"""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


# ==================== 令牌签发与校验 ====================


def sign_session_token(payload: Dict[str, Any], secret: str) -> str:
    """用 HMAC-SHA256 签发会话令牌

    payload 至少含 uid/sid; iat/exp 由调用方 (或本函数) 填充。
    """
    body = _b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return body + "." + _b64encode(sig)


def verify_session_token(token: str, secret: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """校验令牌: 合法返回 payload dict; 任何一步失败返回 None (不抛异常)

    校验顺序:
        1. 结构: 必须恰好两段 (body.sig), base64url 字符集内不含 '.', 天然防拆分歧义;
        2. 签名: hmac.compare_digest 常数时间比较;
        3. 载荷: 必须是 JSON object 且带数值型 exp;
        4. 过期: exp 已过 -> None (与"签名错误"同返回值, 不向客户端泄露区别)。
    """
    if not token or not secret:
        return None
    if token.count(".") != 1:
        return None
    body, sig_text = token.split(".", 1)
    try:
        got_sig = _b64decode(sig_text)
    except Exception:  # binascii.Error 等解码失败
        return None
    expected_sig = hmac.new(
        secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected_sig, got_sig):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or (now if now is not None else time.time()) >= exp:
        return None
    return payload


# ==================== 会话字典 (脏标记) ====================


class SessionDict(dict):
    """request.session 用的 dict: 记录"被修改过", 响应阶段据此重签/清除 cookie

    与 starlette SessionMiddleware 行为对齐: 只有被改动的会话才重发 cookie;
    clear() 之后 (登出) 发删除型 Set-Cookie。
    """

    def __init__(self, initial: Optional[dict] = None):
        super().__init__(initial or {})
        self.dirty = False

    def __setitem__(self, key, value) -> None:
        self.dirty = True
        super().__setitem__(key, value)

    def __delitem__(self, key) -> None:
        self.dirty = True
        super().__delitem__(key)

    def pop(self, key, *args):
        self.dirty = True
        return super().pop(key, *args)

    def clear(self) -> None:
        self.dirty = True
        super().clear()

    def update(self, *args, **kwargs) -> None:  # type: ignore[override]
        self.dirty = True
        super().update(*args, **kwargs)

    def setdefault(self, key, default=None):
        if key not in self:
            self.dirty = True
        return super().setdefault(key, default)


# ==================== ASGI 中间件 ====================


class TokenSessionMiddleware:
    """签名 cookie 会话中间件 (纯 ASGI, 兼容 Starlette middleware 栈)

    请求: 从 Cookie 解出令牌并验签 -> scope["session"] = SessionDict(载荷)。
    响应: 会话被修改过 -> 重签令牌 (exp 顺延 max_age) 写 Set-Cookie;
          会话被清空过 -> 发 Max-Age=0 删除型 Set-Cookie。
    """

    def __init__(
        self,
        app,
        secret_key: str,
        cookie_name: str = "ose_web_session",
        max_age: int = 7 * 24 * 3600,
        same_site: str = "lax",
        https_only: bool = False,
        path: str = "/",
    ):
        self.app = app
        self.secret_key = secret_key
        self.cookie_name = cookie_name
        self.max_age = max_age
        self.same_site = same_site
        self.https_only = https_only
        self.path = path

    # ---- cookie 解析 ----

    @staticmethod
    def _extract_cookie(headers, name: str) -> str:
        """从请求头取指定 cookie 值 (多个同名取第一个; 值内不含分号)"""
        raw = headers.get("cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v.strip()
        return ""

    def _build_set_cookie(self, token: str, delete: bool = False) -> str:
        parts = [f"{self.cookie_name}={token}"]
        parts.append(f"Path={self.path}")
        parts.append(f"Max-Age={0 if delete else self.max_age}")
        parts.append("HttpOnly")
        parts.append(f"SameSite={self.same_site}")
        if self.https_only:
            parts.append("Secure")
        return "; ".join(parts)

    # ---- ASGI 入口 ----

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import Headers

        headers = Headers(scope=scope)
        token = self._extract_cookie(headers, self.cookie_name)
        payload = verify_session_token(token, self.secret_key)
        session = SessionDict(payload)
        scope["session"] = session

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                if session.dirty:
                    from starlette.datastructures import MutableHeaders

                    resp_headers = MutableHeaders(scope=message)
                    if session:
                        now = int(time.time())
                        new_token = sign_session_token(
                            {**session, "iat": now, "exp": now + self.max_age},
                            self.secret_key,
                        )
                        resp_headers.append(
                            "set-cookie", self._build_set_cookie(new_token)
                        )
                    else:
                        # 登出: 会话被 clear -> 删除浏览器 cookie
                        resp_headers.append(
                            "set-cookie", self._build_set_cookie("", delete=True)
                        )
            await send(message)

        await self.app(scope, receive, send_wrapper)
