"""Tests for Phase 2: JSON schema, README injection, diff, gates, impact."""

import json
import os
import tempfile

import networkx as nx
import pytest

from pyvisualizer.api import build_graph
from pyvisualizer.config import Rules
from pyvisualizer.diff import diff_graphs
from pyvisualizer.gates import check_layer_rules, find_cycles
from pyvisualizer.impact import analyze_impact
from pyvisualizer.inject import END_MARKER, START_MARKER, inject
from pyvisualizer.serializers.json_graph import SCHEMA_ID, graph_to_dict, graph_to_json


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


class TestJsonSchema:
    def test_schema_id_present_and_deterministic(self):
        tmp = _project(SAMPLE)
        r1 = build_graph(tmp)
        j1 = graph_to_json(r1.graph, project_root=r1.project_root)
        r2 = build_graph(tmp)
        j2 = graph_to_json(r2.graph, project_root=r2.project_root)
        assert j1 == j2  # byte-identical
        data = json.loads(j1)
        assert data["schema"] == SCHEMA_ID
        assert data["stats"]["nodes"] == r1.graph.number_of_nodes()

    def test_paths_are_relative(self):
        tmp = _project(SAMPLE)
        r = build_graph(tmp)
        data = graph_to_dict(r.graph, project_root=r.project_root)
        for node in data["nodes"]:
            assert not os.path.isabs(node["file"])


class TestInjection:
    MERMAID = "flowchart LR\n    a --> b"

    def test_appends_when_markers_absent(self):
        content = "# Title\n\nBody.\n"
        new, changed = inject(content, self.MERMAID)
        assert changed
        assert START_MARKER in new and END_MARKER in new
        assert "```mermaid" in new

    def test_updates_between_markers(self):
        content = "# T\n\n" + START_MARKER + "\nOLD\n" + END_MARKER + "\n\nAfter.\n"
        new, changed = inject(content, self.MERMAID)
        assert changed
        assert "OLD" not in new
        assert "After." in new  # content after markers preserved

    def test_idempotent_when_unchanged(self):
        content = "# T\n"
        once, _ = inject(content, self.MERMAID)
        twice, changed = inject(once, self.MERMAID)
        assert not changed
        assert once == twice


class TestDiff:
    def test_detects_new_cycle(self):
        base = _project(
            {
                "a.py": "from b import B\nclass A:\n    def run(self):\n        B().go()\n",
                "b.py": "class B:\n    def go(self):\n        pass\n",
            }
        )
        head = _project(
            {
                "a.py": "from b import B\nclass A:\n    def run(self):\n        B().go()\n",
                "b.py": "from a import A\nclass B:\n    def go(self):\n        A().run()\n",
            }
        )
        rb = build_graph(base)
        rh = build_graph(head)
        d = diff_graphs(
            graph_to_dict(rb.graph, project_root=rb.project_root),
            graph_to_dict(rh.graph, project_root=rh.project_root),
        )
        assert len(d.new_cycles) == 1
        assert d.has_changes

    def test_no_changes_reported_for_identical(self):
        tmp = _project(SAMPLE)
        r = build_graph(tmp)
        data = graph_to_dict(r.graph, project_root=r.project_root)
        d = diff_graphs(data, data)
        assert not d.has_changes
        assert d.new_cycles == []


class TestGates:
    def test_layer_rule_violation_detected(self):
        # domain calls into api -> forbidden
        tmp = _project(
            {
                "domain.py": "from api import handler\ndef service():\n    handler()\n",
                "api.py": "def handler():\n    pass\n",
            }
        )
        # modules are top-level names 'domain' and 'api'
        G = build_graph(tmp).graph
        rules = Rules(layers=["domain", "api"], forbid=["domain -> api"])
        violations = check_layer_rules(G, rules)
        assert len(violations) == 1
        assert violations[0].caller.startswith("domain")
        assert violations[0].callee.startswith("api")

    def test_clean_project_no_violations(self):
        tmp = _project(SAMPLE)
        G = build_graph(tmp).graph
        rules = Rules(layers=["a", "b"], forbid=["b -> a"])
        assert check_layer_rules(G, rules) == []

    def test_find_cycles(self):
        tmp = _project(
            {
                "a.py": "from b import B\nclass A:\n    def run(self):\n        B().go()\n",
                "b.py": "from a import A\nclass B:\n    def go(self):\n        A().run()\n",
            }
        )
        G = build_graph(tmp).graph
        assert len(find_cycles(G)) >= 1


class TestImpact:
    def test_blast_radius(self):
        tmp = _project(
            {
                "m.py": (
                    "def leaf():\n    pass\n" "def mid():\n    leaf()\n" "def top():\n    mid()\n"
                ),
            }
        )
        G = build_graph(tmp).graph
        result = analyze_impact(G, "leaf")
        assert result.found
        # top -> mid -> leaf : leaf has 2 transitive callers
        assert result.blast_radius == 2
        assert "m.mid" in result.direct_callers

    def test_not_found(self):
        tmp = _project(SAMPLE)
        G = build_graph(tmp).graph
        assert not analyze_impact(G, "does_not_exist").found
