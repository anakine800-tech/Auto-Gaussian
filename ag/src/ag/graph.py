"""Read-only Attempt graph display, including missing parents and shared children."""

import json
from pathlib import Path
import sys


def read_graph(study):
    attempts = Path(study) / "attempts"
    if not attempts.is_dir():
        raise ValueError("Study has no attempts directory")
    nodes, edges = {}, []
    for path in sorted(attempts.glob("*/manifest.json")):
        manifest = json.loads(path.read_text())
        identity = manifest["attempt_id"]
        if identity in nodes:
            raise ValueError(f"Duplicate Attempt id: {identity}")
        status_path = path.with_name("status.json")
        status = json.loads(status_path.read_text()).get("state", "unavailable") if status_path.exists() else "unavailable"
        nodes[identity] = {"attempt_id": identity, "template": manifest.get("template"),
                           "label": manifest.get("label"), "state": status, "missing": False}
        for parent in manifest.get("parents", []):
            edges.append({"parent": parent["attempt_id"], "child": identity,
                          "relation": parent.get("relation", "")})
    for edge in edges:
        if edge["parent"] not in nodes:
            nodes[edge["parent"]] = {"attempt_id": edge["parent"], "template": None,
                                     "label": None, "state": "missing", "missing": True}
    return {"nodes": list(nodes.values()), "edges": edges}


def tree_text(graph):
    nodes = {node["attempt_id"]: node for node in graph["nodes"]}
    children = {identity: [] for identity in nodes}
    for edge in graph["edges"]:
        children[edge["parent"]].append(edge)
    nonroots = {edge["child"] for edge in graph["edges"]}
    visited, lines = set(), []

    def walk(root):
        stack = [(root, 0, "")]
        while stack:
            identity, depth, relation = stack.pop()
            node = nodes[identity]
            suffix = " [missing parent]" if node["missing"] else f" [{node['template']} | {node['label']} | {node['state']}]"
            repeated = identity in visited
            lines.append("  " * depth + (f"({relation}) " if relation else "") + identity
                         + suffix + (" [already shown]" if repeated else ""))
            if repeated:
                continue
            visited.add(identity)
            stack.extend((edge["child"], depth + 1, edge["relation"])
                         for edge in reversed(children[identity]))

    for identity in nodes:
        if identity not in nonroots:
            walk(identity)
    # Cycles are displayed once, never hidden or followed indefinitely.
    for identity in nodes:
        if identity not in visited:
            walk(identity)
    return "\n".join(lines) or "No Attempts."


def run(args):
    try:
        result = read_graph(args.study)
        print(json.dumps(result, indent=2) if args.json else tree_text(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"graph: {exc}", file=sys.stderr)
        return 1


def register(subparsers):
    parser = subparsers.add_parser("graph", description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)
