"""订阅 HTTP 服务测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import SubscriptionIndex
from proxystack.generator.sub import SubscriptionNode
from proxystack.generator.sub import index_to_json
from proxystack.subserver import create_app


def test_health_reads_current_index(tmp_path: Path) -> None:
    """验证 /health 只依赖 current/index.json。"""
    write_index(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "index": True, "users": 2}


def test_subscription_routes_render_three_formats(tmp_path: Path) -> None:
    """验证三种订阅路由按 user 输出文本。"""
    write_index(tmp_path)
    client = TestClient(create_app(tmp_path))

    clash_response = client.get("/sub/alice", params={"token": "demo-token"})
    premium_response = client.get("/premium_sub/alice", params={"token": "demo-token"})
    surge_response = client.get("/surge_sub/alice", params={"token": "demo-token"})

    assert clash_response.status_code == 200
    assert "proxies:" in clash_response.text
    assert "alice socks" in clash_response.text
    assert premium_response.status_code == 200
    assert "proxies:" in premium_response.text
    assert surge_response.status_code == 200
    assert "[Proxy]" in surge_response.text
    assert "alice socks = socks5" in surge_response.text


def test_subscription_routes_require_token(tmp_path: Path) -> None:
    """验证缺少 token 时返回 401。"""
    write_index(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.get("/sub/alice")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_subscription_routes_reject_wrong_token(tmp_path: Path) -> None:
    """验证 token 错误时返回 403。"""
    write_index(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.get("/sub/alice", params={"token": "bad-token"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_subscription_routes_return_404_for_missing_user(tmp_path: Path) -> None:
    """验证用户不存在时返回统一 404 JSON 错误。"""
    write_index(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.get("/sub/missing", params={"token": "demo-token"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_subscription_routes_return_404_for_empty_user(tmp_path: Path) -> None:
    """验证用户存在但节点为空时返回 404。"""
    write_index(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.get("/sub/empty", params={"token": "demo-token"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def write_index(data_dir: Path) -> None:
    """写入测试用 current/index.json。"""
    current_dir = data_dir / "current"
    current_dir.mkdir(parents=True)
    index = SubscriptionIndex(
        index_version=1,
        generated_at="2026-06-05T12:00:00+08:00",
        sources=["test"],
        nodes=[alice_node()],
        users={"alice": [alice_node()], "empty": []},
        access=SubscriptionAccess(type="token", token="demo-token"),
    )
    (current_dir / "index.json").write_text(index_to_json(index), encoding="utf-8")


def alice_node() -> SubscriptionNode:
    """生成测试用 alice socks5 节点。"""
    return SubscriptionNode(
        id="test:alice",
        user="alice",
        protocol="socks5",
        server="proxy.example.com",
        port=24001,
        tag="socks5:24001:alice",
        remark="alice socks",
        auth={
            "type": "password",
            "username": "alice",
            "password": "alice-pass",
        },
    )
