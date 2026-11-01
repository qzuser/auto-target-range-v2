"""控制台登录与统一安全边界。

从 `app.create_app` 里整段搬出来的第一刀：登录页 / 登录 / 登出，以及那条
所有请求都要过的安全中间件，属于同一个关注点（"谁能进来"），与路由分发
无关。搬出来之后 `create_app` 只管装配，这条边界的改动也不必再翻上千行。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from pydantic import BaseModel

from spiritscout.web import auth as web_auth

_STATIC_DIR = Path(__file__).parent.parent / "static"
_LOGIN = _STATIC_DIR / "login.html"

# 无管理员本机模式允许的 Host（DNS 重绑定防护）：正规本机访问只会用回环名
_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})

# 未登录也可访问：登录页、登录/登出接口、状态查询（客户端据此决定要不要登录）、
# 前端静态资源
_PUBLIC_PATHS = frozenset({
    "/login", "/api/auth/login", "/api/auth/logout", "/api/auth/status",
})


def _is_public_path(path: str) -> bool:
    return (path in _PUBLIC_PATHS or path == "/static"
            or path.startswith("/static/"))


class LoginPayload(BaseModel):
    """登录请求体。

    不在这里声明长度上限：Pydantic 的 422 会把原始输入回显给客户端，
    超长密码不该出现在响应里；长度在路由内手工校验。
    """

    username: str
    password: str


def _secure(response: Response) -> Response:
    """统一打上三个安全响应头（每个出口都要过，别漏）。"""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


def mount_auth(app: FastAPI, *, admin_store: web_auth.AdminStore,
               auth_enabled: bool, limiter: web_auth.LoginRateLimiter,
               loopback: bool) -> None:
    """挂登录相关路由与安全边界中间件。"""

    @app.middleware("http")
    async def console_security(request: Request, call_next):
        """统一的控制台安全边界。

        管理员登录启用后，浏览器走签名 Cookie，API 客户端仍可用 Basic；
        服务端永不下发 WWW-Authenticate，避免浏览器弹原生认证框。
        跨站写防护始终启用——恶意网页同样能向本机回环地址提交表单。
        """
        path = request.url.path
        # DNS 重绑定防护：无管理员的本机模式只接受回环 Host——恶意网页把
        # 自有域名解析到 127.0.0.1 后，Host 与 Origin 都是攻击者域名，
        # 下面的同源自洽检查分辨不出；远程访问应配置管理员凭据。
        if (loopback and not auth_enabled
                and (request.url.hostname or "").lower() not in _LOCAL_HOSTNAMES):
            return _secure(PlainTextResponse(
                "拒绝非同源主机访问（本机控制台仅响应回环地址）",
                status_code=403))
        username = ""
        if auth_enabled:
            username = admin_store.verify_session(
                request.cookies.get(web_auth.SESSION_COOKIE, "")) or ""
            if not username:
                supplied = web_auth.parse_basic_header(
                    request.headers.get("authorization", ""))
                if supplied and admin_store.verify(*supplied):
                    username = supplied[0]
            if not username and not _is_public_path(path):
                if path == "/api" or path.startswith("/api/"):
                    return _secure(JSONResponse(
                        {"detail": "需要管理员登录"}, status_code=401))
                return _secure(RedirectResponse("/login", status_code=302))
        request.state.authenticated = bool(username)
        request.state.username = username
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            fetch_site = request.headers.get("sec-fetch-site", "").lower()
            origin = request.headers.get("origin", "").rstrip("/")
            expected = str(request.base_url).rstrip("/")
            if fetch_site == "cross-site" or (origin and origin != expected):
                return _secure(PlainTextResponse(
                    "拒绝跨站写请求", status_code=403))
        return _secure(await call_next(request))

    @app.get("/api/auth/status")
    def auth_status(request: Request) -> dict[str, Any]:
        """控制台要不要登录——前端据此决定是否显示「未登录」提示，不用猜。"""
        return {"required": bool(auth_enabled),
                "authenticated": bool(getattr(request.state, "authenticated", False)),
                "username": str(getattr(request.state, "username", "") or "")}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Response:
        if not auth_enabled or request.state.authenticated:
            return RedirectResponse("/", status_code=302)
        return HTMLResponse(
            _LOGIN.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store"})

    @app.post("/api/auth/login")
    def login(payload: LoginPayload, request: Request) -> Response:
        if not auth_enabled:
            return JSONResponse({"detail": "未配置管理员凭据"},
                                status_code=400)
        client = request.client.host if request.client else "unknown"
        retry = limiter.retry_after(client)
        if retry is not None:
            return JSONResponse(
                {"detail": "登录尝试过于频繁，请稍后再试"},
                status_code=429, headers={"Retry-After": str(retry)})
        username = payload.username.strip()
        if (not username or len(username) > web_auth.MAX_USERNAME_LENGTH
                or len(payload.password) > web_auth.MAX_PASSWORD_LENGTH
                or not admin_store.verify(username, payload.password)):
            limiter.failure(client)
            return JSONResponse({"detail": "用户名或密码错误"},
                                status_code=401)
        limiter.reset(client)
        forwarded = request.headers.get("x-forwarded-proto", "")
        secure = (request.url.scheme == "https"
                  or forwarded.split(",")[0].strip().lower() == "https")
        response = JSONResponse({"ok": True, "username": username})
        response.set_cookie(
            web_auth.SESSION_COOKIE, admin_store.issue_session(username),
            max_age=web_auth.SESSION_TTL_SECONDS, httponly=True,
            samesite="lax", secure=secure, path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/logout", status_code=204)
    async def logout() -> Response:
        response = Response(status_code=204)
        response.delete_cookie(web_auth.SESSION_COOKIE, path="/")
        return response
