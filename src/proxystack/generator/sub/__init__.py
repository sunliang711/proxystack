"""订阅生成器入口。"""

from proxystack.generator.sub.config import BundleManifest
from proxystack.generator.sub.config import BundleImportResult
from proxystack.generator.sub.config import SubscriptionAccess
from proxystack.generator.sub.config import SubscriptionBundleSummary
from proxystack.generator.sub.config import SubscriptionGeneratorError
from proxystack.generator.sub.config import SubscriptionInputSummary
from proxystack.generator.sub.config import SubscriptionIndex
from proxystack.generator.sub.config import SubscriptionInput
from proxystack.generator.sub.config import SubscriptionNode
from proxystack.generator.sub.config import SubscriptionTemplateError
from proxystack.generator.sub.config import access_from_stack_set
from proxystack.generator.sub.config import build_index
from proxystack.generator.sub.config import extract_bundle_inputs
from proxystack.generator.sub.config import extract_bundle_inputs_with_result
from proxystack.generator.sub.config import find_subscription_template_source
from proxystack.generator.sub.config import index_to_json
from proxystack.generator.sub.config import input_dir_files
from proxystack.generator.sub.config import input_to_yaml
from proxystack.generator.sub.config import load_index_file
from proxystack.generator.sub.config import load_input_file
from proxystack.generator.sub.config import load_inputs
from proxystack.generator.sub.config import merge_input_files
from proxystack.generator.sub.config import merge_inputs
from proxystack.generator.sub.config import render_clash_subscription
from proxystack.generator.sub.config import render_premium_clash_subscription
from proxystack.generator.sub.config import render_stack_index
from proxystack.generator.sub.config import render_stack_input
from proxystack.generator.sub.config import render_surge_subscription
from proxystack.generator.sub.config import stack_input_file
from proxystack.generator.sub.config import summarize_input_files
from proxystack.generator.sub.config import validate_bundle_input_name
from proxystack.generator.sub.config import write_bundle

__all__ = [
    "BundleManifest",
    "BundleImportResult",
    "SubscriptionAccess",
    "SubscriptionBundleSummary",
    "SubscriptionGeneratorError",
    "SubscriptionInputSummary",
    "SubscriptionIndex",
    "SubscriptionInput",
    "SubscriptionNode",
    "SubscriptionTemplateError",
    "access_from_stack_set",
    "build_index",
    "extract_bundle_inputs",
    "extract_bundle_inputs_with_result",
    "find_subscription_template_source",
    "index_to_json",
    "input_dir_files",
    "input_to_yaml",
    "load_index_file",
    "load_input_file",
    "load_inputs",
    "merge_input_files",
    "merge_inputs",
    "render_clash_subscription",
    "render_premium_clash_subscription",
    "render_stack_index",
    "render_stack_input",
    "render_surge_subscription",
    "stack_input_file",
    "summarize_input_files",
    "validate_bundle_input_name",
    "write_bundle",
]
