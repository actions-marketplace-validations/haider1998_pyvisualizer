"""Tests for health metrics, dead-code detection, and AI export."""

import json
import os
import tempfile

import pytest

from pyvisualizer.api import build_graph
from pyvisualizer.export import build_ai_markdown, export_for_ai
from pyvisualizer.metrics import (
    _grade,
    badge_svg,
    compute_health,
    find_dead_code,
)


def _project(sources: dict) -> str:
    tmp = tempfile.mkdtemp()
    for name, code in sources.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(code)
    return tmp


class TestHealth:
    def test_clean_project_scores_high(self):
        tmp = _project(
            {
                "a.py": "from b import B\ndef main():\n    B().go()\n",
                "b.py": "class B:\n    def go(self):\n        self.step()\n    def step(self):\n        pass\n",
            }
        )
        r = compute_health(build_graph(tmp).graph)
        assert r.score >= 80
        assert r.grade[0] in ("A", "B")

    def test_cycles_lower_the_score(self):
        clean = _project(
            {
                "a.py": "from b import B\nclass A:\n    def run(self):\n        B().go()\n",
                "b.py": "class B:\n    def go(self):\n        pass\n",
            }
        )
        cyclic = _project(
            {
                "a.py": "from b import B\nclass A:\n    def run(self):\n        B().go()\n",
                "b.py": "from a import A\nclass B:\n    def go(self):\n        A().run()\n",
            }
        )
        s_clean = compute_health(build_graph(clean).graph).score
        s_cyclic = compute_health(build_graph(cyclic).graph).score
        assert s_cyclic < s_clean

    def test_deterministic(self):
        tmp = _project({"m.py": "def a():\n    b()\ndef b():\n    pass\n"})
        G = build_graph(tmp).graph
        assert compute_health(G).to_dict() == compute_health(G).to_dict()

    def test_grade_boundaries(self):
        assert _grade(100) == "A+"
        assert _grade(85) == "B"
        assert _grade(59) == "F"


class TestDeadCode:
    def test_finds_uncalled_function(self):
        tmp = _project(
            {
                "m.py": (
                    "def main():\n    used()\n"
                    "def used():\n    pass\n"
                    "def orphan_helper():\n    pass\n"
                ),
            }
        )
        dead = find_dead_code(build_graph(tmp).graph)
        assert any(d.endswith("orphan_helper") for d in dead)
        assert not any(d.endswith(".used") for d in dead)

    def test_respects_entry_decorators(self):
        tmp = _project(
            {
                "app.py": ("def route(f):\n    return f\n" "@route\n" "def handler():\n    pass\n"),
            }
        )
        dead = find_dead_code(build_graph(tmp).graph)
        assert not any(d.endswith(".handler") for d in dead)


class TestBadge:
    def test_badge_is_svg(self):
        tmp = _project({"m.py": "def a():\n    pass\n"})
        svg = badge_svg(compute_health(build_graph(tmp).graph))
        assert svg.startswith("<svg")
        assert "architecture" in svg


class TestAiExport:
    def test_writes_both_files(self):
        tmp = _project(
            {
                "a.py": "from b import B\ndef main():\n    B().go()\n",
                "b.py": "class B:\n    def go(self):\n        pass\n",
            }
        )
        r = build_graph(tmp)
        out = tempfile.mkdtemp()
        paths = export_for_ai(r, out_dir=out, tool_version="9.9.9")
        assert os.path.exists(paths["json"])
        assert os.path.exists(paths["markdown"])
        data = json.load(open(paths["json"]))
        assert data["schema"].startswith("pyvisualizer/graph@")
        assert "health" in data
        md = open(paths["markdown"]).read()
        assert "Ground truth" in md or "ground truth" in md
        assert "## Modules" in md
