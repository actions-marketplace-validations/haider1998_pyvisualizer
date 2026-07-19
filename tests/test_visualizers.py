"""Tests for the HTML viewer and GitHub-safe Mermaid output."""

import os
import re
import tempfile

import pytest

from pyvisualizer.api import build_graph
from pyvisualizer.visualizers.html import generate_html_visualization
from pyvisualizer.visualizers.mermaid import generate_github_mermaid


def _project(sources: dict) -> str:
    tmp = tempfile.mkdtemp()
    for name, code in sources.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(code)
    return tmp


SAMPLE = {
    "a.py": "from b import B\ndef main():\n    B().go()\n",
    "b.py": "class B:\n    def go(self):\n        self.step()\n    def step(self):\n        pass\n",
}


class TestHtmlViewer:
    def test_self_contained_no_external_resources(self):
        tmp = _project(SAMPLE)
        r = build_graph(tmp)
        out = os.path.join(tmp, "viz.html")
        generate_html_visualization(r.graph, out, "Sample", project_root=r.project_root)
        content = open(out, encoding="utf-8").read()
        assert "<!DOCTYPE html>" in content
        assert "__GRAPH_DATA__" not in content  # template fully rendered
        for pat in ('src="http', "src='http", 'href="http', "@import", "cdn."):
            assert pat not in content

    def test_embeds_graph_and_features(self):
        tmp = _project(SAMPLE)
        r = build_graph(tmp)
        out = os.path.join(tmp, "viz.html")
        generate_html_visualization(r.graph, out, "Sample", project_root=r.project_root)
        content = open(out, encoding="utf-8").read()
        assert 'id="graph-data"' in content
        # Key interactive features present.
        for feature in (
            "openPalette",
            "function rollup",
            "Tour",
            "minimap",
            "restoreHash",
            'id="inspector"',
        ):
            assert feature in content


class TestGithubMermaid:
    def test_no_fontawesome_or_title_node(self):
        tmp = _project(SAMPLE)
        G = build_graph(tmp).graph
        code = generate_github_mermaid(G, detail="module")
        assert "fa:fa" not in code
        assert "title(" not in code
        assert code.startswith("flowchart")

    def test_deterministic(self):
        tmp = _project(SAMPLE)
        G = build_graph(tmp).graph
        assert generate_github_mermaid(G) == generate_github_mermaid(G)

    def test_module_level_has_module_nodes(self):
        tmp = _project(SAMPLE)
        G = build_graph(tmp).graph
        code = generate_github_mermaid(G, detail="module")
        # a -> b module dependency (main calls B) should appear.
        assert "-->" in code

    def test_detail_levels_differ(self):
        tmp = _project(SAMPLE)
        G = build_graph(tmp).graph
        mod = generate_github_mermaid(G, detail="module")
        fn = generate_github_mermaid(G, detail="function")
        # function level has at least as many node lines as module level
        assert fn.count("[") >= mod.count("[")


class TestC4:
    def test_valid_structurizr_dsl(self):
        from pyvisualizer.serializers.c4 import generate_c4_dsl

        tmp = _project(SAMPLE)
        G = build_graph(tmp).graph
        dsl = generate_c4_dsl(G, "Sample")
        assert dsl.startswith("workspace")
        assert "softwareSystem" in dsl
        assert dsl.count("{") == dsl.count("}")  # balanced braces
        assert "component" in dsl


class TestChurnOverlay:
    def test_graceful_without_git(self):
        from pyvisualizer.overlays import apply_churn

        tmp = _project(SAMPLE)  # a bare temp dir, not a git repo
        G = build_graph(tmp).graph
        # Should not raise and should report no data applied.
        assert apply_churn(G, tmp) is False
