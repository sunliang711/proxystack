"""订阅 golden 快照测试。"""

from pathlib import Path

from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import SubscriptionIndex
from proxystack.generator.sub import SubscriptionInput
from proxystack.generator.sub import SubscriptionNode
from proxystack.generator.sub import index_to_json
from proxystack.generator.sub import input_to_yaml
from proxystack.generator.sub import render_clash_subscription
from proxystack.generator.sub import render_premium_clash_subscription
from proxystack.generator.sub import render_surge_subscription
from proxystack.generator.sub.config import SubscriptionAuth

GOLDEN_DIR = Path("tests/golden/sub")


def test_subscription_input_and_index_match_golden() -> None:
    """验证订阅 input 和 index 输出需要显式更新 golden。"""
    subscription_input, index = make_subscription_golden_models()

    assert input_to_yaml(subscription_input) == (GOLDEN_DIR / "input.yaml").read_text(encoding="utf-8")
    assert index_to_json(index) == (GOLDEN_DIR / "index.json").read_text(encoding="utf-8")


def test_subscription_formats_match_golden() -> None:
    """验证三类订阅格式输出需要显式更新 golden。"""
    _subscription_input, index = make_subscription_golden_models()
    clash_golden = (GOLDEN_DIR / "clash.yaml").read_text(encoding="utf-8")
    surge_golden = (GOLDEN_DIR / "surge.txt").read_text(encoding="utf-8")

    assert render_clash_subscription(index, "alice") == clash_golden
    assert render_premium_clash_subscription(index, "alice") == clash_golden
    assert render_surge_subscription(index, "alice") == surge_golden


def make_subscription_golden_models() -> tuple[SubscriptionInput, SubscriptionIndex]:
    """生成固定时间戳的订阅模型，避免 golden 受当前时间影响。"""
    node = SubscriptionNode(
        id="manual:relay",
        user="alice",
        protocol="socks5",
        server="proxy.example.com",
        port=24001,
        tag="socks5:24001:relay",
        remark="Manual Relay",
        udp=True,
        auth=SubscriptionAuth(type="password", username="demo-user", password="demo-pass"),
    )
    subscription_input = SubscriptionInput(
        input_version=1,
        source="manual",
        generated_at="2026-06-05T12:00:00+08:00",
        nodes=[node],
    )
    index = SubscriptionIndex(
        index_version=1,
        generated_at="2026-06-05T12:00:00+08:00",
        sources=["manual"],
        nodes=[node],
        users={"alice": [node]},
        access=SubscriptionAccess(type="token", token="demo-token"),
    )
    return subscription_input, index
