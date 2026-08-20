"""Private structural validation shared by recording and durable reopen."""

from __future__ import annotations

import heapq

from .models import WorkflowDefinition, WorkflowValueError


def graph_order(definition: WorkflowDefinition) -> tuple[str, ...]:
    node_ids = {node.node_id for node in definition.nodes}
    indegree = {node_id: 0 for node_id in node_ids}
    children = {node_id: set() for node_id in node_ids}
    dependencies: set[tuple[str, str]] = set()
    for edge in definition.edges:
        dependencies.add((edge.source_node_id, edge.target_node_id))
    for mapping in definition.maps:
        for _key, target_node_id, _role in mapping.items:
            dependencies.add((mapping.source_node_id, target_node_id))
    for source, target in dependencies:
        if source == target:
            raise WorkflowValueError("Workflow graph contains a self dependency")
        if target not in children[source]:
            children[source].add(target)
            indegree[target] += 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(queue)
    order: list[str] = []
    while queue:
        node_id = heapq.heappop(queue)
        order.append(node_id)
        for child in sorted(children[node_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(queue, child)
    if len(order) != len(node_ids):
        raise WorkflowValueError("combined Edge/Map graph must be acyclic")
    return tuple(order)


def validate_definition_structure(definition: WorkflowDefinition) -> None:
    """Validate every closed non-Core relation in a WorkflowDefinition."""

    nodes = {node.node_id: node for node in definition.nodes}
    edges = {edge.edge_id: edge for edge in definition.edges}
    conditions = {condition.condition_id: condition for condition in definition.conditions}
    producer_guards: dict[tuple[str, str], list[tuple[str | None, str | None]]] = {}

    for edge in definition.edges:
        source = nodes.get(edge.source_node_id)
        target = nodes.get(edge.target_node_id)
        if source is None or target is None:
            raise WorkflowValueError("Edge references a missing Node")
        if edge.source_output_role not in source.output_roles:
            raise WorkflowValueError("Edge references an unknown source output role")
        if edge.target_input_role not in target.input_roles:
            raise WorkflowValueError("Edge references an unknown target input role")
        if edge.branch == "always":
            if edge.condition_id is not None:
                raise WorkflowValueError("always Edge must not name a Condition")
            guard = (None, None)
        else:
            if edge.condition_id not in conditions:
                raise WorkflowValueError("conditional Edge references a missing Condition")
            guard = (edge.condition_id, edge.branch)
        producer_guards.setdefault(
            (edge.target_node_id, edge.target_input_role), []
        ).append(guard)

    for mapping in definition.maps:
        source = nodes.get(mapping.source_node_id)
        if source is None:
            raise WorkflowValueError("Map references a missing source Node")
        if mapping.source_output_role not in source.output_roles:
            raise WorkflowValueError("Map references an unknown source output role")
        for _key, target_node_id, target_role in mapping.items:
            target = nodes.get(target_node_id)
            if target is None:
                raise WorkflowValueError("Map item references a missing target Node")
            if target_role not in target.input_roles:
                raise WorkflowValueError("Map item references an unknown target input role")
            producer_guards.setdefault((target_node_id, target_role), []).append((None, None))

    conditional_membership: set[str] = set()
    for condition in definition.conditions:
        if condition.source_node_id not in nodes:
            raise WorkflowValueError("Condition references a missing source Node")
        for branch, edge_ids in (
            ("true", condition.true_edge_ids),
            ("false", condition.false_edge_ids),
        ):
            for edge_id in edge_ids:
                edge = edges.get(edge_id)
                if edge is None:
                    raise WorkflowValueError("Condition references a missing Edge")
                if edge_id in conditional_membership:
                    raise WorkflowValueError("conditional Edge occurs in more than one branch")
                conditional_membership.add(edge_id)
                if edge.condition_id != condition.condition_id or edge.branch != branch:
                    raise WorkflowValueError("Edge and Condition branch metadata disagree")
    declared_conditional = {edge.edge_id for edge in definition.edges if edge.branch != "always"}
    if conditional_membership != declared_conditional:
        raise WorkflowValueError("Condition branches must exactly enumerate conditional Edges")

    gated_nodes: set[str] = set()
    for gate in definition.human_gates:
        for node_id in gate.target_node_ids:
            if node_id not in nodes:
                raise WorkflowValueError("HumanGate references a missing Node")
            if node_id in gated_nodes:
                raise WorkflowValueError("HumanGate target sets must be globally disjoint")
            gated_nodes.add(node_id)

    for node in definition.nodes:
        for role in node.input_roles:
            guards = producer_guards.get((node.node_id, role), [])
            if not guards:
                raise WorkflowValueError("declared input role has no producer")
            for index, left in enumerate(guards):
                for right in guards[index + 1 :]:
                    mutually_exclusive = (
                        left[0] is not None
                        and left[0] == right[0]
                        and left[1] != right[1]
                    )
                    if not mutually_exclusive:
                        raise WorkflowValueError("target input role has ambiguous producers")

    graph_order(definition)
