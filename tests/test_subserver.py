"""订阅 HTTP 服务测试。"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
import pytest
from pytest import LogCaptureFixture
from pytest import MonkeyPatch

from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import SubscriptionInput
from proxystack.generator.sub import SubscriptionNode
from proxystack.generator.sub import input_to_yaml
from proxystack.subserver import ManagedConfig
from proxystack.subserver import SubscriptionState
from proxystack.subserver import create_app
from proxystack.subserver.watcher import IN_ATTRIB
from proxystack.subserver.watcher import IN_CLOSE_WRITE
from proxystack.subserver.watcher import IN_CREATE
from proxystack.subserver.watcher import IN_DELETE
from proxystack.subserver.watcher import IN_ISDIR
from proxystack.subserver.watcher import IN_MODIFY
from proxystack.subserver.watcher import IN_MOVED_FROM
from proxystack.subserver.watcher import IN_MOVED_TO
from proxystack.subserver.watcher import IN_Q_OVERFLOW
from proxystack.subserver.watcher import PollingInputWatcher
from proxystack.subserver.watcher import WATCH_MASK
from proxystack.subserver.watcher import is_relevant_input_event


def test_health_reads_loaded_memory_index(tmp_path: Path) -> None:
    """验证 /health 返回内存索引状态。"""
    state = loaded_state(tmp_path)
    client = TestClient(create_app(state))

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["index"] is True
    assert payload["users"] == 1


def test_subscription_routes_render_three_formats(tmp_path: Path) -> None:
    """验证三种订阅路由按 user 输出文本。"""
    state = loaded_state(tmp_path)
    client = TestClient(create_app(state))

    clash_response = client.get("/sub/alice", params={"token": "demo-token"})
    premium_response = client.get("/premium_sub/alice", params={"token": "demo-token"})
    surge_response = client.get("/surge_sub/alice", params={"token": "demo-token"})

    assert clash_response.status_code == 200
    assert "proxies:" in clash_response.text
    assert "proxy-groups:" in clash_response.text
    assert "alice socks" in clash_response.text
    assert premium_response.status_code == 200
    assert "proxies:" in premium_response.text
    assert "rules:" in premium_response.text
    assert surge_response.status_code == 200
    assert surge_response.text.startswith(
        "#!MANAGED-CONFIG http://testserver/surge_sub/alice?token=demo-token interval=86400 strict=true\n[General]"
    )
    assert "[Proxy]" in surge_response.text
    assert "[Proxy Group]" in surge_response.text
    assert "alice socks = socks5" in surge_response.text
    assert "🌐 其他地区 = url-test, alice socks" in surge_response.text


def test_surge_subscription_uses_public_base_url_for_managed_config(tmp_path: Path) -> None:
    """验证反代公网前缀会用于 Surge 托管配置自引用 URL。"""
    state = loaded_state(tmp_path)
    client = TestClient(
        create_app(
            state,
            managed_config=ManagedConfig(public_base_url="https://sub.example.com/api"),
        )
    )

    response = client.get("/surge_sub/alice", params={"token": "demo-token"})

    assert response.status_code == 200
    assert response.text.startswith(
        "#!MANAGED-CONFIG https://sub.example.com/api/surge_sub/alice?token=demo-token interval=86400 strict=true\n[General]"
    )


def test_surge_subscription_can_disable_managed_config_header(tmp_path: Path) -> None:
    """验证可关闭 Surge 托管配置头，方便本地模板复用。"""
    state = loaded_state(tmp_path)
    client = TestClient(create_app(state, managed_config=ManagedConfig(enabled=False)))

    response = client.get("/surge_sub/alice", params={"token": "demo-token"})

    assert response.status_code == 200
    assert response.text.startswith("[General]")


def test_subscription_routes_require_token(tmp_path: Path) -> None:
    """验证缺少 token 时返回 401。"""
    state = loaded_state(tmp_path)
    client = TestClient(create_app(state))

    response = client.get("/sub/alice")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_subscription_routes_reject_wrong_token(tmp_path: Path) -> None:
    """验证 token 错误时返回 403。"""
    state = loaded_state(tmp_path)
    client = TestClient(create_app(state))

    response = client.get("/sub/alice", params={"token": "bad-token"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_subscription_routes_return_404_for_missing_user(tmp_path: Path) -> None:
    """验证用户不存在时返回统一 404 JSON 错误。"""
    state = loaded_state(tmp_path)
    client = TestClient(create_app(state))

    response = client.get("/sub/missing", params={"token": "demo-token"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_subscription_route_returns_503_for_bad_template(tmp_path: Path) -> None:
    """验证本地订阅模板错误时返回模板错误，而不是用户不存在。"""
    state = loaded_state(tmp_path)
    template_dir = tmp_path / "templates" / "sub"
    template_dir.mkdir(parents=True)
    (template_dir / "clash.yaml.j2").write_text("mode: {{ missing_value }}", encoding="utf-8")
    client = TestClient(create_app(state))

    response = client.get("/sub/alice", params={"token": "demo-token"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "template_error"


def test_subscription_state_reload_writes_reload_logs(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """验证 reload 成功时输出可排查的日志。"""
    caplog.set_level(logging.INFO)
    input_dir = tmp_path / "inputs"
    write_input(input_dir / "manual.yaml", alice_node())
    state = SubscriptionState(tmp_path, access=SubscriptionAccess(type="token", token="demo-token"))

    assert state.reload() is True
    assert "Subscription inputs reload started" in caplog.text
    assert "Subscription inputs reloaded" in caplog.text
    assert "inputs=1" in caplog.text
    assert "nodes=1" in caplog.text


def test_subscription_state_load_rejects_duplicate_proxy_name(tmp_path: Path) -> None:
    """验证 serve 启动加载 inputs 时会拒绝同一用户下重复订阅代理名。"""
    input_dir = tmp_path / "inputs"
    write_input(input_dir / "a.yaml", alice_node("same proxy", node_id="test:a"))
    write_input(input_dir / "b.yaml", alice_node("same proxy", node_id="test:b"))
    state = SubscriptionState(tmp_path, access=SubscriptionAccess(type="token", token="demo-token"))

    with pytest.raises(SubscriptionGeneratorError, match="duplicate proxy name for user: user=alice name=same proxy"):
        state.load()


def test_subscription_state_reload_keeps_previous_index_on_bad_input(
    tmp_path: Path,
    caplog: LogCaptureFixture,
) -> None:
    """验证 reload 失败时保留上一份可用内存索引，且日志不输出凭据明文。"""
    input_dir = tmp_path / "inputs"
    write_input(input_dir / "manual.yaml", alice_node())
    state = SubscriptionState(tmp_path, access=SubscriptionAccess(type="token", token="demo-token"))
    state.load()
    caplog.set_level(logging.WARNING)
    (input_dir / "bad.yaml").write_text(
        "\n".join(
            [
                "input_version: 1",
                "source: bad",
                'generated_at: "2026-06-05T12:00:00+08:00"',
                "nodes:",
                "  - id: bad:ss",
                "    user: alice",
                "    protocol: shadowsocks",
                "    server: proxy.example.com",
                "    port: 24002",
                "    tag: ss:24002:bad",
                "    remark: bad ss",
                "    password: secret-pass",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert state.reload() is False
    assert state.snapshot().users["alice"][0].id == "test:alice"
    assert state.health().last_error
    assert "Subscription inputs reload failed" in caplog.text
    assert "error_type=SubscriptionGeneratorError" in caplog.text
    assert "secret-pass" not in caplog.text


def test_subscription_state_reload_records_filesystem_errors(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 reload 遇到文件系统异常时保留旧索引并记录错误。"""
    import proxystack.subserver.state as state_module

    state = loaded_state(tmp_path)

    def raise_os_error(_input_dir: Path, access: SubscriptionAccess) -> None:
        """模拟 inputs 目录读取时出现文件系统异常。"""
        raise OSError("permission denied")

    monkeypatch.setattr(state_module, "merge_input_files", raise_os_error)

    assert state.reload() is False
    assert state.snapshot().users["alice"][0].id == "test:alice"
    assert "permission denied" in str(state.health().last_error)


