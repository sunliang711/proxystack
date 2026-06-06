"""服务依赖图和循环检测。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.graph.references import RefFormatError
from proxystack.graph.references import ReferenceIndex
from proxystack.graph.references import parse_component_ref
from proxystack.graph.references import parse_xrelay_inbound_ref


@dataclass(frozen=True)
class GraphIssue:
    """引用图校验问题。"""

    path: str
    message: str


@dataclass(frozen=True, order=True)
class ServiceNode:
    """依赖图中的单个服务实例节点。"""

    stack: str
    component: str

    def service_name(self) -> str:
        """返回当前节点对应的 systemd 服务名。"""
        if self.component == "xrelay":
            return f"ps-xray@{self.stack}.service"
        return f"ps-{self.component}@{self.stack}.service"

    def label(self) -> str:
        """返回 plan 输出使用的紧凑标签。"""
        return f"{self.stack}.{self.component}"


@dataclass(frozen=True)
class DependencyPlan:
    """plan 命令展示所需的依赖服务和操作顺序。"""

    target: Optional[str]
    dependency_nodes: list[ServiceNode]
    dependency_edges: list[tuple[ServiceNode, ServiceNode]]
    operation_order: list[ServiceNode]


@dataclass(frozen=True)
class ReferenceGraph:
    """已解析的 endpoint 索引和服务依赖关系。"""

    index: ReferenceIndex
    dependencies: dict[ServiceNode, frozenset[ServiceNode]]
    nodes: frozenset[ServiceNode]
    stack_names: frozenset[str]

    def validate_acyclic(self) -> list[GraphIssue]:
        """校验服务依赖图没有循环依赖。"""
        cycle = self.find_cycle()
        if not cycle:
            return []
        return [
            GraphIssue(
                path="dependency_graph",
                message=f"dependency cycle detected: {format_cycle(cycle)}",
            )
        ]

    def find_cycle(self) -> list[ServiceNode]:
        """使用深度优先搜索寻找一个依赖环。"""
        states: dict[ServiceNode, str] = {}
        path: list[ServiceNode] = []
        for node in sorted(self.nodes):
            if states.get(node) == "done":
                continue
            cycle = self._visit_for_cycle(node, states, path)
            if cycle:
                return cycle
        return []

    def _visit_for_cycle(
        self,
        node: ServiceNode,
        states: dict[ServiceNode, str],
        path: list[ServiceNode],
    ) -> list[ServiceNode]:
        """递归访问依赖边，并在遇到回边时返回环路径。"""
        states[node] = "visiting"
        path.append(node)
        for dependency in sorted(self.dependencies.get(node, frozenset())):
            if states.get(dependency) == "visiting":
                cycle_start = path.index(dependency)
                return path[cycle_start:] + [dependency]
            if states.get(dependency) == "done":
                continue
            cycle = self._visit_for_cycle(dependency, states, path)
            if cycle:
                return cycle
        path.pop()
        states[node] = "done"
        return []

    def topological_order(self, selected_nodes: Optional[set[ServiceNode]] = None) -> list[ServiceNode]:
        """返回依赖优先的服务操作顺序。"""
        allowed_nodes = selected_nodes if selected_nodes is not None else set(self.nodes)
        ordered_nodes: list[ServiceNode] = []
        visited_nodes: set[ServiceNode] = set()
        for node in sorted(allowed_nodes):
            self._append_topological(node, allowed_nodes, visited_nodes, ordered_nodes)
        return ordered_nodes

    def _append_topological(
        self,
        node: ServiceNode,
        allowed_nodes: set[ServiceNode],
        visited_nodes: set[ServiceNode],
        ordered_nodes: list[ServiceNode],
    ) -> None:
        """递归追加节点依赖，确保依赖服务排在当前服务之前。"""
        if node in visited_nodes:
            return
        for dependency in sorted(self.dependencies.get(node, frozenset())):
            if dependency in allowed_nodes:
                self._append_topological(dependency, allowed_nodes, visited_nodes, ordered_nodes)
        visited_nodes.add(node)
        ordered_nodes.append(node)

    def build_plan(self, target: Optional[str] = None) -> DependencyPlan:
        """按目标 stack 计算依赖闭包和建议操作顺序。"""
        target_nodes = self.select_target_nodes(target)
        plan_nodes = self.collect_dependency_closure(target_nodes)
        ordered_nodes = self.topological_order(plan_nodes)
        dependency_nodes = [node for node in ordered_nodes if node not in target_nodes]
        dependency_edges = self.collect_dependency_edges(plan_nodes, ordered_nodes)
        return DependencyPlan(
            target=target,
            dependency_nodes=dependency_nodes,
            dependency_edges=dependency_edges,
            operation_order=ordered_nodes,
        )

    def select_target_nodes(self, target: Optional[str]) -> set[ServiceNode]:
        """选择 plan 的目标节点；未指定目标时选择全部服务。"""
        if target is None:
            return set(self.nodes)
        if target not in self.stack_names:
            raise ValueError(f"stack does not exist: {target}")
        return {node for node in self.nodes if node.stack == target}

    def collect_dependency_closure(self, target_nodes: set[ServiceNode]) -> set[ServiceNode]:
        """收集目标服务以及它们递归依赖的全部服务。"""
        collected_nodes: set[ServiceNode] = set()
        pending_nodes = list(target_nodes)
        while pending_nodes:
            node = pending_nodes.pop()
            if node in collected_nodes:
                continue
            collected_nodes.add(node)
            pending_nodes.extend(self.dependencies.get(node, frozenset()))
        return collected_nodes

    def collect_dependency_edges(
        self,
        plan_nodes: set[ServiceNode],
        ordered_nodes: list[ServiceNode],
    ) -> list[tuple[ServiceNode, ServiceNode]]:
        """收集 plan 范围内的服务依赖边，保持输出顺序稳定。"""
        dependency_edges: list[tuple[ServiceNode, ServiceNode]] = []
        for node in ordered_nodes:
            for dependency in sorted(self.dependencies.get(node, frozenset())):
                if dependency in plan_nodes:
                    dependency_edges.append((node, dependency))
        return dependency_edges


@dataclass(frozen=True)
class GraphCompileResult:
    """引用图编译结果，允许校验阶段汇总多个问题。"""

    graph: ReferenceGraph
    issues: list[GraphIssue]


class ReferenceGraphError(ValueError):
    """引用图构建失败异常。"""

    def __init__(self, issues: list[GraphIssue]) -> None:
        """保存图校验问题并生成单行错误列表。"""
        self.issues = issues
        super().__init__("\n".join(f"{issue.path}: {issue.message}" for issue in issues))


def compile_reference_graph(stack_set: StackSet) -> GraphCompileResult:
    """编译 stack set 的 ref endpoint 索引和服务依赖图。"""
    index = ReferenceIndex.from_stacks(stack_set.stacks)
    nodes = collect_service_nodes(stack_set.stacks)
    dependencies: dict[ServiceNode, set[ServiceNode]] = {node: set() for node in nodes}
    issues: list[GraphIssue] = []
    for stack in stack_set.stacks:
        issues.extend(add_xrelay_dependencies(stack, index, dependencies))
        issues.extend(add_clash_dependencies(stack, index, dependencies))
    graph = ReferenceGraph(
        index=index,
        dependencies={node: frozenset(node_dependencies) for node, node_dependencies in dependencies.items()},
        nodes=frozenset(nodes),
        stack_names=frozenset(stack.name for stack in stack_set.stacks),
    )
    if not issues:
        issues.extend(graph.validate_acyclic())
    return GraphCompileResult(graph=graph, issues=issues)


def build_reference_graph(stack_set: StackSet) -> ReferenceGraph:
    """构建无错误的引用图，供 CLI plan 和后续生成器使用。"""
    result = compile_reference_graph(stack_set)
    if result.issues:
        raise ReferenceGraphError(result.issues)
    return result.graph


def collect_service_nodes(stacks: list[Stack]) -> set[ServiceNode]:
    """收集当前配置中的启用服务节点。"""
    nodes: set[ServiceNode] = set()
    for stack in stacks:
        if not stack.enabled:
            continue
        if stack.xrelay.enabled:
            nodes.add(ServiceNode(stack=stack.name, component="xrelay"))
        if stack.clash.enabled:
            nodes.add(ServiceNode(stack=stack.name, component="clash"))
    return nodes


def add_xrelay_dependencies(
    stack: Stack,
    index: ReferenceIndex,
    dependencies: dict[ServiceNode, set[ServiceNode]],
) -> list[GraphIssue]:
    """把 xrelay outbound 引用转换为服务依赖。"""
    if not stack.enabled or not stack.xrelay.enabled:
        return []
    outbound = stack.xrelay.outbound
    if outbound.type != "clash":
        return []
    path = f"stacks.{stack.name}.xrelay.outbound.ref"
    try:
        parsed_ref = parse_component_ref(outbound.ref, path)
    except RefFormatError as exc:
        return [GraphIssue(path=exc.path, message=exc.message)]
    if parsed_ref.component != "clash":
        return [GraphIssue(path=path, message="xrelay clash outbound ref must target clash component")]
    if parsed_ref.kind != "socks":
        return [GraphIssue(path=path, message="xrelay clash outbound ref must target socks listener")]
    endpoint = index.resolve_clash_listener(parsed_ref.raw)
    if endpoint is None:
        return [GraphIssue(path=path, message=f"clash listener ref does not exist: {parsed_ref.raw}")]
    source_node = ServiceNode(stack=stack.name, component="xrelay")
    target_node = ServiceNode(stack=endpoint.stack, component="clash")
    dependencies.setdefault(source_node, set()).add(target_node)
    dependencies.setdefault(target_node, set())
    return []


def add_clash_dependencies(
    stack: Stack,
    index: ReferenceIndex,
    dependencies: dict[ServiceNode, set[ServiceNode]],
) -> list[GraphIssue]:
    """把 clash upstream 引用转换为服务依赖。"""
    if not stack.enabled or not stack.clash.enabled:
        return []
    issues: list[GraphIssue] = []
    source_node = ServiceNode(stack=stack.name, component="clash")
    for upstream_index, upstream in enumerate(stack.clash.upstreams):
        if upstream.type != "xrelay-socks5":
            continue
        path = f"stacks.{stack.name}.clash.upstreams[{upstream_index}].ref"
        try:
            parsed_ref = parse_xrelay_inbound_ref(upstream.ref, path)
        except RefFormatError as exc:
            issues.append(GraphIssue(path=exc.path, message=exc.message))
            continue
        endpoint = index.resolve_xrelay_inbound(parsed_ref.raw)
        if endpoint is None:
            issues.append(GraphIssue(path=path, message=f"xrelay inbound ref does not exist: {parsed_ref.raw}"))
            continue
        if endpoint.kind != "socks5":
            issues.append(
                GraphIssue(
                    path=path,
                    message=f"xrelay-socks5 ref must target socks5 inbound, got {endpoint.kind}: {parsed_ref.raw}",
                )
            )
            continue
        target_node = ServiceNode(stack=endpoint.stack, component="xrelay")
        dependencies.setdefault(source_node, set()).add(target_node)
        dependencies.setdefault(target_node, set())
    return issues


def format_cycle(cycle: list[ServiceNode]) -> str:
    """格式化依赖环路径，方便 CLI 直接展示。"""
    return " -> ".join(node.service_name() for node in cycle)
