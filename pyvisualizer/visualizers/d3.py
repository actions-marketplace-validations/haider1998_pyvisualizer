"""
Backwards-compatible entry point for interactive HTML generation.

The interactive viewer is now fully self-contained (no CDN / D3 dependency) and
lives in :mod:`pyvisualizer.visualizers.html`. This module preserves the
historical ``generate_d3_visualization`` name so existing callers keep working.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx

from pyvisualizer.visualizers.html import generate_html_visualization


def generate_d3_visualization(
    G: nx.DiGraph,
    output_path: str,
    project_name: str,
    project_root: Optional[str] = None,
    tool_version: str = "",
) -> None:
    """Generate the self-contained interactive HTML viewer (compat shim)."""
    generate_html_visualization(
        G,
        output_path,
        project_name,
        project_root=project_root,
        tool_version=tool_version,
    )