def test_polling_watcher_detects_atomic_input_replace(tmp_path: Path) -> None:
    """验证轮询 watcher 能发现 import 使用的原子替换。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_input(input_dir / "manual.yaml", alice_node())
    changed = Event()
    watcher = PollingInputWatcher(input_dir, changed.set, interval=0.01)

    watcher.start()
    write_input(input_dir / "manual.yaml", alice_node(remark="updated socks"))
    try:
        assert changed.wait(1)
    finally:
        watcher.stop()


def test_polling_watcher_ignores_non_input_files(tmp_path: Path) -> None:
    """验证轮询 watcher 忽略非 input 后缀文件变化。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_input(input_dir / "manual.yaml", alice_node())
    changed = Event()
    watcher = PollingInputWatcher(input_dir, changed.set, interval=0.01)

    watcher.start()
    (input_dir / ".manual.yaml.tmp").write_text("temporary", encoding="utf-8")
    try:
        assert not changed.wait(0.1)
    finally:
        watcher.stop()


def test_inotify_event_filter_only_accepts_supported_input_changes() -> None:
    """验证 inotify 只把订阅 input 文件的有效变更视为 reload 触发条件。"""
    assert WATCH_MASK & IN_MODIFY == 0
    assert WATCH_MASK & IN_ATTRIB == 0
    assert is_relevant_input_event(IN_CLOSE_WRITE, "manual.yaml") is True
    assert is_relevant_input_event(IN_CLOSE_WRITE, "manual.yml") is True
    assert is_relevant_input_event(IN_CREATE, "manual.json") is True
    assert is_relevant_input_event(IN_DELETE, "manual.yaml") is True
    assert is_relevant_input_event(IN_MOVED_FROM, "manual.yaml") is True
    assert is_relevant_input_event(IN_MOVED_TO, "manual.yaml") is True
    assert is_relevant_input_event(IN_CLOSE_WRITE, ".manual.yaml.tmp") is False
    assert is_relevant_input_event(IN_MODIFY, "manual.yaml") is False
    assert is_relevant_input_event(IN_ATTRIB, "manual.yaml") is False
    assert is_relevant_input_event(IN_CREATE | IN_ISDIR, "manual.yaml") is False
    assert is_relevant_input_event(IN_Q_OVERFLOW, "") is True


