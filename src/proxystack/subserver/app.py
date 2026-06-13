"""订阅 HTTP 服务。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from typing import Callable
from typing import Optional
from urllib.parse import quote
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse

from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import SubscriptionIndex
from proxystack.generator.sub import SubscriptionTemplateError
from proxystack.generator.sub import render_clash_subscription
from proxystack.generator.sub import render_premium_clash_subscription
from proxystack.generator.sub import render_surge_subscription
from proxystack.subserver.config import ManagedConfig
from proxystack.subserver.state import SubscriptionState
from proxystack.subserver.watcher import InputWatcher


def create_app(
    state: SubscriptionState,
    watcher: InputWatcher | None = None,
    templates_dir: Path | None = None,
    data_dir: Path | None = None,
    managed_config: ManagedConfig | None = None,
) -> FastAPI:
    """创建从内存状态读取订阅索引的 FastAPI 应用。"""
    render_data_dir = data_dir or state.data_dir
    render_managed_config = managed_config or ManagedConfig()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """在服务生命周期内启动和停止 inputs 目录监控。"""
        if watcher is not None:
            watcher.start()
        try:
            yield
        finally:
            if watcher is not None:
                watcher.stop()

    app = FastAPI(title="proxystack subscription server", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
        """保持订阅服务错误响应为统一 JSON 结构。"""
        return error_response(exc)

    @app.get("/health")
    def health() -> dict[str, object]:
        """返回服务健康状态和内存索引状态。"""
        state_health = state.health()
        response: dict[str, object] = {
            "status": "ok" if state_health.loaded and state_health.last_error is None else "error",
            "index": state_health.loaded,
            "users": state_health.users,
        }
        if state_health.last_error is not None:
            response["last_error"] = state_health.last_error
        return response

    @app.get("/sub/{user}")
    def clash_sub(user: str, token: Optional[str] = Query(None)) -> PlainTextResponse:
        """返回普通 Clash 订阅。"""
        return render_subscription_response(
            user,
            token,
            state,
            lambda index, requested_user: render_clash_subscription(
                index,
                requested_user,
                template_dir=templates_dir,
                data_dir=render_data_dir,
            ),
        )

    @app.get("/premium_sub/{user}")
    def premium_clash_sub(user: str, token: Optional[str] = Query(None)) -> PlainTextResponse:
        """返回 Premium Clash 订阅。"""
        return render_subscription_response(
            user,
            token,
            state,
            lambda index, requested_user: render_premium_clash_subscription(
                index,
                requested_user,
                template_dir=templates_dir,
                data_dir=render_data_dir,
            ),
        )

    @app.get("/surge_sub/{user}")
    def surge_sub(request: Request, user: str, token: Optional[str] = Query(None)) -> PlainTextResponse:
        """返回 Surge 订阅。"""
        return render_subscription_response(
            user,
            token,
            state,
            lambda index, requested_user: render_surge_subscription(
                index,
                requested_user,
                template_dir=templates_dir,
                data_dir=render_data_dir,
                managed_config_url=managed_config_url(request, requested_user, token, render_managed_config),
                managed_config_interval=render_managed_config.interval,
                managed_config_strict=render_managed_config.strict,
            ),
        )

    return app


def managed_config_url(
    request: Request,
    user: str,
    token: Optional[str],
    managed_config: ManagedConfig,
) -> Optional[str]:
    """生成 Surge 托管配置自引用 URL；未启用时返回 None。"""
    if not managed_config.enabled:
        return None
    if managed_config.public_base_url:
        query = f"?{urlencode({'token': token})}" if token is not None else ""
        return f"{managed_config.public_base_url}/surge_sub/{quote(user, safe='')}{query}"
    return str(request.url)


def render_subscription_response(
    user: str,
    token: Optional[str],
    state: SubscriptionState,
    renderer: Callable[[SubscriptionIndex, str], str],
) -> PlainTextResponse:
    """读取内存索引、执行 token 鉴权并返回订阅文本。"""
    index = read_request_index(state)
    verify_token(index, token)
    try:
        content = renderer(index, user)
    except SubscriptionTemplateError as exc:
        raise json_error(503, "template_error", "subscription template unavailable") from exc
    except SubscriptionGeneratorError as exc:
        raise json_error(404, "not_found", "subscription not found") from exc
    return PlainTextResponse(content)


def read_request_index(state: SubscriptionState) -> SubscriptionIndex:
    """读取请求使用的内存索引，失败时返回统一 JSON 错误。"""
    try:
        return state.snapshot()
    except SubscriptionGeneratorError as exc:
        raise json_error(503, "index_unavailable", "subscription index unavailable") from exc


def verify_token(index: SubscriptionIndex, token: Optional[str]) -> None:
    """根据 index.access 校验 token query 参数。"""
    if index.access.type != "token":
        return
    if token is None:
        raise json_error(401, "unauthorized", "subscription token is required")
    if token != index.access.token:
        raise json_error(403, "forbidden", "subscription token is invalid")


def json_error(status_code: int, code: str, message: str) -> HTTPException:
    """构造统一 JSON 错误响应。"""
    return HTTPException(status_code=status_code, detail={"error": {"code": code, "message": message}})


def error_response(exc: HTTPException) -> JSONResponse:
    """把 HTTPException detail 原样转换为 JSONResponse。"""
    return JSONResponse(status_code=exc.status_code, content=exc.detail)
