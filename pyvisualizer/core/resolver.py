"""
Graph filtering utilities (module scoping and call-depth slicing).

Note: call *resolution* now lives in :mod:`pyvisualizer.core.graph`, where it
is done deterministically with explicit confidence tagging. The previous
"return the first match as a fallback" heuristic was deliberately removed —
it fabricated edges, the exact failure mode this tool exists to eliminate.
"""

from typing import List

import networkx as nx


def filter_by_modules(G: nx.DiGraph, included_modules: List[str]) -> nx.DiGraph:
    """Filter graph to only include specified modules."""
    nodes_to_keep = []
    for node in G.nodes():
        module = G.nodes[node].get("module", "")
        if any(module.startswith(included) for included in included_modules):
            nodes_to_keep.append(node)
    return G.subgraph(nodes_to_keep).copy()


def filter_by_depth(G: nx.DiGraph, root_function: str, max_depth: int = 2) -> nx.DiGraph:
    """Filter graph to only include functions within a certain call depth."""
    if root_function not in G.nodes:
        # Try to find a matching function
        for node in G.nodes:
            if node.endswith(root_function) or root_function in node:
                root_function = node
                break
        else:
            # No match found, return empty graph
            return nx.DiGraph()

    # BFS to find nodes within depth limit
    nodes_to_include = {root_function}
    current_level = {root_function}

    for _ in range(max_depth):
        next_level = set()
        for node in current_level:
            # Get successors (callee functions)
            for successor in G.successors(node):
                if successor not in nodes_to_include:
                    nodes_to_include.add(successor)
                    next_level.add(successor)
            # Get predecessors (caller functions)
            for predecessor in G.predecessors(node):
                if predecessor not in nodes_to_include:
                    nodes_to_include.add(predecessor)
                    next_level.add(predecessor)
        current_level = next_level

    return G.subgraph(nodes_to_include).copy()
