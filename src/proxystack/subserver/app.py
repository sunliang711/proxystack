"""订阅 HTTP 服务。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from typing import Optional

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse

from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import SubscriptionIndex
from proxystack.generator.sub import load_index_file
from proxystack.generator.sub import render_clash_subscription
from proxystack.generator.sub import render_premium_clash_subscription
from proxystack.generator.sub import render_surge_subscription


def create_app(data_dir: Path) -> FastAPI:
    """创建只读取 data_dir/current/index.json 的 FastAPI 应用。"""
    app = FastAPI(title="proxystack subscription server")
    index_path = data_dir / "current" / "index.json"

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
        """保持订阅服务错误响应为统一 JSON 结构。"""
        return error_response(exc)

    @app.get("/health")
    def health() -> dict[str, object]:
        """返回服务健康状态和当前索引可读性。"""
        try:
            index = load_index_file(index_path)
        except SubscriptionGeneratorError:
            return {"status": "error", "index": False}
        return {"status": "ok", "index": True, "users": len(index.users)}

    @app.get("/sub/{user}")
    def clash_sub(user: str, token: Optional[str] = Query(None)) -> PlainTextResponse:
        """返回普通 Clash 订阅。"""
        return render_subscription_response(user, token, index_path, render_clash_subscription)

    @app.get("/premium_sub/{user}")
    def premium_clash_sub(user: str, token: Optional[str] = Query(None)) -> PlainTextResponse:
        """返回 Premium Clash 订阅。"""
        return render_subscription_response(user, token, index_path, render_premium_clash_subscription)

    @app.get("/surge_sub/{user}")
    def surge_sub(user: str, token: Optional[str] = Query(None)) -> PlainTextResponse:
        """返回 Surge 订阅。"""
        return render_subscription_response(user, token, index_path, render_surge_subscription)

    return app


def render_subscription_response(
    user: str,
    token: Optional[str],
    index_path: Path,
    renderer: Callable[[SubscriptionIndex, str], str],
) -> PlainTextResponse:
    """读取索引、执行 token 鉴权并返回订阅文本。"""
    index = read_request_index(index_path)
    verify_token(index, token)
    try:
        content = renderer(index, user)
    except SubscriptionGeneratorError as exc:
        raise json_error(404, "not_found", "subscription not found") from exc
    return PlainTextResponse(content)


def read_request_index(index_path: Path) -> SubscriptionIndex:
    """读取请求使用的订阅索引，失败时返回统一 JSON 错误。"""
    try:
        return load_index_file(index_path)
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