def test_polling_watcher_survives_callback_error(tmp_path: Path) -> None:
    """验证 reload 回调异常不会终止 polling watcher 线程。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_input(input_dir / "manual.yaml", alice_node())
    changed = Event()
    calls = {"count": 0}

    def flaky_callback() -> None:
        """第一次触发时抛错，第二次触发时标记成功。"""
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("reload failed")
        changed.set()

    watcher = PollingInputWatcher(input_dir, flaky_callback, interval=0.01)

    watcher.start()
    write_input(input_dir / "manual.yaml", alice_node(remark="first update"))
    for _attempt in range(100):
        if calls["count"] >= 1:
            break
        changed.wait(0.01)
    assert calls["count"] >= 1
    write_input(input_dir / "manual.yaml", alice_node(remark="second update"))
    try:
        assert changed.wait(1)
    finally:
        watcher.stop()


def loaded_state(data_dir: Path) -> SubscriptionState:
    """生成已加载的订阅内存状态。"""
    input_dir = data_dir / "inputs"
    write_input(input_dir / "manual.yaml", alice_node())
    state = SubscriptionState(data_dir, access=SubscriptionAccess(type="token", token="demo-token"))
    state.load()
    return state


def write_input(path: Path, node: SubscriptionNode) -> None:
    """写入测试用订阅 input 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    subscription_input = SubscriptionInput(
        input_version=1,
        source="test",
        generated_at="2026-06-05T12:00:00+08:00",
        nodes=[node],
    )
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(input_to_yaml(subscription_input), encoding="utf-8")
    tmp_path.replace(path)


def alice_node(remark: str = "alice socks", node_id: str = "test:alice") -> SubscriptionNode:
    """生成测试用 alice socks5 节点。"""
    return SubscriptionNode(
        id=node_id,
        user="alice",
        protocol="socks5",
        server="proxy.example.com",
        port=24001,
        tag="socks5:24001:alice",
        remark=remark,
        auth={
            "type": "password",
            "username": "alice",
            "password": "alice-pass",
        },
    )
